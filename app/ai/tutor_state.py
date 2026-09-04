"""Video Tutor의 개발용 단기 상태 저장소.

현재 프로젝트에는 Supabase Auth와 PostgreSQL repository가 아직 연결되지 않았으므로
대화, Tutor 설정, 선제 질문 이력, 피드백을 프로세스 메모리에 저장한다. 저장소 API는
``actor_id``를 받도록 설계해 이후 JWT 사용자 ID와 Supabase repository로 교체해도
HTTP 라우터의 계약이 바뀌지 않도록 한다.
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Callable
from uuid import uuid4

from app.ai.context_builder import (
    ConversationTurn,
    SubtitleLine,
    build_tutor_context,
)


_ENGLISH_WORD_RE = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)*")
_PROACTIVE_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "but",
    "can",
    "could",
    "do",
    "for",
    "from",
    "get",
    "has",
    "have",
    "he",
    "her",
    "him",
    "his",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "she",
    "so",
    "that",
    "the",
    "their",
    "them",
    "there",
    "they",
    "this",
    "to",
    "us",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "will",
    "with",
    "want",
    "would",
    "you",
    "your",
}


@dataclass(frozen=True)
class TutorSettingsState:
    """한 사용자의 Tutor 활성화 설정."""

    tutor_enabled: bool
    updated_at: datetime


@dataclass(frozen=True)
class ProactiveDecision:
    """선제 질문 API가 반환할 판단 결과."""

    should_show: bool
    reason: str
    question_id: str | None = None
    question: str | None = None
    focus_word: str | None = None
    expires_in_seconds: int | None = None


@dataclass(frozen=True)
class TutorFeedbackRecord:
    """메모리 저장소에 기록한 Tutor 답변 평가."""

    feedback_id: str
    conversation_id: str
    message_id: str
    rating: str
    reason: str | None
    comment: str | None
    created_at: datetime


@dataclass
class _ConversationState:
    """한 Tutor 대화의 개발용 저장 상태."""

    video_id: str
    turns: list[ConversationTurn] = field(default_factory=list)
    message_ids: set[str] = field(default_factory=set)


@dataclass
class _ProactiveState:
    """영상별 선제 질문 cooldown·표시 이력."""

    last_question_id: str | None = None
    last_question_at: float | None = None
    seen_focus_words: set[str] = field(default_factory=set)


class InMemoryTutorState:
    """Tutor의 임시 상태를 프로세스 메모리에 보관한다.

    이 클래스는 로컬 실행과 단위 테스트에서 Supabase 없이 Tutor 흐름을 확인하기
    위한 구현이다. 애플리케이션이 여러 worker로 실행되거나 재시작되면 상태가
    공유·복구되지 않으므로 운영 환경에서는 사용자 ID를 기준으로 Supabase/Redis
    repository를 주입해야 한다.
    """

    def __init__(
        self,
        *,
        proactive_cooldown_seconds: float = 45.0,
        requests_per_minute: int = 30,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """기본 설정, 선제 질문 cooldown, 요청 제한을 초기화한다.

        ``clock``을 주입할 수 있게 해 실제 시간을 기다리지 않고 rate limit의
        경계값을 테스트할 수 있다. 운영 환경에서는 이 메모리 제한을 Redis 기반
        제한기로 교체하되, 호출하는 라우터 계약은 유지한다.
        """

        self.proactive_cooldown_seconds = max(proactive_cooldown_seconds, 0.0)
        self.requests_per_minute = max(requests_per_minute, 0)
        self._clock = clock
        self._settings: dict[str, TutorSettingsState] = {}
        self._conversations: dict[tuple[str, str], _ConversationState] = {}
        self._proactive: dict[tuple[str, str], _ProactiveState] = {}
        self._feedback: dict[tuple[str, str], TutorFeedbackRecord] = {}
        self._request_timestamps: dict[str, deque[float]] = {}
        self._lock = RLock()

    def allow_request(self, actor_id: str) -> bool:
        """분당 Tutor 질문 제한 안에 있으면 요청을 소비하고 ``True``를 반환한다.

        반환값이 ``False``이면 호출자가 `429 Too Many Requests`를 반환해야 한다.
        사용자 로그인 전에는 actor가 ``anonymous`` 하나이므로 로컬 개발용 보호
        장치로 동작하고, Auth 연결 후에는 JWT의 `sub`별로 분리된다.
        """

        if self.requests_per_minute <= 0:
            return True

        now = self._clock()
        with self._lock:
            timestamps = self._request_timestamps.setdefault(actor_id, deque())
            cutoff = now - 60.0
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self.requests_per_minute:
                return False
            timestamps.append(now)
            return True

    def get_settings(self, actor_id: str) -> TutorSettingsState:
        """사용자 설정을 조회하고, 최초 조회 시 Tutor ON 기본값을 만든다."""

        with self._lock:
            state = self._settings.get(actor_id)
            if state is None:
                state = TutorSettingsState(
                    tutor_enabled=True,
                    updated_at=datetime.now(timezone.utc),
                )
                self._settings[actor_id] = state
            return state

    def set_tutor_enabled(self, actor_id: str, enabled: bool) -> TutorSettingsState:
        """사용자별 Tutor ON/OFF 상태를 변경한다."""

        with self._lock:
            state = TutorSettingsState(
                tutor_enabled=enabled,
                updated_at=datetime.now(timezone.utc),
            )
            self._settings[actor_id] = state
            return state

    def get_conversation_history(
        self,
        actor_id: str,
        conversation_id: str,
        *,
        limit: int = 10,
    ) -> tuple[ConversationTurn, ...] | None:
        """사용자 소유로 확인된 대화의 최근 이력을 반환한다.

        Returns:
            대화가 존재하면 최근 이력 tuple을, 존재하지 않으면 ``None``을 반환한다.
            빈 대화와 존재하지 않는 대화를 구분해야 잘못된 conversation ID를
            조용히 새 대화로 바꾸지 않을 수 있다.
        """

        with self._lock:
            state = self._conversations.get((actor_id, conversation_id))
            if state is None:
                return None
            if limit <= 0:
                return ()
            return tuple(state.turns[-max(limit, 0) :])

    def get_conversation_video_id(
        self,
        actor_id: str,
        conversation_id: str,
    ) -> str | None:
        """사용자 대화의 원래 영상 ID를 반환하거나, 대화가 없으면 ``None``을 반환한다.

        한 대화 ID를 다른 영상에 재사용하면 문맥이 섞일 수 있으므로 API 계층에서
        이어받는 요청의 ``video_id``를 검증하는 데 사용한다.
        """

        with self._lock:
            state = self._conversations.get((actor_id, conversation_id))
            return state.video_id if state is not None else None

    def record_exchange(
        self,
        *,
        actor_id: str,
        conversation_id: str,
        message_id: str,
        video_id: str,
        user_message: str,
        tutor_reply: str,
        initial_history: tuple[ConversationTurn, ...] = (),
    ) -> None:
        """Tutor 질문과 답변을 대화에 추가한다.

        대화가 처음 생성되는 경우 요청에 포함된 이전 이력을 먼저 저장한다. 이후
        요청에서는 서버 저장 이력을 우선 사용하므로 프론트엔드가 매번 전체 이력을
        다시 보내지 않아도 된다.
        """

        with self._lock:
            key = (actor_id, conversation_id)
            state = self._conversations.setdefault(
                key,
                _ConversationState(video_id=video_id),
            )
            if not state.turns and initial_history:
                state.turns.extend(initial_history[-10:])
            state.turns.extend(
                (
                    ConversationTurn(role="user", message=user_message),
                    ConversationTurn(role="tutor", message=tutor_reply),
                )
            )
            # 지나치게 오래된 대화가 프로세스 메모리를 계속 점유하지 않도록
            # 다음 요청에 전달할 수 있는 범위와 동일한 상한을 둔다.
            del state.turns[:-10]
            state.message_ids.add(message_id)

    def has_message(
        self,
        actor_id: str,
        message_id: str,
        conversation_id: str | None = None,
    ) -> bool:
        """사용자 대화에 평가 대상 메시지가 존재하는지 확인한다.

        ``conversation_id``가 전달되면 메시지가 해당 대화에 속하는지도 함께
        검증해 서로 다른 대화 ID를 조합한 피드백을 막는다.
        """

        with self._lock:
            if conversation_id is not None:
                state = self._conversations.get((actor_id, conversation_id))
                return state is not None and message_id in state.message_ids
            return any(
                message_id in state.message_ids
                for (stored_actor, _), state in self._conversations.items()
                if stored_actor == actor_id
            )

    def record_feedback(
        self,
        *,
        actor_id: str,
        conversation_id: str,
        message_id: str,
        rating: str,
        reason: str | None = None,
        comment: str | None = None,
    ) -> TutorFeedbackRecord:
        """메시지별 최신 피드백을 저장하고 저장 결과를 반환한다."""

        with self._lock:
            record = TutorFeedbackRecord(
                feedback_id=f"fb_{uuid4().hex[:12]}",
                conversation_id=conversation_id,
                message_id=message_id,
                rating=rating,
                reason=reason,
                comment=comment,
                created_at=datetime.now(timezone.utc),
            )
            self._feedback[(actor_id, message_id)] = record
            return record

    def decide_proactive(
        self,
        *,
        actor_id: str,
        video_id: str,
        timestamp: float,
        subtitles: tuple[SubtitleLine, ...],
        playback_state: str,
        last_question_id: str | None = None,
        last_question_at: float | None = None,
    ) -> ProactiveDecision:
        """현재 영상 문맥에서 선제 질문을 표시할지 결정한다.

        초기 구현은 LLM을 호출하지 않고 현재 자막에서 학습 가치가 있어 보이는
        영어 단어 하나를 선택한다. 이 방식은 자막이 갱신될 때마다 발생하는
        불필요한 token 사용을 줄이며, 이후 별도 후보 평가 모델로 교체할 수 있다.
        """

        if not self.get_settings(actor_id).tutor_enabled:
            return _hidden_proactive_decision("disabled")

        if playback_state in {"paused", "seeking"}:
            return _hidden_proactive_decision("paused")

        context = build_tutor_context(
            video_id=video_id,
            timestamp=timestamp,
            user_message="선제 학습 질문을 만들어 주세요.",
            subtitles=subtitles,
        )
        current = context.current_subtitle
        if current is None:
            return _hidden_proactive_decision("insufficient_context")

        focus_word = _pick_focus_word(current.english)
        if focus_word is None:
            return _hidden_proactive_decision("insufficient_context")

        with self._lock:
            key = (actor_id, video_id)
            state = self._proactive.setdefault(key, _ProactiveState())
            previous_timestamp = state.last_question_at
            if previous_timestamp is None:
                previous_timestamp = last_question_at

            if (
                previous_timestamp is not None
                and timestamp - previous_timestamp < self.proactive_cooldown_seconds
            ):
                return _hidden_proactive_decision("cooldown")

            normalized_focus = focus_word.casefold()
            if normalized_focus in state.seen_focus_words:
                return _hidden_proactive_decision("already_seen")

            question_id = f"pq_{uuid4().hex[:12]}"
            state.last_question_id = question_id
            state.last_question_at = timestamp
            state.seen_focus_words.add(normalized_focus)

        return ProactiveDecision(
            should_show=True,
            reason="new_expression",
            question_id=question_id,
            question=f"방금 나온 '{focus_word}'의 뜻을 추측해 볼까요?",
            focus_word=focus_word,
            expires_in_seconds=30,
        )

    def reset(self) -> None:
        """개발용 상태를 비운다. 테스트 격리와 로컬 재현에 사용한다."""

        with self._lock:
            self._settings.clear()
            self._conversations.clear()
            self._proactive.clear()
            self._feedback.clear()
            self._request_timestamps.clear()


def _pick_focus_word(english: str) -> str | None:
    """현재 자막에서 조사할 만한 첫 번째 영어 단어를 고른다."""

    for match in _ENGLISH_WORD_RE.finditer(english):
        word = match.group(0)
        if len(word) >= 4 and word.casefold() not in _PROACTIVE_STOPWORDS:
            return word
    return None


def _hidden_proactive_decision(reason: str) -> ProactiveDecision:
    """질문을 표시하지 않을 때 사용하는 공통 응답을 만든다."""

    return ProactiveDecision(should_show=False, reason=reason)


__all__ = [
    "InMemoryTutorState",
    "ProactiveDecision",
    "TutorFeedbackRecord",
    "TutorSettingsState",
]
