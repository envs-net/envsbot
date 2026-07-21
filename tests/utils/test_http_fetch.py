from __future__ import annotations

import json
from unittest.mock import AsyncMock
from types import MappingProxyType, SimpleNamespace

import pytest

from utils.http_fetch import (
    _response_content_type,
    fetch_bytes,
    fetch_json,
    fetch_preview,
    passthrough_validator,
)
from utils.url_safety import UnsafeFetchURL


class FakeResponse:
    def __init__(
        self,
        *,
        body=b"{}",
        status=200,
        headers=None,
        url="https://example.test/",
    ):
        self._body = body
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}
        self.url = url

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def text(self):
        return self._body.decode("utf-8")


class FakeStreamContent:
    def __init__(self, chunks):
        self._chunks = tuple(chunks)

    async def iter_chunked(self, _size):
        for chunk in self._chunks:
            yield chunk


class FakeStreamResponse(FakeResponse):
    def __init__(self, *, chunks, **kwargs):
        super().__init__(body=b"", **kwargs)
        self.content = FakeStreamContent(chunks)


class FakeSession:
    def __init__(self, response, calls, *, accepts_timeout=True):
        self._response = response
        self._calls = calls
        self._accepts_timeout = accepts_timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def get(self, url, *, timeout=None, allow_redirects=False):
        if timeout is not None and not self._accepts_timeout:
            raise TypeError("timeout is not supported by this test double")
        self._calls.append({
            "url": url,
            "timeout": timeout,
            "allow_redirects": allow_redirects,
        })
        return self._response


def _factory_for(response, calls, *, accepts_timeout=True):
    def factory(**_kwargs):
        return FakeSession(response, calls, accepts_timeout=accepts_timeout)

    return factory


@pytest.mark.asyncio
async def test_fetch_bytes_passes_timeout_and_disables_redirects():
    calls = []

    result = await fetch_bytes(
        "https://example.test/data.json",
        validator=passthrough_validator,
        session_factory=_factory_for(FakeResponse(body=b"ok"), calls),
    )

    assert result.body == b"ok"
    assert calls
    assert calls[0]["timeout"] is not None
    assert calls[0]["allow_redirects"] is False


@pytest.mark.asyncio
async def test_fetch_bytes_fallback_still_disables_redirects():
    calls = []

    await fetch_bytes(
        "https://example.test/data.json",
        validator=passthrough_validator,
        session_factory=_factory_for(FakeResponse(), calls, accepts_timeout=False),
    )

    assert calls == [
        {
            "url": "https://example.test/data.json",
            "timeout": None,
            "allow_redirects": False,
        }
    ]


def test_response_content_type_accepts_mapping_headers():
    response = SimpleNamespace(
        headers=MappingProxyType({"Content-Type": "application/json"})
    )

    assert _response_content_type(response) == "application/json"


@pytest.mark.asyncio
async def test_fetch_json_empty_response_raises_decode_error():
    with pytest.raises(json.JSONDecodeError):
        await fetch_json(
            "https://example.test/empty.json",
            validator=passthrough_validator,
            session_factory=_factory_for(FakeResponse(body=b""), []),
        )


@pytest.mark.asyncio
async def test_fetch_bytes_raises_after_redirect_limit():
    response = FakeResponse(status=302, headers={"Location": "/next"})

    with pytest.raises(UnsafeFetchURL, match="too many redirects"):
        await fetch_bytes(
            "https://example.test/start",
            validator=passthrough_validator,
            session_factory=_factory_for(response, []),
            max_redirects=0,
        )


@pytest.mark.asyncio
async def test_fetch_bytes_redirect_without_location_raises():
    response = FakeResponse(status=302, headers={})

    with pytest.raises(
        UnsafeFetchURL,
        match="redirect response without Location header",
    ):
        await fetch_bytes(
            "https://example.test/start",
            validator=passthrough_validator,
            session_factory=_factory_for(response, []),
        )



@pytest.mark.asyncio
async def test_fetch_preview_returns_partial_body_without_large_error():
    calls = []
    body = b"<html><head><title>Example</title></head>" + b"x" * 1000

    result = await fetch_preview(
        "https://example.test/large.html",
        validator=passthrough_validator,
        session_factory=_factory_for(
            FakeResponse(
                body=body,
                headers={
                    "Content-Type": "text/html",
                    "Content-Length": str(len(body)),
                },
            ),
            calls,
        ),
        max_bytes=64,
    )

    assert result.body == body[:64]
    assert result.content_length == len(body)
    assert result.truncated is True


@pytest.mark.asyncio
async def test_fetch_preview_obeys_stop_predicate():
    result = await fetch_preview(
        "https://example.test/large.html",
        validator=passthrough_validator,
        session_factory=_factory_for(
            FakeStreamResponse(
                chunks=[b"<html><head>", b"<title>Example</title>", b"x" * 1000],
                headers={"Content-Type": "text/html"},
            ),
            [],
        ),
        max_bytes=256,
        stop_when=lambda data: b"</title>" in data,
    )

    assert result.body == b"<html><head><title>Example</title>"
    assert result.truncated is False




@pytest.mark.asyncio
async def test_pinned_resolver_uses_only_validated_addresses():
    from utils.http_fetch import _PinnedResolver
    from utils.url_safety import ValidatedFetchTarget

    resolver = _PinnedResolver(
        ValidatedFetchTarget(
            "https://example.org/path",
            "example.org",
            443,
            ("93.184.216.34", "2001:4860:4860::8888"),
        )
    )

    ipv4 = await resolver.resolve("example.org", 443, family=__import__("socket").AF_INET)
    assert [item["host"] for item in ipv4] == ["93.184.216.34"]
    assert all(item["hostname"] == "example.org" for item in ipv4)

    both = await resolver.resolve("EXAMPLE.ORG.", 443, family=__import__("socket").AF_UNSPEC)
    assert {item["host"] for item in both} == {
        "93.184.216.34",
        "2001:4860:4860::8888",
    }

    with pytest.raises(OSError, match="differs"):
        await resolver.resolve("attacker.example", 443)


@pytest.mark.asyncio
async def test_validated_hop_builds_pinned_connector_for_real_aiohttp(monkeypatch):
    from utils import http_fetch
    from utils.url_safety import ValidatedFetchTarget, validate_fetch_url_async

    target = ValidatedFetchTarget(
        "https://example.org/path",
        "example.org",
        443,
        ("93.184.216.34",),
    )
    monkeypatch.setattr(http_fetch, "resolve_fetch_target_async", AsyncMock(return_value=target))
    connector = object()
    monkeypatch.setattr(http_fetch, "_pinned_connector", lambda value: connector)

    url, resolved_connector = await http_fetch._validated_hop(
        target.url,
        validator=validate_fetch_url_async,
        allow_private=False,
        session_factory=http_fetch.aiohttp.ClientSession,
    )

    assert url == target.url
    assert resolved_connector is connector
