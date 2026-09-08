"""저장 단어의 입력 정리와 Supabase 저장소 호출을 담당하는 서비스."""

from __future__ import annotations

import re
from uuid import UUID

from app.core.config import settings
from app.db.saved_words import (
    SavedWordNotFound,
    SavedWordRecord,
    SavedWordsRepository,
    SavedWordsRepositoryError,
)


def normalize_saved_word(word: str) -> tuple[str, str]:
    """표시용 단어와 중복 확인용 소문자 단어를 반환한다.

    ``Apple``과 ``apple``은 같은 단어로 취급하지만, 처음 저장한 표기인
    ``Apple``은 그대로 보존한다. ``run``과 ``running``은 서로 다른 값이다.
    """

    cleaned = re.sub(r"\s+", " ", word.strip())
    if not cleaned or len(cleaned) > 100:
        raise ValueError("저장할 단어는 1~100자여야 합니다.")
    return cleaned, cleaned.casefold()


class SavedWordService:
    """저장 단어 입력을 정리하고 Supabase repository를 호출한다."""

    def __init__(self, repository: SavedWordsRepository | None = None) -> None:
        """저장 단어 repository를 준비한다."""

        self.repository = repository or SavedWordsRepository(
            url=settings.supabase_url,
            secret_key=settings.supabase_secret_key,
            timeout_seconds=settings.api_log_timeout_seconds,
        )

    async def save_word(
        self,
        *,
        user_id: UUID,
        word: str,
    ) -> tuple[SavedWordRecord, bool]:
        """단어를 저장하고 신규 저장 여부를 반환한다."""

        display_word, word_lower = normalize_saved_word(word)
        return await self.repository.save(
            user_id=user_id,
            word=display_word,
            word_lower=word_lower,
        )

    async def list_words(
        self,
        *,
        user_id: UUID,
        limit: int = 100,
    ) -> list[SavedWordRecord]:
        """사용자의 저장 단어 목록을 조회한다."""

        return await self.repository.list_for_user(user_id=user_id, limit=limit)

    async def delete_word(self, *, user_id: UUID, word_id: UUID) -> None:
        """사용자 소유의 저장 단어를 삭제한다."""

        await self.repository.delete_for_user(user_id=user_id, word_id=word_id)


__all__ = [
    "SavedWordNotFound",
    "SavedWordRecord",
    "SavedWordService",
    "SavedWordsRepositoryError",
    "normalize_saved_word",
]
