"""RSS administration and subscription commands."""

from __future__ import annotations

from utils.command import command, Role
from utils.config import config
from utils.audit import audit_event
from bot.room_state import JOINED_ROOMS
from core_plugins._core import paginate_items
from core_plugins.users import user_has_room_plugin_grant

from .config import DEFAULT_POLL_INTERVAL, RSS_BROKEN_ERROR_THRESHOLD
from .fetch import (
    _extract_entry_link,
    _format_feed_fetch_error,
    _get_entry_id,
    _log_feed_fetch_error,
    _normalize_url,
    _resolve_relative_url,
    entry_get,
    fetch_feed,
    html_to_text_with_links,
)
from .formatting import (
    DEFAULT_RSS_TEMPLATE,
    _SAMPLE_TEMPLATE_CONTEXT,
    _build_rss_message_from_context,
    _build_rss_template_context,
    _entry_date,
    _filter_feeds_for_room,
    _format_feed_list,
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
    _set_feed_field,
    get_effective_template,
    get_default_template,
    get_feed_template,
    get_feeds,
    get_room_template,
    log,
    save_feeds,
    set_feed_template,
    set_default_template,
    set_room_template,
    unset_feed_template,
    unset_feed_templates_for_feed,
    unset_default_template,
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

    if is_room and msg.get("type") == "groupchat" and room_jid:
        return str(room_jid)

    if (
        msg.get("type") in ("chat", "normal")
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
def _looks_like_room_arg(value) -> bool:
    """Best-effort test for explicit room JID arguments."""
    text = str(value or "").strip()
    return "@" in text and "://" not in text
async def _save_last_id(bot, store, url, entry_id):
    return await _set_feed_field(bot, store, url, "last_id", entry_id)
def _rss_list_usage(bot=None) -> str:
    """Return the usage string for paginated RSS list output."""
    return f"Usage: {_command_prefix(bot)}rss list [page|all|last]"
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
def _split_template_scope_args(msg, is_room: bool, args: list[str]):
    """Return ``(room, feed_url, rest)`` for RSS template subcommands.

    Scope syntax is intentionally compact:

    * ``[room_jid]`` targets a room template.
    * ``[room_jid] <feed_url>`` targets a feed template in that room.
    * In a public room/MUC PM, ``<feed_url>`` is enough for a feed template.
    """
    rest = list(args)
    explicit_room = None
    if rest and _looks_like_room_arg(rest[0]):
        explicit_room = rest.pop(0)
    room = _room_for_feed_command(msg, is_room, explicit_room=explicit_room)

    feed_url = None
    if rest and _looks_like_feed_arg(rest[0]):
        feed_url = _normalize_url(rest.pop(0))

    return room, feed_url, rest
async def _template_feed_for_room(store, room: str, feed_url: str):
    """Return feed metadata when the feed is subscribed in the room."""
    feeds = await get_feeds(store)
    feed = feeds.get(_normalize_url(feed_url))
    if not isinstance(feed, dict):
        return None
    rooms = feed.get("rooms")
    if not isinstance(rooms, list):
        return None
    target = _normalize_room_jid(room)
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
    bot, sender_jid: str, room: str | None
) -> bool:
    """Return True when sender may view or change a room RSS template."""
    if not room:
        return False
    return await _sender_can_manage_rss_room(bot, sender_jid, room)
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

    global_default = bool(
        rest and str(rest[0]).strip().lower() in {"default", "global"}
    )
    if global_default:
        rest.pop(0)
        room = None
        feed_url = None
        if not await _sender_can_manage_rss_globally(bot, sender_jid):
            bot.reply(
                msg,
                "🔴 You need a global moderator role to manage the default "
                "RSS template.",
            )
            return
    else:
        room, feed_url, rest = _split_template_scope_args(msg, is_room, rest)
        if not room:
            bot.reply(msg, _rss_template_usage(bot))
            return

        if not await _sender_can_manage_template(bot, sender_jid, room):
            bot.reply(
                msg,
                "🔴 You need a global moderator role, or an RSS plugin grant "
                f"and owner/admin affiliation in {room}.",
            )
            return

    feed = None
    if feed_url:
        feed = await _template_feed_for_room(store, room, feed_url)
        if feed is None:
            bot.reply(msg, f"🔴 Feed is not configured for {room}: {feed_url}")
            return

    scope = (
        "global default"
        if global_default
        else f"{room} / {feed_url}" if feed_url else room
    )

    if action == "show":
        if rest:
            bot.reply(msg, _rss_template_usage(bot))
            return
        if global_default:
            template = await get_default_template(store)
            source = "custom" if template else "built-in"
            template = template or DEFAULT_RSS_TEMPLATE
        elif feed_url:
            feed_template = await get_feed_template(store, room, feed_url)
            room_template = await get_room_template(store, room)
            default_template = await get_default_template(store)
            if feed_template:
                source = "feed custom"
                template = feed_template
            elif room_template:
                source = "room custom"
                template = room_template
            elif default_template:
                source = "global default"
                template = default_template
            else:
                source = "built-in default"
                template = DEFAULT_RSS_TEMPLATE
        else:
            template = await get_room_template(store, room)
            if template:
                source = "custom"
            else:
                template = await get_default_template(store)
                source = "global default" if template else "built-in default"
                template = template or DEFAULT_RSS_TEMPLATE
        bot.reply(
            msg,
            f"🧩 RSS template for {scope} ({source}):\n"
            f"{template}\n\n{_rss_template_variables_text()}",
        )
        return

    if action == "unset":
        if rest:
            bot.reply(msg, _rss_template_usage(bot))
            return
        if global_default:
            removed = await unset_default_template(store)
            event_type = "rss_default_template_unset"
            success = "✅ Global default RSS template reset to the built-in default."
            unchanged = "ℹ️ The built-in default RSS template is already active."
        elif feed_url:
            removed = await unset_feed_template(store, room, feed_url)
            event_type = "rss_feed_template_unset"
            success = f"✅ RSS feed template reset for {scope}."
            unchanged = f"ℹ️ {scope} already uses the room/default RSS template."
        else:
            removed = await unset_room_template(store, room)
            event_type = "rss_template_unset"
            success = f"✅ RSS template reset to default for {room}."
            unchanged = f"ℹ️ {room} already uses the default RSS template."
        if removed:
            bot.reply(msg, success)
            await audit_event(
                bot,
                event_type,
                actor=sender_jid,
                target=scope,
            )
        else:
            bot.reply(msg, unchanged)
        return

    if action == "test":
        template = _join_template_args(rest) if rest else (
            await get_default_template(store)
            if global_default else await get_effective_template(store, room, feed_url)
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
        return

    if action == "set":
        template = _join_template_args(rest)
        error = _validate_rss_template(template)
        if error:
            bot.reply(msg, f"🔴 {error}\n{_rss_template_variables_text()}")
            return
        if global_default:
            await set_default_template(store, template)
            event_type = "rss_default_template_set"
            success = "✅ Global default RSS template set for all rooms."
        elif feed_url:
            await set_feed_template(store, room, feed_url, template)
            event_type = "rss_feed_template_set"
            success = f"✅ RSS feed template set for {scope}."
        else:
            await set_room_template(store, room, template)
            event_type = "rss_template_set"
            success = f"✅ RSS template set for {room}."
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
            f"errors: {error_count}; last success: {_format_rss_timestamp(feed.get('last_success'))}; "
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
@command(
    "rss",
    role=Role.USER,
    short="Manage RSS feed subscriptions for rooms.",
    usage="{prefix}rss <add|delete|remove|del|rm|retry|reset|pause|resume|health|broken|list|template> ...",
    examples=[
        "{prefix}rss add https://example.org/feed.rss room@conference.example.org",
        "{prefix}rss list room@conference.example.org",
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
        "{prefix}rss template set 📰 $feed_title: $title\n$link",
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
    {prefix}rss retry|reset <feedurl>|all [room_jid]
    {prefix}rss pause|resume <feedurl> [room_jid|all]
    {prefix}rss health|broken [room_jid] [page|all|last]
    {prefix}rss list [room_jid] [page|all|last]
    {prefix}rss template [show|set|unset|test] [default|room_jid] [feedurl] [template]
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

    # Add feed to room
    if sub == "add":
        if len(args) not in (2, 3):
            bot.reply(
                msg,
                f"Usage: {_command_prefix(bot)}rss add <feedurl> [room_jid]",
            )
            return

        room = _room_for_feed_command(
            msg,
            is_room,
            explicit_room=args[2] if len(args) == 3 else None,
        )
        if not room:
            bot.reply(
                msg,
                "🔴 RSS add needs a room context or explicit room JID.",
            )
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

    # Delete feed from a room, or remove it completely from direct/admin PMs.
    elif sub in {"delete", "remove", "del", "rm"}:
        if len(args) not in (2, 3):
            bot.reply(
                msg,
                f"Usage: {_command_prefix(bot)}rss delete <feedurl> [room|all]",
            )
            return

        delete_target = args[2] if len(args) == 3 else None
        target_room = None
        if delete_target and str(delete_target).strip().lower() != "all":
            target_room = _normalize_room_jid(delete_target)
        elif room:
            target_room = room

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
            bot.reply(
                msg,
                "🔴 RSS delete from private chat needs an explicit room JID "
                "unless you are a global moderator.",
            )
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

    elif sub in {"retry", "reset"}:
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

    elif sub in {"pause", "resume"}:
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

    elif sub in {"health", "broken"}:
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
                page_items, page, total_pages, total = paginate_items(detail_lines, page, int(page_size))
                lines[0] += f" - Page {page}/{total_pages}"
            lines.extend(page_items)
            if not show_all and page < total_pages:
                lines.append("")
                lines.append(f"Use {_command_prefix(bot)}rss {sub} {page + 1} for the next page.")
        bot.reply(msg, lines)
        return

    # List rooms or one explicitly targeted room.
    elif sub == "list":
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

        is_global_manager = await _sender_can_manage_rss_globally(
            bot, sender_jid
        )
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

        lines = _format_feed_list(feeds, list_args, bot=bot)

        if lines is None:
            bot.reply(msg, _rss_list_usage(bot))
            return

        bot.reply(msg, lines)

    else:
        bot.reply(
            msg,
            "Unknown subcommand. Use add, delete, remove, retry, "
            "reset, pause, resume, health, broken, list, or template.",
        )
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
            # await _flush_user_store(bot)
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
            # await _flush_user_store(bot)

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

    if not rooms:
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

    for url, feed in feeds.items():
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
    # await _flush_user_store(bot)
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
