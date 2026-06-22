import json
from types import SimpleNamespace

import pytest

from utils import updatecheck


class FakeResponse:
    def __init__(self, payload=b"{}", final_url="https://example.test"):
        self.payload = payload
        self.final_url = final_url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload

    def geturl(self):
        return self.final_url


def test_github_api_url_from_release_url():
    assert (
        updatecheck.github_api_url_from_release_url(
            "https://github.com/envs-net/envsbot/releases/latest"
        )
        == "https://api.github.com/repos/envs-net/envsbot/releases/latest"
    )
    assert updatecheck.github_api_url_from_release_url("https://envs.net") is None


def test_version_comparison():
    assert updatecheck.parse_version_tuple("v1.2.3") == (1, 2, 3)
    assert updatecheck.is_remote_version_newer("1.4.0", "1.3.0") is True
    assert updatecheck.is_remote_version_newer("1.3.0", "1.3.0") is False


def test_fetch_latest_release_version_via_github_api_sync(monkeypatch):
    payload = json.dumps({"tag_name": "v1.4.0"}).encode()
    monkeypatch.setattr(
        updatecheck.urllib.request,
        "urlopen",
        lambda req, timeout=15: FakeResponse(payload),
    )

    assert (
        updatecheck.fetch_latest_release_version_via_github_api_sync(
            "https://github.com/envs-net/envsbot/releases/latest"
        )
        == "1.4.0"
    )


def test_fetch_latest_release_version_via_redirect_sync(monkeypatch):
    monkeypatch.setattr(
        updatecheck.urllib.request,
        "urlopen",
        lambda req, timeout=15: FakeResponse(
            final_url="https://github.com/envs-net/envsbot/releases/tag/v1.4.0"
        ),
    )

    assert (
        updatecheck.fetch_latest_release_version_via_redirect_sync(
            "https://github.com/envs-net/envsbot/releases/latest"
        )
        == "1.4.0"
    )


@pytest.mark.asyncio
async def test_check_for_updates_once_disabled(monkeypatch):
    monkeypatch.setattr(
        updatecheck,
        "version_check_settings",
        lambda: (False, 3600, "https://example.test"),
    )

    result = await updatecheck.check_for_updates_once(SimpleNamespace())

    assert result == (False, None, "Version check is disabled")


@pytest.mark.asyncio
async def test_check_for_updates_once_newer(monkeypatch):
    bot = SimpleNamespace(last_version_check_result=None)
    monkeypatch.setattr(
        updatecheck,
        "version_check_settings",
        lambda: (True, 3600, "https://example.test"),
    )
    monkeypatch.setattr(
        updatecheck,
        "fetch_latest_release_version_sync",
        lambda url: "9.9.9",
    )

    available, remote, error = await updatecheck.check_for_updates_once(
        bot, announce=False
    )

    assert available is True
    assert remote == "9.9.9"
    assert error is None
    assert bot.last_version_check_result == "9.9.9"


@pytest.mark.asyncio
async def test_check_for_updates_once_manual_bypasses_disabled(monkeypatch):
    bot = SimpleNamespace(last_version_check_result=None)
    monkeypatch.setattr(
        updatecheck,
        "version_check_settings",
        lambda: (False, 3600, "https://example.test"),
    )
    monkeypatch.setattr(
        updatecheck,
        "fetch_latest_release_version_sync",
        lambda url: "1.3.0",
    )

    available, remote, error = await updatecheck.check_for_updates_once(
        bot, announce=False, require_enabled=False
    )

    assert available is False
    assert remote == "1.3.0"
    assert error is None
