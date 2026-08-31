"""GitHub release/version check helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.request
from urllib.parse import unquote, urlparse, urlsplit

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

DEFAULT_RELEASE_URL = "https://github.com/envs-net/envsbot/releases/latest"


def parse_version_tuple(version: str) -> tuple[int, ...]:
    """Return numeric version parts for simple release comparisons."""
    parts = re.findall(r"\d+", str(version))
    return tuple(int(part) for part in parts)


def is_remote_version_newer(remote_version: str, local_version: str | None = None) -> bool:
    """Return whether *remote_version* is newer than *local_version*."""
    local = normalized_version(local_version or __version__)
    return parse_version_tuple(remote_version) > parse_version_tuple(local)


def github_api_url_from_release_url(release_url: str) -> str | None:
    """Convert a GitHub releases URL to the releases/latest API endpoint."""
    parsed = urlparse(str(release_url))
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc.lower() != "github.com":
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    return f"https://api.github.com/repos/{owner}/{repo}/releases/latest"


def _user_agent() -> str:
    return resolve_user_agent(config.get("http_user_agent"))


def _timeout() -> float:
    return float(config.get("updatecheck_timeout_seconds", 15) or 15)


def fetch_latest_release_version_via_github_api_sync(release_url: str) -> str:
    """Fetch the latest GitHub release tag via the GitHub REST API."""
    api_url = github_api_url_from_release_url(release_url)
    if not api_url:
        raise ValueError("version_check_url is not a supported GitHub releases URL")
    req = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": _user_agent(),
        },
    )
    with urllib.request.urlopen(req, timeout=_timeout()) as response:
        payload = json.loads(response.read().decode("utf-8"))

    tag = str(payload.get("tag_name", "")).strip()
    if not tag:
        raise ValueError("GitHub API response did not contain tag_name")
    return tag.removeprefix("v")


def _release_tag_from_redirect_url(final_url: str) -> str:
    """Extract one release tag path segment from a redirect URL."""
    parsed = urlsplit(str(final_url))
    marker = "/releases/tag/"
    if marker not in parsed.path:
        raise ValueError(f"Unexpected release redirect URL: {final_url}")

    raw_tag = parsed.path.split(marker, 1)[1].strip("/")
    if not raw_tag or "/" in raw_tag:
        raise ValueError("Could not extract release tag from redirect URL")
    tag = unquote(raw_tag).strip()
    if not tag:
        raise ValueError("Could not extract release tag from redirect URL")
    return tag.removeprefix("v")


def fetch_latest_release_version_via_redirect_sync(release_url: str) -> str:
    """Fetch the latest release version via the /releases/latest redirect."""
    if not release_url:
        raise ValueError("version_check_url is not configured")
    req = urllib.request.Request(
        release_url,
        headers={"User-Agent": _user_agent()},
    )
    with urllib.request.urlopen(req, timeout=_timeout()) as response:
        final_url = response.geturl()

    return _release_tag_from_redirect_url(final_url)


def fetch_latest_release_version_sync(release_url: str) -> str:
    """Fetch the latest release version, preferring the GitHub API."""
    if not release_url:
        raise ValueError("version_check_url is not configured")
    try:
        return fetch_latest_release_version_via_github_api_sync(release_url)
    except Exception as api_error:
        log.debug(
            "Version check via GitHub API failed, falling back to redirect: %s",
            api_error,
        )
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
    try:
        remote_version = await asyncio.to_thread(
            fetch_latest_release_version_sync,
            release_url,
        )
        bot.last_version_check_result = remote_version
        current_version = normalized_version()
        if is_remote_version_newer(remote_version, current_version):
            log.info(
                "New EnvsBot version available: remote=%s local=%s url=%s",
                remote_version,
                current_version,
                release_url,
            )
            if announce and getattr(bot, "last_update_notified_version", None) != remote_version:
                if await send_update_notification(bot, remote_version):
                    bot.last_update_notified_version = remote_version
            return True, remote_version, None
        return False, remote_version, None
    except Exception as error:
        log.warning("Version check failed: %s", error)
        return False, None, str(error)


async def version_check_worker(bot) -> None:
    """Periodically check whether a newer bot version is available."""
    while True:
        _enabled, interval, _release_url = version_check_settings()
        await check_for_updates_once(bot, announce=True)
        await sleep_with_heartbeat(bot, "_admin", "version-check", interval)
