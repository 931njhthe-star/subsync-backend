"""Video Tutor HTTP API와 provider 의존성 구성을 담당한다.

요청 DTO를 애플리케이션 서비스의 도메인 객체로 변환하고, 환경변수에 따라
Gemini/Groq/stub provider 조합을 한 번만 생성한다. 실제 튜터 로직은 이 모듈이
아닌 ``app.ai.tutor_service``에서 수행한다.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends

from app.ai.context_builder import ConversationTurn, SubtitleLine
from app.ai.learner_profile import LearnerSignals
from app.ai.llm_client import GeminiClient, GroqClient, RuleBasedTutorClient
from app.ai.provider_router import ProviderQuota, ProviderRouter
from app.ai.tutor_service import TutorAskCommand, TutorService
from app.ai.usage_tracker import InMemoryUsageTracker
from app.core.config import settings
from app.schemas.tutor import TutorAskRequest, TutorAskResponse, TutorUsageResponse


router = APIRouter(prefix="/tutor", tags=["Video Tutor"])


@lru_cache(maxsize=1)
def get_usage_tracker() -> InMemoryUsageTracker:
    """프로세스에서 공유할 개발용 토큰 usage tracker를 생성한다.

    ``lru_cache``를 사용하는 이유는 요청마다 기록 저장소가 새로 만들어지면
    quota 계산이 누적되지 않기 때문이다. 현재 구현은 메모리 저장소이므로 서버
    재시작 시 기록이 초기화된다.
    """

    return InMemoryUsageTracker()


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

    signals = request.learner_signals
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
            conversation_history=tuple(
                ConversationTurn(role=turn.role, message=turn.message)
                for turn in request.conversation_history
            ),
            focus_word=request.focus_word,
        )
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
    )
