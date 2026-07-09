from __future__ import annotations

import json
from types import MappingProxyType, SimpleNamespace

import pytest

from utils.http_fetch import (
    _response_content_type,
    fetch_bytes,
    fetch_json,
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
