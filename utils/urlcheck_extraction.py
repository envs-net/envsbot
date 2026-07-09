"""URL extraction helpers for the URLCheck plugin."""

from __future__ import annotations

import re
from urllib.parse import urlparse

URL_RE = re.compile(r"https?://[^\s<>\"]+", re.I)


def _is_reddit_url(url: str) -> bool:
    """Return whether *url* points to reddit and should be ignored."""
    parsed = urlparse(url) if url else None
    if parsed is None or parsed.scheme not in ("http", "https"):
        return False
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return hostname == "reddit.com" or hostname.endswith(".reddit.com")


def extract_urls_from_message_text(text: str) -> list[str]:
    """Extract URLs from chat text while ignoring quotes and code blocks."""
    lines: list[str] = []
    in_code_block = False

    for line in str(text or "").splitlines():
        if "```" in line:
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if not line.lstrip().startswith(">"):
            lines.append(line)

    urls: list[str] = []
    for line in lines:
        for url in URL_RE.findall(line):
            if _is_reddit_url(url):
                continue
            urls.append(url)
    return urls
