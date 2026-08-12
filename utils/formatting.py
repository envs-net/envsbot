"""Formatting helpers shared by plugins."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import ceil

from utils.config import config

DEFAULT_PAGINATION = config.get("default_pagination", "all")


@dataclass(frozen=True)
class PageRequest:
    """Parsed pagination request."""

    page: int = 1
    all: bool = False
    page_size: int | None = None


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
    """Parse optional ``all|last|<page>`` pagination arguments.

    Unknown values fall back to the default page so existing commands remain
    forgiving.  Command-specific arguments should be stripped before calling
    this helper.  When no paging argument is supplied, the configured
    ``DEFAULT_PAGINATION`` setting decides whether to show all items or use a
    configured default page size.
    """
    if not args:
        return default_page_request(default_page=default_page)

    value = str(args[0]).strip().lower()
    if value == "all":
        return PageRequest(page=1, all=True)
    if value == "last":
        return PageRequest(page=-1, all=False)

    try:
        page = int(value)
    except (TypeError, ValueError):
        page = default_page

    return PageRequest(page=max(page, 1), all=False)


def paginate_lines(
    lines: Sequence[str] | Iterable[str],
    *,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[str], int, int]:
    """Return the requested slice, normalized page and total pages."""
    materialized = list(lines)
    if page_size <= 0:
        page_size = 10

    total_pages = max(1, ceil(len(materialized) / page_size))
    if page == -1:
        page = total_pages
    page = min(max(page, 1), total_pages)

    start = (page - 1) * page_size
    end = start + page_size
    return materialized[start:end], page, total_pages


def format_page(
    title: str,
    lines: Sequence[str] | Iterable[str],
    *,
    page_request: PageRequest | None = None,
    page_size: int = 10,
    command_hint: str | None = None,
) -> list[str]:
    """Format a title and a possibly paginated list of lines."""
    page_request = page_request or PageRequest()
    materialized = list(lines)

    if page_request.all:
        result = [title]
        if materialized:
            result.extend(materialized)
        else:
            result.append("—")
        return result

    page_size = page_size_for(page_size, page_request)
    page_lines, page, total_pages = paginate_lines(
        materialized,
        page=page_request.page,
        page_size=page_size,
    )
    suffix = f" (page {page}/{total_pages})" if total_pages > 1 else ""
    result = [title + suffix]
    result.extend(page_lines or ["—"])
    if total_pages > 1 and command_hint:
        result.append(f"Use {command_hint} <page|last|all> for more.")
    return result


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
