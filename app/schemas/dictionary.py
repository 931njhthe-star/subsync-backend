"""사전 API의 요청·응답 Pydantic 모델."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DictionaryPhrase(BaseModel):
    """상세 사전에서 제공할 표현 하나."""

    expression: str = Field(description="영어 표현")
    meaning: str = Field(description="표현의 한국어 뜻")


class DictionaryHoverResponse(BaseModel):
    """Hover에서 빠르게 표시할 기본 뜻 응답."""

    word: str = Field(description="조회한 단어", examples=["honest"])
    meanings: list[str] = Field(
        description=(
            "자막 문맥이 있으면 대표 뜻 하나를 제공하며, 문맥이 없으면 "
            "가장 짧은 뜻 하나를 제공함"
        ),
    )
    source: str = Field(
        description=(
            "응답 출처: redis, free_dictionary, wiktionary 또는 "
            "deepl_fallback"
        )
    )
    cache_hit: bool = Field(description="기본 단어 캐시 적중 여부")


class DictionaryDetailResponse(BaseModel):
    """Click 시 표시할 사전 상세 응답."""

    word: str = Field(description="조회한 단어", examples=["honest"])
    phonetic: str | None = Field(default=None, description="발음 기호")
    part_of_speech: str | None = Field(default=None, description="품사")
    definitions: list[str] = Field(
        description="중복을 줄인 한국어 정의 최대 5개"
    )
    meanings: list[str] = Field(
        default_factory=list,
        description=(
            "프론트엔드 상세 팝업 호환용 한국어 뜻 목록. "
            "definitions와 같은 값을 제공함"
        ),
    )
    english_definitions: list[str] = Field(
        description="중복을 줄인 영어 정의 최대 5개"
    )
    context_meaning: str | None = Field(
        default=None,
        description="자막 문장을 참고한 문맥상 의미",
    )
    examples: list[str] = Field(description="영어 예문 목록")
    phrases: list[DictionaryPhrase] = Field(
        default_factory=list,
        description="연관 표현. Free Dictionary 응답에 없으면 빈 목록",
    )
    is_saved: bool | None = Field(
        default=None,
        description="인증·saved_words 연동 전에는 null",
    )
    source: str = Field(
        description=(
            "응답 출처: redis, free_dictionary, wiktionary 또는 "
            "deepl_fallback"
        )
    )
    cache_hit: bool = Field(description="기본 단어 캐시 적중 여부")
