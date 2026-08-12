"""Template-specific RSS command handling."""

from __future__ import annotations

from utils.audit import audit_event
from utils.command import Role

from .command_support import (
    _direct_subscriptions,
    _looks_like_feed_arg,
    _looks_like_room_arg,
    _room_for_feed_command,
    _sender_can_manage_rss_globally,
    _sender_can_manage_rss_room,
    _sender_role,
)
from .fetch import _normalize_url
from .formatting import (
    _SAMPLE_TEMPLATE_CONTEXT,
    DEFAULT_RSS_TEMPLATE,
    _build_rss_message_from_context,
    _normalize_rss_template_input,
    _rss_template_usage,
    _rss_template_variables_text,
    _validate_rss_template,
)
from .store import (
    _normalize_room_jid,
    get_default_template,
    get_effective_template,
    get_feed_template,
    get_feeds,
    get_room_template,
    set_default_template,
    set_feed_template,
    set_room_template,
    unset_default_template,
    unset_feed_template,
    unset_room_template,
)


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
