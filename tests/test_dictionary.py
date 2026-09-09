"""사전·Redis 캐시 흐름을 외부 네트워크 없이 검증한다."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi.testclient import TestClient

from app.api.v1.dictionary import get_dictionary_service
from app.cache.redis_client import RedisJsonCache
from app.core.config import settings
from app.main import app
from app.services.dict_service import (
    DictionaryProviderError,
    DictionaryResult,
    DictionaryService,
    normalize_word,
    parse_free_dictionary_payload,
    parse_wiktionary_payload,
    select_distinct_meanings,
)


client = TestClient(app)


class MemoryCache:
    """Redis 대신 테스트에서 사용하는 작은 비동기 메모리 캐시."""

    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}

    async def get_json(self, key: str) -> dict[str, Any] | None:
        return self.values.get(key)

    async def set_json(
        self,
        key: str,
        value: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> bool:
        self.values[key] = value
        return True


def test_normalize_word_uses_one_cache_key_for_case_variants():
    """대소문자가 다른 같은 단어가 같은 Redis 키 기준을 사용한다."""

    assert normalize_word("  Honest, ") == "honest"


def test_select_distinct_meanings_removes_similar_values_and_limits_to_five():
    """상세 응답은 비슷한 뜻을 합치고 최대 5개까지만 제공한다."""

    meanings = select_distinct_meanings(
        [
            "정직한",
            "정직한 사람",
            "세다/계산하다",
            "중요하다",
            "간주하다/믿다",
            "정확하다",
            "공정하다",
        ],
        max_count=5,
    )

    assert meanings == (
        "정직한",
        "세다/계산하다",
        "중요하다",
        "간주하다/믿다",
        "정확하다",
    )


def test_invalid_redis_url_disables_cache_without_crashing():
    """Redis URL 오타가 있어도 사전 서비스 자체는 시작할 수 있다."""

    cache = RedisJsonCache("https://not-a-redis-url")

    assert cache.enabled is False


def test_parse_free_dictionary_payload_extracts_definition_and_example():
    """Free Dictionary의 중첩 응답에서 필요한 값을 추출한다."""

    parsed = parse_free_dictionary_payload(
        [
            {
                "phonetic": "/ˈɒnɪst/",
                "meanings": [
                    {
                        "partOfSpeech": "adjective",
                        "definitions": [
                            {
                                "definition": "Not disposed to cheat or lie",
                                "example": "She was honest about the mistake.",
                            }
                        ],
                    }
                ],
            }
        ],
        "honest",
    )

    assert parsed["phonetic"] == "/ˈɒnɪst/"
    assert parsed["part_of_speech"] == "adjective"
    assert parsed["english_definitions"] == ["Not disposed to cheat or lie"]
    assert parsed["examples"] == ["She was honest about the mistake."]


def test_parse_wiktionary_payload_extracts_english_entry_and_removes_markup():
    """보조 provider 응답의 HTML 링크를 화면용 텍스트로 정리한다."""

    parsed = parse_wiktionary_payload(
        {
            "en": [
                {
                    "partOfSpeech": "Adjective",
                    "definitions": [
                        {
                            "definition": "<a>Scrupulous</a> with regard to truth.",
                            "examples": ["<b>honest</b> reporting"],
                        }
                    ],
                }
            ]
        },
        "honest",
    )

    assert parsed["part_of_speech"] == "Adjective"
    assert parsed["english_definitions"] == [
        "Scrupulous with regard to truth."
    ]
    assert parsed["examples"] == ["honest reporting"]
    assert parsed["source"] == "wiktionary"


def test_parse_wiktionary_payload_prioritizes_common_senses():
    """희귀·법률 의미보다 일반적인 학습 의미를 먼저 배치한다."""

    parsed = parse_wiktionary_payload(
        {
            "en": [
                {
                    "partOfSpeech": "noun",
                    "definitions": [
                        {
                            "definition": "(law, euphemistic) The human genitalia; specifically the penis.",
                            "rawTags": ["law", "euphemistic"],
                        },
                        {
                            "definition": "An individual who has been granted personhood; usually a human being.",
                            "rawTags": [],
                        },
                    ],
                }
            ]
        },
        "person",
    )

    assert parsed["english_definitions"][0].startswith("An individual")


def test_parse_wiktionary_payload_extracts_base_lemma_from_inflected_form():
    """활용형 설명에서 기본형을 찾아 별도 조회할 수 있게 한다."""

    parsed = parse_wiktionary_payload(
        {
            "en": [
                {
                    "partOfSpeech": "verb",
                    "definitions": [
                        {
                            "definition": "third-person singular simple present indicative of have"
                        }
                    ],
                },
                {
                    "partOfSpeech": "noun",
                    "definitions": [
                        {"definition": "plural of ha (the physical body)"}
                    ],
                },
            ]
        },
        "has",
    )

    assert parsed["english_definitions"] == []
    assert parsed["lemma"] == "have"


def test_dictionary_service_caches_only_the_queried_word(monkeypatch):
    """첫 조회 뒤 같은 단어를 다시 요청하면 외부 사전 호출을 생략한다."""

    cache = MemoryCache()
    service = DictionaryService(cache=cache)
    calls = {"dictionary": 0, "deepl": 0}

    async def fake_dictionary(
        word: str,
        *,
        base_url: str,
    ) -> dict[str, Any]:
        calls["dictionary"] += 1
        return {
            "phonetic": "/ˈɒnɪst/",
            "part_of_speech": "adjective",
            "english_definitions": ["Not disposed to cheat or lie"],
            "examples": [],
        }

    async def fake_translate(
        definitions: list[str],
        context: str | None,
    ) -> tuple[str, ...]:
        calls["deepl"] += 1
        return ("정직한",)

    monkeypatch.setattr(service, "_load_from_free_dictionary", fake_dictionary)
    monkeypatch.setattr(service, "_translate_definitions", fake_translate)

    first = asyncio.run(service.lookup("honest"))
    second = asyncio.run(service.lookup("HONEST"))

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert calls == {"dictionary": 1, "deepl": 1}
    assert list(cache.values) == ["dictionary:v3:word:honest"]


def test_dictionary_service_uses_parser_for_configured_wiktionary_url(monkeypatch):
    """환경변수가 Wiktionary를 가리키면 Free Dictionary 파서를 사용하지 않는다."""

    service = DictionaryService(cache=MemoryCache())
    provider_calls: list[tuple[str, str]] = []

    async def fake_wiktionary(
        word: str,
        *,
        base_url: str,
    ) -> dict[str, Any]:
        provider_calls.append((word, base_url))
        return {
            "phonetic": None,
            "part_of_speech": "Adjective",
            "english_definitions": ["Truthful and sincere"],
            "examples": [],
            "source": "wiktionary",
        }

    async def unexpected_free_dictionary(word: str) -> dict[str, Any]:
        raise AssertionError("Wiktionary 설정에서 Free Dictionary를 호출하면 안 됩니다.")

    async def fake_translate(
        definitions: list[str],
        context: str | None,
    ) -> tuple[str, ...]:
        return ("정직한",)

    monkeypatch.setattr(
        settings,
        "dictionary_api_url",
        "https://en.wiktionary.org/api/rest_v1/page/definition/{word}",
    )
    monkeypatch.setattr(
        settings,
        "dictionary_fallback_api_url",
        "https://api.dictionaryapi.dev/api/v2/entries/en/{word}",
    )
    monkeypatch.setattr(service, "_load_from_free_dictionary", unexpected_free_dictionary)
    monkeypatch.setattr(service, "_load_from_wiktionary", fake_wiktionary)
    monkeypatch.setattr(service, "_translate_definitions", fake_translate)

    result = asyncio.run(service.lookup("honest"))

    assert result.definition_translations == ("정직한",)
    assert provider_calls == [
        ("honest", "https://en.wiktionary.org/api/rest_v1/page/definition/{word}")
    ]


def test_dictionary_service_uses_wiktionary_when_primary_provider_fails(monkeypatch):
    """Free Dictionary timeout 때 보조 provider 결과로 조회를 계속한다."""

    service = DictionaryService(cache=MemoryCache())
    provider_calls: list[str] = []

    async def primary_provider_error(
        word: str,
        *,
        base_url: str,
    ) -> dict[str, Any]:
        provider_calls.append("free_dictionary")
        raise DictionaryProviderError("timeout")

    async def fallback_dictionary(
        word: str,
        *,
        base_url: str,
    ) -> dict[str, Any]:
        provider_calls.append("wiktionary")
        return {
            "phonetic": None,
            "part_of_speech": "Adjective",
            "english_definitions": ["Truthful and sincere"],
            "examples": [],
            "source": "wiktionary",
        }

    async def fake_translate(
        definitions: list[str],
        context: str | None,
    ) -> tuple[str, ...]:
        return ("정직한",)

    monkeypatch.setattr(
        service,
        "_load_from_free_dictionary",
        primary_provider_error,
    )
    monkeypatch.setattr(service, "_load_from_wiktionary", fallback_dictionary)
    monkeypatch.setattr(service, "_translate_definitions", fake_translate)

    result = asyncio.run(service.lookup("honest"))

    assert result.source == "wiktionary"
    assert result.definition_translations == ("정직한",)
    assert provider_calls == ["free_dictionary", "wiktionary"]


def test_dictionary_service_selects_contextual_meaning_from_translated_candidates(
    monkeypatch,
):
    """문맥 힌트가 상세 뜻 후보와 일치하면 해당 뜻을 Hover 대표값으로 쓴다."""

    service = DictionaryService(cache=MemoryCache())

    async def fake_dictionary(
        word: str,
        *,
        base_url: str,
    ) -> dict[str, Any]:
        return {
            "phonetic": None,
            "part_of_speech": "Adjective",
            "english_definitions": ["Open; frank.", "Accurate."],
            "examples": [],
            "source": "free_dictionary",
        }

    async def fake_translate(
        definitions: list[str],
        context: str | None,
    ) -> tuple[str, ...]:
        if context:
            return ("솔직한",)
        return ("솔직한; 거침없는", "정확한")

    monkeypatch.setattr(service, "_load_from_free_dictionary", fake_dictionary)
    monkeypatch.setattr(service, "_translate_definitions", fake_translate)

    result = asyncio.run(
        service.lookup(
            "honest",
            context="You have to be honest with yourself.",
        )
    )

    assert result.context_meaning == "솔직한; 거침없는"


def test_dictionary_service_uses_translation_when_dictionary_providers_fail(
    monkeypatch,
):
    """두 사전 provider가 실패해도 단어 자체 번역으로 Hover 뜻을 유지한다."""

    service = DictionaryService(cache=MemoryCache())

    async def primary_provider_error(word: str) -> dict[str, Any]:
        raise DictionaryProviderError("primary unavailable")

    async def fallback_provider_error(word: str) -> dict[str, Any]:
        raise DictionaryProviderError("fallback unavailable")

    async def fake_translate(
        definitions: list[str],
        context: str | None,
    ) -> tuple[str, ...]:
        assert definitions == ["honest"]
        assert context is None
        return ("정직한",)

    monkeypatch.setattr(service, "_load_primary_dictionary", primary_provider_error)
    monkeypatch.setattr(service, "_load_fallback_dictionary", fallback_provider_error)
    monkeypatch.setattr(service, "_translate_definitions", fake_translate)

    result = asyncio.run(service.lookup("honest"))

    assert result.source == "deepl_fallback"
    assert result.definition_translations == ("정직한",)
    assert result.english_definitions == ()
    assert result.cache_hit is False


def test_dictionary_translation_fallback_does_not_cache_context_as_base_word(
    monkeypatch,
):
    """문맥이 섞인 fallback 뜻은 다음 자막의 단어 조회에 재사용하지 않는다."""

    cache = MemoryCache()
    service = DictionaryService(cache=cache)
    translate_calls: list[tuple[list[str], str | None]] = []

    async def provider_error(word: str) -> dict[str, Any]:
        raise DictionaryProviderError("provider unavailable")

    async def fake_translate(
        definitions: list[str],
        context: str | None,
    ) -> tuple[str, ...]:
        translate_calls.append((definitions, context))
        return ("솔직한",)

    monkeypatch.setattr(service, "_load_primary_dictionary", provider_error)
    monkeypatch.setattr(service, "_load_fallback_dictionary", provider_error)
    monkeypatch.setattr(service, "_translate_definitions", fake_translate)

    result = asyncio.run(
        service.lookup("honest", context="Be honest with yourself.")
    )

    assert result.context_meaning == "솔직한"
    assert translate_calls == [(["honest"], "Be honest with yourself.")]
    assert cache.values == {}


class FakeDictionaryService:
    """라우터 테스트에서 외부 API 대신 고정 응답을 반환한다."""

    async def lookup(
        self,
        word: str,
        context: str | None = None,
    ) -> DictionaryResult:
        return DictionaryResult(
            word=word,
            phonetic="/ˈɒnɪst/",
            part_of_speech="adjective",
            english_definitions=("Not disposed to cheat or lie",),
            definition_translations=("정직한", "솔직한"),
            examples=("Be honest with yourself.",),
            context_meaning="현재 문장에서는 솔직한 의미입니다.",
            source="redis",
            cache_hit=True,
        )


def test_dictionary_routes_return_hover_and_detail_contract():
    """Hover·상세 라우터가 프론트엔드용 JSON 형태를 반환한다."""

    app.dependency_overrides[get_dictionary_service] = FakeDictionaryService
    try:
        hover_response = client.get(
            "/api/v1/dictionary/hover",
            params={
                "word": "honest",
                "context": "You have to be honest with yourself.",
            },
        )
        detail_response = client.get(
            "/api/v1/dictionary/detail",
            params={
                "word": "honest",
                "context": "You have to be honest with yourself.",
            },
        )
        legacy_hover_response = client.get(
            "/api/v1/dict/hover",
            params={
                "word": "honest",
                "context": "You have to be honest with yourself.",
            },
        )
        legacy_detail_response = client.get(
            "/api/v1/dict/detail",
            params={
                "word": "honest",
                "context": "You have to be honest with yourself.",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert hover_response.status_code == 200
    assert hover_response.json()["meanings"] == [
        "현재 문장에서는 솔직한 의미입니다."
    ]
    assert detail_response.status_code == 200
    assert detail_response.json()["definitions"] == [
        "현재 문장에서는 솔직한 의미입니다.",
        "정직한",
    ]
    assert detail_response.json()["context_meaning"] == (
        "현재 문장에서는 솔직한 의미입니다."
    )
    assert detail_response.json()["meanings"] == [
        "현재 문장에서는 솔직한 의미입니다.",
        "정직한",
    ]
    assert detail_response.json()["is_saved"] is None
    assert legacy_hover_response.status_code == 200
    assert legacy_hover_response.json()["meanings"] == [
        "현재 문장에서는 솔직한 의미입니다."
    ]
    assert legacy_detail_response.status_code == 200
    assert legacy_detail_response.json()["definitions"] == [
        "현재 문장에서는 솔직한 의미입니다.",
        "정직한",
    ]


def test_dictionary_route_rejects_blank_word():
    """검색어가 없으면 외부 API를 호출하지 않고 422를 반환한다."""

    response = client.get("/api/v1/dictionary/hover?word=")

    assert response.status_code == 422
