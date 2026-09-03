"""LLM provider fallback 및 quota-aware routing."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Mapping, Sequence

from app.ai.llm_client import (
    LLMClient,
    LLMError,
    LLMGeneration,
    TokenUsage,
)
from app.ai.prompts import TutorPrompt
from app.ai.usage_tracker import (
    InMemoryUsageTracker,
    estimate_prompt_tokens,
    estimate_tokens,
)


@dataclass(frozen=True)
class ProviderQuota:
    """provider별 로컬 보호 한도. 0은 해당 guard를 끈다는 뜻이다."""

    daily_token_limit: int = 0
    minute_token_limit: int = 0


class ProviderRouter:
    """provider를 순서대로 시도하고 성공한 provider의 usage를 기록한다.

    실제 provider의 429가 최종 판단 기준이며, 로컬 quota는 그 전에 불필요한
    호출을 줄이는 안전장치다. 429가 오면 Retry-After 또는 cooldown 동안 해당
    provider를 건너뛰고 다음 provider로 요청한다.
    """

    name = "router"
    model = "provider-router"

    def __init__(
        self,
        providers: Sequence[LLMClient],
        *,
        usage_tracker: InMemoryUsageTracker | None = None,
        quotas: Mapping[str, ProviderQuota] | None = None,
        reserve_output_tokens: int = 800,
        failure_cooldown_seconds: float = 30.0,
        clock=time.monotonic,
    ) -> None:
        """provider 순서와 로컬 quota 정책을 저장한다.

        Args:
            providers: 앞에 있는 provider부터 차례로 시도할 목록.
            usage_tracker: 성공한 호출의 실제/추정 usage를 기록할 저장소.
            quotas: provider 이름별 일일·분당 token 보호 한도.
            reserve_output_tokens: 요청 전 quota 계산에 예약할 최대 출력 토큰 수.
            failure_cooldown_seconds: Retry-After가 없을 때 provider를 쉬게 할 시간.
            clock: 테스트에서 cooldown 시간을 제어하기 위한 시계 함수.
        """

        self.providers = tuple(providers)
        self.usage_tracker = usage_tracker or InMemoryUsageTracker()
        self.quotas = dict(quotas or {})
        self.reserve_output_tokens = max(reserve_output_tokens, 0)
        self.failure_cooldown_seconds = max(failure_cooldown_seconds, 0.0)
        self._clock = clock
        self._unavailable_until: dict[str, float] = {}

    async def generate(self, prompt: TutorPrompt) -> LLMGeneration:
        """사용 가능한 provider를 순서대로 호출해 첫 성공 응답을 반환한다.

        호출 전에는 추정 token으로 로컬 quota를 확인하고, 호출 후에는 provider가
        반환한 실제 usage를 기록한다. 모든 provider가 건너뛰어지거나 실패하면
        TutorService가 최종 stub fallback을 실행할 수 있도록 ``LLMError``를 올린다.
        """

        errors: list[str] = []
        estimated_tokens = estimate_prompt_tokens(prompt) + self.reserve_output_tokens

        for provider in self.providers:
            provider_name = getattr(
                provider,
                "name",
                provider.__class__.__name__.lower(),
            )
            if not self._is_configured(provider):
                # API key가 없는 provider는 오류로 취급하지 않고 다음 provider로 간다.
                continue
            if self._is_cooling_down(provider_name):
                errors.append(f"{provider_name}: cooldown")
                continue
            if not self._within_local_quota(provider_name, estimated_tokens):
                errors.append(f"{provider_name}: local token limit")
                continue

            try:
                raw = await provider.generate(prompt)
                generation = self._normalize_generation(
                    raw,
                    provider_name,
                    provider,
                    prompt,
                )
                self.usage_tracker.record(generation)
                self._unavailable_until.pop(provider_name, None)
                return generation
            except LLMError as exc:
                errors.append(f"{provider_name}: {exc}")
                self._mark_unavailable(provider_name, exc)

        detail = "; ".join(errors) or "no configured provider"
        raise LLMError(
            f"All configured LLM providers failed: {detail}",
            provider=self.name,
        )

    def _is_configured(self, provider: LLMClient) -> bool:
        """provider가 호출 가능한 상태인지 확인한다.

        사용자 정의 테스트 client처럼 ``is_configured`` 속성이 없는 객체는
        기본적으로 호출 가능한 것으로 간주한다.
        """

        configured = getattr(provider, "is_configured", None)
        if configured is None:
            return True
        return bool(configured)

    def _is_cooling_down(self, provider_name: str) -> bool:
        """최근 실패로 일시 정지된 provider인지 확인한다."""

        return self._unavailable_until.get(provider_name, 0.0) > self._clock()

    def _within_local_quota(self, provider_name: str, estimated_tokens: int) -> bool:
        """예상 사용량이 provider의 로컬 일일·분당 한도 안에 있는지 확인한다."""

        quota = self.quotas.get(provider_name)
        if quota is None:
            return True

        if quota.daily_token_limit > 0:
            used_today = self.usage_tracker.total_tokens(provider_name)
            if used_today + estimated_tokens >= quota.daily_token_limit:
                return False

        if quota.minute_token_limit > 0:
            used_this_minute = self.usage_tracker.total_tokens(
                provider_name,
                within_seconds=60,
            )
            if used_this_minute + estimated_tokens >= quota.minute_token_limit:
                return False

        return True

    def _mark_unavailable(self, provider_name: str, error: LLMError) -> None:
        """실패한 provider를 Retry-After 또는 기본 cooldown 동안 일시 정지한다."""

        cooldown = error.retry_after_seconds
        if cooldown is None:
            cooldown = self.failure_cooldown_seconds
        self._unavailable_until[provider_name] = self._clock() + max(cooldown, 0.0)

    def _normalize_generation(
        self,
        raw: str | LLMGeneration,
        provider_name: str,
        provider: LLMClient,
        prompt: TutorPrompt,
    ) -> LLMGeneration:
        """기존 문자열 client도 공통 ``LLMGeneration``으로 변환한다."""

        if isinstance(raw, LLMGeneration):
            generation = raw
            return LLMGeneration(
                text=generation.text,
                provider=generation.provider or provider_name,
                model=generation.model or getattr(provider, "model", provider_name),
                usage=self._ensure_usage(
                    generation,
                    prompt=prompt,
                    raw_text=generation.text,
                ),
            )
        if isinstance(raw, str):
            input_tokens = estimate_prompt_tokens(prompt)
            output_tokens = estimate_tokens(raw)
            return LLMGeneration(
                text=raw,
                provider=provider_name,
                model=getattr(provider, "model", provider_name),
                usage=TokenUsage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                ),
            )
        raise LLMError(
            "LLM provider returned an unsupported result",
            provider=provider_name,
        )

    def _ensure_usage(
        self,
        generation: LLMGeneration,
        *,
        prompt: TutorPrompt,
        raw_text: str,
    ) -> TokenUsage:
        """usage가 누락된 테스트/custom client에 대해 token을 보수적으로 추정한다."""

        if generation.usage.normalized_total > 0:
            return generation.usage
        input_tokens = estimate_prompt_tokens(prompt)
        output_tokens = estimate_tokens(raw_text)
        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )


__all__ = ["ProviderQuota", "ProviderRouter"]
