"""Video Tutor HTTP API와 provider 의존성 구성을 담당한다.

요청 DTO를 애플리케이션 서비스의 도메인 객체로 변환하고, 환경변수에 따라
Gemini/Groq/stub provider 조합을 한 번만 생성한다. 실제 튜터 로직은 이 모듈이
아닌 ``app.ai.tutor_service``에서 수행한다.
"""

from __future__ import annotations

from functools import lru_cache
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.ai.context_builder import ConversationTurn, SubtitleLine
from app.ai.learner_profile import LearnerSignals
from app.ai.llm_client import GeminiClient, GroqClient, RuleBasedTutorClient
from app.ai.provider_router import ProviderQuota, ProviderRouter
from app.ai.tutor_state import InMemoryTutorState
from app.ai.tutor_service import TutorAskCommand, TutorService
from app.ai.usage_tracker import InMemoryUsageTracker
from app.core.config import settings
from app.db.llm_usage import LLMUsageEntry, LLMUsageRepository
from app.schemas.tutor import (
    ProactiveTutorRequest,
    ProactiveTutorResponse,
    TutorAskRequest,
    TutorAskResponse,
    TutorFeedbackRequest,
    TutorFeedbackResponse,
    TutorUsageResponse,
    TutorUsageSummaryResponse,
)


router = APIRouter(prefix="/tutor", tags=["Video Tutor"])
logger = logging.getLogger(__name__)

# Supabase Auth dependency가 연결되기 전까지 로컬에서 사용할 개발용 actor다.
# 운영 환경에서는 이 값을 사용하지 않고 검증된 JWT의 sub로 교체해야 한다.
_DEVELOPMENT_ACTOR_ID = "test"


@lru_cache(maxsize=1)
def get_llm_usage_repository() -> LLMUsageRepository:
    """프로세스에서 공유할 Tutor 사용량 Supabase 저장소를 생성한다."""

    return LLMUsageRepository(
        url=settings.supabase_url,
        secret_key=settings.supabase_secret_key,
        timeout_seconds=settings.llm_usage_timeout_seconds,
    )


async def _write_llm_usage_safely(
    repository: LLMUsageRepository,
    entry: LLMUsageEntry,
) -> None:
    """사용량 저장 장애가 이미 생성된 Tutor 답변을 실패시키지 않게 한다."""

    try:
        await repository.write(entry)
    except Exception:  # pragma: no cover - network failure is environment-specific
        # 질문 원문·토큰·식별자는 민감할 수 있으므로 저장 실패 원인만 남긴다.
        logger.warning("llm_usage_write_failed")


@lru_cache(maxsize=1)
def get_usage_tracker() -> InMemoryUsageTracker:
    """프로세스에서 공유할 개발용 토큰 usage tracker를 생성한다.

    ``lru_cache``를 사용하는 이유는 요청마다 기록 저장소가 새로 만들어지면
    quota 계산이 누적되지 않기 때문이다. 현재 구현은 메모리 저장소이므로 서버
    재시작 시 기록이 초기화된다.
    """

    return InMemoryUsageTracker()


@lru_cache(maxsize=1)
def get_tutor_state() -> InMemoryTutorState:
    """프로세스에서 공유할 개발용 Tutor 상태 저장소를 생성한다.

    대화·선제 질문 이력·피드백을 요청 사이에 유지하려면 매 요청마다 새
    저장소를 만들면 안 된다. 실제 사용자별 영구 저장소가 연결되면 이 dependency를
    Supabase/Redis repository로 교체한다.
    """

    return InMemoryTutorState(
        proactive_cooldown_seconds=settings.tutor_proactive_cooldown_seconds,
        proactive_max_questions_per_video=(
            settings.tutor_proactive_max_questions_per_video
        ),
        requests_per_minute=settings.tutor_requests_per_minute,
    )


@lru_cache(maxsize=1)
def get_tutor_service() -> TutorService:
    """프로세스 단위 provider 생성.

    기본은 stub이며, 외부 provider를 켜면 quota-aware router가 Gemini와 Groq를
    순서대로 시도한다. API key가 없거나 quota/rate limit이 발생하면 다음 provider,
    마지막에는 stub으로 내려간다.
    테스트에서는 FastAPI dependency override 또는 직접 service 주입이 가능하다.
    """

    # 외부 API가 모두 실패해도 응답을 반환할 수 있도록 마지막 fallback을 항상 준비한다.
    stub_client = RuleBasedTutorClient()
    if settings.llm_provider == "stub":
        return TutorService(stub_client)

    gemini_client = GeminiClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        timeout_seconds=settings.gemini_timeout_seconds,
        max_output_tokens=settings.tutor_max_output_tokens,
    )
    groq_client = GroqClient(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        timeout_seconds=settings.groq_timeout_seconds,
        max_output_tokens=settings.tutor_max_output_tokens,
    )

    if settings.llm_provider == "groq":
        providers = (groq_client, gemini_client)
    else:
        # gemini와 auto는 Gemini를 우선 사용하고 Groq로 failover한다.
        providers = (gemini_client, groq_client)

    router = ProviderRouter(
        providers,
        usage_tracker=get_usage_tracker(),
        quotas={
            "gemini": ProviderQuota(
                daily_token_limit=settings.gemini_daily_token_limit,
                minute_token_limit=settings.gemini_minute_token_limit,
            ),
            "groq": ProviderQuota(
                daily_token_limit=settings.groq_daily_token_limit,
                minute_token_limit=settings.groq_minute_token_limit,
            ),
        },
        reserve_output_tokens=settings.tutor_max_output_tokens,
    )
    return TutorService(router, fallback_client=stub_client)


@router.post("/ask", response_model=TutorAskResponse)
async def ask_tutor(
    request: TutorAskRequest,
    background_tasks: BackgroundTasks,
    service: TutorService = Depends(get_tutor_service),
    state: InMemoryTutorState = Depends(get_tutor_state),
    usage_repository: LLMUsageRepository = Depends(get_llm_usage_repository),
) -> TutorAskResponse:
    """영상 시점의 자막 문맥을 바탕으로 Tutor 답변을 생성한다.

    Args:
        request: Extension이 보낸 영상 위치, 자막, 학습자 신호 및 질문.
        service: FastAPI dependency로 주입되는 Tutor 오케스트레이터.

    Returns:
        실제로 답변에 사용된 provider/model과 토큰 usage를 포함한 Tutor 응답.

    Note:
        인증/DB 계층이 아직 연결되지 않아 현재는 요청에 포함된
        ``learner_signals``를 그대로 사용한다. 운영 단계에서는 인증된 사용자 ID로
        서버가 학습 신호를 조회해야 한다. 선제 질문 답변은 요청의
        ``proactive_question_id``가 실제로 전달된 경우에만 피드백 모드로 처리하며,
        일반 질문은 자연스러운 Tutor 대화로 유지한다. 같은 대화의 후속 요청에
        자막이 생략되면 마지막으로 저장한 자막 문맥을 재사용한다.
    """

    if not state.allow_request(_DEVELOPMENT_ACTOR_ID):
        raise HTTPException(
            status_code=429,
            detail="Tutor 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
        )

    signals = request.learner_signals
    focus_word = request.focus_word
    is_proactive_answer = False
    proactive_question_id = request.proactive_question_id
    # 선제 질문 ID가 명시된 요청만 퀴즈 답변으로 처리한다. pending 질문을
    # 추측해 일반 질문까지 채점 모드로 바꾸면 사용자가 갑자기 판정 화면을
    # 보게 되므로, 애매한 요청은 항상 일반 대화로 남긴다.
    if request.proactive_question_id:
        focus_word = state.get_proactive_focus_word(
            _DEVELOPMENT_ACTOR_ID,
            request.video_id,
            request.proactive_question_id,
        )
        if focus_word is None:
            raise HTTPException(
                status_code=404,
                detail="답변할 Tutor 선제 질문을 찾을 수 없습니다.",
            )
        is_proactive_answer = True

    stored_history = None
    stored_subtitles: tuple[SubtitleLine, ...] = ()
    if request.conversation_id:
        conversation = state.get_conversation(
            _DEVELOPMENT_ACTOR_ID,
            request.conversation_id,
        )
        if conversation is None:
            raise HTTPException(
                status_code=404,
                detail="이어갈 Tutor 대화를 찾을 수 없습니다.",
            )
        stored_video_id, stored_history = conversation
        if stored_video_id != request.video_id:
            raise HTTPException(
                status_code=409,
                detail="Tutor 대화와 영상 ID가 일치하지 않습니다.",
            )
        stored_subtitles = (
            state.get_conversation_subtitles(
                _DEVELOPMENT_ACTOR_ID,
                request.conversation_id,
            )
            or ()
        )
    # 저장된 대화가 있으면 서버 이력을 우선한다. 아직 저장된 대화가 없는 최초
    # 요청만 클라이언트가 보낸 history를 사용해 대화를 초기화한다.
    conversation_history = (
        stored_history
        if stored_history is not None
        else tuple(
            ConversationTurn(role=turn.role, message=turn.message)
            for turn in request.conversation_history
        )
    )

    # 저장 단어 배열과 별도로 전달된 count 중 큰 값을 사용해 부분 데이터도 보정한다.
    saved_words = tuple(item.word for item in signals.saved_words)
    saved_word_count = max(signals.saved_word_count or 0, len(saved_words))
    subtitles = tuple(
        SubtitleLine(timestamp=line.time, english=line.en, korean=line.ko)
        for line in request.recent_subtitles
    )
    if not subtitles and stored_subtitles:
        # 같은 대화의 후속 질문이 자막을 생략해도 마지막으로 확인한 문장을
        # 재사용한다. 새로운 자막이 오면 위의 요청 문맥이 항상 우선한다.
        subtitles = stored_subtitles

    # HTTP 경계의 Pydantic DTO를 AI 계층이 사용하는 불변 도메인 객체로 변환한다.
    result = await service.ask(
        TutorAskCommand(
            video_id=request.video_id,
            timestamp=request.timestamp,
            user_message=request.user_message,
            subtitles=subtitles,
            learner_signals=LearnerSignals(
                saved_word_count=saved_word_count,
                quiz_attempts=signals.quiz_attempts,
                accuracy=signals.quiz_accuracy,
                average_response_time_ms=signals.average_response_time_ms,
                recent_accuracy=signals.recent_quiz_accuracy,
                recent_response_time_ms=signals.recent_response_time_ms,
                saved_words=saved_words,
            ),
            conversation_history=conversation_history,
            focus_word=focus_word,
            is_proactive_answer=is_proactive_answer,
            conversation_id=request.conversation_id,
        )
    )

    state.record_exchange(
        actor_id=_DEVELOPMENT_ACTOR_ID,
        conversation_id=result.conversation_id,
        message_id=result.message_id,
        video_id=request.video_id,
        user_message=request.user_message,
        tutor_reply=result.answer.reply,
        initial_history=conversation_history if stored_history is None else (),
        subtitles=subtitles,
    )
    if is_proactive_answer and proactive_question_id:
        state.mark_proactive_question_answered(
            _DEVELOPMENT_ACTOR_ID,
            request.video_id,
            proactive_question_id,
        )

    # provider가 반환한 사용량은 응답 본문뿐 아니라 DB에도 남긴다. stub fallback은
    # 실제 외부 모델을 호출하지 않아 0 token일 수 있지만 호출 흐름은 확인 가능하다.
    background_tasks.add_task(
        _write_llm_usage_safely,
        usage_repository,
        LLMUsageEntry(
            provider=result.answer.provider,
            model_name=result.answer.model,
            input_tokens=result.answer.usage.input_tokens,
            output_tokens=result.answer.usage.output_tokens,
            total_tokens=result.answer.usage.normalized_total,
        ),
    )

    proactive_feedback = result.answer.proactive_feedback
    reply = result.answer.reply

    return TutorAskResponse(
        conversation_id=result.conversation_id,
        message_id=result.message_id,
        reply=reply,
        suggested_questions=list(result.answer.suggested_questions),
        provider=result.answer.provider,
        model=result.answer.model,
        usage=TutorUsageResponse(
            input_tokens=result.answer.usage.input_tokens,
            output_tokens=result.answer.usage.output_tokens,
            total_tokens=result.answer.usage.normalized_total,
        ),
        learner_level=result.profile.level.value,
        tutor_difficulty=result.profile.tutor_difficulty.value,
        profile_confidence=result.profile.confidence,
        context_subtitle_count=len(result.context.nearby_subtitles),
        proactive_feedback=(
            {
                "result": proactive_feedback.result,
                "criteria": proactive_feedback.criteria,
            }
            if proactive_feedback
            else None
        ),
    )


@router.get("/usage", response_model=TutorUsageSummaryResponse)
async def get_tutor_usage(
    usage_repository: LLMUsageRepository = Depends(get_llm_usage_repository),
) -> TutorUsageSummaryResponse:
    """개발 Supabase에 저장된 전체 토큰 사용량 합계를 반환한다.

    현재 Tutor 호출은 인증 전 개발 actor로 저장되어 전체 개발 사용량만 조회한다.
    사용자별 조회가 필요해지면 JWT ``sub`` 기반 소유권 검사를 추가해야 한다.
    """

    try:
        summary = await usage_repository.summarize_all()
    except Exception:
        # 조회 장애를 성공처럼 보이게 하지 않는다. 사용량 화면은 원인을 알 수 있어야 한다.
        raise HTTPException(
            status_code=503,
            detail="LLM 사용량을 조회할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        ) from None
    return TutorUsageSummaryResponse(
        request_count=summary.request_count,
        input_tokens=summary.input_tokens,
        output_tokens=summary.output_tokens,
        total_tokens=summary.total_tokens,
    )


@router.post("/proactive", response_model=ProactiveTutorResponse)
def proactive_tutor_question(
    request: ProactiveTutorRequest,
    state: InMemoryTutorState = Depends(get_tutor_state),
) -> ProactiveTutorResponse:
    """현재 자막에 기반해 Tutor 선제 질문을 표시할지 판단한다.

    초기 버전은 자막에서 학습 단어를 규칙으로 선택하므로 선제 질문을 위해 LLM을
    호출하지 않는다. cooldown과 이미 표시한 표현은 개발용 상태 저장소에서 관리한다.
    """

    decision = state.decide_proactive(
        actor_id=_DEVELOPMENT_ACTOR_ID,
        video_id=request.video_id,
        timestamp=request.timestamp,
        subtitles=tuple(
            SubtitleLine(
                timestamp=line.time,
                english=line.en,
                korean=line.ko,
            )
            for line in request.recent_subtitles
        ),
        playback_state=request.playback_state,
        last_question_at=request.last_question_at,
    )
    return ProactiveTutorResponse(
        should_show=decision.should_show,
        reason=decision.reason,
        question_id=decision.question_id,
        question=decision.question,
        focus_word=decision.focus_word,
        expires_in_seconds=decision.expires_in_seconds,
    )


@router.post(
    "/feedback",
    response_model=TutorFeedbackResponse,
    status_code=201,
)
def create_tutor_feedback(
    request: TutorFeedbackRequest,
    state: InMemoryTutorState = Depends(get_tutor_state),
) -> TutorFeedbackResponse:
    """Tutor 답변 평가를 개발용 메모리 저장소에 기록한다.

    운영 환경에서는 사용자/DB 계층이 JWT의 ``sub``로 메시지 소유권을 확인하고
    영구 저장소에 기록한다. Tutor 라우터는 답변과 평가의 연결 계약만 유지한다.
    """

    if not state.has_message(
        _DEVELOPMENT_ACTOR_ID,
        request.message_id,
        request.conversation_id,
    ):
        raise HTTPException(
            status_code=404,
            detail="평가할 Tutor 메시지를 찾을 수 없습니다.",
        )

    record = state.create_feedback(
        actor_id=_DEVELOPMENT_ACTOR_ID,
        conversation_id=request.conversation_id,
        message_id=request.message_id,
        rating=request.rating,
        reason=request.reason,
        comment=request.comment,
    )
    if record is None:
        raise HTTPException(
            status_code=409,
            detail="이 Tutor 답변에는 이미 피드백을 남겼습니다.",
        )
    return TutorFeedbackResponse(
        feedback_id=record.feedback_id,
        conversation_id=record.conversation_id,
        message_id=record.message_id,
        rating=record.rating,
        reason=record.reason,
        comment=record.comment,
        created_at=record.created_at,
    )
