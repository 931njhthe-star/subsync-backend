"""LLM provider 어댑터.

도메인 코드는 provider별 SDK나 응답 형식에 의존하지 않는다. Gemini와 Groq는
각각의 REST 응답을 ``LLMGeneration``으로 정규화하고, 실제 provider 장애/한도
초과는 ``LLMError``의 메타데이터로 전달한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from app.ai.prompts import TutorPrompt


class LLMError(RuntimeError):
    """LLM 호출 또는 응답 처리 실패.

    ``status_code=429``인 경우 provider quota/rate limit으로 간주할 수 있다.
    ``retry_after_seconds``는 provider가 보낸 ``Retry-After`` 헤더를 보존한다.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class TokenUsage:
    """provider 응답에서 정규화한 토큰 사용량."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    @property
    def normalized_total(self) -> int:
        """total 필드가 없는 provider 응답에도 사용할 수 있는 총량."""

        return self.total_tokens or self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class LLMGeneration:
    """모델 원문 응답과 provider/usage 메타데이터."""

    text: str
    provider: str
    model: str
    usage: TokenUsage = TokenUsage()


class LLMClient(Protocol):
    """Tutor service가 의존하는 최소 LLM provider 계약."""

    async def generate(self, prompt: TutorPrompt) -> str | LLMGeneration:
        """프롬프트를 받아 모델 원문 응답 또는 정규화 응답을 반환한다."""


def _as_non_negative_int(value: object) -> int:
    """provider 응답의 토큰 값을 음수가 아닌 정수로 변환한다."""

    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def _retry_after_seconds(headers: object) -> float | None:
    """Retry-After 헤더를 안전하게 숫자로 변환한다."""

    try:
        value = headers.get("retry-after")  # type: ignore[union-attr]
    except AttributeError:
        return None
    if value is None:
        return None
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return None


class RuleBasedTutorClient:
    """개발/테스트용 네트워크 없는 fallback.

    실제 튜터 품질을 대체하는 구현은 아니며, API 계약과 전체 파이프라인을 검증하기
    위한 안전한 응답이다. 외부 provider가 모두 실패해도 사용자가 문맥을 잃지 않도록 한다.
    """

    name = "stub"
    model = "rule-based"
    is_configured = True

    async def generate(self, prompt: TutorPrompt) -> str:
        """네트워크 없이 문맥을 포함한 JSON 형식의 개발용 답변을 반환한다."""

        current = prompt.context.current_subtitle
        if current:
            reference = f'현재 자막 "{current.english}"'
            reply = (
                f"{reference}을 기준으로 설명할게요. 질문하신 표현의 정확한 뜻과 쓰임을 "
                "이 문장 안에서 먼저 확인해 보세요. 실제 모델을 연결하면 수준에 맞춘 "
                "예문과 연습 문제까지 이어서 제공할 수 있습니다."
            )
        else:
            reply = (
                "현재 시점에 연결된 자막이 없습니다. 영상의 자막 문장과 함께 질문해 "
                "주시면 그 문맥에 맞춰 설명할게요."
            )
        return json.dumps(
            {
                "reply": reply,
                "suggested_questions": [
                    "이 표현을 사용한 다른 예문을 보여줘",
                    "비슷한 표현과 차이를 알려줘",
                ],
            },
            ensure_ascii=False,
        )


@dataclass
class GeminiClient:
    """Google Gemini GenerateContent REST API 클라이언트."""

    api_key: str
    model: str = "gemini-3.6-flash"
    timeout_seconds: float = 20.0
    name: str = "gemini"

    @property
    def is_configured(self) -> bool:
        """Gemini API key가 주입되어 실제 호출 가능한지 반환한다."""

        return bool(self.api_key and self.api_key.strip())

    async def generate(self, prompt: TutorPrompt) -> LLMGeneration:
        """Gemini GenerateContent API를 호출하고 응답/usage를 정규화한다.

        Gemini의 ``usageMetadata`` 필드명은 provider 공통 모델의
        ``input_tokens``/``output_tokens``/``total_tokens``로 변환한다.
        HTTP 429가 반환되면 router가 다음 provider를 선택할 수 있도록 상태 코드와
        ``Retry-After`` 값을 ``LLMError``에 담는다.
        """

        if not self.is_configured:
            raise LLMError(
                "GEMINI_API_KEY is not configured",
                provider=self.name,
            )

        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency packaging guard
            raise LLMError(
                "httpx is required for the Gemini provider",
                provider=self.name,
            ) from exc

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        generation_config = {
            "temperature": 0.35,
            "maxOutputTokens": 800,
            # Gemini 3는 기본 thinking 수준이 높아 긴 Tutor 문맥에서 답변 JSON의
            # 출력 공간을 잠식할 수 있다. 간단한 학습 대화는 low로 제한해 지연과
            # 잘린 JSON 응답을 줄인다. Gemini 2.x에는 이 필드를 보내지 않는다.
            "responseMimeType": "application/json",
        }
        if self.model.startswith("gemini-3"):
            generation_config["thinkingConfig"] = {"thinkingLevel": "low"}

        payload = {
            "system_instruction": {
                "parts": [{"text": prompt.system_instruction}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt.user_prompt}],
                }
            ],
            "generationConfig": generation_config,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    url,
                    headers={
                        "x-goog-api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise LLMError(
                f"Gemini request failed: {exc}",
                provider=self.name,
            ) from exc

        if response.is_error:
            detail = response.text[:500]
            raise LLMError(
                f"Gemini returned HTTP {response.status_code}: {detail}",
                provider=self.name,
                status_code=response.status_code,
                retry_after_seconds=_retry_after_seconds(response.headers),
            )

        try:
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            metadata = data.get("usageMetadata") or {}
            usage = TokenUsage(
                input_tokens=_as_non_negative_int(metadata.get("promptTokenCount")),
                output_tokens=_as_non_negative_int(
                    metadata.get("candidatesTokenCount")
                ),
                total_tokens=_as_non_negative_int(metadata.get("totalTokenCount")),
            )
            if not isinstance(text, str):
                raise TypeError("candidate text is not a string")
            return LLMGeneration(
                text=text,
                provider=self.name,
                model=self.model,
                usage=usage,
            )
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(
                "Gemini response did not contain candidate text",
                provider=self.name,
            ) from exc


@dataclass
class GroqClient:
    """Groq의 OpenAI-compatible Chat Completions REST API 클라이언트."""

    api_key: str
    model: str = "openai/gpt-oss-20b"
    timeout_seconds: float = 20.0
    base_url: str = "https://api.groq.com/openai/v1"
    name: str = "groq"

    @property
    def is_configured(self) -> bool:
        """Groq API key가 주입되어 실제 호출 가능한지 반환한다."""

        return bool(self.api_key and self.api_key.strip())

    async def generate(self, prompt: TutorPrompt) -> LLMGeneration:
        """Groq Chat Completions API를 호출하고 응답/usage를 정규화한다.

        Groq는 OpenAI-compatible 메시지 형식을 사용하므로 시스템 지시문과 사용자
        질문을 각각 ``system``/``user`` 메시지로 전송한다. 답변은 Tutor service가
        JSON shape을 다시 검증하므로 provider에서 별도 SDK 타입을 노출하지 않는다.
        """

        if not self.is_configured:
            raise LLMError(
                "GROQ_API_KEY is not configured",
                provider=self.name,
            )

        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency packaging guard
            raise LLMError(
                "httpx is required for the Groq provider",
                provider=self.name,
            ) from exc

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt.system_instruction},
                {"role": "user", "content": prompt.user_prompt},
            ],
            "temperature": 0.35,
            "max_tokens": 800,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise LLMError(
                f"Groq request failed: {exc}",
                provider=self.name,
            ) from exc

        if response.is_error:
            detail = response.text[:500]
            raise LLMError(
                f"Groq returned HTTP {response.status_code}: {detail}",
                provider=self.name,
                status_code=response.status_code,
                retry_after_seconds=_retry_after_seconds(response.headers),
            )

        try:
            data = response.json()
            message = data["choices"][0]["message"]
            text = message["content"]
            if isinstance(text, list):
                text = "".join(
                    part.get("text", "")
                    for part in text
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                )
            if not isinstance(text, str):
                raise TypeError("message content is not a string")

            metadata = data.get("usage") or {}
            usage = TokenUsage(
                input_tokens=_as_non_negative_int(metadata.get("prompt_tokens")),
                output_tokens=_as_non_negative_int(
                    metadata.get("completion_tokens")
                ),
                total_tokens=_as_non_negative_int(metadata.get("total_tokens")),
            )
            return LLMGeneration(
                text=text,
                provider=self.name,
                model=self.model,
                usage=usage,
            )
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(
                "Groq response did not contain chat completion text",
                provider=self.name,
            ) from exc


__all__ = [
    "GeminiClient",
    "GroqClient",
    "LLMClient",
    "LLMError",
    "LLMGeneration",
    "RuleBasedTutorClient",
    "TokenUsage",
]
