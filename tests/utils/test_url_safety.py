import pytest

from utils import url_safety


def test_validate_fetch_url_allows_public_hostname_with_resolver():
    resolver_calls = []

    def resolver(hostname):
        resolver_calls.append(hostname)
        return ["93.184.216.34"]

    url = "https://example.org/path"

    assert url_safety.validate_fetch_url(url, resolver=resolver) == url
    assert resolver_calls == ["example.org"]


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.org/feed",
        "https:///missing-host",
        "http://localhost/",
        "http://service.localhost/",
        "http://127.0.0.1/",
        "http://10.1.2.3/",
        "http://172.16.0.1/",
        "http://192.168.1.10/",
        "http://169.254.169.254/",
        "http://[::1]/",
    ],
)
def test_validate_fetch_url_rejects_unsafe_literal_targets(url):
    with pytest.raises(url_safety.UnsafeFetchURL):
        url_safety.validate_fetch_url(url, resolver=lambda hostname: [])


def test_validate_fetch_url_rejects_hostname_resolving_to_private_address():
    with pytest.raises(url_safety.UnsafeFetchURL):
        url_safety.validate_fetch_url(
            "https://internal.example.org/",
            resolver=lambda hostname: ["192.168.1.5"],
        )


def test_validate_fetch_url_allow_private_skips_network_checks():
    url = "http://127.0.0.1/status"

    assert url_safety.validate_fetch_url(url, allow_private=True) == url


def test_validate_fetch_url_wraps_resolver_failures(monkeypatch):
    def fail_getaddrinfo(*args, **kwargs):
        raise OSError("dns down")

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", fail_getaddrinfo)

    with pytest.raises(url_safety.UnsafeFetchURL, match="could not be resolved"):
        url_safety.validate_fetch_url("https://example.org/feed")


@pytest.mark.asyncio
async def test_validate_fetch_url_async_uses_same_policy():
    result = await url_safety.validate_fetch_url_async(
        "https://example.org/feed",
        resolver=lambda hostname: ["93.184.216.34"],
    )

    assert result == "https://example.org/feed"
