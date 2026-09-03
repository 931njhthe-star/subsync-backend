"""Tutor 답변에 Hover/Click 상호작용을 붙이기 위한 영어 표현 추출기.

모델이 반환한 답변을 HTML로 다시 해석하지 않고, 원문 문자열의 위치 정보를 별도로
제공한다. 프론트엔드는 이 위치를 이용해 안전하게 영어 표현만 인터랙티브 요소로
렌더링할 수 있다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# 일반적인 영어 단어와 하이픈/아포스트로피가 포함된 표현을 찾는다.
_ENGLISH_TOKEN_RE = re.compile(
    r"(?<![A-Za-z])[A-Za-z]+(?:['-][A-Za-z]+)*(?![A-Za-z])"
)


@dataclass(frozen=True)
class ReplyToken:
    """Tutor 답변에서 추출한 영어 표현의 표시 위치."""

    surface: str
    normalized: str
    start: int
    end: int
    interactive: bool = True


def _utf16_length(value: str) -> int:
    """JavaScript 문자열 offset과 호환되는 UTF-16 code unit 길이를 계산한다."""

    return len(value.encode("utf-16-le")) // 2


def extract_reply_tokens(reply: str) -> tuple[ReplyToken, ...]:
    """답변에 포함된 영어 단어·표현을 Hover/Click 토큰으로 변환한다.

    Args:
        reply: 사용자에게 표시할 Tutor 답변 원문.

    Returns:
        답변 순서대로 정렬된 불변 토큰 목록. ``start``와 ``end``는 Python code
        point가 아니라 JavaScript가 사용하는 UTF-16 code unit 기준이다.

    Note:
        현재 버전은 품사 분석이나 기본형(lemmatization)을 수행하지 않는다. 따라서
        ``went``는 ``went``로 검색되며, 추후 사전 연동 계층에서 기본형 변환을
        추가할 수 있다.
    """

    if not reply:
        return ()

    tokens: list[ReplyToken] = []
    for match in _ENGLISH_TOKEN_RE.finditer(reply):
        surface = match.group(0)
        # 관사 ``a``나 대문자 등 한 글자 조각은 사전 Hover 대상으로 만들지 않는다.
        if len(surface) < 2:
            continue
        start = _utf16_length(reply[: match.start()])
        end = _utf16_length(reply[: match.end()])
        tokens.append(
            ReplyToken(
                surface=surface,
                normalized=surface.casefold(),
                start=start,
                end=end,
            )
        )
    return tuple(tokens)


__all__ = ["ReplyToken", "extract_reply_tokens"]
