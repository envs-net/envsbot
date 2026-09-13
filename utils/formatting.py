"""Formatting helpers shared by plugins."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from envs_xmpp_core.pagination import (
    PageRequest,
    paginate,
    parse_page_request,
)
from envs_xmpp_core.pagination import (
    format_page as core_format_page,
)

from utils.config import config

DEFAULT_PAGINATION = config.get("default_pagination", "all")


def _positive_int(value: object) -> int | None:
    """Return a positive integer from *value*, excluding bools."""
    if isinstance(value, bool):
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def default_page_request(*, default_page: int = 1) -> PageRequest:
    """Return the configured default pagination request.

    ``DEFAULT_PAGINATION = "all"`` shows all items when the user omitted
    explicit paging.  A positive integer, for example ``20``, shows page 1
    with that many items.  Any invalid value falls back to page 1 and the
    command's normal page size.
    """
    value = DEFAULT_PAGINATION
    if str(value).strip().lower() == "all":
        return PageRequest(page=1, all=True)

    page_size = _positive_int(value)
    if page_size is not None:
        return PageRequest(page=default_page, all=False, page_size=page_size)

    return PageRequest(page=default_page, all=False)


def page_size_for(default: int, page_request: PageRequest | None = None) -> int:
    """Return the effective page size for a paginated output."""
    if page_request is not None and page_request.page_size is not None:
        return page_request.page_size
    return max(1, int(default or 10))


def parse_page_args(args: Sequence[str], *, default_page: int = 1) -> PageRequest:
    """Parse optional ``all|last|<page>`` pagination arguments."""
    default = default_page_request(default_page=default_page)
    request, remaining = parse_page_request(args, default=default)
    if remaining:
        return PageRequest(page=max(1, int(default_page)), all=False)
    return request


def paginate_lines(
    lines: Sequence[str] | Iterable[str],
    *,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[str], int, int]:
    """Return the requested slice, normalized page and total pages."""
    result = paginate(
        lines,
        page=page,
        page_size=page_size,
        fallback_page_size=10,
        last_page_sentinel=-1,
    )
    return result.items, result.page, result.total_pages


def format_page(
    title: str,
    lines: Sequence[str] | Iterable[str],
    *,
    page_request: PageRequest | None = None,
    page_size: int = 10,
    command_hint: str | None = None,
    preamble: Sequence[str] | Iterable[str] = (),
) -> list[str]:
    """Format a title and a possibly paginated list using the shared core."""
    request = page_request or PageRequest()
    effective_size = page_size_for(page_size, request)
    return core_format_page(
        title,
        lines,
        page_request=request,
        page_size=effective_size,
        command_hint=command_hint,
        preamble=preamble,
    )


def bool_label(value: bool) -> str:
    """Return a compact enabled/disabled label."""
    return "enabled" if bool(value) else "disabled"


_STATUS_ICONS = {
    "ok": "✅",
    "success": "✅",
    "healthy": "✅",
    "running": "✅",
    "enabled": "✅",
    "info": "ℹ️",
    "done": "ℹ️",
    "disabled": "ℹ️",
    "warning": "⚠️",
    "warn": "⚠️",
    "stale": "⚠️",
    "cancelled": "⚠️",
    "canceled": "⚠️",
    "error": "🔴",
    "failed": "🔴",
    "fail": "🔴",
}


def status_icon(status: str | None) -> str:
    """Return the standard status icon for a status string."""
    return _STATUS_ICONS.get(str(status or "").strip().lower(), "ℹ️")


def status_label(status: str | None, label: str | None = None) -> str:
    """Return ``'<icon> <label>'`` for consistent admin output."""
    label_text = str(label if label is not None else status or "info")
    return f"{status_icon(status)} {label_text}"
