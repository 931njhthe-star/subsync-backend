"""YouTube 자막을 현재 재생 시점 중심의 작은 문맥으로 정리한다."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence


_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class SubtitleLine:
    """영상 자막 한 줄을 표현하는 불변 값 객체."""

    timestamp: float
    english: str
    korean: str | None = None


@dataclass(frozen=True)
class ConversationTurn:
    """Tutor 대화에서 사용자 또는 Tutor가 발화한 한 턴."""

    role: str
    message: str


@dataclass(frozen=True)
class TutorContext:
    """LLM 프롬프트 생성에 필요한 정제된 영상 학습 문맥."""

    video_id: str
    timestamp: float
    user_message: str
    current_subtitle: SubtitleLine | None
    nearby_subtitles: tuple[SubtitleLine, ...]
    saved_words: tuple[str, ...]
    conversation_history: tuple[ConversationTurn, ...]
    focus_word: str | None = None


def normalize_caption_text(value: str | None, max_chars: int = 500) -> str:
    """자막을 프롬프트에 넣기 전에 공백/제어문자를 정리하고 길이를 제한한다."""

    if not value:
        return ""
    normalized = _WHITESPACE_RE.sub(" ", value.replace("\x00", " ")).strip()
    return normalized[:max_chars]


def _clean_lines(lines: Sequence[SubtitleLine], max_input_lines: int) -> list[SubtitleLine]:
    """입력 자막을 정규화하고 비어 있는 줄을 제거한 뒤 시간순으로 정렬한다."""

    cleaned: list[SubtitleLine] = []
    for line in lines[:max_input_lines]:
        english = normalize_caption_text(line.english)
        korean = normalize_caption_text(line.korean)
        if not english and not korean:
            continue
        cleaned.append(
            SubtitleLine(
                timestamp=max(float(line.timestamp), 0.0),
                english=english,
                korean=korean or None,
            )
        )
    return sorted(cleaned, key=lambda item: item.timestamp)


def build_tutor_context(
    *,
    video_id: str,
    timestamp: float,
    user_message: str,
    subtitles: Sequence[SubtitleLine],
    saved_words: Sequence[str] = (),
    conversation_history: Sequence[ConversationTurn] = (),
    focus_word: str | None = None,
    max_context_lines: int = 7,
    max_input_lines: int = 100,
    history_limit: int = 6,
) -> TutorContext:
    """현재 재생 시점을 중심으로 LLM에 전달할 작은 문맥을 만든다.

    Args:
        video_id: YouTube 영상 식별자.
        timestamp: 사용자가 질문한 영상 시점(초).
        user_message: 사용자의 원 질문.
        subtitles: Extension이 전달한 주변 자막 목록.
        saved_words: 프롬프트에 참고로 넣을 저장 단어 목록.
        conversation_history: 최근 대화 목록. 마지막 ``history_limit``개만 사용한다.
        focus_word: 사용자가 지정한 집중 표현.
        max_context_lines: 프롬프트에 넣을 최대 자막 줄 수.
        max_input_lines: 정제 전에 받을 최대 자막 줄 수.
        history_limit: 프롬프트에 넣을 최대 대화 턴 수.

    Returns:
        공백·제어문자·길이를 정리한 ``TutorContext``.

    Raises:
        ValueError: ``max_context_lines``가 1보다 작은 경우.

    Note:
        현재 줄을 찾을 때는 시점보다 이전인 가장 가까운 줄을 우선한다. 시점 이전
        자막이 없으면 가장 가까운 줄을 사용해 첫 문장 질문도 처리한다.
    """

    if max_context_lines < 1:
        raise ValueError("max_context_lines must be at least 1")

    # 먼저 입력량을 제한해 사용자가 과도한 자막을 보내도 프롬프트가 커지지 않게 한다.
    cleaned_lines = _clean_lines(subtitles, max_input_lines)
    current_index: int | None = None
    for index, line in enumerate(cleaned_lines):
        if line.timestamp <= timestamp:
            current_index = index
        else:
            break
    if current_index is None and cleaned_lines:
        current_index = min(
            range(len(cleaned_lines)),
            key=lambda index: abs(cleaned_lines[index].timestamp - timestamp),
        )

    if current_index is None:
        selected_lines: list[SubtitleLine] = []
        current_subtitle = None
    else:
        # 현재 줄을 포함해 앞 4줄과 뒤 2줄을 기본으로 선택한다. 최대 줄 수가
        # 변경되어도 현재 자막은 문맥에서 빠지지 않도록 한다.
        before = min(4, max_context_lines - 1)
        start = max(0, current_index - before)
        end = min(len(cleaned_lines), start + max_context_lines)
        selected_lines = cleaned_lines[start:end]
        current_subtitle = cleaned_lines[current_index]

    # 저장 단어는 수준 판정이 아니라 현재 답변의 개인화 참고 자료로만 사용한다.
    words: list[str] = []
    seen_words: set[str] = set()
    for word in saved_words:
        normalized = normalize_caption_text(word, max_chars=100)
        key = normalized.casefold()
        if normalized and key not in seen_words:
            words.append(normalized)
            seen_words.add(key)
        if len(words) >= 20:
            break

    # 대화 이력은 최근 턴만 전달해 오래된 대화가 현재 질문을 가리지 않게 한다.
    history: list[ConversationTurn] = []
    for turn in conversation_history[-history_limit:]:
        role = turn.role if turn.role in {"user", "tutor"} else "user"
        message = normalize_caption_text(turn.message, max_chars=1_000)
        if message:
            history.append(ConversationTurn(role=role, message=message))

    return TutorContext(
        video_id=normalize_caption_text(video_id, max_chars=100),
        timestamp=max(float(timestamp), 0.0),
        user_message=normalize_caption_text(user_message, max_chars=2_000),
        current_subtitle=current_subtitle,
        nearby_subtitles=tuple(selected_lines),
        saved_words=tuple(words),
        conversation_history=tuple(history),
        focus_word=normalize_caption_text(focus_word, max_chars=100) or None,
    )


def format_subtitles(context: TutorContext) -> str:
    """프롬프트에 넣을 자막을 한 줄씩 포맷한다.

    현재 재생 줄에는 ``CURRENT`` 표시를 붙이고, 번역 자막이 없으면 명시적인
    placeholder를 사용한다. 반환 문자열은 prompt builder가 XML-like 데이터 블록
    안에 삽입하므로 자막 내용 자체가 시스템 지시로 해석되지 않도록 한다.
    """

    if not context.nearby_subtitles:
        return "(제공된 자막 문맥 없음)"

    current = context.current_subtitle
    rows: list[str] = []
    for line in context.nearby_subtitles:
        marker = "CURRENT" if current and line == current else ""
        korean = line.korean or "(번역 자막 없음)"
        rows.append(f"[{marker} t={line.timestamp:.1f}] EN: {line.english} | KO: {korean}")
    return "\n".join(rows)
