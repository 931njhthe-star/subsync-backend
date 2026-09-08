"""Video Tutor 애플리케이션 서비스."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
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
    """모델 답변과 DB 사용량 기록에 필요한 provider 메타데이터."""

    reply: str
    suggested_questions: tuple[str, ...]
    provider: str
    model: str = ""
    usage: TokenUsage = TokenUsage()
    finish_reason: str | None = None
    provider_latency: int | None = None
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
_KOREAN_WORD_RE = re.compile(r"[가-힣]{2,}")
_KOREAN_ENDING_RE = re.compile(
    r"(?:하다|하는|했다|할지|할|한다|이다|이에요|입니다|을|를|은|는|이|가|의|에|로|와|과)$"
)
_HINT_REQUEST_RE = re.compile(
    r"(?:잘\s*)?모르겠(?:어|어요|다)?|힌트|답\s*알려\s*줘"
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
        if result in {"correct", "partial", "incorrect"}:
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


def _extract_reply(parsed: dict[str, object]) -> str | None:
    """provider가 ``reply`` 대신 흔히 쓰는 답변 키를 보수적으로 읽는다."""

    for key in ("reply", "answer", "response", "content"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    message = parsed.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


def _unparsed_response_hint(context: TutorContext) -> str:
    """모든 provider의 형식 복구가 실패했을 때 학습 흐름을 잇는 안전한 답변을 만든다."""

    focus_word = context.focus_word or "이 표현"
    if context.is_proactive_answer:
        current = context.current_subtitle
        if current:
            return (
                f"힌트: '{focus_word}'가 나온 문장 \"{current.english}\"을 다시 보고, "
                "앞뒤 단어가 어떤 의미를 더하는지 생각해 보세요."
            )
        return (
            f"힌트: '{focus_word}'가 문장에서 어떤 역할을 하는지 떠올려 보고, "
            "비슷한 한국어 표현을 찾아보세요."
        )
    return "질문하신 표현을 한 번 더 짧게 적어 주시면, 뜻과 쓰임을 차근차근 설명해 드릴게요."


def _korean_roots(value: str) -> set[str]:
    """한국어 번역과 짧은 답을 비교할 수 있도록 기본 어간 후보를 만든다."""

    roots = set()
    for word in _KOREAN_WORD_RE.findall(value):
        root = _KOREAN_ENDING_RE.sub("", word)
        if len(root) >= 2:
            roots.add(root)
    return roots


def _caption_confirms_answer(context: TutorContext) -> str | None:
    """사용자 답이 자막의 한국어 번역과 명백히 일치하면 그 핵심어를 반환한다."""

    answer_roots = _korean_roots(context.user_message)
    if not answer_roots:
        return None

    subtitle_roots = {
        root
        for subtitle in context.nearby_subtitles
        for root in _korean_roots(subtitle.korean or "")
    }
    matches = answer_roots & subtitle_roots
    return max(matches, key=len) if matches else None


def _apply_caption_answer_check(
    answer: TutorAnswer,
    context: TutorContext,
) -> TutorAnswer:
    """자막 번역에 명시된 정답은 모델의 오판보다 우선한다."""

    matched_word = _caption_confirms_answer(context)
    if not matched_word:
        return answer

    return replace(
        answer,
        proactive_feedback=ProactiveAnswerFeedback(
            result="correct",
            criteria=(
                f"자막의 한국어 번역에도 '{matched_word}'가 나와서 핵심 의미를 잘 짚었어요."
            ),
        ),
    )


def _apply_hint_request_check(
    answer: TutorAnswer,
    context: TutorContext,
) -> TutorAnswer:
    """힌트 요청을 정답으로 오판하지 않고 문맥을 활용한 단서만 제공한다."""

    if not _HINT_REQUEST_RE.search(context.user_message):
        return answer

    focus_word = context.focus_word or "이 표현"
    current = context.current_subtitle
    if current:
        criteria = (
            f"힌트: '{focus_word}'가 나온 문장 \"{current.english}\"을 다시 보고, "
            "문장 전체의 분위기와 앞뒤 단어를 단서로 생각해 보세요."
        )
    else:
        criteria = (
            f"힌트: '{focus_word}'가 문장에서 어떤 역할을 하는지 떠올려 보고, "
            "비슷한 한국어 표현을 찾아보세요."
        )
    return replace(
        answer,
        reply=criteria,
        proactive_feedback=ProactiveAnswerFeedback(
            result="unavailable",
            criteria=criteria,
        ),
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

    reply = _extract_reply(parsed)
    if reply is None:
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
                result in {"correct", "partial", "incorrect"}
                and isinstance(criteria, str)
                and criteria.strip()
            ):
                feedback = ProactiveAnswerFeedback(
                    result=result,
                    criteria=criteria.strip()[:500],
                )

    return TutorAnswer(
        reply=reply[:4_000],
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
    """한 provider 응답을 정규화하고, 형식 오류면 다음 fallback을 시도하게 한다."""

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
    if parsed.reply == invalid_response_reply:
        # JSON 복구에도 답변 필드를 찾지 못한 provider는 성공으로 처리하지 않는다.
        # 그래야 TutorService가 네트워크 없는 fallback까지 한 번 더 시도할 수 있다.
        raise LLMError("LLM response did not contain a usable reply")
    return TutorAnswer(
        reply=parsed.reply,
        suggested_questions=parsed.suggested_questions,
        provider=generation.provider,
        model=generation.model,
        usage=generation.usage,
        finish_reason=generation.finish_reason,
        provider_latency=generation.provider_latency,
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
        recovery_reply = _unparsed_response_hint(context)

        try:
            answer = await _generate_answer(
                self.llm_client,
                prompt,

                invalid_response_reply=(
                    "답변을 정리하는 중에 문제가 있었어요. 자막 속 어떤 표현이 "
                    "궁금한지 다시 알려 주세요."
                ),

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
                    invalid_response_reply=(
                        "지금은 자막 문맥을 제대로 불러오지 못했어요. 잠시 후 다시 "
                        "질문해 주세요."
                    ),
                    expects_proactive_feedback=command.is_proactive_answer,
                )
            except LLMError:
                answer = TutorAnswer(
                    reply=(
                        "지금은 자막 문맥을 제대로 불러오지 못했어요. 잠시 후 다시 "
                        "질문해 주세요."
                    ),

                    suggested_questions=(),
                    provider=fallback_provider,
                    model=getattr(self.fallback_client, "model", ""),
                )

        if command.is_proactive_answer:
            # 모델이 이전 대화의 짧은 "예" 등을 현재 답으로 잘못 읽어도, 현재
            # 자막 번역에 명시된 답은 안정적으로 정답 처리한다.
            answer = _apply_caption_answer_check(answer, context)
            # "모르겠어"·힌트 요청은 답안이 아니므로, 모델의 과도한 정답 판정보다
            # 우선해 정답을 직접 알려주지 않는 힌트 모드로 돌린다.
            answer = _apply_hint_request_check(answer, context)

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
