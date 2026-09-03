"""LLM 토큰 사용량을 기록하고 provider별 로컬 quota를 확인하는 모듈."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Callable

from app.ai.llm_client import LLMGeneration, TokenUsage
from app.ai.prompts import TutorPrompt


@dataclass(frozen=True)
class UsageRecord:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    recorded_at: float


def estimate_tokens(text: str) -> int:
    """토크나이저 없이 사용할 보수적인 사전 추정치.

    실제 한도 판정에는 provider가 응답한 usage를 사용하고, 이 값은 요청 전
    quota guard에만 사용한다. 영어/한국어가 섞인 프롬프트의 정확한 토큰 수가
    아니므로 운영 정책은 항상 429 응답도 함께 처리해야 한다.
    """

    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def estimate_prompt_tokens(prompt: TutorPrompt) -> int:
    """시스템 지시문과 사용자 prompt의 사전 토큰 수를 추정한다."""

    return estimate_tokens(
        f"{prompt.system_instruction}\n{prompt.user_prompt}"
    )


class InMemoryUsageTracker:
    """현재 프로세스에서 최근 사용량을 보관하는 개발용 tracker.

    서버가 여러 대이거나 재시작 후에도 quota를 유지해야 하는 운영 환경에서는
    동일한 인터페이스를 Redis/DB 구현으로 교체해야 한다.
    """

    def __init__(
        self,
        *,
        window_seconds: float = 86_400,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """usage 보관 기간과 시간 함수를 설정한다.

        ``clock``을 주입할 수 있게 해 cooldown·만료 로직을 실제 시간에 의존하지
        않고 테스트할 수 있다.
        """

        self.window_seconds = window_seconds
        self._clock = clock
        self._records: list[UsageRecord] = []
        self._lock = threading.Lock()

    def record(self, generation: LLMGeneration) -> UsageRecord:
        """LLM 응답의 usage를 정규화해 기록하고 생성된 record를 반환한다."""

        usage = generation.usage
        input_tokens = max(usage.input_tokens, 0)
        output_tokens = max(usage.output_tokens, 0)
        total_tokens = usage.normalized_total
        now = self._clock()
        record = UsageRecord(
            provider=generation.provider,
            model=generation.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=max(total_tokens, input_tokens + output_tokens),
            recorded_at=now,
        )
        with self._lock:
            self._purge_locked(now)
            self._records.append(record)
        return record

    def total_tokens(
        self,
        provider: str,
        *,
        within_seconds: float | None = None,
    ) -> int:
        """provider가 지정된 기간 동안 사용한 총 token 수를 반환한다."""

        now = self._clock()
        with self._lock:
            self._purge_locked(now)
            cutoff = (
                now - within_seconds
                if within_seconds is not None
                else now - self.window_seconds
            )
            return sum(
                record.total_tokens
                for record in self._records
                if record.provider == provider and record.recorded_at >= cutoff
            )

    def records(self) -> tuple[UsageRecord, ...]:
        """만료되지 않은 usage record를 시간순 tuple로 반환한다."""

        now = self._clock()
        with self._lock:
            self._purge_locked(now)
            return tuple(self._records)

    def snapshot(self) -> dict[str, dict[str, int]]:
        """provider별 요청 수와 누적 token을 로컬 디버깅용으로 반환한다."""

        snapshot: dict[str, dict[str, int]] = {}
        for record in self.records():
            current = snapshot.setdefault(
                record.provider,
                {
                    "requests": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
            )
            current["requests"] += 1
            current["input_tokens"] += record.input_tokens
            current["output_tokens"] += record.output_tokens
            current["total_tokens"] += record.total_tokens
        return snapshot

    def _purge_locked(self, now: float) -> None:
        """보관 기간이 지난 record를 lock을 획득한 상태에서 제거한다."""

        cutoff = now - self.window_seconds
        self._records = [
            record for record in self._records if record.recorded_at >= cutoff
        ]


__all__ = [
    "InMemoryUsageTracker",
    "UsageRecord",
    "estimate_prompt_tokens",
    "estimate_tokens",
]
