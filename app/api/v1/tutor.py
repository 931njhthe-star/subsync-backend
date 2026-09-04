"""Video Tutor HTTP API와 provider 의존성 구성을 담당한다.

요청 DTO를 애플리케이션 서비스의 도메인 객체로 변환하고, 환경변수에 따라
Gemini/Groq/stub provider 조합을 한 번만 생성한다. 실제 튜터 로직은 이 모듈이
아닌 ``app.ai.tutor_service``에서 수행한다.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException

from app.ai.context_builder import ConversationTurn, SubtitleLine
from app.ai.learner_profile import LearnerSignals
from app.ai.llm_client import GeminiClient, GroqClient, RuleBasedTutorClient
from app.ai.provider_router import ProviderQuota, ProviderRouter
from app.ai.reply_tokenizer import extract_reply_tokens
from app.ai.tutor_state import InMemoryTutorState
from app.ai.tutor_service import TutorAskCommand, TutorService
from app.ai.usage_tracker import InMemoryUsageTracker
from app.core.config import settings
from app.schemas.tutor import (
    ProactiveTutorRequest,
    ProactiveTutorResponse,
    ReplyTokenResponse,
    TutorAskRequest,
    TutorAskResponse,
    TutorFeedbackRequest,
    TutorFeedbackResponse,
    TutorSettingsResponse,
    TutorSettingsUpdateRequest,
    TutorUsageResponse,
)


router = APIRouter(prefix="/tutor", tags=["Video Tutor"])

# Supabase Auth dependency가 연결되기 전까지 로컬에서 사용할 개발용 actor다.
# 운영 환경에서는 이 값을 사용하지 않고 검증된 JWT의 sub로 교체해야 한다.
_DEVELOPMENT_ACTOR_ID = "anonymous"


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

    대화·설정·선제 질문 이력·피드백을 요청 사이에 유지하려면 매 요청마다 새
    저장소를 만들면 안 된다. 실제 사용자별 영구 저장소가 연결되면 이 dependency를
    Supabase/Redis repository로 교체한다.
    """

    return InMemoryTutorState(
        proactive_cooldown_seconds=settings.tutor_proactive_cooldown_seconds,
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
    )
    groq_client = GroqClient(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        timeout_seconds=settings.groq_timeout_seconds,
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
    )
    return TutorService(router, fallback_client=stub_client)


@router.post("/ask", response_model=TutorAskResponse)
async def ask_tutor(
    request: TutorAskRequest,
    service: TutorService = Depends(get_tutor_service),
    state: InMemoryTutorState = Depends(get_tutor_state),
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
        서버가 학습 신호를 조회해야 한다.
    """

    if not state.get_settings(_DEVELOPMENT_ACTOR_ID).tutor_enabled:
        raise HTTPException(
            status_code=409,
            detail="Tutor가 비활성화되어 있습니다.",
        )

    if not state.allow_request(_DEVELOPMENT_ACTOR_ID):
        raise HTTPException(
            status_code=429,
            detail="Tutor 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
        )

    signals = request.learner_signals
    stored_history = None
    if request.conversation_id:
        stored_history = state.get_conversation_history(
            _DEVELOPMENT_ACTOR_ID,
            request.conversation_id,
        )
        stored_video_id = state.get_conversation_video_id(
            _DEVELOPMENT_ACTOR_ID,
            request.conversation_id,
        )
        if stored_video_id is None:
            raise HTTPException(
                status_code=404,
                detail="이어갈 Tutor 대화를 찾을 수 없습니다.",
            )
        if stored_video_id != request.video_id:
            raise HTTPException(
                status_code=409,
                detail="Tutor 대화와 영상 ID가 일치하지 않습니다.",
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

    # HTTP 경계의 Pydantic DTO를 AI 계층이 사용하는 불변 도메인 객체로 변환한다.
    result = await service.ask(
        TutorAskCommand(
            video_id=request.video_id,
            timestamp=request.timestamp,
            user_message=request.user_message,
            subtitles=tuple(
                SubtitleLine(timestamp=line.time, english=line.en, korean=line.ko)
                for line in request.recent_subtitles
            ),
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
            focus_word=request.focus_word,
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
    )

    return TutorAskResponse(
        conversation_id=result.conversation_id,
        message_id=result.message_id,
        reply=result.answer.reply,
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
        reply_tokens=[
            ReplyTokenResponse(
                surface=token.surface,
                normalized=token.normalized,
                start=token.start,
                end=token.end,
                interactive=token.interactive,
            )
            for token in extract_reply_tokens(result.answer.reply)
        ],
    )


@router.get("/settings", response_model=TutorSettingsResponse)
def get_tutor_settings(
    state: InMemoryTutorState = Depends(get_tutor_state),
) -> TutorSettingsResponse:
    """개발용 actor의 Tutor ON/OFF 설정을 조회한다.

    현재는 Supabase Auth가 연결되지 않아 모든 로컬 요청이 anonymous actor로
    처리된다. 운영 전환 시 인증 dependency에서 사용자 ID를 주입해야 한다.
    """

    current = state.get_settings(_DEVELOPMENT_ACTOR_ID)
    return TutorSettingsResponse(
        tutor_enabled=current.tutor_enabled,
        updated_at=current.updated_at,
    )


@router.patch("/settings", response_model=TutorSettingsResponse)
def update_tutor_settings(
    request: TutorSettingsUpdateRequest,
    state: InMemoryTutorState = Depends(get_tutor_state),
) -> TutorSettingsResponse:
    """개발용 actor의 Tutor ON/OFF 설정을 변경한다."""

    updated = state.set_tutor_enabled(
        _DEVELOPMENT_ACTOR_ID,
        request.tutor_enabled,
    )
    return TutorSettingsResponse(
        tutor_enabled=updated.tutor_enabled,
        updated_at=updated.updated_at,
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
        last_question_id=request.last_question_id,
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
    """Tutor 답변 평가를 개발용 메모리 저장소에 기록한다."""

    if not state.has_message(
        _DEVELOPMENT_ACTOR_ID,
        request.message_id,
        request.conversation_id,
    ):
        raise HTTPException(
            status_code=404,
            detail="평가할 Tutor 메시지를 찾을 수 없습니다.",
        )

    record = state.record_feedback(
        actor_id=_DEVELOPMENT_ACTOR_ID,
        conversation_id=request.conversation_id,
        message_id=request.message_id,
        rating=request.rating,
        reason=request.reason,
        comment=request.comment,
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
