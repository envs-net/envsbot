"""GitHub release/version check helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.request
from urllib.parse import urlparse

from utils.config import config
from utils.version import __version__, display_version, normalized_version

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
    return str(config.get("http_user_agent") or "Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)")


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
    return tag.lstrip("v")


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

    marker = "/releases/tag/"
    if marker not in final_url:
        raise ValueError(f"Unexpected release redirect URL: {final_url}")

    tag = final_url.split(marker, 1)[1].strip().strip("/")
    if not tag:
        raise ValueError("Could not extract release tag from redirect URL")
    return tag.lstrip("v")


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
    """Return a safe message type for update notifications."""
    try:
        joined_rooms = getattr(getattr(bot, "presence", None), "joined_rooms", {}) or {}
        if target in joined_rooms:
            return "groupchat"
    except Exception:
        log.debug("Could not inspect joined rooms for update notification", exc_info=True)
    return "chat"


async def send_update_notification(bot, remote_version: str) -> None:
    """Send an update notification to the configured target."""
    target = update_notification_target()
    if not target:
        log.debug("Version check found update but no notification target is configured")
        return

    message = getattr(bot, "make_message", None)
    safe_send = getattr(bot, "_safe_send_message", None)
    if not callable(message) or not callable(safe_send):
        log.debug("Version check notification skipped: bot send helpers unavailable")
        return

    release_url = config.get("version_check_url", DEFAULT_RELEASE_URL)
    body = (
        f"⬆️ New EnvsBot version available: {display_version(remote_version)}\n"
        f"Current version: {display_version()}\n"
        f"Release page: {release_url}"
    )
    outbound = message(mto=target, mbody=body, mtype=_notification_type(bot, target))
    await safe_send(outbound)


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
                await send_update_notification(bot, remote_version)
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
        try:
            await check_for_updates_once(bot, announce=True)
        except asyncio.CancelledError:
            log.info("version_check_worker cancelled")
            raise
        except Exception as error:
            log.warning("Error in version_check_worker: %s", error)
        await asyncio.sleep(interval)
