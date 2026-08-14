"""Shared helpers for RSS administration commands."""

from __future__ import annotations

from bot.room_state import JOINED_ROOMS
from core_plugins.users import user_has_room_plugin_grant
from utils.command import Role
from utils.config import config

from .config import RSS_BROKEN_ERROR_THRESHOLD
from .fetch import (
    _extract_entry_link,
    _get_entry_id,
    _normalize_url,
    _resolve_relative_url,
    entry_get,
    html_to_text_with_links,
)
from .formatting import (
    _build_rss_message_from_context,
    _build_rss_template_context,
    _entry_date,
    _normalize_direct_user_jid,
)
from .store import (
    _direct_subscription_is_paused,
    _ensure_feed_numbers,
    _feed_active_direct_users,
    _feed_active_rooms,
    _feed_article_count,
    _feed_number,
    _feed_paused_rooms,
    _feed_status_label,
    _format_rss_timestamp,
    _normalize_room_jid,
    _normalize_subscription_room,
    _now,
    get_effective_template,
    log,
)


def _command_prefix(bot=None) -> str:
    """Return the currently configured command prefix for usage replies."""
    return str(
        getattr(bot, "prefix", None)
        or config.get("prefix", ",")
        or ","
    )

def _message_type(msg) -> str:
    """Return a normalized message type for mappings and Slixmpp stanzas."""
    try:
        value = msg["type"]
    except Exception:
        getter = getattr(msg, "get", None)
        try:
            value = getter("type") if callable(getter) else None
        except Exception:
            value = None
    if value in (None, ""):
        value = getattr(msg, "type", "")
    return str(value or "").strip().lower()

def _room_for_feed_command(msg, is_room: bool, explicit_room=None) -> str | None:
    """Return the target room for RSS commands.

    Public MUCs and MUC PMs imply the room. Private chats may pass an
    explicit room JID, which is useful for room-scoped plugin grants and stale
    feed cleanup.
    """
    if explicit_room:
        return _normalize_room_jid(explicit_room)

    sender = msg["from"]
    room_jid = getattr(sender, "bare", None)

    msg_type = _message_type(msg)

    if is_room and msg_type == "groupchat" and room_jid:
        return str(room_jid)

    if (
        msg_type in ("chat", "normal")
        and room_jid in JOINED_ROOMS
        and getattr(sender, "resource", None)
    ):
        return str(room_jid)

    return None

async def _sender_is_global_rss_manager(bot, sender_jid: str) -> bool:
    """Return True when sender has global RSS management rights."""
    get_role = getattr(bot, "get_user_role", None)
    if not callable(get_role):
        return False
    try:
        return await get_role(str(sender_jid)) <= Role.MODERATOR
    except Exception:
        log.debug("[RSS] Could not resolve global sender role", exc_info=True)
        return False

async def _sender_can_manage_rss_room(bot, sender_jid: str, room: str) -> bool:
    """Return True for global moderators or RSS grant plus room affiliation."""
    if await _sender_is_global_rss_manager(bot, sender_jid):
        return True
    return await user_has_room_plugin_grant(bot, sender_jid, "rss", room)

async def _sender_can_manage_rss_globally(bot, sender_jid: str) -> bool:
    """Return True when sender can manage RSS state across all rooms."""
    return await _sender_is_global_rss_manager(bot, sender_jid)

async def _sender_role(bot, sender_jid: str) -> Role:
    get_role = getattr(bot, "get_user_role", None)
    if not callable(get_role):
        return Role.USER
    try:
        return await get_role(str(sender_jid))
    except Exception:
        log.debug("[RSS] Could not resolve sender role", exc_info=True)
        return Role.USER

def _direct_subscriptions(feed: dict) -> dict[str, dict]:
    users = feed.get("users")
    return users if isinstance(users, dict) else {}

def _trusted_feed_count(feeds: dict, owner: str) -> int:
    key = _normalize_room_jid(owner)
    return sum(
        1 for feed in feeds.values()
        if key in {_normalize_room_jid(jid) for jid in _direct_subscriptions(feed)}
    )

def _compact_subscription_lines(
    feeds: dict,
    section: str | None = None,
    *,
    owner: str | None = None,
) -> list[str]:
    """Return the compact subscription overview, optionally for one section."""
    _ensure_feed_numbers(feeds)
    room_feeds: dict[str, list[tuple[int, str, str]]] = {}
    mod_lines: list[tuple[int, str]] = []
    trusted_lines: list[tuple[int, str]] = []
    own_lines: list[tuple[int, str]] = []
    room_subscription_count = 0
    owner_key = _normalize_direct_user_jid(owner) if owner else None

    for url, feed in feeds.items():
        title = str(feed.get("title") or url)
        status = _feed_status_label(feed)
        paused_rooms = _feed_paused_rooms(feed)
        period = feed.get("period", "?")
        feed_no = _feed_number(feed) or 10**9
        feed_no_text = str(_feed_number(feed) or "?")
        article_count = _feed_article_count(feed)
        article_text = f"article #{article_count}" if article_count else "no articles yet"

        for room in feed.get("rooms", []):
            room_name = str(room)
            room_status = (
                "paused"
                if _normalize_subscription_room(room_name) in paused_rooms
                else status
            )
            room_line = (
                f"  • #{feed_no_text} · {title} | {article_text} | "
                f"{room_status} | {period}s | {url}"
            )
            room_feeds.setdefault(room_name, []).append((feed_no, title, room_line))
            room_subscription_count += 1

        for jid, meta in sorted(_direct_subscriptions(feed).items()):
            role = str((meta or {}).get("role") or "trusted").lower()
            direct_status = (
                "paused" if _direct_subscription_is_paused(meta) else status
            )
            line = (
                f"• #{feed_no_text} · {title} | {article_text} | {direct_status} | "
                f"{period}s | {jid} | {url}"
            )
            if owner_key and _normalize_direct_user_jid(jid) == owner_key:
                own_lines.append((feed_no, line))
            target = (
                mod_lines
                if role in {"owner", "superadmin", "admin", "moderator"}
                else trusted_lines
            )
            target.append((feed_no, line))

    room_lines: list[str] = []
    for room in sorted(room_feeds, key=str.casefold):
        room_lines.append(f"• {room}")
        room_lines.extend(
            line
            for _feed_no, _title, line in sorted(
                room_feeds[room],
                key=lambda item: (item[0], item[1].casefold(), item[2].casefold()),
            )
        )

    mod_lines.sort(key=lambda item: (item[0], item[1].casefold()))
    trusted_lines.sort(key=lambda item: (item[0], item[1].casefold()))
    own_lines.sort(key=lambda item: (item[0], item[1].casefold()))
    mod_text = [line for _feed_no, line in mod_lines]
    trusted_text = [line for _feed_no, line in trusted_lines]
    own_text = [line for _feed_no, line in own_lines]
    sections = {
        "rooms": [
            f"Room feeds ({room_subscription_count}):",
            *(room_lines or ["• none"]),
        ],
        "mods": [
            f"Moderator feeds ({len(mod_text)}):",
            *(mod_text or ["• none"]),
        ],
        "trusted": [
            f"Trusted user feeds ({len(trusted_text)}):",
            *(trusted_text or ["• none"]),
        ],
        "own": [
            f"Own direct feeds ({len(own_text)}):",
            *(own_text or ["• none"]),
        ],
    }
    if section:
        return sections[section]

    return [
        *sections["rooms"],
        "",
        *sections["mods"],
        "",
        *sections["trusted"],
    ]

def _looks_like_room_arg(value) -> bool:
    """Best-effort test for explicit room JID arguments."""
    text = str(value or "").strip()
    return "@" in text and "://" not in text

def _rss_list_usage(bot=None) -> str:
    """Return the usage string for paginated RSS list output."""
    return (
        f"Usage: {_command_prefix(bot)}rss list "
        "[own|rooms|mods|trusted|room_jid] [page|all|last]"
    )

async def burst_recent_entries(
    bot,
    feed,
    room,
    burst_num,
    store=None,
    feed_url="",
    *,
    feed_no: int | str = "",
    article_start: int | None = None,
    article_end: int | None = None,
    through_entry_id: str = "",
):
    """Burst recent entries to a room, optionally ending at a known cursor.

    ``through_entry_id`` is used when an already tracked feed is added to a
    second room.  The replay then starts at the newest entry the worker has
    already processed instead of accidentally including entries published
    after the stored cursor.  ``article_end`` lets that replay reuse the
    persisted article sequence rather than inventing new article numbers.
    """
    title = feed.feed.get("title", "")
    feed_link = feed.feed.get("link", "")
    source_entries = list(feed.entries)
    article_end_value = article_end

    if through_entry_id:
        anchor_index = next(
            (
                index
                for index, entry in enumerate(source_entries)
                if _get_entry_id(entry) == through_entry_id
            ),
            None,
        )
        if anchor_index is not None:
            source_entries = source_entries[anchor_index:]
        else:
            # A missing persisted cursor means the current snapshot cannot
            # distinguish already-processed history from newer unseen items.
            # Replaying it could therefore post an unseen entry early and then
            # post it again during the next normal poll.  Prefer no history
            # burst over a duplicate or incorrectly numbered delivery.
            log.warning(
                "[RSS] Skipping historical burst for %s: persisted cursor %s "
                "is not present in the current feed snapshot",
                feed_url or feed_link,
                through_entry_id,
            )
            return None

    entries = list(reversed(source_entries[:burst_num]))
    last_id = None

    for index, entry in enumerate(entries):
        entry_link = _extract_entry_link(entry)
        entry_id = _get_entry_id(entry)

        entry_title = html_to_text_with_links(
            entry_get(entry, "title", "No title"))
        entry_desc = html_to_text_with_links(
            entry_get(entry, "description", ""))

        # Resolve and normalize link
        entry_link = _resolve_relative_url(feed_link, entry_link)
        entry_link = _normalize_url(entry_link)

        if article_start is not None:
            article_no: int | str = article_start + index
        elif article_end_value is not None:
            article_no = article_end_value - (len(entries) - 1 - index)
            if article_no <= 0:
                article_no = ""
        else:
            article_no = ""

        context = _build_rss_template_context(
            feed_title=title,
            entry_title=entry_title,
            entry_desc=entry_desc,
            entry_link=entry_link,
            feed_url=feed_url or feed_link,
            feed_link=feed_link,
            feed_no=feed_no,
            article_no=article_no,
            entry_id=entry_id,
            entry_date=_entry_date(entry),
        )
        template = (
            await get_effective_template(store, room, feed_url or feed_link)
            if store else None
        )
        msg_text = _build_rss_message_from_context(context, template)

        bot.reply(
            {
                "from": type("F", (), {"bare": room})(),
                "type": "groupchat",
            },
            msg_text,
            mention=False,
            thread=True,
            rate_limit=False,
            ephemeral=False,
        )

        # Track newest entry ID from the burst.
        last_id = entry_id

    return last_id

def _looks_like_feed_arg(value) -> bool:
    """Best-effort test for feed URL arguments."""
    return "://" in str(value or "")

def _rss_health_lines(feeds: dict, *, broken_only: bool = False, now: int | None = None) -> list[str]:
    """Return concise RSS health lines for all feeds."""
    _ensure_feed_numbers(feeds)
    now = _now() if now is None else int(now)
    rows = []
    for url, feed in sorted(
        feeds.items(),
        key=lambda item: (
            _feed_number(item[1]) if isinstance(item[1], dict) else 10**9,
            str(item[0]).casefold(),
        ),
    ):
        if not isinstance(feed, dict):
            continue
        error_count = int(feed.get("error_count", 0) or 0)
        status = _feed_status_label(feed, now=now)
        broken = error_count >= RSS_BROKEN_ERROR_THRESHOLD or status in {
            "backoff",
            "paused",
            "paused for all destinations",
        }
        if broken_only and not broken:
            continue
        active_rooms = _feed_active_rooms(feed)
        total_rooms = len(feed.get("rooms", []) if isinstance(feed.get("rooms"), list) else [])
        direct_users = _direct_subscriptions(feed)
        active_direct_users = _feed_active_direct_users(feed)
        paused_direct_users = sum(
            1
            for meta in direct_users.values()
            if _direct_subscription_is_paused(meta)
        )
        paused_rooms = sorted(_feed_paused_rooms(feed))
        last_error = str(feed.get("last_error") or "none")
        if len(last_error) > 120:
            last_error = last_error[:117] + "..."
        status_display = {
            "ok": "✅ ok",
            "degraded": "🟡 degraded",
            "backoff": "🟡 backoff",
            "paused": "⏸️ paused",
            "paused for all destinations": "⏸️ paused for all destinations",
        }.get(status, status)
        article_count = _feed_article_count(feed)
        article_text = f"#{article_count}" if article_count else "not posted yet"
        rows.append(
            " • "
            f"#{_feed_number(feed) or '?'} · {status_display}: "
            f"{feed.get('title') or url} — {url}\n"
            f"   rooms: {len(active_rooms)}/{total_rooms} active"
            f"{f' · paused: {len(paused_rooms)}' if paused_rooms else ''}; "
            f"direct users: {len(active_direct_users)}/{len(direct_users)} active"
            f"{f' · paused: {paused_direct_users}' if paused_direct_users else ''}; "
            f"article: {article_text}; "
            f"errors: {error_count}; "
            f"last success: {_format_rss_timestamp(feed.get('last_success'))}; "
            f"last post: {_format_rss_timestamp(feed.get('last_posted'))}; "
            f"last error: {last_error}"
        )
    return rows

def _rss_health_summary(feeds: dict) -> str:
    total = sum(1 for feed in feeds.values() if isinstance(feed, dict))
    paused = sum(
        1
        for feed in feeds.values()
        if isinstance(feed, dict)
        and _feed_status_label(feed) in {"paused", "paused for all destinations"}
    )
    backoff = sum(
        1 for feed in feeds.values()
        if isinstance(feed, dict) and int(feed.get("next_retry") or 0) > _now()
    )
    degraded = sum(
        1 for feed in feeds.values()
        if isinstance(feed, dict) and int(feed.get("error_count", 0) or 0) > 0
    )
    return f"RSS health: {total} feeds · {paused} paused · {backoff} in backoff · {degraded} with errors"

def _rss_normalize_room_list(feed: dict) -> list[str]:
    rooms = feed.setdefault("rooms", [])
    if not isinstance(rooms, list):
        rooms = []
        feed["rooms"] = rooms
    deduped = []
    seen = set()
    for room in rooms:
        key = _normalize_subscription_room(room)
        if not key or key in seen:
            continue
        deduped.append(str(room))
        seen.add(key)
    if deduped != rooms:
        feed["rooms"] = deduped
    return deduped
