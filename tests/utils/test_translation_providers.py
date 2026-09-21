from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from utils import translation_providers as providers


def test_libretranslate_endpoint_accepts_base_or_exact_endpoint():
    assert (
        providers.libretranslate_endpoint("https://translate.envs.net/")
        == "https://translate.envs.net/translate"
    )
    assert (
        providers.libretranslate_endpoint("https://example.org/api/translate")
        == "https://example.org/api/translate"
    )
    with pytest.raises(ValueError, match="empty"):
        providers.libretranslate_endpoint("")


def test_deepl_endpoint_selects_free_and_pro_hosts():
    assert (
        providers.deepl_endpoint("abc:fx")
        == "https://api-free.deepl.com/v2/translate"
    )
    assert (
        providers.deepl_endpoint("abc")
        == "https://api.deepl.com/v2/translate"
    )


@pytest.mark.asyncio
async def test_libretranslate_request_and_response_with_optional_api_key():
    post = AsyncMock(
        return_value={
            "translatedText": "Hallo Welt",
            "detectedLanguage": {"confidence": 99.0, "language": "en"},
        }
    )

    result = await providers.translate_libretranslate(
        "Hello world",
        source_language="auto",
        target_language="de",
        base_url="https://translate.envs.net/",
        api_key="libre-secret",
        timeout_seconds=8,
        max_bytes=262144,
        post_json=post,
    )

    assert result == providers.ProviderTranslation("Hallo Welt", "en")
    kwargs = post.await_args.kwargs
    assert post.await_args.args[0] == "https://translate.envs.net/translate"
    assert kwargs["payload"] == {
        "q": "Hello world",
        "source": "auto",
        "target": "de",
        "format": "text",
        "api_key": "libre-secret",
    }


@pytest.mark.asyncio
async def test_google_cloud_uses_header_key_and_omits_auto_source():
    post = AsyncMock(
        return_value={
            "data": {
                "translations": [
                    {
                        "translatedText": "Hallo &amp; Welt",
                        "detectedSourceLanguage": "en",
                    }
                ]
            }
        }
    )

    result = await providers.translate_google_cloud(
        "Hello & world",
        source_language="auto",
        target_language="de",
        api_key="google-secret",
        timeout_seconds=8,
        max_bytes=262144,
        post_json=post,
    )

    assert result == providers.ProviderTranslation("Hallo & Welt", "en")
    kwargs = post.await_args.kwargs
    assert kwargs["headers"] == {"X-goog-api-key": "google-secret"}
    assert kwargs["payload"] == {
        "q": "Hello & world",
        "target": "de",
        "format": "text",
    }


@pytest.mark.asyncio
async def test_deepl_uses_auth_header_and_normalizes_language_codes():
    post = AsyncMock(
        return_value={
            "translations": [
                {
                    "detected_source_language": "EN",
                    "text": "Hallo Welt",
                }
            ]
        }
    )

    result = await providers.translate_deepl(
        "Hello world",
        source_language="en",
        target_language="de",
        api_key="deepl-secret:fx",
        timeout_seconds=8,
        max_bytes=262144,
        post_json=post,
    )

    assert result == providers.ProviderTranslation("Hallo Welt", "en")
    assert (
        post.await_args.args[0]
        == "https://api-free.deepl.com/v2/translate"
    )
    kwargs = post.await_args.kwargs
    assert kwargs["headers"] == {
        "Authorization": "DeepL-Auth-Key deepl-secret:fx"
    }
    assert kwargs["payload"] == {
        "text": ["Hello world"],
        "target_lang": "DE",
        "source_lang": "EN",
    }


@pytest.mark.asyncio
async def test_provider_payload_errors_are_explicit():
    bad = AsyncMock(return_value={"translatedText": ""})
    with pytest.raises(providers.ProviderPayloadError):
        await providers.translate_libretranslate(
            "Hello",
            source_language="en",
            target_language="de",
            base_url="https://translate.envs.net/",
            api_key=None,
            timeout_seconds=8,
            max_bytes=262144,
            post_json=bad,
        )


def test_capability_endpoints_follow_provider_base_urls():
    assert (
        providers.libretranslate_languages_endpoint("https://translate.envs.net/")
        == "https://translate.envs.net/languages"
    )
    assert (
        providers.libretranslate_languages_endpoint(
            "https://translate.envs.net/translate"
        )
        == "https://translate.envs.net/languages"
    )
    assert providers.deepl_base_url("abc:fx") == "https://api-free.deepl.com/v2"
    assert providers.deepl_base_url("abc") == "https://api.deepl.com/v2"


@pytest.mark.asyncio
async def test_libretranslate_capabilities_include_exact_pairs():
    get = AsyncMock(
        return_value=[
            {"code": "de", "name": "German", "targets": ["en", "fr"]},
            {"code": "en", "name": "English", "targets": ["de"]},
        ]
    )

    result = await providers.fetch_libretranslate_capabilities(
        base_url="https://translate.envs.net/",
        timeout_seconds=8,
        max_bytes=262144,
        get_json=get,
    )

    assert result.source_languages == frozenset({"de", "en"})
    assert result.target_languages == frozenset({"de", "en", "fr"})
    assert result.translation_pairs == frozenset(
        {("de", "en"), ("de", "fr"), ("en", "de")}
    )
    assert get.await_args.args[0] == "https://translate.envs.net/languages"


@pytest.mark.asyncio
async def test_google_cloud_capabilities_normalize_language_codes():
    get = AsyncMock(
        return_value={
            "data": {
                "languages": [
                    {"language": "EN"},
                    {"language": "pt_BR"},
                ]
            }
        }
    )

    result = await providers.fetch_google_cloud_capabilities(
        api_key="google-secret",
        timeout_seconds=8,
        max_bytes=262144,
        get_json=get,
    )

    assert result.source_languages == frozenset({"en", "pt-br"})
    assert result.target_languages == frozenset({"en", "pt-br"})
    assert result.translation_pairs is None
    assert get.await_args.kwargs["headers"] == {"X-goog-api-key": "google-secret"}


@pytest.mark.asyncio
async def test_deepl_capabilities_fetch_source_and_target_lists():
    get = AsyncMock(
        side_effect=[
            [{"language": "EN"}, {"language": "DE"}],
            [{"language": "DE"}, {"language": "EN-GB"}, {"language": "EN-US"}],
        ]
    )

    result = await providers.fetch_deepl_capabilities(
        api_key="deepl-secret:fx",
        timeout_seconds=8,
        max_bytes=262144,
        get_json=get,
    )

    assert result.source_languages == frozenset({"en", "de"})
    assert result.target_languages == frozenset({"de", "en-gb", "en-us"})
    assert [call.args[0] for call in get.await_args_list] == [
        "https://api-free.deepl.com/v2/languages",
        "https://api-free.deepl.com/v2/languages",
    ]
    assert [call.kwargs["params"] for call in get.await_args_list] == [
        {"type": "source"},
        {"type": "target"},
    ]
    assert all(
        call.kwargs["headers"]
        == {"Authorization": "DeepL-Auth-Key deepl-secret:fx"}
        for call in get.await_args_list
    )


@pytest.mark.asyncio
async def test_capability_payload_errors_are_explicit():
    with pytest.raises(providers.ProviderPayloadError):
        await providers.fetch_libretranslate_capabilities(
            base_url="https://translate.envs.net/",
            timeout_seconds=8,
            max_bytes=262144,
            get_json=AsyncMock(return_value=[]),
        )

    with pytest.raises(providers.ProviderPayloadError):
        await providers.fetch_google_cloud_capabilities(
            api_key="google-secret",
            timeout_seconds=8,
            max_bytes=262144,
            get_json=AsyncMock(return_value={"data": {"languages": []}}),
        )
