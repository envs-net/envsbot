"""RSS list and search command handlers."""

from __future__ import annotations

from core_plugins._core import paginate_items
from utils.command import Role
from utils.config import config

from .command_support import (
    _command_prefix,
    _compact_subscription_lines,
    _direct_subscriptions,
    _format_rss_search_item,
    _looks_like_room_arg,
    _message_type,
    _rss_list_usage,
    _rss_search_matches,
    _rss_search_scope_feeds,
    _rss_search_usage,
    _sender_can_manage_rss_globally,
    _sender_can_manage_rss_room,
    _sender_role,
)
from .formatting import (
    _filter_feeds_for_room,
    _format_feed_list,
    _normalize_direct_user_jid,
    _rss_list_page,
)
from .store import _feed_article_count, _normalize_room_jid, get_feeds


def _rss_parse_search_args(args) -> tuple[str | None, str, list[str]] | None:
    """Parse optional RSS search scope, query text and paging arguments."""
    if len(args) < 2:
        return None

    search_args = [str(value).strip() for value in args[1:]]
    scope: str | None = None
    if search_args and search_args[0].lower() in {"own", "rooms", "mods", "trusted"}:
        scope = search_args.pop(0).lower()
    elif len(search_args) >= 2 and _looks_like_room_arg(search_args[0]):
        scope = _normalize_room_jid(search_args.pop(0))

    if not search_args:
        return None

    page_arg: str | None = None
    if len(search_args) >= 2:
        candidate = search_args[-1].lower()
        if candidate in {"all", "last"} or candidate.lstrip("+-").isdigit():
            page_arg = search_args.pop()

    query = " ".join(search_args).strip()
    if not query:
        return None

    paging_args = ["search"]
    if page_arg is not None:
        paging_args.append(page_arg)
    return scope, query, paging_args


async def _rss_handle_search(bot, sender_jid, args, msg, is_room, store, room):
    parsed_args = _rss_parse_search_args(args)
    if parsed_args is None:
        bot.reply(msg, _rss_search_usage(bot))
        return

    scope, query, paging_args = parsed_args
    feeds = await get_feeds(store)
    if not feeds:
        bot.reply(msg, "No feeds configured.")
        return

    is_global_manager = await _sender_can_manage_rss_globally(bot, sender_jid)
    message_is_private = _message_type(msg) in ("chat", "normal") and room is None

    if scope == "own":
        if not message_is_private:
            bot.reply(
                msg,
                "🔴 Own direct RSS subscriptions can only be searched in a normal 1:1 chat.",
            )
            return
        role = await _sender_role(bot, sender_jid)
        if role > Role.TRUSTED:
            bot.reply(msg, "🔴 Direct RSS subscriptions require trusted role or higher.")
            return
        feeds = _rss_search_scope_feeds(
            feeds,
            "own",
            owner=_normalize_room_jid(sender_jid),
        )
    elif scope in {"rooms", "mods", "trusted"}:
        if not is_global_manager:
            bot.reply(
                msg,
                "🔴 Only global moderators can search this RSS subscription scope.",
            )
            return
        feeds = _rss_search_scope_feeds(feeds, scope)
    elif scope:
        target_room = _normalize_room_jid(scope)
        if not await _sender_can_manage_rss_room(bot, sender_jid, target_room):
            bot.reply(
                msg,
                "🔴 You need a global moderator role, or an RSS plugin "
                f"grant and owner/admin affiliation in {target_room}.",
            )
            return
        feeds = _filter_feeds_for_room(feeds, target_room)
    elif room:
        # Search is intentionally scoped to the current room, even for global
        # managers. Use a normal 1:1 chat for a global feed search.
        if not await _sender_can_manage_rss_room(bot, sender_jid, room):
            bot.reply(
                msg,
                "🔴 You need a global moderator role, or an RSS plugin "
                f"grant and owner/admin affiliation in {room}.",
            )
            return
        feeds = _filter_feeds_for_room(feeds, room)
    elif message_is_private:
        if not is_global_manager:
            role = await _sender_role(bot, sender_jid)
            if role > Role.TRUSTED:
                bot.reply(
                    msg,
                    "🔴 RSS search from private chat needs an explicit room JID "
                    "unless you are trusted or a global moderator.",
                )
                return
            feeds = _rss_search_scope_feeds(
                feeds,
                "own",
                owner=_normalize_room_jid(sender_jid),
            )
    else:
        bot.reply(msg, _rss_search_usage(bot))
        return

    matches = _rss_search_matches(feeds, query)
    if not matches:
        bot.reply(msg, f'No RSS feeds matching "{query}".')
        return

    page_size = int(config.get("rss_list_page_size", 10) or 10)
    parsed_page = _rss_list_page(paging_args, len(matches), page_size)
    if parsed_page is None:
        bot.reply(msg, _rss_search_usage(bot))
        return

    page, show_all, page_size = parsed_page
    if show_all:
        page_items = matches
        lines = [f'RSS search "{query}" — {len(matches)} match(es) - all:']
        total_pages = 1
    else:
        page_items, page, total_pages, total = paginate_items(
            matches,
            page,
            page_size,
        )
        lines = [
            f'RSS search "{query}" — {total} match(es) - Page {page}/{total_pages}:',
        ]

    lines.extend(_format_rss_search_item(url, feed) for url, feed in page_items)
    if not show_all and page < total_pages:
        scope_hint = f"{scope} " if scope else ""
        lines.extend([
            "",
            f"Use {_command_prefix(bot)}rss search {scope_hint}{query} {page + 1} "
            "for the next page.",
        ])
    bot.reply(msg, lines)


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
