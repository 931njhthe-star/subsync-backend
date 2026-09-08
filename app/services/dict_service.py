"""Free Dictionary와 DeepL을 연결하는 사전 조회 서비스."""

from __future__ import annotations

import hashlib
import html
import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable
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


def select_distinct_meanings(
    meanings: Iterable[str],
    max_count: int = 5,
) -> tuple[str, ...]:
    """비슷한 뜻을 하나로 보고 앞에서부터 최대 개수만 선택한다.

    provider마다 같은 뜻을 문장형·단어형으로 반복해서 보내는 경우가 있어,
    상세 화면이 같은 번역으로 채워지지 않도록 간단한 문자열 유사도 기준을
    적용한다. ``세다/계산하다``와 ``중요하다``처럼 짧지만 다른 뜻은 보존한다.
    """

    if max_count <= 0:
        return ()

    selected: list[str] = []
    selected_keys: list[str] = []
    for meaning in meanings:
        if not isinstance(meaning, str):
            continue
        cleaned = re.sub(r"\s+", " ", meaning.strip())
        if not cleaned:
            continue

        key = re.sub(r"[\W_]+", "", cleaned.casefold())
        if not key:
            continue
        if any(_meanings_are_similar(key, selected_key) for selected_key in selected_keys):
            continue

        selected.append(cleaned)
        selected_keys.append(key)
        if len(selected) >= max_count:
            break

    return tuple(selected)


def select_shortest_meaning(meanings: Iterable[str]) -> str | None:
    """중복을 제외한 뜻 중 가장 짧은 대표 뜻 하나를 반환한다."""

    distinct = select_distinct_meanings(meanings, max_count=100)
    return min(distinct, key=len) if distinct else None


def _meanings_are_similar(left: str, right: str) -> bool:
    """정확히 같거나 거의 같은 번역인지 판단한다."""

    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    if len(shorter) >= 3 and shorter in longer:
        return True
    return SequenceMatcher(None, left, right).ratio() >= 0.88


def _select_context_meaning(
    context_hint: str,
    meanings: Iterable[str],
) -> str:
    """DeepL의 짧은 문맥 힌트와 일치하는 상세 뜻을 대표값으로 선택한다."""

    hint_key = re.sub(r"[\W_]+", "", context_hint.casefold())
    if not hint_key:
        return context_hint

    for meaning in select_distinct_meanings(meanings, max_count=100):
        meaning_key = re.sub(r"[\W_]+", "", meaning.casefold())
        # 접미사가 달라도 같은 어근(예: 솔직한/솔직하다)을 찾기 위해
        # 문맥 힌트의 앞부분도 비교한다.
        prefixes = {
            hint_key,
            hint_key[: max(2, len(hint_key) - 1)],
            hint_key[:2],
        }
        if any(len(prefix) >= 2 and prefix in meaning_key for prefix in prefixes):
            return meaning

    return context_hint


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
        "source": "free_dictionary",
    }


def parse_wiktionary_payload(
    payload: Any,
    requested_word: str,
) -> dict[str, Any]:
    """Wiktionary REST 응답에서 영어 정의와 예문을 추출한다.

    Wiktionary 응답은 정의 안에 HTML 링크가 포함될 수 있으므로 화면에 보여줄
    텍스트만 남긴다. Free Dictionary와 같은 내부 자료형으로 변환하면 이후
    DeepL 번역과 API 응답 로직을 provider별로 중복 작성하지 않아도 된다.
    """

    english_entries = payload.get("en") if isinstance(payload, dict) else None
    if not isinstance(english_entries, list) or not english_entries:
        raise DictionaryWordNotFound(requested_word)

    part_of_speech: str | None = None
    english_definitions: list[str] = []
    examples: list[str] = []

    for entry in english_entries:
        if not isinstance(entry, dict):
            continue
        part_of_speech = part_of_speech or entry.get("partOfSpeech")
        for definition_item in entry.get("definitions", []):
            if not isinstance(definition_item, dict):
                continue

            definition = _clean_wiktionary_markup(
                definition_item.get("definition")
            )
            if definition:
                english_definitions.append(definition)

            raw_examples = definition_item.get("examples", [])
            if isinstance(raw_examples, list):
                for example in raw_examples:
                    cleaned_example = _clean_wiktionary_markup(example)
                    if cleaned_example and cleaned_example not in examples:
                        examples.append(cleaned_example)

    if not english_definitions:
        raise DictionaryWordNotFound(requested_word)

    return {
        "phonetic": None,
        "part_of_speech": part_of_speech,
        "english_definitions": english_definitions,
        "examples": examples,
        "source": "wiktionary",
    }


def _clean_wiktionary_markup(value: Any) -> str:
    """Wiktionary 정의의 HTML 표시용 태그를 일반 텍스트로 바꾼다."""

    if not isinstance(value, str):
        return ""
    without_tags = re.sub(r"<[^>]*>", "", value)
    return html.unescape(without_tags).strip()


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
            try:
                base_data = await self._load_from_free_dictionary(normalized)
            except (DictionaryWordNotFound, DictionaryProviderError) as exc:
                # 무료 provider의 간헐적인 timeout으로 Hover 전체가 실패하지 않도록
                # Wiktionary를 보조 provider로 사용한다. 기본 provider가 복구되면
                # 다음 캐시 만료 후 다시 Free Dictionary 결과를 우선 사용한다.
                logger.warning(
                    "dictionary_primary_provider_failed error_type=%s",
                    type(exc).__name__,
                )
                try:
                    base_data = await self._load_from_wiktionary(normalized)
                except DictionaryWordNotFound:
                    if isinstance(exc, DictionaryWordNotFound):
                        raise
                    raise DictionaryProviderError(
                        "사전 외부 서비스를 잠시 사용할 수 없습니다."
                    ) from exc
                except DictionaryProviderError as fallback_exc:
                    raise DictionaryProviderError(
                        "사전 외부 서비스를 잠시 사용할 수 없습니다."
                    ) from fallback_exc
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
                    normalized,
                    context.strip(),
                )
                if context_meaning:
                    context_meaning = _select_context_meaning(
                        context_meaning,
                        base_data.get("definition_translations", []),
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
            source=(
                "redis"
                if cache_hit
                else base_data.get("source", "free_dictionary")
            ),
            cache_hit=cache_hit,
        )

    async def _load_from_free_dictionary(self, word: str) -> dict[str, Any]:
        """Free Dictionary API를 호출해 영어 원문 정의를 가져온다."""

        url = self._build_provider_url(settings.dictionary_api_url, word)

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

    async def _load_from_wiktionary(self, word: str) -> dict[str, Any]:
        """Wiktionary REST API를 보조 provider로 호출해 영어 정의를 가져온다."""

        url = self._build_provider_url(settings.dictionary_fallback_api_url, word)
        try:
            async with httpx.AsyncClient(
                timeout=settings.dictionary_timeout_seconds
            ) as client:
                response = await client.get(
                    url,
                    headers={
                        "Accept": "application/json",
                        # Wikimedia API가 자동화 요청을 구분할 수 있도록
                        # 서비스 식별 정보를 보낸다.
                        "User-Agent": "SubSync/0.1 (educational project)",
                    },
                )
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
            logger.warning(
                "dictionary_fallback_provider_failed error_type=%s",
                type(exc).__name__,
            )
            raise DictionaryProviderError("보조 사전 API를 사용할 수 없습니다.") from exc

        return parse_wiktionary_payload(payload, word)

    @staticmethod
    def _build_provider_url(base_url: str, word: str) -> str:
        """환경변수의 URL 형식에 맞춰 단어 경로를 만든다."""

        encoded_word = quote(word, safe="")
        if "{word}" in base_url:
            return base_url.format(word=encoded_word)
        return f"{base_url.rstrip('/')}/{encoded_word}"

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

    async def _translate_context(self, word: str, context: str) -> str | None:
        """자막 문맥을 참고해 단어의 짧은 문맥 뜻을 번역한다."""

        # 긴 정의문 대신 단어 자체를 보내야 Hover에 문장형 설명이 표시되지 않는다.
        translations = await self._translate_definitions([word], context=context)
        return translations[0] if translations else None

    @staticmethod
    def _context_cache_key(word: str, context: str) -> str:
        """문맥 원문을 노출하지 않는 Redis 키를 만든다."""

        digest = hashlib.sha256(context.encode("utf-8")).hexdigest()[:16]
        return f"dictionary:v2:context:{word}:{digest}"
