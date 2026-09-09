"""Supabase ``saved_words`` 테이블에 접근하는 저장소 계층."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import httpx


logger = logging.getLogger(__name__)


class SavedWordsRepositoryError(Exception):
    """Supabase 저장소를 사용할 수 없거나 응답 형식이 잘못되었을 때 발생한다."""


class SavedWordNotFound(Exception):
    """사용자 소유의 저장 단어를 찾지 못했을 때 발생한다."""


@dataclass(frozen=True)
class SavedWordRecord:
    """``saved_words`` 한 행을 애플리케이션에서 다루는 자료형."""

    id: UUID
    user_id: UUID
    word: str
    word_lower: str
    saved_at: datetime


class SavedWordsRepository:
    """Supabase REST Data API를 이용해 저장 단어를 읽고 쓴다.

    Google OAuth가 아직 연결되지 않은 개발 단계에서는 서버 전용 키로 REST API를
    호출한다. 이 키는 RLS를 우회할 수 있으므로 이 저장소는 브라우저에서 직접
    호출하지 않으며, OAuth가 연결되면 검증된 JWT를 사용하는 방식으로 교체한다.
    """

    def __init__(
        self,
        *,
        url: str,
        secret_key: str,
        timeout_seconds: float = 2.0,
    ) -> None:
        """Supabase REST 주소와 서버 전용 키를 설정한다."""

        self._url = url.rstrip("/")
        self._secret_key = secret_key
        self._timeout_seconds = max(timeout_seconds, 0.1)

    @property
    def is_configured(self) -> bool:
        """Supabase 요청에 필요한 주소와 키가 모두 있는지 반환한다."""

        return bool(self._url and self._secret_key)

    def _headers(self, prefer: str | None = None) -> dict[str, str]:
        """Supabase REST 요청에 공통으로 사용할 헤더를 만든다."""

        headers = {
            "apikey": self._secret_key,
            "Authorization": f"Bearer {self._secret_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    async def _request(
        self,
        method: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
        prefer: str | None = None,
    ) -> list[dict[str, Any]]:
        """``saved_words`` REST 요청을 보내고 행 목록으로 변환한다."""

        if not self.is_configured:
            raise SavedWordsRepositoryError("Supabase 설정이 없습니다.")

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.request(
                    method,
                    f"{self._url}/rest/v1/saved_words",
                    headers=self._headers(prefer),
                    params=params,
                    json=json_body,
                )
                if response.status_code >= 400:
                    logger.warning(
                        "saved_words_supabase_failed method=%s status_code=%s",
                        method,
                        response.status_code,
                    )
                    raise SavedWordsRepositoryError(
                        "Supabase saved_words 요청이 실패했습니다."
                    )
                payload = response.json()
        except SavedWordsRepositoryError:
            raise
        except (
            httpx.TimeoutException,
            httpx.RequestError,
            ValueError,
        ) as exc:
            logger.warning(
                "saved_words_supabase_request_failed method=%s error_type=%s",
                method,
                type(exc).__name__,
            )
            raise SavedWordsRepositoryError(
                "Supabase saved_words 서비스를 사용할 수 없습니다."
            ) from exc

        # return=minimal을 사용하지 않는 요청은 행 목록을 반환한다. 빈 응답은
        # 중복 저장을 무시했거나 삭제할 행이 없다는 의미로 처리한다.
        if payload is None:
            return []
        if not isinstance(payload, list) or not all(
            isinstance(row, dict) for row in payload
        ):
            raise SavedWordsRepositoryError(
                "Supabase saved_words 응답 형식이 올바르지 않습니다."
            )
        return payload

    @staticmethod
    def _to_record(row: dict[str, Any]) -> SavedWordRecord:
        """Supabase JSON 행을 ``SavedWordRecord``로 변환한다."""

        try:
            saved_at_value = row["saved_at"]
            if isinstance(saved_at_value, datetime):
                saved_at = saved_at_value
            else:
                saved_at = datetime.fromisoformat(
                    str(saved_at_value).replace("Z", "+00:00")
                )
            if saved_at.tzinfo is None:
                saved_at = saved_at.replace(tzinfo=timezone.utc)
            return SavedWordRecord(
                id=UUID(str(row["id"])),
                user_id=UUID(str(row["user_id"])),
                word=str(row["word"]),
                word_lower=str(row["word_lower"]),
                saved_at=saved_at,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SavedWordsRepositoryError(
                "Supabase saved_words 행 형식이 올바르지 않습니다."
            ) from exc

    async def save(
        self,
        *,
        user_id: UUID,
        word: str,
        word_lower: str,
    ) -> tuple[SavedWordRecord, bool]:
        """사용자 단어를 저장하고 ``(행, 신규 저장 여부)``를 반환한다.

        ``(user_id, word_lower)`` unique index와 함께 upsert를 사용하므로 동시에
        같은 단어를 저장해도 대소문자만 다른 중복 행이 만들어지지 않는다.
        """

        row = {
            "id": str(uuid4()),
            "user_id": str(user_id),
            "word": word,
            "word_lower": word_lower,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        rows = await self._request(
            "POST",
            params={"on_conflict": "user_id,word_lower"},
            json_body=row,
            prefer="resolution=ignore-duplicates,return=representation",
        )
        if rows:
            return self._to_record(rows[0]), True

        # 이미 같은 단어가 있으면 기존 행을 반환해 저장 버튼을 멱등적으로 만든다.
        existing = await self.find_by_word_lower(
            user_id=user_id,
            word_lower=word_lower,
        )
        if existing is None:
            raise SavedWordsRepositoryError(
                "단어 저장 결과를 확인할 수 없습니다."
            )
        return existing, False

    async def find_by_word_lower(
        self,
        *,
        user_id: UUID,
        word_lower: str,
    ) -> SavedWordRecord | None:
        """사용자의 정규화된 단어가 이미 저장되어 있는지 조회한다."""

        rows = await self._request(
            "GET",
            params={
                "select": "id,user_id,word,word_lower,saved_at",
                "user_id": f"eq.{user_id}",
                "word_lower": f"eq.{word_lower}",
                "limit": "1",
            },
        )
        return self._to_record(rows[0]) if rows else None

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        limit: int = 100,
    ) -> list[SavedWordRecord]:
        """사용자의 저장 단어를 최근 저장 순서로 조회한다."""

        rows = await self._request(
            "GET",
            params={
                "select": "id,user_id,word,word_lower,saved_at",
                "user_id": f"eq.{user_id}",
                "order": "saved_at.desc",
                "limit": str(limit),
            },
        )
        return [self._to_record(row) for row in rows]

    async def delete_for_user(self, *, user_id: UUID, word_id: UUID) -> None:
        """사용자 소유의 저장 단어 한 건을 삭제한다."""

        rows = await self._request(
            "DELETE",
            params={
                "id": f"eq.{word_id}",
                "user_id": f"eq.{user_id}",
                "select": "id",
            },
            prefer="return=representation",
        )
        if not rows:
            raise SavedWordNotFound


__all__ = [
    "SavedWordNotFound",
    "SavedWordRecord",
    "SavedWordsRepository",
    "SavedWordsRepositoryError",
]
