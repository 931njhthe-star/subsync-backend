"""Video Tutor 문맥·프로필·provider fallback 계약을 검증한다."""

import pytest
from fastapi.testclient import TestClient

from app.ai.reply_tokenizer import extract_reply_tokens
from app.ai.context_builder import SubtitleLine, build_tutor_context
from app.ai.learner_profile import (
    CEFRLevel,
    LearnerSignals,
    TutorDifficulty,
    infer_learner_profile,
)
from app.ai.llm_client import (
    GeminiClient,
    GroqClient,
    LLMError,
    LLMGeneration,
    TokenUsage,
)
from app.ai.prompts import build_tutor_prompt
from app.ai.provider_router import ProviderQuota, ProviderRouter
from app.api.v1.tutor import get_tutor_state
from app.ai.tutor_service import TutorAskCommand, TutorService
from app.ai.usage_tracker import InMemoryUsageTracker
from app.main import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_development_tutor_state():
    """메모리 기반 Tutor 상태가 테스트 사이에 섞이지 않도록 초기화한다."""

    state = get_tutor_state()
    original_requests_per_minute = state.requests_per_minute
    state.reset()
    yield
    state.reset()
    state.requests_per_minute = original_requests_per_minute


def test_empty_signals_keep_safe_a2_default():
    profile = infer_learner_profile(LearnerSignals())

    assert profile.level is CEFRLevel.A2
    assert profile.tutor_difficulty is TutorDifficulty.GUIDED
    assert profile.confidence == 0


def test_strong_recent_signals_raise_tutor_difficulty():
    profile = infer_learner_profile(
        LearnerSignals(
            saved_word_count=180,
            quiz_attempts=20,
            accuracy=0.96,
            average_response_time_ms=2_200,
        )
    )

    assert profile.level is CEFRLevel.C1
    assert profile.tutor_difficulty is TutorDifficulty.CHALLENGE
    assert profile.confidence == 1


def test_context_is_local_to_current_timestamp_and_deduplicates_words():
    context = build_tutor_context(
        video_id="video-1",
        timestamp=20,
        user_message="이 표현이 뭐예요?",
        subtitles=[
            SubtitleLine(0, "first", "첫째"),
            SubtitleLine(10, "second", "둘째"),
            SubtitleLine(20, "current", "현재"),
            SubtitleLine(30, "next", "다음"),
        ],
        saved_words=["honest", "HONEST", "yourself"],
    )

    assert context.current_subtitle is not None
    assert context.current_subtitle.english == "current"
    assert [line.english for line in context.nearby_subtitles] == [
        "first",
        "second",
        "current",
        "next",
    ]
    assert context.saved_words == ("honest", "yourself")


def test_prompt_marks_subtitles_as_reference_data():
    context = build_tutor_context(
        video_id="video-1",
        timestamp=20,
        user_message="honest가 어떤 뜻인가요?",
        subtitles=[SubtitleLine(20, "Be honest with yourself.", "너 자신에게 솔직해.")],
    )
    profile = infer_learner_profile(LearnerSignals())
    prompt = build_tutor_prompt(context, profile)

    assert "untrusted reference data" in prompt.system_instruction
    assert "Be honest with yourself." in prompt.user_prompt
    assert "guided" in prompt.system_instruction


def test_tutor_api_works_without_gemini_key():
    response = client.post(
        "/api/v1/tutor/ask",
        json={
            "video_id": "arj7oStGLkU",
            "timestamp": 156.4,
            "user_message": "be honest with는 언제 쓰나요?",
            "recent_subtitles": [
                {
                    "time": 156.4,
                    "en": "I want to be honest with you.",
                    "ko": "솔직하게 말씀드리고 싶어요.",
                }
            ],
            "learner_signals": {
                "saved_words": [{"word": "honest"}],
                "quiz_accuracy": 0.72,
                "average_response_time_ms": 7_500,
                "quiz_attempts": 6,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["learner_level"] == "A2"
    assert body["tutor_difficulty"] == "guided"
    assert body["context_subtitle_count"] == 1
    assert "honest" in body["reply"]
    assert body["message_id"].startswith("msg_")
    assert body["reply_tokens"]


def test_reply_tokens_use_javascript_compatible_utf16_offsets():
    """이모지처럼 2개의 UTF-16 unit을 차지하는 문자가 있어도 offset이 맞아야 한다."""

    tokens = extract_reply_tokens("😀 honest")

    assert len(tokens) == 1
    assert tokens[0].surface == "honest"
    assert tokens[0].normalized == "honest"
    assert tokens[0].start == 3
    assert tokens[0].end == 9


def test_tutor_conversation_id_reuses_in_memory_history():
    """첫 답변의 conversation_id를 다시 보내면 같은 대화 ID와 이력을 유지한다."""

    first = client.post(
        "/api/v1/tutor/ask",
        json={
            "video_id": "conversation-video",
            "timestamp": 1,
            "user_message": "honest가 무슨 뜻인가요?",
            "recent_subtitles": [
                {"time": 1, "en": "Be honest with yourself.", "ko": "너 자신에게 솔직해."}
            ],
        },
    )
    conversation_id = first.json()["conversation_id"]

    second = client.post(
        "/api/v1/tutor/ask",
        json={
            "video_id": "conversation-video",
            "timestamp": 2,
            "user_message": "다른 예문도 보여줘.",
            "conversation_id": conversation_id,
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["conversation_id"] == conversation_id
    history = get_tutor_state().get_conversation_history("anonymous", conversation_id)
    assert history is not None
    assert len(history) == 4
    assert history[-1].role == "tutor"


def test_unknown_conversation_id_is_not_silently_created():
    """존재하지 않는 conversation_id를 새 대화로 조용히 바꾸지 않는다."""

    response = client.post(
        "/api/v1/tutor/ask",
        json={
            "video_id": "conversation-video",
            "timestamp": 1,
            "user_message": "질문",
            "conversation_id": "conv_missing",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "이어갈 Tutor 대화를 찾을 수 없습니다."


def test_conversation_cannot_be_reused_for_another_video():
    """한 영상의 대화 ID를 다른 영상 문맥에 재사용하지 못하게 한다."""

    first = client.post(
        "/api/v1/tutor/ask",
        json={
            "video_id": "conversation-video",
            "timestamp": 1,
            "user_message": "질문",
        },
    )
    conversation_id = first.json()["conversation_id"]

    response = client.post(
        "/api/v1/tutor/ask",
        json={
            "video_id": "different-video",
            "timestamp": 1,
            "user_message": "다른 영상 질문",
            "conversation_id": conversation_id,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Tutor 대화와 영상 ID가 일치하지 않습니다."


def test_tutor_request_rate_limit_resets_after_one_minute():
    """분당 제한을 넘긴 뒤 시간이 지나면 다시 요청할 수 있다."""

    from app.ai.tutor_state import InMemoryTutorState

    now = [100.0]
    state = InMemoryTutorState(
        requests_per_minute=2,
        clock=lambda: now[0],
    )

    assert state.allow_request("user-1") is True
    assert state.allow_request("user-1") is True
    assert state.allow_request("user-1") is False

    now[0] = 160.0
    assert state.allow_request("user-1") is True


def test_tutor_api_returns_429_after_request_limit():
    """HTTP API도 설정된 분당 한도를 넘기면 429를 반환한다."""

    get_tutor_state().requests_per_minute = 1
    payload = {
        "video_id": "rate-limit-video",
        "timestamp": 1,
        "user_message": "첫 질문",
    }

    first = client.post("/api/v1/tutor/ask", json=payload)
    second = client.post(
        "/api/v1/tutor/ask",
        json={**payload, "user_message": "두 번째 질문"},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"] == (
        "Tutor 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."
    )


def test_tutor_settings_disable_manual_and_proactive_questions():
    """Tutor OFF가 수동 질문과 선제 질문 모두에 반영되는지 확인한다."""

    updated = client.patch(
        "/api/v1/tutor/settings",
        json={"tutor_enabled": False},
    )
    assert updated.status_code == 200
    assert updated.json()["tutor_enabled"] is False

    ask_response = client.post(
        "/api/v1/tutor/ask",
        json={
            "video_id": "off-video",
            "timestamp": 1,
            "user_message": "질문",
        },
    )
    proactive_response = client.post(
        "/api/v1/tutor/proactive",
        json={
            "video_id": "off-video",
            "timestamp": 1,
            "recent_subtitles": [
                {"time": 1, "en": "Be honest with yourself."}
            ],
        },
    )

    assert ask_response.status_code == 409
    assert proactive_response.status_code == 200
    assert proactive_response.json() == {
        "should_show": False,
        "reason": "disabled",
        "question_id": None,
        "question": None,
        "focus_word": None,
        "expires_in_seconds": None,
    }


def test_proactive_question_applies_cooldown_and_seen_word_guard():
    """선제 질문이 새 표현에만 노출되고 짧은 간격의 반복을 차단하는지 확인한다."""

    payload = {
        "video_id": "proactive-video",
        "timestamp": 10,
        "recent_subtitles": [
            {"time": 10, "en": "I want to be honest with you."}
        ],
    }
    first = client.post("/api/v1/tutor/proactive", json=payload)
    second = client.post(
        "/api/v1/tutor/proactive",
        json={**payload, "timestamp": 20},
    )
    third = client.post(
        "/api/v1/tutor/proactive",
        json={**payload, "timestamp": 100},
    )

    assert first.json()["should_show"] is True
    assert first.json()["focus_word"] == "honest"
    assert second.json()["reason"] == "cooldown"
    assert third.json()["reason"] == "already_seen"


def test_tutor_feedback_is_recorded_for_an_existing_message():
    """질문 답변으로 생성된 메시지에 대해서만 피드백을 저장한다."""

    ask_response = client.post(
        "/api/v1/tutor/ask",
        json={
            "video_id": "feedback-video",
            "timestamp": 1,
            "user_message": "질문",
        },
    )
    body = ask_response.json()
    feedback_response = client.post(
        "/api/v1/tutor/feedback",
        json={
            "conversation_id": body["conversation_id"],
            "message_id": body["message_id"],
            "rating": "not_helpful",
            "reason": "too_difficult",
            "comment": "설명이 조금 어려웠어요.",
        },
    )
    missing_response = client.post(
        "/api/v1/tutor/feedback",
        json={
            "conversation_id": body["conversation_id"],
            "message_id": "msg_missing",
            "rating": "not_helpful",
        },
    )

    assert feedback_response.status_code == 201
    assert feedback_response.json()["message_id"] == body["message_id"]
    assert feedback_response.json()["reason"] == "too_difficult"
    assert feedback_response.json()["comment"] == "설명이 조금 어려웠어요."
    assert missing_response.status_code == 404


class FailingClient:
    """주 provider 장애를 재현하는 테스트용 client."""

    name = "gemini"

    async def generate(self, prompt):
        raise LLMError("down")


def test_service_uses_fallback_when_provider_fails():
    service = TutorService(FailingClient())

    import asyncio

    result = asyncio.run(
        service.ask(
            TutorAskCommand(
                video_id="v",
                timestamp=0,
                user_message="질문",
                subtitles=(SubtitleLine(0, "Hello", "안녕"),),
            )
        )
    )

    assert result.answer.provider == "stub"
    assert result.answer.reply


class FakeGroqResponse:
    """Groq 성공 응답과 usage metadata를 재현하는 테스트 객체."""

    is_error = False
    status_code = 200
    text = ""
    headers = {}

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"reply":"Groq 답변", "suggested_questions":[]}'
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 321,
                "completion_tokens": 45,
                "total_tokens": 366,
            },
        }


class FakeGeminiResponse:
    """Gemini 성공 응답과 usage metadata를 재현하는 테스트 객체."""

    is_error = False
    status_code = 200
    text = ""
    headers = {}

    def json(self):
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": '{"reply":"Gemini 답변", "suggested_questions":[]}'
                            }
                        ]
                    }
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 321,
                "candidatesTokenCount": 45,
                "totalTokenCount": 366,
            },
        }


class FakeAsyncClient:
    """실제 네트워크 대신 Groq HTTP 호출을 가로채는 async client."""

    response = FakeGroqResponse()
    last_call = None

    def __init__(self, *, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def post(self, url, *, headers, json):
        type(self).last_call = {
            "url": url,
            "headers": headers,
            "json": json,
        }
        return self.response


def test_groq_client_parses_openai_compatible_response(monkeypatch):
    import asyncio
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    prompt = build_tutor_prompt(
        build_tutor_context(
            video_id="v",
            timestamp=0,
            user_message="질문",
            subtitles=(SubtitleLine(0, "Hello", "안녕"),),
        ),
        infer_learner_profile(LearnerSignals()),
    )

    generation = asyncio.run(
        GroqClient(api_key="gsk_test").generate(prompt)
    )

    assert isinstance(generation, LLMGeneration)
    assert generation.provider == "groq"
    assert generation.model == "openai/gpt-oss-20b"
    assert generation.usage.total_tokens == 366
    assert FakeAsyncClient.last_call["url"].endswith("/chat/completions")
    assert FakeAsyncClient.last_call["headers"]["Authorization"] == "Bearer gsk_test"


def test_gemini3_client_limits_thinking_level_for_tutor_json(monkeypatch):
    import asyncio
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(FakeAsyncClient, "response", FakeGeminiResponse())
    prompt = build_tutor_prompt(
        build_tutor_context(
            video_id="v",
            timestamp=0,
            user_message="질문",
            subtitles=(SubtitleLine(0, "Hello", "안녕"),),
        ),
        infer_learner_profile(LearnerSignals()),
    )

    generation = asyncio.run(
        GeminiClient(api_key="AIza_test", model="gemini-3.6-flash").generate(prompt)
    )

    assert generation.provider == "gemini"
    assert generation.model == "gemini-3.6-flash"
    assert generation.usage.total_tokens == 366
    assert FakeAsyncClient.last_call["json"]["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "low"
    }


class QuotaFailingClient:
    """Gemini quota 초과 HTTP 429를 재현하는 테스트용 client."""

    name = "gemini"
    model = "gemini-3.6-flash"
    is_configured = True

    async def generate(self, prompt):
        raise LLMError(
            "quota exceeded",
            provider=self.name,
            status_code=429,
            retry_after_seconds=0,
        )


class SuccessfulGroqClient:
    """fallback 성공 generation을 반환하는 테스트용 Groq client."""

    name = "groq"
    model = "openai/gpt-oss-20b"
    is_configured = True

    async def generate(self, prompt):
        return LLMGeneration(
            text='{"reply":"Groq fallback", "suggested_questions":[]}',
            provider=self.name,
            model=self.model,
            usage=TokenUsage(input_tokens=100, output_tokens=20, total_tokens=120),
        )


def test_provider_router_falls_back_to_groq_on_quota_error():
    import asyncio

    tracker = InMemoryUsageTracker()
    router = ProviderRouter(
        (QuotaFailingClient(), SuccessfulGroqClient()),
        usage_tracker=tracker,
        failure_cooldown_seconds=0,
    )

    result = asyncio.run(
        TutorService(router).ask(
            TutorAskCommand(
                video_id="v",
                timestamp=0,
                user_message="질문",
                subtitles=(SubtitleLine(0, "Hello", "안녕"),),
            )
        )
    )

    assert result.answer.provider == "groq"
    assert result.answer.model == "openai/gpt-oss-20b"
    assert result.answer.usage.normalized_total == 120
    assert tracker.snapshot()["groq"]["total_tokens"] == 120


def test_provider_router_skips_provider_at_local_token_limit():
    import asyncio

    tracker = InMemoryUsageTracker()
    tracker.record(
        LLMGeneration(
            text="previous",
            provider="gemini",
            model="gemini-3.6-flash",
            usage=TokenUsage(input_tokens=900, output_tokens=100, total_tokens=1_000),
        )
    )
    router = ProviderRouter(
        (QuotaFailingClient(), SuccessfulGroqClient()),
        usage_tracker=tracker,
        quotas={"gemini": ProviderQuota(daily_token_limit=1_001)},
    )

    result = asyncio.run(
        router.generate(
            build_tutor_prompt(
                build_tutor_context(
                    video_id="v",
                    timestamp=0,
                    user_message="질문",
                    subtitles=(),
                ),
                infer_learner_profile(LearnerSignals()),
            )
        )
    )

    assert result.provider == "groq"
