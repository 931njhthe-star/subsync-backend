"""Dictionary용 Redis JSON 캐시 래퍼.

Redis가 잠시 중단되더라도 사전 조회 자체는 외부 API를 통해 계속될 수 있도록
캐시 오류를 호출자에게 전파하지 않는다. 캐시에는 API Key나 사용자 토큰을
저장하지 않는다.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError


logger = logging.getLogger(__name__)


class RedisJsonCache:
    """JSON 직렬화를 사용하는 비동기 Redis 캐시."""

    def __init__(self, url: str, default_ttl_seconds: int = 86_400) -> None:
        """Redis URL과 기본 만료 시간을 받아 캐시 객체를 만든다.

        Args:
            url: ``redis://`` 또는 ``rediss://`` 형식의 접속 URL.
            default_ttl_seconds: 별도 TTL이 없을 때 사용할 캐시 보관 시간.
        """

        self.default_ttl_seconds = max(1, default_ttl_seconds)
        self._client: Redis | None = None

        # 로컬에서 Redis URL을 비워 둔 경우에도 애플리케이션이 시작되어야 하므로
        # 이 시점에는 예외를 내지 않고 비활성 캐시로 동작시킨다.
        if url.strip():
            try:
                self._client = Redis.from_url(
                    url.strip(),
                    decode_responses=True,
                    socket_connect_timeout=3,
                    socket_timeout=3,
                )
            except ValueError:
                # 환경변수 오타가 있어도 사전 API까지 함께 중단시키지 않도록
                # Redis만 비활성화하고 다음 조회를 원본 provider로 보낸다.
                logger.warning("dictionary_cache_invalid_url")

    @property
    def enabled(self) -> bool:
        """Redis 클라이언트가 설정되어 있는지 반환한다."""

        return self._client is not None

    async def get_json(self, key: str) -> dict[str, Any] | None:
        """키에 저장된 JSON 객체를 읽는다.

        Redis 장애나 잘못된 캐시 값은 캐시 miss로 취급한다. 이렇게 해야 캐시가
        원본 사전 API보다 더 큰 장애 지점이 되지 않는다.
        """

        if self._client is None:
            return None

        try:
            raw_value = await self._client.get(key)
        except (RedisError, OSError):
            logger.warning("dictionary_cache_get_failed")
            return None

        if raw_value is None:
            return None

        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError:
            logger.warning("dictionary_cache_invalid_json")
            return None

        return value if isinstance(value, dict) else None

    async def set_json(
        self,
        key: str,
        value: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> bool:
        """JSON 객체를 TTL과 함께 저장하고 성공 여부를 반환한다."""

        if self._client is None:
            return False

        ttl = max(1, ttl_seconds or self.default_ttl_seconds)
        try:
            await self._client.set(
                key,
                json.dumps(value, ensure_ascii=False),
                ex=ttl,
            )
        except (RedisError, OSError):
            logger.warning("dictionary_cache_set_failed")
            return False
        return True

    async def close(self) -> None:
        """애플리케이션 종료 시 Redis 연결 풀을 닫는다."""

        if self._client is not None:
            await self._client.aclose()
