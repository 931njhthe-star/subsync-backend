"""Free Dictionary와 DeepL을 연결하는 사전 조회 서비스."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from app.cache.redis_client import RedisJsonCache
from app.core.config import settings


logger = logging.getLogger(__name__)


class DictionaryWordNotFound(Exception):
    """Free Dictionary에서 검색 단어를 찾지 못했을 때 발생한다."""


class DictionaryProviderError(Exception):
    """외부 사전·번역 provider에 일시적인 문제가 있을 때 발생한다."""


@dataclass(frozen=True)
class DictionaryResult:
    """라우터가 사용할 수 있도록 정리한 사전 결과."""

    word: str
    phonetic: str | None
    part_of_speech: str | None
    english_definitions: tuple[str, ...]
    definition_translations: tuple[str, ...]
    examples: tuple[str, ...]
    context_meaning: str | None
    source: str
    cache_hit: bool


def normalize_word(word: str) -> str:
    """검색어 앞뒤의 불필요한 공백·구두점을 정리한다.

    같은 단어를 대소문자만 다르게 조회해도 Redis에서 같은 키를 사용해야 하므로
    ``casefold``를 적용한다. 실제 화면에 표시할 표기는 라우터에서 정규화 전
    입력을 사용할 수 있지만, 사전 검색과 캐시 키는 이 값을 사용한다.
    """

    cleaned = re.sub(r"\s+", " ", word.strip())
    cleaned = cleaned.strip(".,!?;:()[]{}\"")
    if not cleaned or len(cleaned) > 100:
        raise ValueError("검색 단어는 1~100자여야 합니다.")
    return cleaned.casefold()


def parse_free_dictionary_payload(
    payload: Any,
    requested_word: str,
) -> dict[str, Any]:
    """Free Dictionary 응답 JSON을 애플리케이션 공통 형태로 변환한다."""

    if not isinstance(payload, list) or not payload:
        raise DictionaryWordNotFound(requested_word)

    first_entry = payload[0]
    if not isinstance(first_entry, dict):
        raise DictionaryWordNotFound(requested_word)

    phonetic = first_entry.get("phonetic")
    if not phonetic:
        for phonetic_item in first_entry.get("phonetics", []):
            if isinstance(phonetic_item, dict) and phonetic_item.get("text"):
                phonetic = phonetic_item["text"]
                break

    part_of_speech: str | None = None
    english_definitions: list[str] = []
    examples: list[str] = []

    for meaning in first_entry.get("meanings", []):
        if not isinstance(meaning, dict):
            continue
        part_of_speech = part_of_speech or meaning.get("partOfSpeech")
        for definition_item in meaning.get("definitions", []):
            if not isinstance(definition_item, dict):
                continue
            definition = definition_item.get("definition")
            if isinstance(definition, str) and definition.strip():
                english_definitions.append(definition.strip())
            example = definition_item.get("example")
            if isinstance(example, str) and example.strip():
                examples.append(example.strip())

    if not english_definitions:
        raise DictionaryWordNotFound(requested_word)

    return {
        "phonetic": phonetic,
        "part_of_speech": part_of_speech,
        "english_definitions": english_definitions,
        "examples": examples,
    }


class DictionaryService:
    """Redis → Free Dictionary → DeepL 순서로 단어 뜻을 조회한다."""

    def __init__(self, cache: RedisJsonCache | None = None) -> None:
        """사전 서비스와 Redis 캐시를 준비한다."""

        self.cache = cache or RedisJsonCache(
            settings.redis_url,
            default_ttl_seconds=settings.dictionary_cache_ttl_seconds,
        )

    async def lookup(
        self,
        word: str,
        context: str | None = None,
    ) -> DictionaryResult:
        """단어 뜻을 조회하고 선택적으로 자막 문맥 뜻을 번역한다.

        Redis에는 전체 자막을 미리 넣지 않는다. 사용자가 실제로 Hover/Click한
        단어만 ``dictionary:v1:word:<word>`` 키로 저장한다. 문맥 뜻은 문장마다
        달라질 수 있으므로 문장 원문 대신 SHA-256 일부를 키에 사용한다.
        """

        normalized = normalize_word(word)
        base_key = f"dictionary:v1:word:{normalized}"
        cached_base = await self.cache.get_json(base_key)
        cache_hit = cached_base is not None

        if cached_base is None:
            base_data = await self._load_from_free_dictionary(normalized)
            # 기본 번역은 문맥 없이 저장해 특정 자막 문장이 다른 조회 결과를
            # 오염시키지 않게 한다. 문맥 번역은 아래에서 별도의 키로 처리한다.
            base_data["definition_translations"] = list(
                await self._translate_definitions(
                    base_data["english_definitions"],
                    context=None,
                )
            )
            await self.cache.set_json(base_key, base_data)
        else:
            base_data = cached_base

        context_meaning: str | None = None
        if context and context.strip():
            context_key = self._context_cache_key(normalized, context)
            cached_context = await self.cache.get_json(context_key)
            if cached_context is not None:
                context_meaning = cached_context.get("context_meaning")
            else:
                context_meaning = await self._translate_context(
                    base_data["english_definitions"][0],
                    context.strip(),
                )
                if context_meaning:
                    await self.cache.set_json(
                        context_key,
                        {"context_meaning": context_meaning},
                    )

        return DictionaryResult(
            word=word.strip(),
            phonetic=base_data.get("phonetic"),
            part_of_speech=base_data.get("part_of_speech"),
            english_definitions=tuple(base_data.get("english_definitions", [])),
            definition_translations=tuple(
                base_data.get("definition_translations", [])
            ),
            examples=tuple(base_data.get("examples", [])),
            context_meaning=context_meaning,
            source="redis" if cache_hit else "free_dictionary",
            cache_hit=cache_hit,
        )

    async def _load_from_free_dictionary(self, word: str) -> dict[str, Any]:
        """Free Dictionary API를 호출해 영어 원문 정의를 가져온다."""

        encoded_word = quote(word, safe="")
        if "{word}" in settings.dictionary_api_url:
            url = settings.dictionary_api_url.format(word=encoded_word)
        else:
            url = f"{settings.dictionary_api_url.rstrip('/')}/{encoded_word}"

        try:
            async with httpx.AsyncClient(
                timeout=settings.dictionary_timeout_seconds
            ) as client:
                response = await client.get(url)
                if response.status_code == 404:
                    raise DictionaryWordNotFound(word)
                response.raise_for_status()
                payload = response.json()
        except DictionaryWordNotFound:
            raise
        except (
            httpx.TimeoutException,
            httpx.RequestError,
            httpx.HTTPStatusError,
            ValueError,
        ) as exc:
            logger.warning("dictionary_provider_failed error_type=%s", type(exc).__name__)
            raise DictionaryProviderError("사전 API를 사용할 수 없습니다.") from exc

        return parse_free_dictionary_payload(payload, word)

    async def _translate_definitions(
        self,
        definitions: list[str],
        context: str | None,
    ) -> tuple[str, ...]:
        """영어 정의 여러 개를 DeepL로 한국어 번역한다."""

        if not settings.deepl_api_key or not definitions:
            logger.warning("deepl_translation_skipped reason=missing_key_or_text")
            return ()

        payload: dict[str, Any] = {
            "text": definitions,
            "source_lang": "EN",
            "target_lang": "KO",
        }
        if context:
            payload["context"] = context

        try:
            async with httpx.AsyncClient(timeout=settings.deepl_timeout_seconds) as client:
                response = await client.post(
                    f"{settings.deepl_api_base_url.rstrip('/')}/v2/translate",
                    headers={
                        "Authorization": f"DeepL-Auth-Key {settings.deepl_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
        except (
            httpx.TimeoutException,
            httpx.RequestError,
            httpx.HTTPStatusError,
            ValueError,
        ) as exc:
            logger.warning("deepl_provider_failed error_type=%s", type(exc).__name__)
            return ()

        if not isinstance(result, dict):
            logger.warning("deepl_provider_invalid_response")
            return ()
        translated = result.get("translations", [])
        return tuple(
            item["text"].strip()
            for item in translated
            if isinstance(item, dict)
            and isinstance(item.get("text"), str)
            and item["text"].strip()
        )

    async def _translate_context(self, definition: str, context: str) -> str | None:
        """자막 문맥을 참고해 대표 정의 하나의 문맥 뜻을 번역한다."""

        translations = await self._translate_definitions([definition], context=context)
        return translations[0] if translations else None

    @staticmethod
    def _context_cache_key(word: str, context: str) -> str:
        """문맥 원문을 노출하지 않는 Redis 키를 만든다."""

        digest = hashlib.sha256(context.encode("utf-8")).hexdigest()[:16]
        return f"dictionary:v1:context:{word}:{digest}"
