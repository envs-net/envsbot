"""URL extraction helpers for the URLCheck plugin."""

from __future__ import annotations

import re
from urllib.parse import urlparse

URL_RE = re.compile(r"https?://[^\s<>\"]+", re.I)
_TRAILING_PUNCTUATION = ".,;:!?)]}"


def _strip_trailing_punctuation(url: str) -> str:
    """Strip prose punctuation commonly attached after URLs."""
    return url.rstrip(_TRAILING_PUNCTUATION)


def _is_reddit_url(url: str) -> bool:
    """Return whether *url* points to reddit and should be ignored."""
    parsed = urlparse(url) if url else None
    if parsed is None or parsed.scheme not in ("http", "https"):
        return False
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return hostname == "reddit.com" or hostname.endswith(".reddit.com")


def _non_code_segments(text: str) -> list[str]:
    """Return text segments outside markdown-style triple-backtick blocks."""
    lines: list[str] = []
    in_code_block = False

    for raw_line in str(text or "").splitlines():
        if raw_line.startswith(("    ", "\t")) or raw_line.lstrip().startswith(">"):
            continue

        parts = raw_line.split("```")
        for index, part in enumerate(parts):
            if not in_code_block and part and not part.lstrip().startswith(">"):
                lines.append(part)
            if index < len(parts) - 1:
                in_code_block = not in_code_block

    return lines


def extract_urls_from_message_text(text: str) -> list[str]:
    """Extract URLs from chat text while ignoring quotes and code blocks."""
    urls: list[str] = []
    for line in _non_code_segments(text):
        for url in URL_RE.findall(line):
            url = _strip_trailing_punctuation(url)
            if not url or _is_reddit_url(url):
                continue
            urls.append(url)
    return urls
