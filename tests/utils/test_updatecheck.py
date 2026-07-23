import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
        lambda url: updatecheck.normalized_version(),
    )

    available, remote, error = await updatecheck.check_for_updates_once(
        bot, announce=False, require_enabled=False
    )

    assert available is False
    assert remote == updatecheck.normalized_version()
    assert error is None


def test_fetch_latest_release_version_sync_falls_back_to_redirect(monkeypatch):
    calls = []

    def api(url):
        calls.append(("api", url))
        raise RuntimeError("api down")

    def redirect(url):
        calls.append(("redirect", url))
        return "2.0.0"

    monkeypatch.setattr(updatecheck, "fetch_latest_release_version_via_github_api_sync", api)
    monkeypatch.setattr(updatecheck, "fetch_latest_release_version_via_redirect_sync", redirect)

    assert updatecheck.fetch_latest_release_version_sync("https://example.test/latest") == "2.0.0"
    assert calls == [
        ("api", "https://example.test/latest"),
        ("redirect", "https://example.test/latest"),
    ]


def test_updatecheck_settings_targets_and_notification_type(monkeypatch):
    monkeypatch.setitem(updatecheck.config, "version_check_enabled", True)
    monkeypatch.setitem(updatecheck.config, "version_check_interval", 1)
    monkeypatch.setitem(updatecheck.config, "version_check_url", "https://example.test/releases/latest")
    assert updatecheck.version_check_settings() == (
        True,
        60,
        "https://example.test/releases/latest",
    )

    monkeypatch.setitem(updatecheck.config, "version_check_notify_jid", " room@conf.test ")
    monkeypatch.setitem(updatecheck.config, "owner", "owner@example.org")
    assert updatecheck.update_notification_target() == "room@conf.test"

    monkeypatch.setitem(updatecheck.config, "version_check_notify_jid", "  ")
    assert updatecheck.update_notification_target() is None
    monkeypatch.setitem(updatecheck.config, "version_check_notify_jid", None)
    assert updatecheck.update_notification_target() == "owner@example.org"

    bot = SimpleNamespace(presence=SimpleNamespace(joined_rooms={"room@conf.test": "Bot"}))
    assert updatecheck._notification_type(bot, "room@conf.test") == "groupchat"
    assert updatecheck._notification_type(bot, "user@example.org") == "chat"

    class BadPresence:
        @property
        def joined_rooms(self):
            raise RuntimeError("broken")

    assert updatecheck._notification_type(SimpleNamespace(presence=BadPresence()), "room@conf.test") == "chat"


@pytest.mark.asyncio
async def test_send_update_notification_targets_room_and_skips_missing_helpers(monkeypatch):
    monkeypatch.setitem(updatecheck.config, "version_check_url", "https://example.test/releases/latest")
    monkeypatch.setitem(updatecheck.config, "version_check_notify_jid", "room@conf.test")
    monkeypatch.setitem(updatecheck.config, "owner", "owner@example.org")

    sent = []

    async def safe_send(message):
        sent.append(message)

    def make_message(**kwargs):
        return kwargs

    bot = SimpleNamespace(
        presence=SimpleNamespace(joined_rooms={"room@conf.test": "Bot"}),
        make_message=make_message,
        _safe_send_message=safe_send,
    )
    assert await updatecheck.send_update_notification(bot, "9.9.9") is True
    assert sent[0]["mto"] == "room@conf.test"
    assert sent[0]["mtype"] == "groupchat"
    assert "9.9.9" in sent[0]["mbody"]

    sent.clear()
    assert await updatecheck.send_update_notification(SimpleNamespace(), "9.9.9") is False
    assert sent == []

    monkeypatch.setitem(updatecheck.config, "version_check_notify_jid", "")
    monkeypatch.setitem(updatecheck.config, "owner", "")
    assert await updatecheck.send_update_notification(bot, "9.9.9") is False
    assert sent == []


@pytest.mark.asyncio
async def test_check_for_updates_once_missing_error_and_announce_dedup(monkeypatch):
    bot = SimpleNamespace(last_version_check_result=None, last_update_notified_version=None)
    monkeypatch.setattr(updatecheck, "version_check_settings", lambda: (True, 3600, ""))
    assert await updatecheck.check_for_updates_once(bot) == (False, None, "Version check URL is missing")

    monkeypatch.setattr(updatecheck, "version_check_settings", lambda: (True, 3600, "https://example.test"))
    monkeypatch.setattr(updatecheck, "fetch_latest_release_version_sync", lambda url: (_ for _ in ()).throw(RuntimeError("boom")))
    assert await updatecheck.check_for_updates_once(bot) == (False, None, "boom")

    notify = AsyncMock(return_value=True)
    monkeypatch.setattr(updatecheck, "fetch_latest_release_version_sync", lambda url: "9.9.9")
    monkeypatch.setattr(updatecheck, "send_update_notification", notify)
    available, remote, error = await updatecheck.check_for_updates_once(bot, announce=True)
    assert (available, remote, error) == (True, "9.9.9", None)
    notify.assert_awaited_once_with(bot, "9.9.9")
    assert bot.last_update_notified_version == "9.9.9"

    notify.reset_mock()
    await updatecheck.check_for_updates_once(bot, announce=True)
    notify.assert_not_awaited()

    bot.last_update_notified_version = None
    notify.reset_mock(return_value=True)
    notify.return_value = False
    await updatecheck.check_for_updates_once(bot, announce=True)
    notify.assert_awaited_once_with(bot, "9.9.9")
    assert bot.last_update_notified_version is None

    notify.reset_mock(return_value=True)
    notify.return_value = True
    await updatecheck.check_for_updates_once(bot, announce=True)
    assert bot.last_update_notified_version == "9.9.9"


@pytest.mark.asyncio
async def test_version_check_worker_cancelled(monkeypatch):
    async def cancelled(bot, announce=True):
        raise asyncio.CancelledError

    monkeypatch.setattr(updatecheck, "version_check_settings", lambda: (True, 60, "https://example.test"))
    monkeypatch.setattr(updatecheck, "check_for_updates_once", cancelled)

    with pytest.raises(asyncio.CancelledError):
        await updatecheck.version_check_worker(SimpleNamespace())


@pytest.mark.asyncio
async def test_send_update_notification_joins_muc_target(monkeypatch):
    monkeypatch.setitem(updatecheck.config, "version_check_url", "https://example.test/releases/latest")
    monkeypatch.setitem(updatecheck.config, "version_check_notify_jid", "room@conf.test")
    monkeypatch.setitem(updatecheck.config, "owner", "owner@example.org")

    joined = AsyncMock()
    monkeypatch.setattr(updatecheck, "ensure_notification_target_joined", joined)

    sent = []

    async def safe_send(message):
        sent.append(message)

    def make_message(**kwargs):
        return kwargs

    bot = SimpleNamespace(
        presence=SimpleNamespace(joined_rooms={}),
        make_message=make_message,
        _safe_send_message=safe_send,
    )

    assert await updatecheck.send_update_notification(bot, "9.9.9") is True

    joined.assert_awaited_once_with(bot, "room@conf.test")
    assert sent[0]["mto"] == "room@conf.test"


def test_redirect_version_fetch_validates_request_and_redirect_shape(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["user_agent"] = req.get_header("User-agent")
        captured["timeout"] = timeout
        return FakeResponse(
            final_url="https://github.com/envs-net/envsbot/releases/tag/vv1.7.0/"
        )

    monkeypatch.setattr(updatecheck, "_user_agent", lambda: "envsbot-test-agent")
    monkeypatch.setattr(updatecheck, "_timeout", lambda: 12.5)
    monkeypatch.setattr(updatecheck.urllib.request, "urlopen", fake_urlopen)

    assert updatecheck.fetch_latest_release_version_via_redirect_sync(
        "https://github.com/envs-net/envsbot/releases/latest"
    ) == "v1.7.0"
    assert captured == {
        "url": "https://github.com/envs-net/envsbot/releases/latest",
        "user_agent": "envsbot-test-agent",
        "timeout": 12.5,
    }


@pytest.mark.parametrize("value", ["", None])
def test_redirect_version_fetch_rejects_missing_configuration(value):
    with pytest.raises(ValueError, match="^version_check_url is not configured$"):
        updatecheck.fetch_latest_release_version_via_redirect_sync(value)


@pytest.mark.parametrize(
    ("final_url", "message"),
    [
        (
            "https://github.com/envs-net/envsbot/releases/latest",
            "Unexpected release redirect URL",
        ),
        (
            "https://github.com/envs-net/envsbot/releases/tag/",
            "Could not extract release tag from redirect URL",
        ),
        (
            "https://github.com/envs-net/envsbot/releases/tag////",
            "Could not extract release tag from redirect URL",
        ),
        (
            "https://github.com/envs-net/envsbot/releases/tag/v1.7.0/notes",
            "Could not extract release tag from redirect URL",
        ),
    ],
)
def test_redirect_version_fetch_rejects_invalid_final_urls(monkeypatch, final_url, message):
    monkeypatch.setattr(
        updatecheck.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(final_url=final_url),
    )
    with pytest.raises(ValueError, match=message):
        updatecheck.fetch_latest_release_version_via_redirect_sync(
            "https://github.com/envs-net/envsbot/releases/latest"
        )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/o/r/releases/tag/v1.7.0", "1.7.0"),
        ("https://github.com/o/r/releases/tag/1.7.0/", "1.7.0"),
        ("https://github.com/o/r/releases/tag/v1.7.0?x=1#fragment", "1.7.0"),
        ("https://github.com/o/r/releases/tag/release%20candidate", "release candidate"),
        ("https://github.com/o/r/releases/tag/vv1.7.0", "v1.7.0"),
    ],
)
def test_release_tag_from_redirect_url_uses_one_path_segment(url, expected):
    assert updatecheck._release_tag_from_redirect_url(url) == expected
