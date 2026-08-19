"""HTTP User-Agent helpers shared by envsbot network clients."""

from __future__ import annotations

from utils.version import normalized_version

LEGACY_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)"
)
DEFAULT_USER_AGENT_TEMPLATE = (
    "envsbot/{version} (https://github.com/envs-net/envsbot)"
)


def automatic_user_agent(version: str | None = None) -> str:
    """Return envsbot's release-aware default User-Agent."""
    return DEFAULT_USER_AGENT_TEMPLATE.format(version=normalized_version(version))


def resolve_user_agent(value: object | None) -> str:
    """Resolve a configured User-Agent, expanding the ``{version}`` token.

    The historical built-in Mozilla-style value is treated as an automatic
    default so existing configurations receive the release-aware User-Agent
    without requiring an operator edit after upgrading.
    """
    raw = str(value or "").strip()
    if not raw or raw == LEGACY_DEFAULT_USER_AGENT:
        raw = DEFAULT_USER_AGENT_TEMPLATE
    return raw.replace("{version}", normalized_version())
