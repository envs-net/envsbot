"""RSS administration and subscription commands."""

from __future__ import annotations

from bot.room_state import JOINED_ROOMS
from core_plugins._core import paginate_items
from core_plugins.users import user_has_room_plugin_grant
from utils.audit import audit_event
from utils.command import Role, command
from utils.command_metadata import help_example, help_subcommand
from utils.config import config

from .config import (
    DEFAULT_POLL_INTERVAL,
    RSS_BROKEN_ERROR_THRESHOLD,
    RSS_TRUSTED_MAX_FEEDS,
)
from .fetch import (
    _extract_entry_link,
    _format_feed_fetch_error,
    _get_entry_id,
    _get_latest_entry_id,
    _log_feed_fetch_error,
    _normalize_url,
    _resolve_relative_url,
    entry_get,
    fetch_feed,
    html_to_text_with_links,
)
from .formatting import (
    _SAMPLE_TEMPLATE_CONTEXT,
    DEFAULT_RSS_TEMPLATE,
    _build_rss_message_from_context,
    _build_rss_template_context,
    _entry_date,
    _filter_feeds_for_room,
    _format_feed_list,
    _normalize_direct_user_jid,
    _normalize_rss_template_input,
    _rss_list_page,
    _rss_template_usage,
    _rss_template_variables_text,
    _validate_rss_template,
)
from .store import (
    _apply_retry_state,
    _feed_active_rooms,
    _feed_is_globally_paused,
    _feed_paused_rooms,
    _feed_status_label,
    _format_rss_timestamp,
    _normalize_room_jid,
    _normalize_subscription_room,
    _now,
    get_default_template,
    get_effective_template,
    get_feed_template,
    get_feeds,
    get_room_template,
    log,
    save_feeds,
    set_default_template,
    set_feed_template,
    set_room_template,
    unset_default_template,
    unset_feed_template,
    unset_feed_templates_for_feed,
    unset_feed_templates_for_room,
    unset_room_template,
)
from .tasks import (
    _cancel_feed_task,
    ensure_task,
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
    room_feeds: dict[str, list[tuple[str, str]]] = {}
    mod_lines: list[str] = []
    trusted_lines: list[str] = []
    own_lines: list[str] = []
    room_subscription_count = 0
    owner_key = _normalize_direct_user_jid(owner) if owner else None

    for url, feed in feeds.items():
        title = str(feed.get("title") or url)
        status = _feed_status_label(feed)
        period = feed.get("period", "?")
        room_line = f"  • {title} | {status} | {period}s | {url}"

        for room in feed.get("rooms", []):
            room_name = str(room)
            room_feeds.setdefault(room_name, []).append((title, room_line))
            room_subscription_count += 1

        for jid, meta in sorted(_direct_subscriptions(feed).items()):
            role = str((meta or {}).get("role") or "trusted").lower()
            line = f"• {title} | {status} | {period}s | {jid} | {url}"
            if owner_key and _normalize_direct_user_jid(jid) == owner_key:
                own_lines.append(line)
            target = (
                mod_lines
                if role in {"owner", "superadmin", "admin", "moderator"}
                else trusted_lines
            )
            target.append(line)

    room_lines: list[str] = []
    for room in sorted(room_feeds, key=str.casefold):
        room_lines.append(f"• {room}")
        room_lines.extend(
            line
            for _title, line in sorted(
                room_feeds[room],
                key=lambda item: (item[0].casefold(), item[1].casefold()),
            )
        )

    mod_lines.sort(key=str.casefold)
    trusted_lines.sort(key=str.casefold)
    own_lines.sort(key=str.casefold)
    sections = {
        "rooms": [
            f"Room feeds ({room_subscription_count}):",
            *(room_lines or ["• none"]),
        ],
        "mods": [
            f"Moderator feeds ({len(mod_lines)}):",
            *(mod_lines or ["• none"]),
        ],
        "trusted": [
            f"Trusted user feeds ({len(trusted_lines)}):",
            *(trusted_lines or ["• none"]),
        ],
        "own": [
            f"Own direct feeds ({len(own_lines)}):",
            *(own_lines or ["• none"]),
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
async def burst_recent_entries(bot, feed, room, burst_num, store=None, feed_url=""):
    """
    Burst the last N entries of the given feed to the room.
    """
    title = feed.feed.get("title", "")
    feed_link = feed.feed.get("link", "")
    entries = feed.entries[:burst_num]
    entries = list(reversed(entries))
    last_id = None

    for entry in entries:
        entry_link = _extract_entry_link(entry)
        entry_id = _get_entry_id(entry)

        entry_title = html_to_text_with_links(
            entry_get(entry, "title", "No title"))
        entry_desc = html_to_text_with_links(
            entry_get(entry, "description", ""))

        # Resolve and normalize link
        entry_link = _resolve_relative_url(feed_link, entry_link)
        entry_link = _normalize_url(entry_link)

        context = _build_rss_template_context(
            feed_title=title,
            entry_title=entry_title,
            entry_desc=entry_desc,
            entry_link=entry_link,
            feed_url=feed_url or feed_link,
            feed_link=feed_link,
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
def _split_template_scope_args(
    msg,
    is_room: bool,
    args: list[str],
    sender_jid: str | None = None,
):
    """Return ``(destination, feed_url, rest)`` for template subcommands.

    Scope syntax is intentionally compact:

    * ``[room_jid]`` targets a room template.
    * ``[room_jid] <feed_url>`` targets a feed template in that room.
    * In a public room/MUC PM, ``<feed_url>`` is enough for a feed template.
    * In a normal direct chat, an omitted room targets the sender's direct
      subscriptions. The optional ``direct`` marker is accepted before or
      after the feed URL for clarity and is never stored as template text.
    """
    rest = list(args)
    direct_requested = False
    if rest and str(rest[0]).strip().lower() == "direct":
        direct_requested = True
        rest.pop(0)

    explicit_room = None
    if rest and _looks_like_room_arg(rest[0]):
        explicit_room = rest.pop(0)

    implied_room = _room_for_feed_command(msg, is_room)
    destination = _room_for_feed_command(
        msg,
        is_room,
        explicit_room=explicit_room,
    )

    feed_url = None
    if rest and _looks_like_feed_arg(rest[0]):
        feed_url = _normalize_url(rest.pop(0))

    if rest and str(rest[0]).strip().lower() == "direct":
        direct_requested = True
        rest.pop(0)

    personal_direct = (
        not is_room
        and explicit_room is None
        and implied_room is None
        and bool(sender_jid)
    )
    if personal_direct:
        destination = _normalize_room_jid(str(sender_jid))
    elif direct_requested:
        return None, feed_url, rest

    return destination, feed_url, rest


def _is_personal_template_scope(
    msg,
    is_room: bool,
    sender_jid: str,
    destination: str | None,
) -> bool:
    """Return True for the sender's direct-subscription template scope."""
    if not destination or is_room:
        return False
    if _room_for_feed_command(msg, is_room) is not None:
        return False
    return _normalize_room_jid(destination) == _normalize_room_jid(sender_jid)


async def _template_feed_for_room(
    store,
    room: str,
    feed_url: str,
    *,
    direct: bool = False,
):
    """Return feed metadata when subscribed at the requested destination."""
    feeds = await get_feeds(store)
    feed = feeds.get(_normalize_url(feed_url))
    if not isinstance(feed, dict):
        return None
    target = _normalize_room_jid(room)
    if direct:
        users = _direct_subscriptions(feed)
        if target not in {
            _normalize_room_jid(item)
            for item in users
        }:
            return None
        return feed

    rooms = feed.get("rooms")
    if not isinstance(rooms, list):
        return None
    if not any(_normalize_room_jid(item) == target for item in rooms):
        return None
    return feed
def _sample_template_context_for_feed(feed, feed_url: str) -> dict[str, str]:
    """Return sample template context enriched with feed metadata."""
    context = dict(_SAMPLE_TEMPLATE_CONTEXT)
    if isinstance(feed, dict):
        context["feed_title"] = str(feed.get("title") or context["feed_title"])
        context["feed_link"] = str(feed.get("link") or context["feed_link"])
    context["feed_url"] = str(feed_url or context["feed_url"])
    return context
def _sample_rss_template_preview(
    template: str,
    feed=None,
    feed_url: str = "",
) -> str:
    """Render a template using example RSS data."""
    return _build_rss_message_from_context(
        _sample_template_context_for_feed(feed, feed_url),
        template,
    )
def _join_template_args(parts: list[str]) -> str:
    """Build a template string from command arguments."""
    return _normalize_rss_template_input(" ".join(str(part) for part in parts))
async def _sender_can_manage_template(
    bot,
    sender_jid: str,
    room: str | None,
    *,
    direct: bool = False,
) -> bool:
    """Return True when sender may manage an RSS destination template."""
    if not room:
        return False
    if direct:
        return await _sender_role(bot, sender_jid) <= Role.TRUSTED
    return await _sender_can_manage_rss_room(bot, sender_jid, room)
async def _rss_template_show(
    bot,
    msg,
    store,
    *,
    global_default: bool,
    room: str | None,
    feed_url: str | None,
    direct_scope: bool,
    scope: str,
    rest: list[str],
) -> None:
    """Show the effective RSS template for one resolved scope."""
    if rest:
        bot.reply(msg, _rss_template_usage(bot))
        return
    if global_default:
        template = await get_default_template(store)
        source = "custom" if template else "built-in"
        template = template or DEFAULT_RSS_TEMPLATE
    else:
        if room is None:
            bot.reply(msg, _rss_template_usage(bot))
            return
        room_key = room
    if not global_default and feed_url:
        feed_template = await get_feed_template(store, room_key, feed_url)
        room_template = await get_room_template(store, room_key)
        default_template = await get_default_template(store)
        if feed_template:
            source = "feed custom"
            template = feed_template
        elif room_template:
            source = "personal custom" if direct_scope else "room custom"
            template = room_template
        elif default_template:
            source = "global default"
            template = default_template
        else:
            source = "built-in default"
            template = DEFAULT_RSS_TEMPLATE
    elif not global_default:
        template = await get_room_template(store, room_key)
        if template:
            source = "personal custom" if direct_scope else "custom"
        else:
            template = await get_default_template(store)
            source = "global default" if template else "built-in default"
            template = template or DEFAULT_RSS_TEMPLATE
    bot.reply(
        msg,
        f"🧩 RSS template for {scope} ({source}):\n"
        f"{template}\n\n{_rss_template_variables_text()}",
    )


async def _rss_template_unset(
    bot,
    sender_jid: str,
    msg,
    store,
    *,
    global_default: bool,
    room: str | None,
    feed_url: str | None,
    direct_scope: bool,
    scope: str,
    rest: list[str],
) -> None:
    """Remove a custom RSS template from one resolved scope."""
    if rest:
        bot.reply(msg, _rss_template_usage(bot))
        return
    if global_default:
        removed = await unset_default_template(store)
        event_type = "rss_default_template_unset"
        success = "✅ Global default RSS template reset to the built-in default."
        unchanged = "ℹ️ The built-in default RSS template is already active."
    else:
        if room is None:
            bot.reply(msg, _rss_template_usage(bot))
            return
        room_key = room
    if not global_default and feed_url:
        removed = await unset_feed_template(store, room_key, feed_url)
        event_type = "rss_feed_template_unset"
        success = f"✅ RSS feed template reset for {scope}."
        fallback_name = "personal/default" if direct_scope else "room/default"
        unchanged = f"ℹ️ {scope} already uses the {fallback_name} RSS template."
    elif not global_default:
        removed = await unset_room_template(store, room_key)
        event_type = "rss_template_unset"
        success = (
            f"✅ Personal RSS template reset to default for {room}."
            if direct_scope
            else f"✅ RSS template reset to default for {room}."
        )
        unchanged = f"ℹ️ {room} already uses the default RSS template."
    if not removed:
        bot.reply(msg, unchanged)
        return
    bot.reply(msg, success)
    await audit_event(bot, event_type, actor=sender_jid, target=scope)


async def _rss_template_test(
    bot,
    msg,
    store,
    *,
    global_default: bool,
    room: str | None,
    feed_url: str | None,
    scope: str,
    feed,
    rest: list[str],
) -> None:
    """Render an RSS template preview without mutating configuration."""
    template = _join_template_args(rest) if rest else (
        await get_default_template(store)
        if global_default
        else await get_effective_template(store, room or "", feed_url or "")
    ) or DEFAULT_RSS_TEMPLATE
    error = _validate_rss_template(template)
    if error:
        bot.reply(msg, f"🔴 {error}\n{_rss_template_variables_text()}")
        return
    bot.reply(
        msg,
        f"🧪 RSS template preview for {scope}:\n"
        f"{_sample_rss_template_preview(template, feed, feed_url or '')}",
    )


async def _rss_template_set(
    bot,
    sender_jid: str,
    msg,
    store,
    *,
    global_default: bool,
    room: str | None,
    feed_url: str | None,
    direct_scope: bool,
    scope: str,
    feed,
    rest: list[str],
) -> None:
    """Validate and persist one custom RSS template."""
    template = _join_template_args(rest)
    error = _validate_rss_template(template)
    if error:
        bot.reply(msg, f"🔴 {error}\n{_rss_template_variables_text()}")
        return
    if global_default:
        await set_default_template(store, template)
        event_type = "rss_default_template_set"
        success = "✅ Global default RSS template set for all destinations."
    else:
        if room is None:
            bot.reply(msg, _rss_template_usage(bot))
            return
        room_key = room
    if not global_default and feed_url:
        await set_feed_template(store, room_key, feed_url, template)
        event_type = "rss_feed_template_set"
        success = f"✅ RSS feed template set for {scope}."
    elif not global_default:
        await set_room_template(store, room_key, template)
        event_type = "rss_template_set"
        success = (
            f"✅ Personal RSS template set for {room}."
            if direct_scope
            else f"✅ RSS template set for {room}."
        )
    bot.reply(
        msg,
        f"{success}\nPreview:\n"
        f"{_sample_rss_template_preview(template, feed, feed_url or '')}",
    )
    await audit_event(
        bot,
        event_type,
        actor=sender_jid,
        target=scope,
        details={"length": len(template)},
    )


async def _rss_template_command(bot, sender_jid, msg, is_room, args, store):
    """Handle global-, room-, and feed-scoped RSS template commands."""
    if not args:
        action = "show"
        rest = []
    else:
        first = str(args[0]).strip().lower()
        if first in {"show", "get"}:
            action = "show"
            rest = list(args[1:])
        elif first in {"set", "unset", "reset", "test"}:
            action = "unset" if first == "reset" else first
            rest = list(args[1:])
        else:
            action = "show"
            rest = list(args)

    room = None
    direct_scope = False
    global_default = bool(
        rest and str(rest[0]).strip().lower() in {"default", "global"}
    )
    if global_default:
        rest.pop(0)
        feed_url = None
        if not await _sender_can_manage_rss_globally(bot, sender_jid):
            bot.reply(
                msg,
                "🔴 You need a global moderator role to manage the default "
                "RSS template.",
            )
            return
    else:
        room, feed_url, rest = _split_template_scope_args(
            msg,
            is_room,
            rest,
            sender_jid=sender_jid,
        )
        if not room:
            bot.reply(msg, _rss_template_usage(bot))
            return

        direct_scope = _is_personal_template_scope(
            msg,
            is_room,
            sender_jid,
            room,
        )
        if not await _sender_can_manage_template(
            bot,
            sender_jid,
            room,
            direct=direct_scope,
        ):
            if direct_scope:
                bot.reply(
                    msg,
                    "🔴 Direct RSS templates require trusted role or higher.",
                )
            else:
                bot.reply(
                    msg,
                    "🔴 You need a global moderator role, or an RSS plugin "
                    f"grant and owner/admin affiliation in {room}.",
                )
            return

    room_key = room or ""
    feed = None
    if feed_url:
        feed = await _template_feed_for_room(
            store,
            room_key,
            feed_url,
            direct=direct_scope,
        )
        if feed is None:
            destination_label = (
                f"direct user {room}" if direct_scope else room
            )
            bot.reply(
                msg,
                f"🔴 Feed is not configured for {destination_label}: "
                f"{feed_url}",
            )
            return

    scope = str(
        "global default"
        if global_default
        else (
            f"direct user {room} / {feed_url}"
            if direct_scope and feed_url
            else f"direct user {room}"
            if direct_scope
            else f"{room} / {feed_url}"
            if feed_url
            else room
        )
    )

    if action == "show":
        await _rss_template_show(
            bot, msg, store,
            global_default=global_default, room=room, feed_url=feed_url,
            direct_scope=direct_scope, scope=scope, rest=rest,
        )
        return
    if action == "unset":
        await _rss_template_unset(
            bot, sender_jid, msg, store,
            global_default=global_default, room=room, feed_url=feed_url,
            direct_scope=direct_scope, scope=scope, rest=rest,
        )
        return
    if action == "test":
        await _rss_template_test(
            bot, msg, store,
            global_default=global_default, room=room, feed_url=feed_url,
            scope=scope, feed=feed, rest=rest,
        )
        return
    if action == "set":
        await _rss_template_set(
            bot, sender_jid, msg, store,
            global_default=global_default, room=room, feed_url=feed_url,
            direct_scope=direct_scope, scope=scope, feed=feed, rest=rest,
        )
        return
    bot.reply(msg, _rss_template_usage(bot))


def _rss_health_lines(feeds: dict, *, broken_only: bool = False, now: int | None = None) -> list[str]:
    """Return concise RSS health lines for all feeds."""
    now = _now() if now is None else int(now)
    rows = []
    for url, feed in sorted(feeds.items()):
        if not isinstance(feed, dict):
            continue
        error_count = int(feed.get("error_count", 0) or 0)
        status = _feed_status_label(feed, now=now)
        broken = error_count >= RSS_BROKEN_ERROR_THRESHOLD or status in {"backoff", "paused", "paused for all rooms"}
        if broken_only and not broken:
            continue
        active_rooms = _feed_active_rooms(feed)
        total_rooms = len(feed.get("rooms", []) if isinstance(feed.get("rooms"), list) else [])
        direct_users = len(_direct_subscriptions(feed))
        paused_rooms = sorted(_feed_paused_rooms(feed))
        last_error = str(feed.get("last_error") or "none")
        if len(last_error) > 120:
            last_error = last_error[:117] + "..."
        status_display = {
            "ok": "✅ ok",
            "degraded": "🟡 degraded",
            "backoff": "🟡 backoff",
            "paused": "⏸️ paused",
            "paused for all rooms": "⏸️ paused for all rooms",
        }.get(status, status)
        rows.append(
            " • "
            f"{status_display}: {feed.get('title') or url} — {url}\n"
            f"   rooms: {len(active_rooms)}/{total_rooms} active"
            f"{f' · paused: {len(paused_rooms)}' if paused_rooms else ''}; "
            f"direct users: {direct_users}; errors: {error_count}; "
            f"last success: {_format_rss_timestamp(feed.get('last_success'))}; "
            f"last post: {_format_rss_timestamp(feed.get('last_posted'))}; "
            f"last error: {last_error}"
        )
    return rows
def _rss_health_summary(feeds: dict) -> str:
    total = sum(1 for feed in feeds.values() if isinstance(feed, dict))
    paused = sum(1 for feed in feeds.values() if isinstance(feed, dict) and _feed_is_globally_paused(feed))
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
async def _rss_set_pause_state(bot, msg, store, url, room, target, paused: bool) -> None:
    url = _normalize_url(url)
    feeds = await get_feeds(store)
    feed = feeds.get(url)
    if not isinstance(feed, dict):
        bot.reply(msg, "Feed not found.")
        return

    scope = str(target or "").strip()
    changed = False
    if scope.lower() == "all":
        feed["paused"] = paused
        changed = True
        label = "globally"
    else:
        target_room = _normalize_room_jid(scope) if scope else room
        if not target_room:
            bot.reply(msg, "🔴 RSS pause/resume needs a room context, room JID, or 'all'.")
            return
        rooms = _rss_normalize_room_list(feed)
        room_key = _normalize_subscription_room(target_room)
        if not any(_normalize_subscription_room(item) == room_key for item in rooms):
            bot.reply(msg, f"ℹ️ Room {target_room} is not subscribed to this feed.")
            return
        paused_rooms = sorted(_feed_paused_rooms(feed))
        if paused and room_key not in paused_rooms:
            paused_rooms.append(room_key)
            changed = True
        if not paused and room_key in paused_rooms:
            paused_rooms.remove(room_key)
            changed = True
        feed["paused_rooms"] = paused_rooms
        label = f"for {target_room}"

    if changed:
        await save_feeds(store, feeds)
        await _cancel_feed_task(bot, url)
        if not paused or not feed.get("paused"):
            await ensure_task(bot, store, url, feed.get("period", DEFAULT_POLL_INTERVAL))

    action = "Paused" if paused else "Resumed"
    bot.reply(msg, f"✅ {action} RSS feed {label}: {url}" if changed else f"ℹ️ RSS feed already {'paused' if paused else 'active'} {label}: {url}")
async def _rss_handle_add(bot, sender_jid, args, msg, is_room, store, room):
    if len(args) not in (2, 3):
        bot.reply(
            msg,
            f"Usage: {_command_prefix(bot)}rss add <feedurl> [room_jid]",
        )
        return

    explicit_room = args[2] if len(args) == 3 else None
    if (
        explicit_room
        and room is None
        and _message_type(msg) in ("chat", "normal")
    ):
        explicit_user = _normalize_direct_user_jid(explicit_room)
        sender_user = _normalize_direct_user_jid(sender_jid)
        if (
            not _looks_like_room_arg(explicit_room)
            or (
                explicit_user is not None
                and explicit_user == sender_user
            )
        ):
            # A normal 1:1 chat already identifies the subscriber. Ignore
            # redundant own-JID arguments and common placeholder text,
            # while preserving the documented explicit-room form.
            explicit_room = None

    room = _room_for_feed_command(
        msg,
        is_room,
        explicit_room=explicit_room,
    )
    if not room:
        role = await _sender_role(bot, sender_jid)
        if role > Role.TRUSTED:
            bot.reply(msg, "🔴 Direct RSS subscriptions require trusted role or higher.")
            return
        feeds = await get_feeds(store)
        owner = _normalize_room_jid(sender_jid)
        if role == Role.TRUSTED and _trusted_feed_count(feeds, owner) >= RSS_TRUSTED_MAX_FEEDS:
            bot.reply(msg, f"🔴 Trusted RSS feed limit reached ({RSS_TRUSTED_MAX_FEEDS}).")
            return
        await _add_direct_feed(bot, msg, args[1], store, owner, role)
        await audit_event(bot, "rss_direct_feed_add_requested", actor=sender_jid, target=owner, details={"url": _normalize_url(args[1])})
        return
    if not await _sender_can_manage_rss_room(bot, sender_jid, room):
        bot.reply(
            msg,
            "🔴 You need a global moderator role, or an RSS plugin grant "
            f"and owner/admin affiliation in {room}.",
        )
        return

    await _add_feed(bot, msg, args[1], store, room)
    await audit_event(
        bot,
        "rss_feed_add_requested",
        actor=sender_jid,
        target=room,
        details={"url": _normalize_url(args[1])},
    )
    return

async def _rss_handle_delete(bot, sender_jid, args, msg, is_room, store, room):
    if len(args) == 3 and str(args[1]).strip().lower() == "all":
        if room or _message_type(msg) not in ("chat", "normal"):
            bot.reply(
                msg,
                "🔴 Bulk removal of a user's direct RSS feeds is only "
                "available in a normal 1:1 chat.",
            )
            return

        role = await _sender_role(bot, sender_jid)
        if role > Role.ADMIN:
            bot.reply(
                msg,
                "🔴 Only owner, superadmin, or admin can remove all "
                "direct RSS feeds for a user.",
            )
            return

        direct_target = _normalize_direct_user_jid(args[2])
        if not direct_target:
            bot.reply(msg, f"🔴 Invalid direct subscriber JID: {args[2]}")
            return

        removed = await _delete_all_direct_feeds_for_user(
            bot,
            msg,
            store,
            direct_target,
        )
        if removed:
            await audit_event(
                bot,
                "rss_direct_feeds_bulk_removed",
                actor=sender_jid,
                target=direct_target,
                details={"removed": removed},
            )
        return

    if len(args) not in (2, 3):
        bot.reply(
            msg,
            f"Usage: {_command_prefix(bot)}rss delete "
            "<feedurl> [room|jid|all] | "
            f"{_command_prefix(bot)}rss delete all <user_jid>",
        )
        return

    delete_target = args[2] if len(args) == 3 else None
    target_room = None
    if delete_target and str(delete_target).strip().lower() != "all":
        target_room = _normalize_room_jid(delete_target)
    elif room:
        target_room = room

    direct_target = None
    if delete_target and str(delete_target).strip().lower() != "all":
        current_feed = (await get_feeds(store)).get(_normalize_url(args[1]), {})
        candidate = _normalize_room_jid(delete_target)
        if candidate in _direct_subscriptions(current_feed):
            direct_target = candidate

    if direct_target:
        role = await _sender_role(bot, sender_jid)
        if direct_target != _normalize_room_jid(sender_jid) and role > Role.ADMIN:
            bot.reply(msg, "🔴 Only owner, superadmin, or admin can remove another user's direct RSS feed.")
            return
        await _delete_direct_feed_target(bot, msg, args[1], store, direct_target)
        return
    if delete_target and str(delete_target).strip().lower() == "all":
        if not await _sender_can_manage_rss_globally(bot, sender_jid):
            bot.reply(msg, "🔴 Only global moderators can delete RSS feeds everywhere.")
            return
    elif target_room:
        if not await _sender_can_manage_rss_room(bot, sender_jid, target_room):
            bot.reply(
                msg,
                "🔴 You need a global moderator role, or an RSS plugin "
                f"grant and owner/admin affiliation in {target_room}.",
            )
            return
    elif not await _sender_can_manage_rss_globally(bot, sender_jid):
        role = await _sender_role(bot, sender_jid)
        if role > Role.TRUSTED:
            bot.reply(msg, "🔴 Direct RSS subscriptions require trusted role or higher.")
            return
        await _delete_direct_feed(bot, msg, args[1], store, sender_jid, allow_other=False)
        return

    if not target_room and not delete_target and not room and msg.get("type") in ("chat", "normal"):
        role = await _sender_role(bot, sender_jid)
        if role <= Role.ADMIN:
            await _delete_direct_feed(bot, msg, args[1], store, sender_jid, allow_other=True)
            return

    await _del_feed(bot, msg, args[1], store, room, delete_target)
    await audit_event(
        bot,
        "rss_feed_delete_requested",
        actor=sender_jid,
        target=target_room or delete_target or room or "rss",
        details={"url": _normalize_url(args[1]), "target": delete_target},
    )
    return

async def _rss_handle_retry(bot, sender_jid, args, msg, is_room, store, room):
    sub = str(args[0]).lower()
    if len(args) not in (2, 3):
        bot.reply(
            msg,
            f"Usage: {_command_prefix(bot)}rss {sub} <feedurl>|all [room_jid]",
        )
        return

    retry_target = str(args[1]).strip()
    if retry_target.lower() == "all":
        if len(args) != 2:
            bot.reply(
                msg,
                f"Usage: {_command_prefix(bot)}rss {sub} <feedurl>|all [room_jid]",
            )
            return
        if not await _sender_can_manage_rss_globally(bot, sender_jid):
            bot.reply(msg, "🔴 Only global moderators can reset all RSS retries.")
            return
        await _reset_all_feed_retries(bot, msg, store)
        await audit_event(
            bot,
            "rss_retry_reset",
            actor=sender_jid,
            target="all",
        )
        return

    target_room = _room_for_feed_command(
        msg,
        is_room,
        explicit_room=args[2] if len(args) == 3 else None,
    )
    if target_room:
        if not await _sender_can_manage_rss_room(bot, sender_jid, target_room):
            bot.reply(
                msg,
                "🔴 You need a global moderator role, or an RSS plugin "
                f"grant and owner/admin affiliation in {target_room}.",
            )
            return
    elif not await _sender_can_manage_rss_globally(bot, sender_jid):
        bot.reply(
            msg,
            f"🔴 RSS {sub} needs an explicit room JID unless you are a "
            "global moderator.",
        )
        return

    await _reset_feed_retry(bot, msg, retry_target, store)
    await audit_event(
        bot,
        "rss_retry_reset",
        actor=sender_jid,
        target=target_room or "rss",
        details={"url": _normalize_url(retry_target)},
    )
    return

async def _rss_handle_pause(bot, sender_jid, args, msg, is_room, store, room):
    sub = str(args[0]).lower()
    if len(args) not in (2, 3):
        bot.reply(
            msg,
            f"Usage: {_command_prefix(bot)}rss {sub} <feedurl> [room_jid|all]",
        )
        return
    target = args[2] if len(args) == 3 else None
    if target and str(target).strip().lower() == "all":
        if not await _sender_can_manage_rss_globally(bot, sender_jid):
            bot.reply(msg, "🔴 Only global moderators can pause/resume RSS feeds globally.")
            return
    else:
        target_room = _room_for_feed_command(msg, is_room, explicit_room=target)
        if not target_room:
            bot.reply(msg, "🔴 RSS pause/resume needs a room context or explicit room JID.")
            return
        if not await _sender_can_manage_rss_room(bot, sender_jid, target_room):
            bot.reply(
                msg,
                "🔴 You need a global moderator role, or an RSS plugin "
                f"grant and owner/admin affiliation in {target_room}.",
            )
            return
    await _rss_set_pause_state(
        bot,
        msg,
        store,
        args[1],
        room,
        target,
        paused=(sub == "pause"),
    )
    await audit_event(
        bot,
        f"rss_feed_{sub}",
        actor=sender_jid,
        target=target or room or "rss",
        details={"url": _normalize_url(args[1])},
    )
    return

async def _rss_handle_health(bot, sender_jid, args, msg, is_room, store, room):
    sub = str(args[0]).lower()
    feeds = await get_feeds(store)
    if not feeds:
        bot.reply(msg, "No feeds configured.")
        return
    list_args = args
    target_room = room
    explicit_room = False
    if len(args) >= 2 and _looks_like_room_arg(args[1]):
        target_room = _normalize_room_jid(args[1])
        list_args = [args[0], *args[2:]]
        explicit_room = True
    is_global_manager = await _sender_can_manage_rss_globally(bot, sender_jid)
    if explicit_room or not is_global_manager:
        if not target_room:
            bot.reply(msg, "🔴 RSS health from private chat needs an explicit room JID unless you are a global moderator.")
            return
        if not await _sender_can_manage_rss_room(bot, sender_jid, target_room):
            bot.reply(
                msg,
                "🔴 You need a global moderator role, or an RSS plugin "
                f"grant and owner/admin affiliation in {target_room}.",
            )
            return
        feeds = _filter_feeds_for_room(feeds, target_room)
    lines = [_rss_health_summary(feeds)]
    detail_lines = _rss_health_lines(feeds, broken_only=(sub == "broken"))
    if not detail_lines:
        lines.append("✅ No broken RSS feeds." if sub == "broken" else "No matching RSS feeds.")
    else:
        page_size = config.get("rss_list_page_size", 10) or 10
        parsed = _rss_list_page(list_args, len(detail_lines), int(page_size))
        if parsed is None:
            bot.reply(msg, f"Usage: {_command_prefix(bot)}rss {sub} [room_jid] [page|all|last]")
            return
        page, show_all, page_size = parsed
        if show_all:
            page_items = detail_lines
            lines[0] += " - all"
        else:
            page_items, page, total_pages, _total = paginate_items(detail_lines, page, int(page_size))
            lines[0] += f" - Page {page}/{total_pages}"
        lines.extend(page_items)
        if not show_all and page < total_pages:
            lines.append("")
            lines.append(f"Use {_command_prefix(bot)}rss {sub} {page + 1} for the next page.")
    bot.reply(msg, lines)
    return

async def _rss_handle_list(bot, sender_jid, args, msg, is_room, store, room):
    feeds = await get_feeds(store)

    if not feeds:
        bot.reply(msg, "No feeds configured.")
        return

    list_args = args
    target_room = room
    explicit_room = False
    compact_section = None
    if len(args) >= 2 and str(args[1]).lower() in {
        "own",
        "rooms",
        "mods",
        "trusted",
    }:
        compact_section = str(args[1]).lower()
        list_args = [args[0], *args[2:]]
    elif len(args) >= 2 and _looks_like_room_arg(args[1]):
        target_room = _normalize_room_jid(args[1])
        list_args = [args[0], *args[2:]]
        explicit_room = True

    is_global_manager = await _sender_can_manage_rss_globally(
        bot, sender_jid
    )
    if compact_section == "own" and (
        room is not None or _message_type(msg) not in ("chat", "normal")
    ):
        bot.reply(
            msg,
            "🔴 Own direct RSS subscriptions can only be listed in a "
            "normal 1:1 chat.",
        )
        return
    if not explicit_room and _message_type(msg) in ("chat", "normal"):
        if (
            compact_section
            and compact_section != "own"
            and len(list_args) != 1
        ):
            bot.reply(msg, _rss_list_usage(bot))
            return
        role = await _sender_role(bot, sender_jid)
        if compact_section == "own":
            if role > Role.TRUSTED:
                bot.reply(
                    msg,
                    "🔴 Direct RSS subscriptions require trusted role "
                    "or higher.",
                )
                return
            owner = _normalize_room_jid(sender_jid)
            own_lines = _compact_subscription_lines(
                feeds,
                "own",
                owner=owner,
            )[1:]
            if own_lines == ["• none"]:
                bot.reply(msg, "No direct RSS feeds configured for you.")
                return
            page_size = int(config.get("rss_list_page_size", 10) or 10)
            parsed = _rss_list_page(list_args, len(own_lines), page_size)
            if parsed is None:
                bot.reply(msg, _rss_list_usage(bot))
                return
            page, show_all, page_size = parsed
            if show_all:
                page_items = own_lines
                lines = [f"Own direct feeds ({len(own_lines)}) - all:"]
            else:
                page_items, page, total_pages, total = paginate_items(
                    own_lines,
                    page,
                    page_size,
                )
                lines = [
                    f"Own direct feeds ({total}) - Page "
                    f"{page}/{total_pages}:"
                ]
            lines.extend(page_items)
            if not show_all and page < total_pages:
                lines.extend([
                    "",
                    f"Use {_command_prefix(bot)}rss list own {page + 1} "
                    "for the next page.",
                ])
            bot.reply(msg, lines)
            return
        if role <= Role.MODERATOR:
            bot.reply(
                msg,
                _compact_subscription_lines(feeds, compact_section),
            )
            return
        if role <= Role.TRUSTED:
            if compact_section in {"rooms", "mods"}:
                bot.reply(
                    msg,
                    "🔴 Only global moderators can list room or moderator RSS subscriptions.",
                )
                return
            owner = _normalize_room_jid(sender_jid)
            own = {
                url: {
                    **feed,
                    "rooms": [],
                    "users": {
                        owner: _direct_subscriptions(feed).get(owner),
                    },
                }
                for url, feed in feeds.items()
                if owner in _direct_subscriptions(feed)
            }
            if not own:
                bot.reply(msg, "No direct RSS feeds configured for you.")
                return
            bot.reply(
                msg,
                _compact_subscription_lines(own, "trusted"),
            )
            return
    if explicit_room or not is_global_manager:
        if not target_room:
            bot.reply(
                msg,
                "🔴 RSS list from private chat needs an explicit room JID "
                "unless you are a global moderator.",
            )
            return
        if not await _sender_can_manage_rss_room(bot, sender_jid, target_room):
            bot.reply(
                msg,
                "🔴 You need a global moderator role, or an RSS plugin "
                f"grant and owner/admin affiliation in {target_room}.",
            )
            return
        feeds = _filter_feeds_for_room(feeds, target_room)
        if not feeds:
            bot.reply(msg, f"No feeds configured for {target_room}.")
            return

    if compact_section:
        if compact_section in {"mods", "trusted"} and not is_global_manager:
            bot.reply(
                msg,
                "🔴 Only global moderators can list direct RSS subscriptions.",
            )
            return
        if len(list_args) != 1:
            bot.reply(msg, _rss_list_usage(bot))
            return
        bot.reply(
            msg,
            _compact_subscription_lines(feeds, compact_section),
        )
        return

    formatted_lines = _format_feed_list(feeds, list_args, bot=bot)

    if formatted_lines is None:
        bot.reply(msg, _rss_list_usage(bot))
        return

    bot.reply(msg, formatted_lines)

@command(
    "rss",
    role=Role.USER,
    short="Manage RSS feed subscriptions for rooms and direct users.",
    usage="{prefix}rss <add|delete|remove|del|rm|retry|reset|pause|resume|health|broken|list|template> ...",
    subcommands=[
        help_subcommand(
            "add",
            "{prefix}rss add <feed_url> [room_jid]",
            "Subscribe a room or your direct chat to an RSS/Atom feed.",
            examples=[
                help_example(
                    "{prefix}rss add https://example.org/feed.rss",
                    "Subscribe the current 1:1 chat to a feed.",
                ),
                help_example(
                    "{prefix}rss add https://example.org/feed.rss room@conference.example.org",
                    "Subscribe an explicitly named room to a feed.",
                ),
            ],
        ),
        help_subcommand(
            "list",
            "{prefix}rss list [own|rooms|mods|trusted|room_jid] [page|all|last]",
            "List RSS subscriptions visible to you.",
            examples=[
                help_example(
                    "{prefix}rss list",
                    "Show your direct subscriptions or the full moderator overview.",
                ),
                help_example(
                    "{prefix}rss list own",
                    "Show only your own personal direct subscriptions.",
                ),
                help_example(
                    "{prefix}rss list trusted",
                    "Show trusted-user direct subscriptions permitted for your role.",
                ),
            ],
        ),
        help_subcommand(
            "delete",
            "{prefix}rss delete <feed_url> [room_jid|jid|all] | "
            "{prefix}rss delete all <user_jid>",
            "Remove one subscription, or all direct subscriptions for a user.",
            aliases=("del", "remove", "rm"),
            examples=[
                help_example(
                    "{prefix}rss delete https://example.org/feed.rss",
                    "Remove the feed from the current room or your direct subscriptions.",
                ),
                help_example(
                    "{prefix}rss delete all user@example.org",
                    "As an admin, remove every direct RSS subscription for one user.",
                ),
            ],
        ),
        help_subcommand(
            "retry",
            "{prefix}rss retry <feed_url|all> [room_jid]",
            "Clear retry/backoff state and schedule another feed attempt.",
            aliases=("reset",),
            examples=[
                help_example(
                    "{prefix}rss retry https://example.org/feed.rss room@conference.example.org",
                    "Retry one room feed immediately.",
                ),
            ],
            role=Role.MODERATOR,
        ),
        help_subcommand(
            "pause",
            "{prefix}rss pause <feed_url> [room_jid|all]",
            "Pause feed delivery without deleting the subscription.",
            examples=[
                help_example(
                    "{prefix}rss pause https://example.org/feed.rss",
                    "Pause the feed for the current room.",
                ),
            ],
            role=Role.MODERATOR,
        ),
        help_subcommand(
            "resume",
            "{prefix}rss resume <feed_url> [room_jid|all]",
            "Resume a paused RSS subscription.",
            examples=[
                help_example(
                    "{prefix}rss resume https://example.org/feed.rss",
                    "Resume delivery for the current room.",
                ),
            ],
            role=Role.MODERATOR,
        ),
        help_subcommand(
            "health",
            "{prefix}rss health [room_jid] [page|all|last]",
            "Show feed status, retries, errors and last successful delivery.",
            examples=[
                help_example(
                    "{prefix}rss health",
                    "Inspect the health of feeds visible in the current context.",
                ),
            ],
            role=Role.MODERATOR,
        ),
        help_subcommand(
            "broken",
            "{prefix}rss broken [room_jid] [page|all|last]",
            "List only feeds that currently exceed the error threshold.",
            examples=[
                help_example(
                    "{prefix}rss broken",
                    "Show only broken feeds visible in the current context.",
                ),
            ],
            role=Role.MODERATOR,
        ),
        help_subcommand(
            "template",
            "{prefix}rss template [show|set|unset|test] [default|direct|room_jid] [feed_url] [template]",
            "Show, test or configure global, room and personal RSS templates.",
            examples=[
                help_example(
                    "{prefix}rss template",
                    "Show the effective template for the current destination.",
                ),
                help_example(
                    "{prefix}rss template set 📰 $feed_title: $title\\n$link",
                    "Set the default template for the current room or direct user.",
                ),
            ],
        ),
    ],
    examples=[
        "{prefix}rss add https://example.org/feed.rss room@conference.example.org",
        "{prefix}rss add https://example.org/feed.rss",
        "{prefix}rss list room@conference.example.org",
        "{prefix}rss list rooms",
        "{prefix}rss list mods",
        "{prefix}rss list trusted",
        "{prefix}rss list 2",
        "{prefix}rss list all",
        "{prefix}rss retry all",
        "{prefix}rss health",
        "{prefix}rss broken",
        "{prefix}rss pause https://example.org/feed.rss",
        "{prefix}rss resume https://example.org/feed.rss",
        "{prefix}rss reset all",
        "{prefix}rss retry https://example.org/feed.rss room@conference.example.org",
        "{prefix}rss template",
        "{prefix}rss template set default 📰 $feed_title: $title\n$link",
        "{prefix}rss template set 📰 $feed_title: $title\\n$link",
        "{prefix}rss template set https://example.org/feed.rss 📰 $title\n$link",
        "{prefix}rss template test [$feed_title] $title",
        "{prefix}rss template unset",
        "{prefix}rss delete https://example.org/feed.rss",
        "{prefix}rss remove https://example.org/feed.rss old@conference.example.org",
    ],
    category="rooms",
    context="any",
)
async def rss_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Manage RSS feeds.

    Add/delete/list Feed URLs to your room. The feeds are checked every
    20 minutes globally (configurable).

    Usage:
    {prefix}rss add <feedurl> [room_jid]
    {prefix}rss delete|remove|del|rm <feedurl> [room_jid|all]
    {prefix}rss delete|remove|del|rm all <user_jid>
    {prefix}rss retry|reset <feedurl>|all [room_jid]
    {prefix}rss pause|resume <feedurl> [room_jid|all]
    {prefix}rss health|broken [room_jid] [page|all|last]
    {prefix}rss list [own|rooms|mods|trusted|room_jid] [page|all|last]
    {prefix}rss template [show|set|unset|test] [default|direct|room_jid] [feedurl] [template]
    Direct chat: omit room_jid to manage your personal template.
    Room/MUC PM: omit room_jid to manage the current room template.
    """
    store = bot.db.users.plugin("rss")

    if not args:
        bot.reply(
            msg,
            f"Usage: {_command_prefix(bot)}rss "
            "<add|delete|remove|del|rm|retry|reset|pause|resume|health|broken|list|template> ...",
        )
        return

    sub = args[0].lower()
    room = _room_for_feed_command(msg, is_room)

    if sub == "template":
        await _rss_template_command(
            bot, sender_jid, msg, is_room, args[1:], store
        )
        return

    handlers = {
        "add": _rss_handle_add,
        "delete": _rss_handle_delete,
        "remove": _rss_handle_delete,
        "del": _rss_handle_delete,
        "rm": _rss_handle_delete,
        "retry": _rss_handle_retry,
        "reset": _rss_handle_retry,
        "pause": _rss_handle_pause,
        "resume": _rss_handle_pause,
        "health": _rss_handle_health,
        "broken": _rss_handle_health,
        "list": _rss_handle_list,
    }
    handler = handlers.get(sub)
    if handler is None:
        bot.reply(
            msg,
            "Unknown subcommand. Use add, delete, del, remove, rm, retry, "
            "reset, pause, resume, health, broken, list, or template.",
        )
        return
    await handler(bot, sender_jid, args, msg, is_room, store, room)

async def _add_direct_feed(bot, msg, url, store, owner: str, role: Role):
    url = _normalize_url(url)
    feeds = await get_feeds(store)
    if url not in feeds:
        try:
            parsed = await fetch_feed(url)
            feeds[url] = {
                "title": parsed.feed.get("title", url),
                "link": parsed.feed.get("link", url),
                "period": config.get("rss_global_query_interval", DEFAULT_POLL_INTERVAL),
                "rooms": [],
                "users": {},
                # Establish the subscription cursor from the feed snapshot used
                # during add. Otherwise the first polling run initializes the
                # cursor from whatever is newest at that later time and can
                # silently skip an entry published between add and first poll.
                "last_id": _get_latest_entry_id(parsed),
                "error_count": 0,
                "next_retry": 0,
                "paused": False,
                "paused_rooms": [],
                "last_checked": _now(),
                "last_success": _now(),
                "last_error": "",
                "last_error_at": 0,
                "last_posted": 0,
                "posted_count": 0,
            }
        except Exception as exc:
            _log_feed_fetch_error("Failed to add direct RSS feed", url, exc)
            bot.reply(msg, f"Failed to fetch or parse feed: {_format_feed_fetch_error(url, exc)}")
            return
    users = _direct_subscriptions(feeds[url])
    key = _normalize_direct_user_jid(owner)
    if not key:
        bot.reply(msg, f"🔴 Invalid direct subscriber JID: {owner}")
        return
    if key in users:
        bot.reply(msg, f"ℹ️ Feed already added for you: {url}")
        return
    users[key] = {"owner": key, "role": str(role)}
    feeds[url]["users"] = users
    await save_feeds(store, feeds)
    await ensure_task(bot, store, url, feeds[url]["period"])
    bot.reply(
        msg,
        f"✅ Added direct RSS feed: {feeds[url]['title']} ({url})\n"
        "New entries will be delivered in this chat.",
    )


async def _delete_direct_feed_target(bot, msg, url, store, target: str):
    url = _normalize_url(url)
    feeds = await get_feeds(store)
    feed = feeds.get(url)
    if not feed:
        bot.reply(msg, "Feed not found.")
        return
    users = _direct_subscriptions(feed)
    target = _normalize_room_jid(target)
    if target not in users:
        bot.reply(msg, f"ℹ️ {target} was not subscribed to the feed.")
        return
    users.pop(target, None)
    if not feed.get("rooms") and not users:
        feeds.pop(url, None)
        await unset_feed_templates_for_feed(store, url)
        await _cancel_feed_task(bot, url)
    else:
        feed["users"] = users
        await unset_feed_template(store, target, url)
    await save_feeds(store, feeds)
    bot.reply(msg, f"🗑 Removed direct RSS subscription for {target}: {url}")


async def _delete_direct_feed(bot, msg, url, store, actor: str, allow_other: bool):
    url = _normalize_url(url)
    feeds = await get_feeds(store)
    feed = feeds.get(url)
    if not feed:
        bot.reply(msg, "Feed not found.")
        return
    users = _direct_subscriptions(feed)
    actor_key = _normalize_room_jid(actor)
    target = actor_key if actor_key in users else None
    if target is None and allow_other:
        trusted = [jid for jid, meta in users.items() if str((meta or {}).get("role", "trusted")).lower() == "trusted"]
        if len(trusted) == 1:
            target = trusted[0]
    if target is None:
        bot.reply(msg, "🔴 You may only remove your own direct RSS feeds.")
        return
    await _delete_direct_feed_target(bot, msg, url, store, target)


async def _delete_all_direct_feeds_for_user(
    bot,
    msg,
    store,
    target: str,
) -> int:
    """Remove every direct RSS subscription belonging to one user."""
    target_key = _normalize_direct_user_jid(target)
    if not target_key:
        bot.reply(msg, f"🔴 Invalid direct subscriber JID: {target}")
        return 0

    feeds = await get_feeds(store)
    removed = 0
    removed_feeds: list[str] = []

    for url, feed in list(feeds.items()):
        if not isinstance(feed, dict):
            continue

        users = _direct_subscriptions(feed)
        matching_keys = [
            jid
            for jid in users
            if _normalize_direct_user_jid(jid) == target_key
        ]
        if not matching_keys:
            continue

        for jid in matching_keys:
            users.pop(jid, None)
        removed += 1

        if not feed.get("rooms") and not users:
            feeds.pop(url, None)
            removed_feeds.append(url)
        else:
            feed["users"] = users

    if not removed:
        bot.reply(
            msg,
            f"ℹ️ No direct RSS subscriptions found for {target_key}.",
        )
        return 0

    await unset_feed_templates_for_room(store, target_key)
    for url in removed_feeds:
        await unset_feed_templates_for_feed(store, url)
        await _cancel_feed_task(bot, url)
    await save_feeds(store, feeds)

    bot.reply(
        msg,
        f"🗑 Removed {removed} direct RSS subscription"
        f"{'s' if removed != 1 else ''} for {target_key}.",
    )
    return removed


async def _add_feed(bot, msg, url, store, room):
    url = _normalize_url(url)
    feeds = await get_feeds(store)

    if url not in feeds:
        try:
            feed = await fetch_feed(url)
            title = feed.feed.get("title", url)
            feed_link = feed.feed.get("link", url)

            # Burst last N (default 5) items to this room
            burst_num = config.get("max_new_feed_entries", 5)
            last_id = await burst_recent_entries(
                bot, feed, room, burst_num, store=store, feed_url=url
            )

            # After burst, remember last_id so next poll ignores
            # already-shown history.
            feeds[url] = {
                "title": title,
                "link": feed_link,
                "period": config.get("rss_global_query_interval",
                                     DEFAULT_POLL_INTERVAL),
                "rooms": [room],
                "last_id": last_id,
                "error_count": 0,
                "next_retry": 0,
                "paused": False,
                "paused_rooms": [],
                "last_checked": _now(),
                "last_success": _now(),
                "last_error": "",
                "last_error_at": 0,
                "last_posted": _now() if last_id else 0,
                "posted_count": 0,
            }

            await save_feeds(store, feeds)
            await ensure_task(bot, store, url, feeds[url]["period"])

            log.debug("[RSS] Added new feed url=%s", url)
            period = feeds[url]["period"]
            bot.reply(
                msg,
                f"✅ Added feed: {title} ({url}) every {period}s to {room}",
            )
        except Exception as e:
            _log_feed_fetch_error("Failed to add RSS feed", url, e)
            bot.reply(
                msg,
                f"Failed to fetch or parse feed: {_format_feed_fetch_error(url, e)}",
            )
            return
    else:
        rooms = _rss_normalize_room_list(feeds[url])
        if not any(_normalize_subscription_room(item) == _normalize_subscription_room(room) for item in rooms):
            rooms.append(room)
            feeds[url]["rooms"] = rooms
            await save_feeds(store, feeds)

            log.debug("[RSS] Added room to feed url=%s", url)
            await ensure_task(
                bot,
                store,
                url,
                feeds[url]["period"],
            )

            # Burst most recent N entries to this newly added room.
            try:
                feed = await fetch_feed(url)
                burst_num = config.get("max_new_feed_entries", 5)
                await burst_recent_entries(
                    bot, feed, room, burst_num, store=store, feed_url=url
                )
            except Exception as e:
                _log_feed_fetch_error(
                    "Failed to fetch or parse feed during burst to new room",
                    url,
                    e,
                )

            bot.reply(
                msg,
                f"✅ Added room {room} to feed: {
                    feeds[url]['title']} ({url})",
            )
        else:
            bot.reply(
                msg,
                f"ℹ️ Feed already added for this room: {url}",
            )

    return
async def _delete_feed_everywhere(bot, msg, url, store, feeds):
    """Remove a feed and its task regardless of subscribed rooms."""
    rooms = list(feeds[url].get("rooms", []))
    feeds.pop(url)
    await unset_feed_templates_for_feed(store, url)
    await _cancel_feed_task(bot, url)

    room_text = ", ".join(rooms) if rooms else "no rooms"
    bot.reply(msg, f"🗑 Deleted feed: {url} ({room_text})")
async def _delete_feed_room(bot, msg, url, store, feeds, room):
    """Remove one room subscription from an existing feed."""
    rooms = feeds[url].setdefault("rooms", [])
    normalized_room = _normalize_room_jid(room)
    stored_room = next(
        (item for item in rooms if _normalize_room_jid(item) == normalized_room),
        None,
    )

    if stored_room is None:
        bot.reply(
            msg,
            f"ℹ️ Room {room} was not subscribed to the feed.",
        )
        return

    rooms.remove(stored_room)

    if not rooms and not _direct_subscriptions(feeds[url]):
        feeds.pop(url)
        await unset_feed_templates_for_feed(store, url)
        await _cancel_feed_task(bot, url)
        bot.reply(
            msg,
            f"🗑 Deleted feed: {url} (no rooms left, feed removed)",
        )
        return

    await unset_feed_template(store, stored_room, url)

    await ensure_task(
        bot,
        store,
        url,
        feeds[url]["period"],
    )

    bot.reply(
        msg,
        f"🗑 Removed room {stored_room} from feed: {url}",
    )
async def _reset_all_feed_retries(bot, msg, store):
    """Clear retry state for every configured RSS feed and restart checks."""
    feeds = await get_feeds(store)

    if not feeds:
        bot.reply(msg, "No feeds configured.")
        return

    for _url, feed in feeds.items():
        _apply_retry_state(feed, 0, 0)

    await save_feeds(store, feeds)

    for url, feed in feeds.items():
        await _cancel_feed_task(bot, url)
        await ensure_task(
            bot,
            store,
            url,
            feed.get("period", DEFAULT_POLL_INTERVAL),
        )

    bot.reply(
        msg,
        f"🔁 Retry state reset and RSS checks scheduled for all feeds ({len(feeds)}).",
    )
async def _del_feed(bot, msg, url, store, room=None, delete_target=None):
    url = _normalize_url(url)
    feeds = await get_feeds(store)
    log.debug("[RSS] Delete feed request url=%s", url)

    if url not in feeds:
        bot.reply(msg, "Feed not found.")
        return

    target = str(delete_target).strip() if delete_target else ""

    if target.lower() == "all":
        await _delete_feed_everywhere(bot, msg, url, store, feeds)
    elif target:
        await _delete_feed_room(
            bot, msg, url, store, feeds, _normalize_room_jid(target)
        )
    elif room:
        await _delete_feed_room(bot, msg, url, store, feeds, room)
    else:
        # Direct/private cleanup path: useful for stale feeds whose room no
        # longer exists and cannot be addressed via a room or MUC PM anymore.
        await _delete_feed_everywhere(bot, msg, url, store, feeds)

    await save_feeds(store, feeds)
    return
async def _reset_feed_retry(bot, msg, url, store):
    """Clear a feed's retry state and restart its checker immediately."""
    url = _normalize_url(url)
    feeds = await get_feeds(store)

    if url not in feeds:
        bot.reply(msg, "Feed not found.")
        return

    feed = feeds[url]
    _apply_retry_state(feed, 0, 0)
    await save_feeds(store, feeds)

    await _cancel_feed_task(bot, url)
    await ensure_task(
        bot,
        store,
        url,
        feed.get("period", DEFAULT_POLL_INTERVAL),
    )

    bot.reply(msg, f"🔁 Retry state reset and RSS check scheduled: {url}")
