"""
XKCD Comic plugin.

Periodically checks for new XKCD comics and posts them to subscribed rooms.
Provides commands to view current or specific XKCD comics.

Commands:
    {prefix}xkcd [number]       - Show current or specific XKCD comic
    {prefix}xkcd on/off/status  - Enable/disable XKCD posting in this room
    {prefix}xkcd search <query> - Search for XKCD by title/alt
    {prefix}xkcd random         - Show a random XKCD comic
"""

import asyncio
import logging
import aiohttp
import random
from functools import partial

from utils.command import command, Role
from plugins.rooms import JOINED_ROOMS

log = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "xkcd",
    "version": "1.0.0",
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


async def fetch_image(url):
    """Fetch image from URL."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    content_type = resp.headers.get("Content-Type", "image/png")
                    filename = url.split("/")[-1] or "comic.png"
                    return data, content_type, filename
    except Exception as e:
        log.warning(f"[XKCD] Failed to fetch image {url}: {e}")
    return None, None, None


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


async def upload_file_xep0363(bot, filename, file_data, content_type):
    """
    Upload file via XEP-0363 (HTTP File Upload).

    Returns:
        Upload URL or None if failed
    """
    try:
        http_upload = bot.plugin.get('xep_0363', None)
        if not http_upload:
            log.debug("[XKCD] XEP-0363 not available")
            return None

        # Request upload slot
        slot = await http_upload.request_slot(
            filename=filename,
            size=len(file_data),
            content_type=content_type,
            timeout=10
        )

        # Upload file
        async with aiohttp.ClientSession() as session:
            headers = {'Content-Type': content_type} if content_type else {}
            async with session.put(
                slot['put'],
                data=file_data,
                headers=headers,
                timeout=30
            ) as resp:
                if resp.status in (200, 201):
                    log.debug(f"[XKCD] File uploaded to {slot['get']}")
                    return slot['get']

        return None

    except Exception as e:
        log.debug(f"[XKCD] XEP-0363 upload failed: {e}")
        return None


async def send_xkcd_room(bot, room_id, comic):
    """Send XKCD comic to a room (for broadcasting and room commands)."""
    if not comic:
        return

    try:
        img_url = comic.get("img")
        if not img_url:
            log.warning(f"[XKCD] No image URL in comic {comic.get('num')}")
            return

        # Ensure img_url has scheme
        if not img_url.startswith("http"):
            img_url = "https:" + img_url

        # Format message with info
        info_msg = format_comic_message(comic)

        # Send info message
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

        # Try to fetch and upload image
        image_data, content_type, filename = await fetch_image(img_url)

        if image_data:
            log.debug(f"[XKCD] Fetched image: {filename} ({len(image_data)} bytes)")
            # Try XEP-0363 upload
            upload_url = await upload_file_xep0363(bot, filename, image_data, content_type)

            if upload_url:
                # Send uploaded image URL
                log.info(f"[XKCD] Sending comic #{comic.get('num')} to room {room_id} via XEP-0363 upload")
                message = bot.make_message(
                    mto=room_id,
                    mbody=upload_url,
                    mtype="groupchat"
                )
                message.send()
                log.info(f"[XKCD] ✅ Comic #{comic.get('num')} sent via XEP-0363")
                return
            else:
                log.debug(f"[XKCD] XEP-0363 upload failed (server might not support it)")

        # Fallback: Send original image URL (will be rendered by client)
        log.info(f"[XKCD] Sending comic #{comic.get('num')} to room {room_id} via direct URL")
        message = bot.make_message(
            mto=room_id,
            mbody=img_url,
            mtype="groupchat"
        )
        message.send()
        log.info(f"[XKCD] ✅ Comic #{comic.get('num')} sent (URL will be rendered by client)")

    except Exception as e:
        log.exception(f"[XKCD] Failed to send comic {comic.get('num')} to room {room_id}: {e}")


async def send_xkcd_dm(bot, target_jid, comic):
    """Send XKCD comic via DM (direct message) with XEP-0363 support."""
    if not comic:
        return

    try:
        img_url = comic.get("img")
        if not img_url:
            log.warning(f"[XKCD] No image URL in comic {comic.get('num')}")
            return

        # Ensure img_url has scheme
        if not img_url.startswith("http"):
            img_url = "https:" + img_url

        # Format message with info
        info_msg = format_comic_message(comic)

        # Send info message
        message = bot.make_message(
            mto=target_jid,
            mbody=info_msg,
            mtype="chat"
        )
        message.send()

        # Try to fetch and upload image
        image_data, content_type, filename = await fetch_image(img_url)

        if image_data:
            log.debug(f"[XKCD] Fetched image: {filename} ({len(image_data)} bytes)")
            # Try XEP-0363 upload
            upload_url = await upload_file_xep0363(bot, filename, image_data, content_type)

            if upload_url:
                # Send uploaded image URL
                log.info(f"[XKCD] Sending comic #{comic.get('num')} to DM {target_jid} via XEP-0363 upload")
                message = bot.make_message(
                    mto=target_jid,
                    mbody=upload_url,
                    mtype="chat"
                )
                message.send()
                log.info(f"[XKCD] ✅ Comic #{comic.get('num')} sent via XEP-0363")
                return
            else:
                log.debug(f"[XKCD] XEP-0363 upload failed (server might not support it)")

        # Fallback: Send original image URL (will be rendered by client)
        log.info(f"[XKCD] Sending comic #{comic.get('num')} to DM {target_jid} via direct URL")
        message = bot.make_message(
            mto=target_jid,
            mbody=img_url,
            mtype="chat"
        )
        message.send()
        log.info(f"[XKCD] ✅ Comic #{comic.get('num')} sent (URL will be rendered by client)")

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


async def build_full_index(bot):
    """Build full search index of all XKCD comics."""
    try:
        # Fetch current comic to know the max ID
        latest = await get_latest_xkcd()
        if not latest:
            log.warning("[XKCD] Could not fetch latest comic for indexing")
            return

        store = await get_xkcd_store(bot)

        # Check if index already exists and is recent
        search_index = await store.get_global(XKCD_INDEX_KEY, default={})
        current_max_id = latest.get("num", 0)

        if search_index and len(search_index) > current_max_id * 0.9:
            log.info(f"[XKCD] Search index up to date with {len(search_index)} entries")
            return

        log.info(f"[XKCD] Building full search index up to comic #{current_max_id}...")

        indexed = 0
        failed = 0

        for comic_id in range(1, current_max_id + 1):
            try:
                comic = await get_xkcd(comic_id)
                if comic:
                    search_index[str(comic_id)] = {
                        "title": comic.get("title", ""),
                        "alt": comic.get("alt", ""),
                    }
                    indexed += 1

                    # Save every 200 comics to avoid losing progress
                    if indexed % 200 == 0:
                        await store.set_global(XKCD_INDEX_KEY, search_index)
                        log.info(f"[XKCD] Indexed {indexed}/{current_max_id} comics...")

                    # Small delay to avoid hammering the API
                    await asyncio.sleep(0.05)
                else:
                    failed += 1
            except asyncio.CancelledError:
                log.info(f"[XKCD] Index building cancelled at {indexed} comics")
                await store.set_global(XKCD_INDEX_KEY, search_index)
                return
            except Exception as e:
                log.debug(f"[XKCD] Failed to index comic #{comic_id}: {e}")
                failed += 1

        # Final save
        await store.set_global(XKCD_INDEX_KEY, search_index)
        log.info(f"[XKCD] ✅ Search index complete! Indexed {indexed} comics ({failed} failed)")

    except Exception as e:
        log.exception(f"[XKCD] Error building search index: {e}")


async def xkcd_check_loop(bot):
    """Periodically check for new XKCD comics and broadcast them."""
    global LAST_COMIC_ID

    try:
        # Get initial latest comic
        latest = await get_latest_xkcd()
        if latest:
            # Load saved ID from database
            LAST_COMIC_ID = await get_last_comic_id(bot)
            current_id = latest.get("num", 0)

            # If LAST_COMIC_ID is 0 (first run), set it to current ID
            # so we don't spam all old comics
            if LAST_COMIC_ID == 0:
                LAST_COMIC_ID = current_id
                await save_last_comic_id(bot, current_id)
                log.info(f"[XKCD] 🚀 First run: Initialized from comic #{current_id}")
            else:
                # Only log if there's a gap (new comics might have been posted)
                if current_id > LAST_COMIC_ID:
                    log.info(f"[XKCD] ⏳ Polling started: Last posted #{LAST_COMIC_ID}, current is #{current_id}")
                else:
                    log.debug(f"[XKCD] Polling started: No new comics (last=#{LAST_COMIC_ID})")
        else:
            log.error("[XKCD] Could not fetch initial comic info")
            return

        while True:
            try:
                await asyncio.sleep(CHECK_INTERVAL)

                latest = await get_latest_xkcd()
                if not latest:
                    log.warning("[XKCD] Failed to fetch latest comic")
                    continue

                current_id = latest.get("num", 0)
                log.debug(f"[XKCD] Poll check: last={LAST_COMIC_ID}, current={current_id}")

                # New comic found
                if current_id > LAST_COMIC_ID:
                    log.info(f"[XKCD] 🆕 New comic found: #{current_id}")
                    LAST_COMIC_ID = current_id

                    # Save new ID to database immediately
                    await save_last_comic_id(bot, current_id)

                    # Index the new comic
                    store = await get_xkcd_store(bot)
                    search_index = await store.get_global(XKCD_INDEX_KEY, default={})
                    search_index[str(current_id)] = {
                        "title": latest.get("title", ""),
                        "alt": latest.get("alt", ""),
                    }
                    await store.set_global(XKCD_INDEX_KEY, search_index)

                    # Get subscribed rooms
                    subscribed = await store.get_global(XKCD_KEY, default={"rooms": []})
                    rooms = subscribed.get("rooms", [])

                    log.info(f"[XKCD] Broadcasting to {len(rooms)} rooms")

                    # Broadcast to all subscribed rooms
                    for room_id in rooms:
                        if room_id in JOINED_ROOMS:
                            try:
                                await send_xkcd_room(bot, room_id, latest)
                                await asyncio.sleep(0.5)  # Small delay between rooms
                            except Exception as e:
                                log.exception(f"[XKCD] Error sending to {room_id}: {e}")
                        else:
                            log.warning(f"[XKCD] Room {room_id} not in JOINED_ROOMS")

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
        {prefix}xkcd              - Show latest comic
        {prefix}xkcd <number>     - Show specific comic
        {prefix}xkcd on           - Enable XKCD in this room (MUC DM only)
        {prefix}xkcd off          - Disable XKCD in this room (MUC DM only)
        {prefix}xkcd status       - Show XKCD status in this room (MUC DM only)
        {prefix}xkcd search <query> - Search for XKCD by title/alt
        {prefix}xkcd random       - Show random XKCD
    """

    from_jid = msg["from"].bare
    is_muc_pm = from_jid in JOINED_ROOMS

    log.debug(f"[XKCD] Command: args={args}, is_room={is_room}, is_muc_pm={is_muc_pm}, from_jid={from_jid}")

    # Handle status command (MUC PM ONLY)
    if args and args[0] == "status":
        if is_room or not is_muc_pm:
            bot.reply(msg, "🔴 This command can only be used in a MUC DM.")
            return

        store = await get_xkcd_store(bot)
        subscribed = await store.get_global(XKCD_KEY, default={"rooms": []})
        rooms = subscribed.get("rooms", [])

        if from_jid in rooms:
            bot.reply(msg, "✅ XKCD posting is **enabled** in this room.")
        else:
            bot.reply(msg, "🛑 XKCD posting is **disabled** in this room.")
        return

    # Handle on/off commands (MUC PM ONLY)
    if args and args[0] in ("on", "off"):
        if is_room or not is_muc_pm:
            bot.reply(msg, "🔴 This command can only be used in a MUC DM.")
            return

        store = await get_xkcd_store(bot)
        subscribed = await store.get_global(XKCD_KEY, default={"rooms": []})
        rooms = subscribed.get("rooms", [])

        if args[0] == "on":
            if from_jid not in rooms:
                rooms.append(from_jid)
                subscribed["rooms"] = rooms
                await store.set_global(XKCD_KEY, subscribed)
                bot.reply(msg, "✅ XKCD posting enabled in this room.")
                log.info(f"[XKCD] Room {from_jid} subscribed")
            else:
                bot.reply(msg, "ℹ️ XKCD posting already enabled.")
        else:
            if from_jid in rooms:
                rooms.remove(from_jid)
                subscribed["rooms"] = rooms
                await store.set_global(XKCD_KEY, subscribed)
                bot.reply(msg, "🛑 XKCD posting disabled in this room.")
                log.info(f"[XKCD] Room {from_jid} unsubscribed")
            else:
                bot.reply(msg, "ℹ️ XKCD posting already disabled.")
        return

    # Check if XKCD is enabled in the room before executing commands
    if is_muc_pm:
        store = await get_xkcd_store(bot)
        subscribed = await store.get_global(XKCD_KEY, default={"rooms": []})
        rooms = subscribed.get("rooms", [])

        if from_jid not in rooms:
            bot.reply(msg, "🛑 XKCD is not enabled in this room. Use ',xkcd on' in a MUC DM to enable it.")
            log.info(f"[XKCD] Command blocked: XKCD not enabled in {from_jid}")
            return

    # Handle search command
    if args and args[0] == "search":
        if len(args) < 2:
            bot.reply(msg, "❌ Usage: xkcd search <query>")
            return

        query = " ".join(args[1:]).lower()
        log.debug(f"[XKCD] Searching for: {query}")

        # Get search index
        store = await get_xkcd_store(bot)
        search_index = await store.get_global(XKCD_INDEX_KEY, default={})

        if not search_index:
            bot.reply(msg, "❌ Search index not built. Please wait for indexing to complete.")
            return

        results = []
        for comic_id_str, comic_data in search_index.items():
            title = comic_data.get("title", "").lower()
            alt = comic_data.get("alt", "").lower()

            # Simple substring search
            if query in title or query in alt:
                results.append({
                    "id": int(comic_id_str),
                    "title": comic_data.get("title", ""),
                    "alt": comic_data.get("alt", ""),
                })

        if not results:
            bot.reply(msg, f"❌ No XKCDs found matching '{query}'")
            return

        # Sort by ID descending (newest first)
        results.sort(key=lambda x: x["id"], reverse=True)

        # Show top 5 results
        msg_lines = [f"🔍 Found {len(results)} results for '{query}':"]
        for i, result in enumerate(results[:5], 1):
            msg_lines.append(f"{i}. #{result['id']}: {result['title']}")
            if result['alt']:
                alt_text = result['alt'][:50]
                if len(result['alt']) > 50:
                    alt_text += "..."
                msg_lines.append(f"   Alt: {alt_text}")

        if len(results) > 5:
            msg_lines.append(f"\n... and {len(results) - 5} more results")

        bot.reply(msg, "\n".join(msg_lines))
        return

    # Handle random command
    if args and args[0] == "random":
        latest = await get_latest_xkcd()
        if not latest:
            bot.reply(msg, "❌ Failed to fetch XKCD data.")
            return

        max_id = latest.get("num", 1)
        random_id = random.randint(1, max_id)

        comic = await get_xkcd(random_id)
        if comic:
            if is_muc_pm:
                await send_xkcd_room(bot, from_jid, comic)
            else:
                await send_xkcd_dm(bot, str(msg["from"]), comic)
        else:
            bot.reply(msg, f"❌ Failed to fetch XKCD #{random_id}.")
        return

    # Handle specific comic number
    if args:
        try:
            comic_id = int(args[0])
            comic = await get_xkcd(comic_id)
            if comic:
                if is_muc_pm:
                    await send_xkcd_room(bot, from_jid, comic)
                else:
                    await send_xkcd_dm(bot, str(msg["from"]), comic)
            else:
                bot.reply(msg, f"❌ XKCD #{comic_id} not found.")
            return
        except ValueError:
            pass

    # Default: show latest comic
    latest = await get_latest_xkcd()
    if latest:
        if is_muc_pm:
            await send_xkcd_room(bot, from_jid, latest)
        else:
            await send_xkcd_dm(bot, str(msg["from"]), latest)
    else:
        bot.reply(msg, "❌ Failed to fetch latest XKCD.")


async def on_load(bot):
    """Load the XKCD plugin and start the check loop."""
    global CHECK_TASK, INDEX_TASK

    log.info("[XKCD] Plugin loading...")

    # Register XEP-0363 if available
    try:
        if not bot.plugin.get('xep_0363', None):
            bot.register_plugin('xep_0363')
            log.info("[XKCD] XEP-0363 (HTTP File Upload) registered")
    except Exception as e:
        log.debug(f"[XKCD] Could not register XEP-0363: {e}")

    # Build full search index in background (non-blocking)
    INDEX_TASK = asyncio.create_task(build_full_index(bot))

    # Start the check loop
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
