"""GitHub release/version check helpers."""

from __future__ import annotations

import logging
import urllib.request

from envs_xmpp_core.release.checks import check_latest_release
from envs_xmpp_core.release.github import (
    fetch_latest_release_version_via_github_api_sync as _core_fetch_api,
)
from envs_xmpp_core.release.github import (
    fetch_latest_release_version_via_redirect_sync as _core_fetch_redirect,
)
from envs_xmpp_core.release.github import (
    github_api_url_from_release_url,
)
from envs_xmpp_core.release.github import (
    release_tag_from_redirect_url as _release_tag_from_redirect_url,
)
from envs_xmpp_core.release.versions import (
    compare_versions,
    parse_version_tuple,
)

from utils.config import config
from utils.http_user_agent import resolve_user_agent
from utils.task_supervisor import sleep_with_heartbeat
from utils.version import __version__, display_version, normalized_version
from utils.xmpp_notify import (
    ensure_notification_target_joined,
    notification_message_type,
    prepare_notification_target,
)

log = logging.getLogger(__name__)

__all__ = [
    "_release_tag_from_redirect_url",
    "github_api_url_from_release_url",
    "parse_version_tuple",
]

DEFAULT_RELEASE_URL = "https://github.com/envs-net/envsbot/releases/latest"


def is_remote_version_newer(remote_version: str, local_version: str | None = None) -> bool:
    """Return whether *remote_version* is newer than *local_version*."""
    local = normalized_version(local_version or __version__)
    return compare_versions(remote_version, local) > 0


def _user_agent() -> str:
    return resolve_user_agent(config.get("http_user_agent"))


def _timeout() -> float:
    return float(config.get("updatecheck_timeout_seconds", 15) or 15)


def fetch_latest_release_version_via_github_api_sync(release_url: str) -> str:
    try:
        return _core_fetch_api(
            release_url, user_agent=_user_agent(), timeout=_timeout(),
            urlopen=urllib.request.urlopen,
        )
    except ValueError as exc:
        if "supported GitHub" in str(exc):
            raise ValueError("version_check_url is not a supported GitHub releases URL") from exc
        raise


def fetch_latest_release_version_via_redirect_sync(release_url: str) -> str:
    if not release_url:
        raise ValueError("version_check_url is not configured")
    return _core_fetch_redirect(
        release_url, user_agent=_user_agent(), timeout=_timeout(),
        urlopen=urllib.request.urlopen,
    )


def fetch_latest_release_version_sync(release_url: str) -> str:
    if not release_url:
        raise ValueError("version_check_url is not configured")
    try:
        return fetch_latest_release_version_via_github_api_sync(release_url)
    except Exception as api_error:
        log.debug("Version check via GitHub API failed, falling back to redirect: %s", api_error)
        return fetch_latest_release_version_via_redirect_sync(release_url)


def version_check_settings() -> tuple[bool, int, str]:
    """Return enabled flag, interval seconds and release URL from config."""
    enabled = bool(config.get("version_check_enabled", False))
    interval = int(config.get("version_check_interval", 3600) or 3600)
    url = str(config.get("version_check_url", DEFAULT_RELEASE_URL) or "")
    return enabled, max(60, interval), url


def update_notification_target() -> str | None:
    """Return the configured update notification target."""
    target = config.get("version_check_notify_jid") or config.get("owner")
    if target is None:
        return None
    target = str(target).strip()
    return target or None


def _notification_type(bot, target: str) -> str:
    """Return the message type for an already prepared notification target."""
    return notification_message_type(bot, target)


async def send_update_notification(bot, remote_version: str) -> bool:
    """Send an update notification to the configured target.

    Return ``True`` only when the message was handed to the XMPP send path.
    A failed send must not be recorded as notified, otherwise the periodic
    worker suppresses every later retry for the same release.
    """
    target = update_notification_target()
    if not target:
        log.debug("Version check found update but no notification target is configured")
        return False
    message = getattr(bot, "make_message", None)
    safe_send = getattr(bot, "_safe_send_message", None)
    if not callable(message) or not callable(safe_send):
        log.debug("Version check notification skipped: bot send helpers unavailable")
        return False

    joined = await ensure_notification_target_joined(bot, target)
    message_type = await prepare_notification_target(bot, target, joined=joined)
    if message_type is None:
        log.warning(
            "Version check notification deferred: MUC target %s is unavailable",
            target,
        )
        return False

    release_url = config.get("version_check_url", DEFAULT_RELEASE_URL)
    body = (
        f"⬆️ New EnvsBot version available: {display_version(remote_version)}\n"
        f"Current version: {display_version()}\n"
        f"Release page: {release_url}"
    )
    outbound = message(mto=target, mbody=body, mtype=message_type)
    return await safe_send(outbound) is not False


async def check_for_updates_once(
    bot,
    *,
    announce: bool = True,
    require_enabled: bool = True,
) -> tuple[bool, str | None, str | None]:
    """Check once whether a newer release is available.

    Returns ``(is_update_available, remote_version, error_message)``.
    """
    enabled, _interval, release_url = version_check_settings()
    if require_enabled and not enabled:
        return False, None, "Version check is disabled"
    if not release_url:
        return False, None, "Version check URL is missing"
    current_version = normalized_version()
    result = await check_latest_release(
        current_version,
        lambda: fetch_latest_release_version_sync(release_url),
    )
    if result.error:
        log.warning("Version check failed: %s", result.error)
        return result.as_tuple()

    remote_version = result.remote_version
    bot.last_version_check_result = remote_version
    if result.update_available and remote_version is not None:
        log.info(
            "New EnvsBot version available: remote=%s local=%s url=%s",
            remote_version,
            current_version,
            release_url,
        )
        if announce and getattr(bot, "last_update_notified_version", None) != remote_version:
            if await send_update_notification(bot, remote_version):
                bot.last_update_notified_version = remote_version
    return result.as_tuple()


async def version_check_worker(bot) -> None:
    """Periodically check whether a newer bot version is available."""
    while True:
        _enabled, interval, _release_url = version_check_settings()
        await check_for_updates_once(bot, announce=True)
        await sleep_with_heartbeat(bot, "_admin", "version-check", interval)
