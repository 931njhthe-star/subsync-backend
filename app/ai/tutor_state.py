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
_GENERIC_PROACTIVE_WORDS = {
    "also",
    "because",
    "does",
    "every",
    "first",
    "get",
    "gets",
    "getting",
    "go",
    "goes",
    "going",
    "look",
    "looks",
    "make",
    "makes",
    "making",
    "need",
    "needs",
    "one",
    "problem",
    "really",
    "said",
    "say",
    "says",
    "thing",
    "think",
    "thought",
    "value",
    "want",
    "wants",
}
_PHRASE_TAILS = {"about", "for", "from", "into", "of", "on", "to", "with"}


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
    last_subtitles: tuple[SubtitleLine, ...] = ()


@dataclass
class _ProactiveState:
    """영상별 선제 질문 cooldown·표시 이력."""

    last_question_at: float | None = None
    seen_focus_words: set[str] = field(default_factory=set)
    questions: dict[str, str] = field(default_factory=dict)
    question_created_at: dict[str, float] = field(default_factory=dict)
    answered_question_ids: set[str] = field(default_factory=set)


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
        proactive_cooldown_seconds: float = 180.0,
        proactive_max_questions_per_video: int = 3,
        proactive_question_ttl_seconds: float = 30.0,
        requests_per_minute: int = 30,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """기본 설정, 선제 질문 만료·cooldown, 요청 제한을 초기화한다.

        ``clock``을 주입할 수 있게 해 실제 시간을 기다리지 않고 rate limit의
        경계값을 테스트할 수 있다. 운영 환경에서는 이 메모리 제한을 Redis 기반
        제한기로 교체하되, 호출하는 라우터 계약은 유지한다.

        ``proactive_question_ttl_seconds``는 선제 질문을 표시한 뒤 답변으로
        연결할 수 있는 시간이다. 영상 재생 시점이 아니라 실제 경과 시간을
        기준으로 만료시켜, 오래된 질문이 일반 대화를 가로채지 않게 한다.
        """

        self.proactive_cooldown_seconds = max(proactive_cooldown_seconds, 0.0)
        self.proactive_max_questions_per_video = max(
            proactive_max_questions_per_video,
            0,
        )
        self.proactive_question_ttl_seconds = max(
            proactive_question_ttl_seconds,
            0.0,
        )
        self.requests_per_minute = max(requests_per_minute, 0)
        self._clock = clock
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

    def get_conversation(
        self,
        actor_id: str,
        conversation_id: str,
    ) -> tuple[str, tuple[ConversationTurn, ...]] | None:
        """대화의 영상 ID와 최근 이력을 함께 반환한다.

        존재하지 않는 대화와 비어 있는 대화를 구분하고, 한 번의 lock 안에서
        video ID와 이력을 읽어 이어가기 요청의 문맥이 섞이지 않게 한다.
        """

        with self._lock:
            state = self._conversations.get((actor_id, conversation_id))
            if state is None:
                return None
            return state.video_id, tuple(state.turns[-10:])

    def get_conversation_subtitles(
        self,
        actor_id: str,
        conversation_id: str,
    ) -> tuple[SubtitleLine, ...] | None:
        """대화에 마지막으로 전달된 자막 문맥을 반환한다.

        후속 질문이 자막 배열을 생략하더라도 같은 대화에서 마지막으로 확인한
        문장을 재사용할 수 있게 한다. 새로운 영상 시점의 자막이 있다면 라우터가
        그 값을 우선 사용하므로 오래된 문맥이 무조건 유지되지는 않는다.
        """

        with self._lock:
            state = self._conversations.get((actor_id, conversation_id))
            if state is None:
                return None
            return state.last_subtitles

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
        subtitles: tuple[SubtitleLine, ...] = (),
    ) -> None:
        """Tutor 질문과 답변을 대화에 추가한다.

        대화가 처음 생성되는 경우 요청에 포함된 이전 이력을 먼저 저장한다. 이후
        요청에서는 서버 저장 이력과 마지막 자막 문맥을 우선 사용하므로
        프론트엔드가 매번 전체 이력과 같은 자막을 다시 보내지 않아도 된다.
        """

        with self._lock:
            key = (actor_id, conversation_id)
            state = self._conversations.setdefault(
                key,
                _ConversationState(video_id=video_id),
            )
            # 새 자막이 전달된 경우에만 문맥을 교체한다. 후속 질문이 자막을
            # 생략한 요청으로 마지막으로 유효한 문맥을 지우지 않기 위해서다.
            if subtitles:
                state.last_subtitles = tuple(subtitles)
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
        conversation_id: str,
    ) -> bool:
        """사용자 대화에 평가 대상 메시지가 존재하는지 확인한다.

        메시지가 해당 대화에 속하는지도 함께 검증해 서로 다른 대화 ID를 조합한
        피드백을 막는다.
        """

        with self._lock:
            state = self._conversations.get((actor_id, conversation_id))
            return state is not None and message_id in state.message_ids

    def create_feedback(
        self,
        *,
        actor_id: str,
        conversation_id: str,
        message_id: str,
        rating: str,
        reason: str | None = None,
        comment: str | None = None,
    ) -> TutorFeedbackRecord | None:
        """메시지별 첫 피드백만 저장하고, 이미 있으면 ``None``을 반환한다.

        확인과 저장을 하나의 lock 안에서 처리해 동시에 들어온 두 요청도 둘 다
        성공하지 않게 한다. 운영 DB에서도 ``UNIQUE (user_id, message_id)`` 제약으로
        같은 규칙을 보장해야 한다.
        """

        with self._lock:
            key = (actor_id, message_id)
            if key in self._feedback:
                return None
            record = TutorFeedbackRecord(
                feedback_id=f"fb_{uuid4().hex[:12]}",
                conversation_id=conversation_id,
                message_id=message_id,
                rating=rating,
                reason=reason,
                comment=comment,
                created_at=datetime.now(timezone.utc),
            )
            self._feedback[key] = record
            return record

    def decide_proactive(
        self,
        *,
        actor_id: str,
        video_id: str,
        timestamp: float,
        subtitles: tuple[SubtitleLine, ...],
        playback_state: str,
        last_question_at: float | None = None,
    ) -> ProactiveDecision:
        """현재 영상 문맥에서 선제 질문을 표시할지 결정한다.

        초기 구현은 LLM을 호출하지 않고 현재 자막에서 학습 가치가 있어 보이는
        영어 단어 하나를 선택한다. 이 방식은 자막이 갱신될 때마다 발생하는
        불필요한 token 사용을 줄이며, 이후 별도 후보 평가 모델로 교체할 수 있다.
        """

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
            if (
                len(state.seen_focus_words)
                >= self.proactive_max_questions_per_video
            ):
                return _hidden_proactive_decision("max_questions_reached")
            previous_timestamp = state.last_question_at
            if previous_timestamp is None:
                previous_timestamp = last_question_at

            # 영상 시작 직후 질문이 학습 흐름을 끊지 않게 첫 노출에도 동일한 대기
            # 시간을 적용한다. 재생 위치는 영상 시작(0초)을 기준으로 전달된다.
            if (
                previous_timestamp is None
                and timestamp < self.proactive_cooldown_seconds
            ):
                return _hidden_proactive_decision("initial_cooldown")

            if (
                previous_timestamp is not None
                and timestamp - previous_timestamp < self.proactive_cooldown_seconds
            ):
                return _hidden_proactive_decision("cooldown")

            normalized_focus = focus_word.casefold()
            if normalized_focus in state.seen_focus_words:
                return _hidden_proactive_decision("already_seen")

            question_id = f"pq_{uuid4().hex[:12]}"
            state.last_question_at = timestamp
            state.seen_focus_words.add(normalized_focus)
            state.questions[question_id] = focus_word
            state.question_created_at[question_id] = self._clock()

        return ProactiveDecision(
            should_show=True,
            reason="new_expression",
            question_id=question_id,
            question=f"방금 나온 '{focus_word}'의 뜻을 추측해 볼까요?",
            focus_word=focus_word,
            expires_in_seconds=int(self.proactive_question_ttl_seconds),
        )

    def get_proactive_focus_word(
        self,
        actor_id: str,
        video_id: str,
        question_id: str,
    ) -> str | None:
        """선제 질문 ID에 저장된 원래 표현을 반환한다.

        클라이언트가 임의의 focus word를 보내도 Tutor가 낸 질문과 다른 표현을
        채점하지 않도록 서버가 발급한 ID를 기준으로 확인한다.
        """

        with self._lock:
            state = self._proactive.get((actor_id, video_id))
            if state is None:
                return None
            focus_word = state.questions.get(question_id)
            if focus_word is None:
                return None
            if not self._is_proactive_question_active(state, question_id):
                return None
            return focus_word

    def find_pending_proactive_question(
        self,
        actor_id: str,
        video_id: str,
        *,
        focus_word: str | None = None,
    ) -> tuple[str, str] | None:
        """아직 답하지 않은 최근 선제 질문을 반환한다.

        호환용으로 남겨 둔 조회 함수지만, ``focus_word``가 명시된 경우에만
        일치하는 질문을 반환한다. 표현이 없는 일반 질문을 선제 답변으로
        자동 연결하면 사용자가 의도하지 않은 채점 화면을 보게 되기 때문이다.
        만료된 질문도 반환하지 않는다.
        """

        if focus_word is None:
            return None

        with self._lock:
            state = self._proactive.get((actor_id, video_id))
            if state is None:
                return None
            candidates = reversed(tuple(state.questions.items()))
            for question_id, stored_focus_word in candidates:
                if question_id in state.answered_question_ids:
                    continue
                if not self._is_proactive_question_active(state, question_id):
                    continue
                if stored_focus_word.casefold() == focus_word.casefold():
                    return question_id, stored_focus_word
            return None

    def _is_proactive_question_active(
        self,
        state: _ProactiveState,
        question_id: str,
    ) -> bool:
        """선제 질문이 아직 답변 가능한 30초 창 안에 있는지 확인한다."""

        created_at = state.question_created_at.get(question_id)
        if created_at is None:
            # 기존 프로세스 상태와의 호환을 위해 생성 시각이 없는 항목은
            # 만료를 적용할 수 없으므로 활성 상태로 취급한다.
            return True
        return self._clock() - created_at < self.proactive_question_ttl_seconds

    def mark_proactive_question_answered(
        self,
        actor_id: str,
        video_id: str,
        question_id: str,
    ) -> None:
        """명시적으로 답변한 선제 질문을 다시 채점하지 않도록 소비 처리한다."""

        with self._lock:
            state = self._proactive.get((actor_id, video_id))
            if state is not None and question_id in state.questions:
                state.answered_question_ids.add(question_id)

    def reset(self) -> None:
        """개발용 상태를 비운다. 테스트 격리와 로컬 재현에 사용한다."""

        with self._lock:
            self._conversations.clear()
            self._proactive.clear()
            self._feedback.clear()
            self._request_timestamps.clear()


def _pick_focus_word(english: str) -> str | None:
    """일반 단어 대신 학습할 만한 구문 또는 긴 표현만 고른다."""

    words = [match.group(0) for match in _ENGLISH_WORD_RE.finditer(english)]
    for index, word in enumerate(words):
        normalized = word.casefold()
        if normalized in _PROACTIVE_STOPWORDS | _GENERIC_PROACTIVE_WORDS:
            continue
        next_word = words[index + 1] if index + 1 < len(words) else None
        if len(word) >= 6 and next_word and next_word.casefold() in _PHRASE_TAILS:
            return f"{word} {next_word}"
        if (
            len(word) >= 6
            and word.casefold().endswith("ly")
            and next_word
            and next_word.casefold() not in _PROACTIVE_STOPWORDS
        ):
            return f"{word} {next_word}"
        if len(word) >= 8:
            return word
    return None


def _hidden_proactive_decision(reason: str) -> ProactiveDecision:
    """질문을 표시하지 않을 때 사용하는 공통 응답을 만든다."""

    return ProactiveDecision(should_show=False, reason=reason)


__all__ = [
    "InMemoryTutorState",
    "ProactiveDecision",
    "TutorFeedbackRecord",
]
