"""
XKCD Comic plugin.

Periodically checks for new XKCD comics and posts them to subscribed rooms.
Provides commands to view current or specific XKCD comics.

Commands:
    {prefix}xkcd [number]              - Show current or specific XKCD comic
    {prefix}xkcd on/off/status         - Enable/disable XKCD posting in this room
    {prefix}xkcd search <query> [page] - Search for XKCD by title/alt
    {prefix}xkcd random                - Show a random XKCD comic
"""

import asyncio
import logging
import aiohttp
import random

from utils.command import command, Role
from plugins.rooms import JOINED_ROOMS
from utils.plugin_helper import handle_room_toggle_command

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "xkcd",
    "version": "1.1.1",
    "description": "XKCD comic fetcher and broadcaster with full indexing",
    "category": "fun",
    "requires": ["rooms"],
}

XKCD_KEY = "XKCD"
XKCD_LAST_ID_KEY = "XKCD_LAST_ID"
XKCD_INDEX_KEY = "XKCD_INDEX"
XKCD_API_URL = "https://xkcd.com/{}/info.0.json"
XKCD_LATEST_URL = "https://xkcd.com/info.0.json"
XKCD_COMIC_URL = "https://xkcd.com/{}"
CHECK_INTERVAL = 3600  # Check every hour
CHECK_TASK = None
INDEX_TASK = None
LAST_COMIC_ID = 0

# XKCD comic #404 intentionally does not exist
MISSING_COMIC_IDS = {404}


async def get_xkcd_store(bot):
    """Get the database store for XKCD settings."""
    return bot.db.users.plugin("xkcd")


async def fetch_xkcd(url):
    """Fetch XKCD comic info from API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        log.warning(f"[XKCD] Failed to fetch {url}: {e}")
    return None


async def get_latest_xkcd():
    """Fetch the latest XKCD comic."""
    return await fetch_xkcd(XKCD_LATEST_URL)


async def get_xkcd(comic_id):
    """Fetch a specific XKCD comic by ID."""
    return await fetch_xkcd(XKCD_API_URL.format(comic_id))


def format_comic_message(comic):
    """Format XKCD comic info text."""
    num = comic.get("num", "?")
    title = comic.get("title", "No title")
    alt = comic.get("alt", "")

    msg = f"🎨 XKCD #{num}: {title}\n"
    if alt:
        msg += f"📝 {alt}\n"
    msg += f"🔗 {XKCD_COMIC_URL.format(num)}"

    return msg


def normalize_image_url(url):
    """Ensure image URL has a usable scheme."""
    if not url:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("//"):
        return "https:" + url
    return url


async def send_url_with_oob(bot, target, url, mtype):
    """
    Send a URL in the message body and include XEP-0066 OOB data.
    """
    message = bot.make_message(
        mto=target,
        mbody=url,
        mtype=mtype,
    )

    try:
        message["oob"]["url"] = url
    except Exception as e:
        log.debug(f"[XKCD] Could not attach XEP-0066 OOB data: {e}")

    message.send()


async def send_xkcd_room(bot, room_id, comic):
    """Send XKCD comic to a room (for broadcasting and room commands)."""
    if not comic:
        return

    try:
        img_url = normalize_image_url(comic.get("img"))
        if not img_url:
            log.warning(f"[XKCD] No image URL in comic {comic.get('num')}")
            return

        info_msg = format_comic_message(comic)

        bot.reply(
            {
                "from": type("F", (), {"bare": room_id})(),
                "type": "groupchat",
            },
            info_msg,
            mention=False,
            thread=True,
            rate_limit=False,
            ephemeral=False,
        )

        # Ensure the info message lands before the image URL/OOB message
        await asyncio.sleep(0.2)

        log.info(f"[XKCD] Sending comic #{comic.get('num')} to room {room_id} via direct URL + OOB")
        await send_url_with_oob(bot, room_id, img_url, "groupchat")
        log.info(f"[XKCD] ✅ Comic #{comic.get('num')} sent to room")

    except Exception as e:
        log.exception(f"[XKCD] Failed to send comic {comic.get('num')} to room {room_id}: {e}")


async def send_xkcd_dm(bot, target_jid, comic):
    """Send XKCD comic via DM (including MUC PM) with XEP-0066 OOB."""
    if not comic:
        return

    try:
        img_url = normalize_image_url(comic.get("img"))
        if not img_url:
            log.warning(f"[XKCD] No image URL in comic {comic.get('num')}")
            return

        info_msg = format_comic_message(comic)

        message = bot.make_message(
            mto=target_jid,
            mbody=info_msg,
            mtype="chat",
        )
        message.send()

        # Ensure the info message lands before the image URL/OOB message
        await asyncio.sleep(0.2)

        log.info(f"[XKCD] Sending comic #{comic.get('num')} to DM {target_jid} via direct URL + OOB")
        await send_url_with_oob(bot, target_jid, img_url, "chat")
        log.info(f"[XKCD] ✅ Comic #{comic.get('num')} sent to DM")

    except Exception as e:
        log.exception(f"[XKCD] Failed to send comic {comic.get('num')} to DM {target_jid}: {e}")


async def get_last_comic_id(bot):
    """Get last posted comic ID from database."""
    store = await get_xkcd_store(bot)
    data = await store.get_global(XKCD_LAST_ID_KEY, default={"id": 0})
    return data.get("id", 0)


async def save_last_comic_id(bot, comic_id):
    """Save last posted comic ID to database."""
    store = await get_xkcd_store(bot)
    await store.set_global(XKCD_LAST_ID_KEY, {"id": comic_id})
    log.debug(f"[XKCD] Saved last comic ID to DB: {comic_id}")


async def add_comic_to_index(bot, comic):
    """Add a comic to the search index."""
    if not comic:
        return

    comic_id = comic.get("num")
    if not comic_id:
        return

    store = await get_xkcd_store(bot)
    search_index = await store.get_global(XKCD_INDEX_KEY, default={})
    search_index[str(comic_id)] = {
        "title": comic.get("title", ""),
        "alt": comic.get("alt", ""),
    }
    await store.set_global(XKCD_INDEX_KEY, search_index)


async def get_subscribed_rooms(bot):
    """Return subscribed rooms."""
    store = await get_xkcd_store(bot)
    subscribed = await store.get_global(XKCD_KEY, default={"rooms": []})
    return subscribed.get("rooms", [])


async def broadcast_comic_to_subscribed_rooms(bot, comic):
    """Broadcast a comic to all subscribed rooms."""
    rooms = await get_subscribed_rooms(bot)
    log.info(f"[XKCD] Broadcasting comic #{comic.get('num')} to {len(rooms)} rooms")

    for room_id in rooms:
        if room_id in JOINED_ROOMS:
            try:
                await send_xkcd_room(bot, room_id, comic)
                await asyncio.sleep(0.5)
            except Exception as e:
                log.exception(f"[XKCD] Error sending comic #{comic.get('num')} to {room_id}: {e}")
        else:
            log.warning(f"[XKCD] Room {room_id} not in JOINED_ROOMS")


async def build_full_index(bot):
    """Build full search index of all XKCD comics."""
    try:
        latest = await get_latest_xkcd()
        if not latest:
            log.warning("[XKCD] Could not fetch latest comic for indexing")
            return

        store = await get_xkcd_store(bot)
        search_index = await store.get_global(XKCD_INDEX_KEY, default={})
        current_max_id = latest.get("num", 0)

        expected_count = current_max_id - len(MISSING_COMIC_IDS)

        if search_index and len(search_index) >= expected_count:
            log.info(f"[XKCD] Search index up to date with {len(search_index)} entries")
            return

        log.info(
            f"[XKCD] Building full search index up to comic #{current_max_id} "
            f"(currently have {len(search_index)}/{expected_count})..."
        )

        indexed = 0
        failed = 0

        for comic_id in range(1, current_max_id + 1):
            if comic_id in MISSING_COMIC_IDS:
                continue
            if str(comic_id) in search_index:
                continue

            try:
                comic = await get_xkcd(comic_id)
                if comic:
                    search_index[str(comic_id)] = {
                        "title": comic.get("title", ""),
                        "alt": comic.get("alt", ""),
                    }
                    indexed += 1

                    if indexed % 200 == 0:
                        await store.set_global(XKCD_INDEX_KEY, search_index)
                        log.info(f"[XKCD] Indexed {indexed} new comics...")

                    await asyncio.sleep(0.05)
                else:
                    failed += 1
                    log.debug(f"[XKCD] Comic #{comic_id} could not be fetched")
            except asyncio.CancelledError:
                log.info(f"[XKCD] Index building cancelled after {indexed} new comics")
                await store.set_global(XKCD_INDEX_KEY, search_index)
                return
            except Exception as e:
                log.debug(f"[XKCD] Failed to index comic #{comic_id}: {e}")
                failed += 1

        await store.set_global(XKCD_INDEX_KEY, search_index)
        log.info(f"[XKCD] ✅ Search index complete! Added {indexed} comics ({failed} failed)")

    except Exception as e:
        log.exception(f"[XKCD] Error building search index: {e}")


async def catch_up_missing_comics(bot, start_id, end_id):
    """Fetch, index, and broadcast comics from start_id to end_id inclusive."""
    global LAST_COMIC_ID

    if end_id < start_id:
        return

    log.info(f"[XKCD] ⏳ Catching up from #{start_id} to #{end_id}")

    for comic_id in range(start_id, end_id + 1):
        if comic_id in MISSING_COMIC_IDS:
            LAST_COMIC_ID = comic_id
            await save_last_comic_id(bot, comic_id)
            continue

        comic = await get_xkcd(comic_id)
        if not comic:
            log.warning(f"[XKCD] Could not fetch comic #{comic_id}")
            continue

        await add_comic_to_index(bot, comic)
        await broadcast_comic_to_subscribed_rooms(bot, comic)

        LAST_COMIC_ID = comic_id
        await save_last_comic_id(bot, comic_id)


async def xkcd_check_loop(bot):
    """Periodically check for new XKCD comics and broadcast them."""
    global LAST_COMIC_ID

    try:
        latest = await get_latest_xkcd()
        if not latest:
            log.error("[XKCD] Could not fetch initial comic info")
            return

        LAST_COMIC_ID = await get_last_comic_id(bot)
        current_id = latest.get("num", 0)

        if LAST_COMIC_ID == 0:
            LAST_COMIC_ID = current_id
            await save_last_comic_id(bot, current_id)
            log.info(f"[XKCD] 🚀 First run: Initialized from comic #{current_id}")
        elif current_id > LAST_COMIC_ID:
            await catch_up_missing_comics(bot, LAST_COMIC_ID + 1, current_id)
        else:
            log.debug(f"[XKCD] Polling started: No new comics (last={LAST_COMIC_ID})")

        while True:
            try:
                await asyncio.sleep(CHECK_INTERVAL)

                latest = await get_latest_xkcd()
                if not latest:
                    log.warning("[XKCD] Failed to fetch latest comic")
                    continue

                current_id = latest.get("num", 0)
                log.debug(f"[XKCD] Poll check: last={LAST_COMIC_ID}, current={current_id}")

                if current_id > LAST_COMIC_ID:
                    await catch_up_missing_comics(bot, LAST_COMIC_ID + 1, current_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.exception(f"[XKCD] Error in check loop: {e}")

    except asyncio.CancelledError:
        log.debug("[XKCD] Check loop cancelled")


@command("xkcd", role=Role.USER)
async def xkcd_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Manage and view XKCD comics.

    Usage:
        {prefix}xkcd                    - Show latest comic
        {prefix}xkcd <number>           - Show specific comic
        {prefix}xkcd on                 - Enable XKCD in this room (MUC DM only)
        {prefix}xkcd off                - Disable XKCD in this room (MUC DM only)
        {prefix}xkcd status             - Show XKCD status in this room (MUC DM only)
        {prefix}xkcd search <query> [page] - Search for XKCD by title/alt
        {prefix}xkcd random             - Show random XKCD
    """

    from_jid = msg["from"].bare
    is_muc_pm = from_jid in JOINED_ROOMS

    log.debug(f"[XKCD] Command: args={args}, is_room={is_room}, is_muc_pm={is_muc_pm}, from_jid={from_jid}")

    # Try to read configured command prefix for help text.
    # Fall back to a comma if the bot does not expose one.
    command_prefix = getattr(bot, "prefix", ",")

    # on/off/status are room-management actions and must be restricted
    # explicitly. Viewing/searching XKCD remains available to users.
    if await handle_room_toggle_command(
        bot, msg, is_room, args,
        store_getter=get_xkcd_store,
        key=XKCD_KEY,
        label="XKCD posting",
        storage="list",
        list_field="rooms",
        log_prefix="[XKCD]",
    ):
        return

    # Commands in MUC PM only work when XKCD is enabled for that room
    if is_muc_pm:
        store = await get_xkcd_store(bot)
        subscribed = await store.get_global(XKCD_KEY, default={"rooms": []})
        rooms = subscribed.get("rooms", [])

        if from_jid not in rooms:
            bot.reply(msg, "🛑 XKCD is not enabled in this room. Use ',xkcd on' in a MUC DM to enable it.")
            log.info(f"[XKCD] Command blocked: XKCD not enabled in {from_jid}")
            return

    # search command with pagination
    if args and args[0] == "search":
        if len(args) < 2:
            bot.reply(msg, "❌ Usage: xkcd search <query> [page]")
            return

        page = 1
        if len(args) >= 3 and args[-1].isdigit():
            page = int(args[-1])
            query = " ".join(args[1:-1]).lower()
        else:
            query = " ".join(args[1:]).lower()

        if not query:
            bot.reply(msg, "❌ Usage: xkcd search <query> [page]")
            return

        if page < 1:
            bot.reply(msg, "❌ Page number must be 1 or greater.")
            return

        log.debug(f"[XKCD] Searching for: {query} (page {page})")

        store = await get_xkcd_store(bot)
        search_index = await store.get_global(XKCD_INDEX_KEY, default={})

        if not search_index:
            bot.reply(msg, "❌ Search index not built. Please wait for indexing to complete.")
            return

        results = []
        for comic_id_str, comic_data in search_index.items():
            title = comic_data.get("title", "").lower()
            alt = comic_data.get("alt", "").lower()

            if query in title or query in alt:
                results.append({
                    "id": int(comic_id_str),
                    "title": comic_data.get("title", ""),
                    "alt": comic_data.get("alt", ""),
                })

        if not results:
            bot.reply(msg, f"❌ No XKCDs found matching '{query}'")
            return

        results.sort(key=lambda x: x["id"], reverse=True)

        per_page = 10
        total_results = len(results)
        total_pages = (total_results + per_page - 1) // per_page

        if page > total_pages:
            bot.reply(
                msg,
                f"❌ Page {page} does not exist. There {'is' if total_pages == 1 else 'are'} only {total_pages} page{'s' if total_pages != 1 else ''}."
            )
            return

        start = (page - 1) * per_page
        end = start + per_page
        page_results = results[start:end]

        msg_lines = [
            f"🔍 Found {total_results} results for '{query}' (page {page}/{total_pages}):"
        ]

        for i, result in enumerate(page_results, start + 1):
            msg_lines.append(f"{i}. #{result['id']}: {result['title']}")
            if result["alt"]:
                alt_text = result["alt"][:80]
                if len(result["alt"]) > 80:
                    alt_text += "..."
                msg_lines.append(f"   Alt: {alt_text}")

        if page < total_pages:
            msg_lines.append(f"\n➡️ Next page: {command_prefix}xkcd search {query} {page + 1}")
        if page > 1:
            msg_lines.append(f"⬅️ Previous page: {command_prefix}xkcd search {query} {page - 1}")

        bot.reply(msg, "\n".join(msg_lines))
        return

    # random command
    if args and args[0] == "random":
        latest = await get_latest_xkcd()
        if not latest:
            bot.reply(msg, "❌ Failed to fetch XKCD data.")
            return

        max_id = latest.get("num", 1)

        while True:
            random_id = random.randint(1, max_id)
            if random_id not in MISSING_COMIC_IDS:
                break

        comic = await get_xkcd(random_id)
        if comic:
            if is_room:
                await send_xkcd_room(bot, from_jid, comic)
            else:
                await send_xkcd_dm(bot, str(msg["from"]), comic)
        else:
            bot.reply(msg, f"❌ Failed to fetch XKCD #{random_id}.")
        return

    # specific comic number
    if args:
        try:
            comic_id = int(args[0])

            if comic_id in MISSING_COMIC_IDS:
                bot.reply(msg, f"❌ XKCD #{comic_id} does not exist.")
                return

            comic = await get_xkcd(comic_id)
            if comic:
                if is_room:
                    await send_xkcd_room(bot, from_jid, comic)
                else:
                    await send_xkcd_dm(bot, str(msg["from"]), comic)
            else:
                bot.reply(msg, f"❌ XKCD #{comic_id} not found.")
            return
        except ValueError:
            pass

    # default: latest comic
    latest = await get_latest_xkcd()
    if latest:
        if is_room:
            await send_xkcd_room(bot, from_jid, latest)
        else:
            await send_xkcd_dm(bot, str(msg["from"]), latest)
    else:
        bot.reply(msg, "❌ Failed to fetch latest XKCD.")


async def on_load(bot):
    """Load the XKCD plugin and start the check loop."""
    global CHECK_TASK, INDEX_TASK

    log.info("[XKCD] Plugin loading...")

    # Register XEP-0066 if available
    try:
        if not bot.plugin.get("xep_0066", None):
            bot.register_plugin("xep_0066")
            log.info("[XKCD] XEP-0066 (Out of Band Data) registered")
    except Exception as e:
        log.debug(f"[XKCD] Could not register XEP-0066: {e}")

    INDEX_TASK = asyncio.create_task(build_full_index(bot))
    CHECK_TASK = asyncio.create_task(xkcd_check_loop(bot))
    log.info("[XKCD] Plugin loaded, check loop started")


async def on_unload(bot):
    """Unload the XKCD plugin and stop the check loop."""
    global CHECK_TASK, INDEX_TASK

    log.info("[XKCD] Plugin unloading...")

    if INDEX_TASK and not INDEX_TASK.done():
        INDEX_TASK.cancel()
        try:
            await INDEX_TASK
        except asyncio.CancelledError:
            pass

    if CHECK_TASK and not CHECK_TASK.done():
        CHECK_TASK.cancel()
        try:
            await CHECK_TASK
        except asyncio.CancelledError:
            pass

    log.info("[XKCD] Plugin unloaded")
