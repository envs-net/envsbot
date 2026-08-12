"""RSS administration and subscription commands."""

from __future__ import annotations

from core_plugins._core import paginate_items
from utils.audit import audit_event
from utils.command import Role, command
from utils.command_metadata import help_example, help_subcommand
from utils.config import config

from .command_support import (
    _command_prefix,
    _compact_subscription_lines,
    _direct_subscriptions,
    _looks_like_room_arg,
    _message_type,
    _room_for_feed_command,
    _rss_health_lines,
    _rss_health_summary,
    _rss_list_usage,
    _rss_normalize_room_list,
    _sender_can_manage_rss_globally,
    _sender_can_manage_rss_room,
    _sender_role,
    _trusted_feed_count,
)
from .config import DEFAULT_POLL_INTERVAL, RSS_TRUSTED_MAX_FEEDS
from .fetch import _normalize_url
from .formatting import (
    _filter_feeds_for_room,
    _format_feed_list,
    _normalize_direct_user_jid,
    _rss_list_page,
)
from .store import (
    _feed_article_count,
    _feed_paused_rooms,
    _feed_url_by_number,
    _normalize_room_jid,
    _normalize_subscription_room,
    get_feeds,
    save_feeds,
)
from .subscriptions import (
    _add_direct_feed,
    _add_feed,
    _del_feed,
    _delete_all_direct_feeds_for_user,
    _delete_direct_feed,
    _delete_direct_feed_target,
    _reset_all_feed_retries,
    _reset_feed_retry,
)
from .tasks import _cancel_feed_task, ensure_task
from .templates import _rss_template_command


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
            "<feedurl|feed_no> [room|jid|all] | "
            f"{_command_prefix(bot)}rss delete all <user_jid>",
        )
        return

    feed_selector = str(args[1]).strip()
    feed_url = feed_selector
    if feed_selector.isdecimal():
        feeds = await get_feeds(store)
        resolved = _feed_url_by_number(feeds, int(feed_selector))
        if not resolved:
            bot.reply(msg, f"Feed #{feed_selector} not found.")
            return
        feed_url = resolved

    delete_target = args[2] if len(args) == 3 else None
    target_room = None
    if delete_target and str(delete_target).strip().lower() != "all":
        target_room = _normalize_room_jid(delete_target)
    elif room:
        target_room = room

    direct_target = None
    if delete_target and str(delete_target).strip().lower() != "all":
        current_feed = (await get_feeds(store)).get(_normalize_url(feed_url), {})
        candidate = _normalize_room_jid(delete_target)
        if candidate in _direct_subscriptions(current_feed):
            direct_target = candidate

    if direct_target:
        role = await _sender_role(bot, sender_jid)
        if direct_target != _normalize_room_jid(sender_jid) and role > Role.ADMIN:
            bot.reply(msg, "🔴 Only owner, superadmin, or admin can remove another user's direct RSS feed.")
            return
        await _delete_direct_feed_target(bot, msg, feed_url, store, direct_target)
        return

    # A bare delete in a normal 1:1 chat is always scoped to the sender's
    # direct subscription, regardless of whether the sender also has global
    # RSS management rights. Global deletion must be explicit via ``all``.
    if (
        not delete_target
        and not room
        and _message_type(msg) in ("chat", "normal")
    ):
        role = await _sender_role(bot, sender_jid)
        if role > Role.TRUSTED:
            bot.reply(msg, "🔴 Direct RSS subscriptions require trusted role or higher.")
            return
        await _delete_direct_feed(
            bot,
            msg,
            feed_url,
            store,
            sender_jid,
            allow_other=False,
        )
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
        bot.reply(msg, "🔴 Only global moderators can delete RSS feeds without a direct or room scope.")
        return

    await _del_feed(bot, msg, feed_url, store, room, delete_target)
    await audit_event(
        bot,
        "rss_feed_delete_requested",
        actor=sender_jid,
        target=target_room or delete_target or room or "rss",
        details={
            "url": _normalize_url(feed_url),
            "feed_selector": feed_selector,
            "target": delete_target,
        },
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
            own_article_total = sum(
                _feed_article_count(feed)
                for feed in feeds.values()
                if isinstance(feed, dict)
                and any(
                    _normalize_direct_user_jid(jid) == owner
                    for jid in _direct_subscriptions(feed)
                )
            )
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
                lines = [
                    f"Own direct feeds ({len(own_lines)} feeds, "
                    f"{own_article_total} articles) - all:"
                ]
            else:
                page_items, page, total_pages, total = paginate_items(
                    own_lines,
                    page,
                    page_size,
                )
                lines = [
                    f"Own direct feeds ({total} feeds, "
                    f"{own_article_total} articles) - Page "
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
            "{prefix}rss delete <feed_url|feed_no> [room_jid|jid|all] | "
            "{prefix}rss delete all <user_jid>",
            "Remove one scoped subscription by URL/feed number, or explicitly remove a feed everywhere.",
            aliases=("del", "remove", "rm"),
            examples=[
                help_example(
                    "{prefix}rss delete 12",
                    "In 1:1 remove only your own direct subscription; in a room remove only that room subscription.",
                ),
                help_example(
                    "{prefix}rss delete 12 user@example.org",
                    "As owner, superadmin, or admin, remove only this user's direct subscription to feed #12.",
                ),
                help_example(
                    "{prefix}rss delete all user@example.org",
                    "As owner, superadmin, or admin, remove every direct RSS subscription for one user.",
                ),
                help_example(
                    "{prefix}rss delete 12 all",
                    "As a global RSS manager, remove feed #12 everywhere: all rooms and all direct subscriptions.",
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
        "{prefix}rss delete 12",
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
    {prefix}rss delete|remove|del|rm <feedurl|feed_no> [room_jid|all]
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
