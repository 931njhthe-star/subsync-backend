"""Video Tutor 애플리케이션 서비스."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from uuid import uuid4

from app.ai.context_builder import (
    ConversationTurn,
    SubtitleLine,
    TutorContext,
    build_tutor_context,
)
from app.ai.learner_profile import LearnerProfile, LearnerSignals, infer_learner_profile
from app.ai.llm_client import (
    LLMClient,
    LLMError,
    LLMGeneration,
    RuleBasedTutorClient,
    TokenUsage,
)
from app.ai.prompts import TutorPrompt, build_tutor_prompt


@dataclass(frozen=True)
class TutorAskCommand:
    """Tutor 답변 생성에 필요한 애플리케이션 서비스 입력."""

    video_id: str
    timestamp: float
    user_message: str
    subtitles: tuple[SubtitleLine, ...]
    learner_signals: LearnerSignals = LearnerSignals()
    conversation_history: tuple[ConversationTurn, ...] = ()
    focus_word: str | None = None
    is_proactive_answer: bool = False
    conversation_id: str | None = None


@dataclass(frozen=True)
class TutorAnswer:
    """모델 답변과 어떤 provider가 생성했는지에 대한 메타데이터."""

    reply: str
    suggested_questions: tuple[str, ...]
    provider: str
    model: str = ""
    usage: TokenUsage = TokenUsage()
    proactive_feedback: ProactiveAnswerFeedback | None = None


@dataclass(frozen=True)
class ProactiveAnswerFeedback:
    """Tutor 선제 질문에 대한 사용자의 답 판정과 기준."""

    result: str
    criteria: str


@dataclass(frozen=True)
class TutorResult:
    """Tutor service가 반환하는 답변·프로필·문맥 묶음."""

    conversation_id: str
    message_id: str
    answer: TutorAnswer
    profile: LearnerProfile
    context: TutorContext


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_PARTIAL_JSON_FIELD_RE = re.compile(
    r'"(?P<field>reply|result|criteria)"\s*:\s*"(?P<value>(?:\\.|[^"\\])*)(?:"|$)'
)


def _partial_json_field(raw: str, field: str) -> str | None:
    """끝이 잘린 JSON에서도 이미 완성된 문자열 필드를 안전하게 읽는다."""

    for match in _PARTIAL_JSON_FIELD_RE.finditer(raw):
        if match.group("field") != field:
            continue
        value = match.group("value")
        try:
            return json.loads(f'"{value}"')
        except json.JSONDecodeError:
            # 끝이 잘린 마지막 문자열은 탈출 문자가 완전하지 않을 수 있다.
            return value.replace("\\n", "\n").replace('\\"', '"').strip()
    return None


def _recover_truncated_json(
    raw: str,
    fallback: TutorAnswer,
    *,
    expects_proactive_feedback: bool,
) -> TutorAnswer:
    """토큰 한도로 끊긴 JSON에서 완성된 답변과 판정값만 복구한다."""

    reply = _partial_json_field(raw, "reply")
    if not reply or not reply.strip():
        return fallback

    feedback = None
    if expects_proactive_feedback:
        result = _partial_json_field(raw, "result")
        criteria = _partial_json_field(raw, "criteria")
        if result in {"correct", "partial", "incorrect", "unavailable"}:
            feedback = ProactiveAnswerFeedback(
                result=result,
                # criteria가 잘린 경우에도 reply에는 모델이 이미 설명한 핵심이 있다.
                criteria=(criteria or reply).strip()[:500],
            )

    return TutorAnswer(
        reply=reply.strip()[:4_000],
        suggested_questions=(),
        provider=fallback.provider,
        proactive_feedback=feedback,
    )


def _parse_model_response(
    raw: str,
    fallback: TutorAnswer,
    *,
    expects_proactive_feedback: bool = False,
) -> TutorAnswer:
    """모델 원문을 Tutor 응답 shape으로 정규화한다.

    모델이 JSON만 반환하도록 요청하더라도 provider에 따라 code fence나 앞뒤
    설명이 붙을 수 있다. JSON이 아닌 짧은 텍스트는 답변으로 사용하고, 토큰 한도로
    잘린 JSON은 완성된 ``reply``와 판정 필드만 복구한다.
    """

    if not raw or not raw.strip():
        return fallback

    candidate = _FENCE_RE.sub("", raw.strip()).strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        # 모델이 JSON 앞뒤에 짧은 설명을 붙이는 경우를 위한 최소 복구.
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            if candidate.lstrip().startswith("{"):
                return _recover_truncated_json(
                    candidate,
                    fallback,
                    expects_proactive_feedback=expects_proactive_feedback,
                )
            return TutorAnswer(
                reply=candidate[:4_000],
                suggested_questions=fallback.suggested_questions,
                provider=fallback.provider,
            )
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            return _recover_truncated_json(
                candidate,
                fallback,
                expects_proactive_feedback=expects_proactive_feedback,
            )

    if not isinstance(parsed, dict):
        return fallback

    reply = parsed.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        return fallback

    suggestions = parsed.get("suggested_questions", [])
    if not isinstance(suggestions, list):
        suggestions = []
    clean_suggestions: list[str] = []
    for suggestion in suggestions:
        if isinstance(suggestion, str) and suggestion.strip():
            clean_suggestions.append(suggestion.strip()[:200])
        if len(clean_suggestions) == 3:
            break

    feedback = None
    if expects_proactive_feedback:
        value = parsed.get("proactive_feedback")
        if isinstance(value, dict):
            result = value.get("result")
            criteria = value.get("criteria")
            if (
                result in {"correct", "partial", "incorrect", "unavailable"}
                and isinstance(criteria, str)
                and criteria.strip()
            ):
                feedback = ProactiveAnswerFeedback(
                    result=result,
                    criteria=criteria.strip()[:500],
                )

    return TutorAnswer(
        reply=reply.strip()[:4_000],
        suggested_questions=tuple(clean_suggestions),
        provider=fallback.provider,
        proactive_feedback=feedback,
    )


def _coerce_generation(raw: str | LLMGeneration, client: LLMClient) -> LLMGeneration:
    """기존 문자열 반환 client와 usage를 반환하는 client를 함께 지원한다."""

    if isinstance(raw, LLMGeneration):
        return raw
    if isinstance(raw, str):
        return LLMGeneration(
            text=raw,
            provider=getattr(client, "name", "llm"),
            model=getattr(client, "model", ""),
        )
    raise LLMError("LLM provider returned an unsupported result")


async def _generate_answer(
    client: LLMClient,
    prompt: TutorPrompt,
    *,
    invalid_response_reply: str,
    expects_proactive_feedback: bool,
) -> TutorAnswer:
    """한 provider의 응답을 API가 반환할 Tutor 답변으로 정규화한다."""

    generation = _coerce_generation(await client.generate(prompt), client)
    parsed = _parse_model_response(
        generation.text,
        TutorAnswer(
            reply=invalid_response_reply,
            suggested_questions=(),
            provider=generation.provider,
            model=generation.model,
            usage=generation.usage,
        ),
        expects_proactive_feedback=expects_proactive_feedback,
    )
    return TutorAnswer(
        reply=parsed.reply,
        suggested_questions=parsed.suggested_questions,
        provider=generation.provider,
        model=generation.model,
        usage=generation.usage,
        proactive_feedback=parsed.proactive_feedback,
    )


class TutorService:
    """문맥/프로필/LLM을 조합하는 오케스트레이터.

    ``llm_client``를 주입할 수 있으므로 실제 Gemini 없이도 단위 테스트가 가능하다.
    이후 DB 연동 시 ``TutorAskCommand.learner_signals``를 repository 조회 결과로
    채우면 API 계약은 유지된다.
    """

    def __init__(self, llm_client: LLMClient, fallback_client: LLMClient | None = None):
        """주 provider와 최종 네트워크 없는 fallback을 주입한다."""

        self.llm_client = llm_client
        self.fallback_client = fallback_client or RuleBasedTutorClient()

    async def ask(self, command: TutorAskCommand) -> TutorResult:
        """문맥 구성, 수준 추론, prompt 생성, LLM 호출을 순서대로 수행한다.

        주 provider가 실패하면 fallback client를 한 번 호출한다. ProviderRouter를
        주 provider로 전달한 경우 Gemini/Groq 사이의 전환은 router가 처리하고,
        이 service의 fallback은 모든 외부 provider가 실패했을 때만 사용된다.
        """

        profile = infer_learner_profile(command.learner_signals)
        context = build_tutor_context(
            video_id=command.video_id,
            timestamp=command.timestamp,
            user_message=command.user_message,
            subtitles=command.subtitles,
            saved_words=command.learner_signals.saved_words,
            conversation_history=command.conversation_history,
            focus_word=command.focus_word,
            is_proactive_answer=command.is_proactive_answer,
        )
        prompt = build_tutor_prompt(context, profile)

        try:
            answer = await _generate_answer(
                self.llm_client,
                prompt,
                invalid_response_reply="모델 응답을 해석하지 못했습니다.",
                expects_proactive_feedback=command.is_proactive_answer,
            )
        except LLMError:
            # 외부 모델 오류를 사용자에게 노출하지 않고, 현재 자막을 포함한
            # 네트워크 없는 안내 답변을 제공한다.
            fallback_provider = getattr(self.fallback_client, "name", "fallback")
            try:
                answer = await _generate_answer(
                    self.fallback_client,
                    prompt,
                    invalid_response_reply="문맥을 불러오지 못했습니다.",
                    expects_proactive_feedback=command.is_proactive_answer,
                )
            except LLMError:
                answer = TutorAnswer(
                    reply="문맥을 불러오지 못했습니다.",
                    suggested_questions=(),
                    provider=fallback_provider,
                    model=getattr(self.fallback_client, "model", ""),
                )

        return TutorResult(
            # 클라이언트가 기존 대화를 전달하면 같은 ID를 유지하고, 첫 질문이면
            # 새 opaque ID를 발급해 다음 요청에서 대화를 이어갈 수 있게 한다.
            conversation_id=command.conversation_id or f"conv_{uuid4().hex[:12]}",
            message_id=f"msg_{uuid4().hex[:12]}",
            answer=answer,
            profile=profile,
            context=context,
        )


__all__ = [
    "TutorAskCommand",
    "TutorAnswer",
    "TutorResult",
    "ProactiveAnswerFeedback",
    "TutorService",
    "_parse_model_response",
]
