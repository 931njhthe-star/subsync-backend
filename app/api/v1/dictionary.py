"""Hover·Click 사전 조회 API 라우터."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.schemas.dictionary import DictionaryDetailResponse, DictionaryHoverResponse
from app.services.dict_service import (
    DictionaryProviderError,
    DictionaryService,
    DictionaryWordNotFound,
    select_distinct_meanings,
    select_shortest_meaning,
)


router = APIRouter(prefix="/dictionary", tags=["Dictionary"])


@lru_cache(maxsize=1)
def get_dictionary_service() -> DictionaryService:
    """프로세스에서 공유할 사전 서비스를 생성한다."""

    return DictionaryService()


async def _lookup_or_http_error(
    service: DictionaryService,
    word: str,
    context: str | None,
):
    """서비스 예외를 API의 상태 코드로 변환한다."""

    try:
        return await service.lookup(word, context=context)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DictionaryWordNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail="사전에서 단어를 찾을 수 없습니다.",
        ) from exc
    except DictionaryProviderError as exc:
        raise HTTPException(
            status_code=503,
            detail="사전 외부 서비스를 잠시 사용할 수 없습니다.",
        ) from exc


@router.get("/hover", response_model=DictionaryHoverResponse)
async def get_hover_meaning(
    word: Annotated[
        str,
        Query(min_length=1, max_length=100, description="조회할 영어 단어"),
    ],
    context: Annotated[
        str | None,
        Query(max_length=1_000, description="현재 자막 문장"),
    ] = None,
    service: DictionaryService = Depends(get_dictionary_service),
) -> DictionaryHoverResponse:
    """로그인 없이 Hover용 빠른 단어 뜻을 반환한다."""

    result = await _lookup_or_http_error(service, word, context)
    if result.context_meaning:
        # Hover는 영상 시청을 방해하지 않도록 문맥상 대표 뜻 하나만 보여준다.
        meanings = [result.context_meaning]
    else:
        shortest_meaning = select_shortest_meaning(
            result.definition_translations or result.english_definitions
        )
        meanings = [shortest_meaning] if shortest_meaning else []
    return DictionaryHoverResponse(
        word=result.word,
        meanings=meanings,
        source=result.source,
        cache_hit=result.cache_hit,
    )


@router.get("/detail", response_model=DictionaryDetailResponse)
async def get_dictionary_detail(
    word: Annotated[
        str,
        Query(min_length=1, max_length=100, description="조회할 영어 단어"),
    ],
    context: Annotated[
        str | None,
        Query(max_length=1_000, description="현재 자막 문장"),
    ] = None,
    service: DictionaryService = Depends(get_dictionary_service),
) -> DictionaryDetailResponse:
    """로그인 없이 Click용 상세 사전 정보를 반환한다.

    단어 저장 여부는 사용자 JWT와 saved_words 연결이 필요한 별도 기능이므로,
    현재 사전 API에서는 ``is_saved``를 null로 반환한다.
    """

    result = await _lookup_or_http_error(service, word, context)
    # 일부 확장 프로그램 버전은 별도의 context_meaning 필드보다 definitions만
    # 렌더링한다. 문맥 뜻을 목록의 첫 항목으로 함께 넣어 두 버전이 같은 상세
    # 정보를 보여주도록 한다.
    definition_candidates: list[str] = []
    if result.context_meaning:
        definition_candidates.append(result.context_meaning)
    definition_candidates.extend(
        result.definition_translations or result.english_definitions
    )
    definitions = list(
        select_distinct_meanings(definition_candidates, max_count=5)
    )
    english_definitions = list(
        select_distinct_meanings(result.english_definitions, max_count=5)
    )
    return DictionaryDetailResponse(
        word=result.word,
        phonetic=result.phonetic,
        part_of_speech=result.part_of_speech,
        definitions=definitions,
        # 기존 Extension 상세 팝업은 meanings를 사용하므로 definitions와
        # 동일한 번역 목록을 호환 필드로 함께 반환한다.
        meanings=definitions,
        english_definitions=english_definitions,
        context_meaning=result.context_meaning,
        examples=list(result.examples),
        is_saved=None,
        source=result.source,
        cache_hit=result.cache_hit,
    )
