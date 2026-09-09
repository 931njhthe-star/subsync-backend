"""저장 단어 API의 요청·응답 Pydantic 모델."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SavedWordCreateRequest(BaseModel):
    """저장 버튼을 눌렀을 때 받는 단어 요청."""

    word: str = Field(
        min_length=1,
        max_length=100,
        description="저장할 영어 단어 또는 표현",
        examples=["Apple"],
    )


class SavedWordResponse(BaseModel):
    """저장된 단어 한 건의 응답."""

    id: UUID = Field(description="저장 단어 ID")
    word: str = Field(description="처음 저장한 표기")
    word_lower: str = Field(
        description="대소문자 중복 확인용 정규화 값",
    )
    saved_at: datetime = Field(description="저장 시각")


class SavedWordListResponse(BaseModel):
    """사용자의 저장 단어 목록 응답."""

    items: list[SavedWordResponse] = Field(description="저장 단어 목록")
    total: int = Field(description="조회된 저장 단어 수")
