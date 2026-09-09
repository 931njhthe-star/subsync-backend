"""사용자 저장 단어의 저장·조회·삭제 API 라우터."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.api.deps import get_saved_words_user_id
from app.core.config import settings
from app.db.saved_words import SavedWordNotFound, SavedWordsRepositoryError
from app.schemas.words import (
    SavedWordCreateRequest,
    SavedWordListResponse,
    SavedWordResponse,
)
from app.services.word_service import SavedWordRecord, SavedWordService


router = APIRouter(prefix="/words", tags=["Saved Words"])


@lru_cache(maxsize=1)
def get_saved_word_service() -> SavedWordService:
    """프로세스에서 공유할 저장 단어 서비스를 생성한다."""

    return SavedWordService()


def _to_response(record: SavedWordRecord) -> SavedWordResponse:
    """repository 행을 프론트엔드 응답 모델로 변환한다."""

    return SavedWordResponse(
        id=record.id,
        word=record.word,
        word_lower=record.word_lower,
        saved_at=record.saved_at,
    )


def _raise_repository_error(exc: SavedWordsRepositoryError) -> None:
    """Supabase 장애를 외부에 내부 상세 없이 503으로 변환한다."""

    raise HTTPException(
        status_code=503,
        detail="저장 단어 데이터베이스를 잠시 사용할 수 없습니다.",
    ) from exc


@router.post("", response_model=SavedWordResponse, status_code=201)
async def create_saved_word(
    request: SavedWordCreateRequest,
    response: Response,
    user_id: Annotated[UUID, Depends(get_saved_words_user_id)],
    service: Annotated[SavedWordService, Depends(get_saved_word_service)],
) -> SavedWordResponse:
    """현재 사용자의 단어를 저장한다.

    같은 사용자가 대소문자만 다르게 다시 저장하면 기존 행을 반환하고 상태 코드는
    ``200``으로 바꾼다. 이렇게 저장 버튼을 여러 번 눌러도 단어가 중복되지 않는다.
    """

    try:
        record, created = await service.save_word(
            user_id=user_id,
            word=request.word,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SavedWordsRepositoryError as exc:
        _raise_repository_error(exc)

    if not created:
        response.status_code = 200
    return _to_response(record)


@router.get("", response_model=SavedWordListResponse)
async def list_saved_words(
    user_id: Annotated[UUID, Depends(get_saved_words_user_id)],
    service: Annotated[SavedWordService, Depends(get_saved_word_service)],
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="최대 조회 개수"),
    ] = 100,
) -> SavedWordListResponse:
    """현재 사용자의 저장 단어를 최근 저장 순으로 조회한다."""

    try:
        records = await service.list_words(user_id=user_id, limit=limit)
    except SavedWordsRepositoryError as exc:
        _raise_repository_error(exc)

    return SavedWordListResponse(
        items=[_to_response(record) for record in records],
        total=len(records),
    )


@router.delete("/{word_id}", status_code=204)
async def delete_saved_word(
    word_id: UUID,
    user_id: Annotated[UUID, Depends(get_saved_words_user_id)],
    service: Annotated[SavedWordService, Depends(get_saved_word_service)],
) -> Response:
    """현재 사용자의 저장 단어를 삭제한다."""

    try:
        await service.delete_word(user_id=user_id, word_id=word_id)
    except SavedWordNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail="삭제할 저장 단어를 찾을 수 없습니다.",
        ) from exc
    except SavedWordsRepositoryError as exc:
        _raise_repository_error(exc)

    return Response(status_code=204)
