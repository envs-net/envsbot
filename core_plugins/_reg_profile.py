"""
Bot profile initialization plugin.

This plugin manages the public profile of the bot on the XMPP
network.

No Commands
-----------
This plugin has no commands, it is just run at startup or on reload
and sets the vCard and the Avatar if they've changed.

Responsibilities
----------------
• Publish or update the bot vCard (from vcard.py)
• Publish or update the bot avatar (XEP-0084)
• Do Avatar publishing using PEP (Personal Eventing Protocol) (XEP-0163)
• Avoid unnecessary updates using SHA1 hash comparison

If the configured avatar or vCard data has not changed since
the last run, the plugin skips the update to reduce network
traffic.

The profile setup is executed automatically when the XMPP
session starts or on plugin reload.
"""

import asyncio
import hashlib
import logging
import os

from envs_xmpp_core.xmpp.avatar import (
    cache_xep0153_hash,
    load_avatar_payload,
    publish_xep0084_avatar,
)
from slixmpp.xmlstream import ET

from bot.connection import session_is_ready
from utils.bundled_assets import resolve_bundled_asset
from utils.config import config
from utils.python_source import load_python_namespace
from utils.runtime_paths import profile_state_file, vcard_file

PLUGIN_META = {
    "name": "_reg_profile",
    "version": "0.3.0",
    "description": "Bot avatar and vCard profile management",
    "category": "core",
}

# Setup logging
log = logging.getLogger(__name__)

AVATAR_HASH_FILE = str(profile_state_file(config, "avatar_hash.asc"))
VCARD_HASH_FILE = str(profile_state_file(config, "vcard_hash.asc"))


# -------------------------------------------------
# HASH HELPERS
# -------------------------------------------------
def read_hash(path):
    """
    Read a previously stored SHA1 hash from a file.

    Parameters
    ----------
    path : str
        Path to the file containing the stored hash.

    Returns
    -------
    str or None
        The stored hash string if the file exists and can be read.
        Returns None if the file does not exist or reading fails.

    Notes
    -----
    Hash files are used to avoid unnecessary network updates
    for avatars and vCards. If the stored hash matches the newly
    calculated hash, the update will be skipped.
    """

    if not os.path.exists(path):
        return None

    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None


def _load_vcard_xml(path):
    """Load the configured vCard XML string without writing bytecode caches."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    namespace = load_python_namespace(path, module_name="_envsbot_runtime_vcard")
    return namespace["VCARD"]



def write_hash(path, value):
    """
    Store a SHA1 hash value in a file.

    Parameters
    ----------
    path : str
        File path where the hash should be written.
    value : str
        SHA1 hash string to store.

    Notes
    -----
    This function is used after successfully publishing
    an avatar or updating a vCard. The stored hash allows
    the bot to detect whether the data has changed on
    subsequent startups.
    """

    try:
        with open(path, "w") as f:
            f.write(value)
    except Exception as e:
        log.error(f"[_REG_PROFILE] 🔴 Failed writing hash file {path}: {e}")


def sha1(data):
    """
    Compute the SHA1 hash of arbitrary binary data.

    Parameters
    ----------
    data : bytes
        Data for which the SHA1 digest should be calculated.

    Returns
    -------
    str
        Hexadecimal SHA1 digest string.

    Notes
    -----
    SHA1 hashes are used by the XMPP avatar specification
    and also serve as a lightweight method to detect whether
    avatar or vCard data has changed since the last run.
    """

    return hashlib.sha1(data).hexdigest()


# -------------------------------------------------
# VCARD BUILDER
# -------------------------------------------------
def build_vcard(card, data):
    """
    Recursively populate a vCard stanza from configuration data.

    Parameters
    ----------
    card : slixmpp.xmlstream.stanzabase.ElementBase
        The vCard stanza object obtained from the XEP-0054 plugin.
    data : dict
        Dictionary containing vCard fields from the configuration.

    Behavior
    --------
    - Iterates through all keys in the configuration dictionary.
    - If the value is another dictionary, a nested vCard element
      is created and populated recursively.
    - If the value is a scalar, it is assigned directly to the
      corresponding vCard field.
    """

    for key, value in data.items():

        if isinstance(value, dict):
            sub = card[key]
            build_vcard(sub, value)
        else:
            card[key] = value


# -------------------------------------------------
# VCARD UPDATE
# -------------------------------------------------
async def update_vcard(bot):
    """
    Update the XMPP vCard if the configured runtime vcard.py has changed.
    Uses VCARD global from vcard.py (XML, as string).
    Skips update if hash matches.
    """
    if not session_is_ready(bot):
        log.warning("[_REG_PROFILE] vCard update skipped: XMPP session is not ready")
        return

    vcard_py_path = str(vcard_file(config))
    try:
        VCARD = await asyncio.to_thread(_load_vcard_xml, vcard_py_path)
    except FileNotFoundError:
        log.warning(
            "[_REG_PROFILE] vcard.py does not exist. Skipping vCard update.")
        return
    except Exception as e:
        log.error(f"[_REG_PROFILE] Error importing vcard.py: {e}")
        return

    if not isinstance(VCARD, str):
        log.error(
            "[_REG_PROFILE] VCARD variable in vcard.py is not a string!")
        return

    # For hash comparison
    serialized = VCARD.encode("utf-8")
    new_hash = sha1(serialized)
    stored_hash = await asyncio.to_thread(read_hash, VCARD_HASH_FILE)
    if stored_hash == new_hash:
        log.debug(
            "[_REG_PROFILE] vCard (from vcard.py/XML) unchanged"
            " — skipping update")
        return

    try:
        vcard_elem = ET.fromstring(VCARD)
        iq = bot.make_iq_set()
        iq.append(vcard_elem)
        await iq.send()
        await asyncio.to_thread(write_hash, VCARD_HASH_FILE, new_hash)
        log.info("[_REG_PROFILE]✅ vCard (from vcard.py, XML string) updated")
    except Exception as e:
        log.error(
            f"[_REG_PROFILE]🔴 vCard upload from vcard.py (XML) failed: {e}")


# -------------------------------------------------
# AVATAR UPDATE
# -------------------------------------------------
async def update_avatar(bot):
    """Publish the configured avatar through modern and legacy XMPP paths.

    XEP-0084 data/metadata and the XEP-0054/XEP-0153 compatibility path are
    attempted independently.  The persisted v2 marker is written only after
    both network publications succeed, so a partial server-side update is
    retried on the next profile refresh.
    """
    if not session_is_ready(bot):
        log.warning("[_REG_PROFILE] Avatar update skipped: XMPP session is not ready")
        return

    avatar_path = config.get("avatar")
    avatar_type = config.get("avatar_type")
    if not avatar_path:
        return

    try:
        resolved_avatar = resolve_bundled_asset(str(avatar_path))
        payload = await asyncio.to_thread(
            load_avatar_payload,
            resolved_avatar,
            media_type=avatar_type,
        )
    except FileNotFoundError:
        log.warning("[_REG_PROFILE]🟡️ Avatar file not found")
        return
    except (OSError, ValueError) as exc:
        log.error("[_REG_PROFILE]🔴 Invalid avatar: %s", exc)
        return

    image_hash = payload.sha1
    new_hash = f"v2:{image_hash}"
    stored_hash = await asyncio.to_thread(read_hash, AVATAR_HASH_FILE)

    if stored_hash == new_hash:
        log.debug("[_REG_PROFILE] Avatar unchanged — skipping upload")
        if await cache_xep0153_hash(bot, image_hash):
            bot.avatar_hash = image_hash
            if hasattr(bot, "presence"):
                bot.presence.broadcast()
        else:
            log.debug("[_REG_PROFILE] Could not seed XEP-0153 avatar hash cache")
        return

    xep0084_ok = False
    try:
        await publish_xep0084_avatar(bot, payload)
        xep0084_ok = True
    except Exception as exc:  # Slixmpp may expose transport/IQ errors by plugin version.
        log.warning("[_REG_PROFILE]🟡 XEP-0084 avatar publish failed: %s", exc)

    xep0153_ok = False
    try:
        # Slixmpp's XEP-0153 helper updates PHOTO/BINVAL in the existing
        # XEP-0054 vCard, preserving the configured profile fields.
        await bot["xep_0153"].set_avatar(
            jid=bot.boundjid.bare,
            avatar=payload.data,
            mtype=payload.media_type,
        )
        xep0153_ok = True
    except Exception as exc:  # Slixmpp may expose transport/IQ errors by plugin version.
        log.warning("[_REG_PROFILE]🟡 XEP-0054/XEP-0153 avatar publish failed: %s", exc)

    if xep0153_ok:
        if await cache_xep0153_hash(bot, image_hash):
            bot.avatar_hash = image_hash
            if hasattr(bot, "presence"):
                bot.presence.broadcast()
        else:
            log.debug("[_REG_PROFILE] Could not seed XEP-0153 avatar hash cache")

    if xep0084_ok and xep0153_ok:
        await asyncio.to_thread(write_hash, AVATAR_HASH_FILE, new_hash)
        log.info("[_REG_PROFILE]✅ Avatar updated")
    elif xep0084_ok or xep0153_ok:
        log.warning(
            "[_REG_PROFILE]🟡 Avatar updated only partially; publication will be retried"
        )
    else:
        log.error("[_REG_PROFILE]🔴 Avatar update failed on all XMPP publication paths")


# -------------------------------------------------
# MAIN SETUP
# -------------------------------------------------
async def setup_profile(bot):
    """
    Initialize the bot profile during session startup.

    Parameters
    ----------
    bot : Bot
        Instance of the Slixmpp bot client.

    Behavior
    --------
    This function performs all profile-related tasks once
    the XMPP session has started:

    1. Ensures the bot has a user record.
    2. Updates the vCard if necessary.
    3. Publishes a new avatar if it has changed.

    The bot lifecycle already requested the roster before plugin readiness.
    Profile publication therefore runs from ``on_ready`` rather than during
    module loading.
    """

    try:
        um = bot.db.users
        if await um.get(str(bot.boundjid.bare)) is None:
            await um.create(str(bot.boundjid.bare), config.get("nick", None))
        log.info("[_REG_PROFILE]✅ user DB entry created or already exists")
    except Exception as e:
        log.error(f"['_REG_PROFILE]🔴 user DB entry creation failed: {e}")

    await update_vcard(bot)

    await update_avatar(bot)


# -------------------------------------------------
# REGISTER
# -------------------------------------------------
async def on_load(bot):
    """
    Register the profile plugin with the bot. That means it sets the the avatar
    and the vCard, if they've changed.

    Parameters
    ----------
    bot : Bot
        The main bot instance that loads this plugin.

    Behavior
    --------
    - Registers the required XMPP extensions for vcard-temp, PEP, User Avatar
    - Hooks the profile initialization into the
      ``session_start`` event.

    Registered Extensions
    ---------------------
    - XEP-0054 : vCard-temp
    - XEP-0163 : Personal Eventing Protocol
    - XEP-0084 : User Avatar
    """

    bot.register_plugin("xep_0054")
    bot.register_plugin("xep_0084")
    bot.register_plugin("xep_0153")
    bot.register_plugin("xep_0163")


async def on_ready(bot):
    """
    Sets the timezone of the bot in the PluginRuntimeStore(GLOBAL)
    if the bot is fully set up.

    Parameters
    ----------
    bot : Bot
        The main bot instance.
    """
    # Network profile publication belongs in the readiness phase, after all
    # plugins are loaded and while the XMPP session is known to be established.
    await setup_profile(bot)

    # Set timezone on startup from config file
    store = bot.db.users.plugin("vcard")
    await store.set(str(bot.boundjid.bare), "TIMEZONE", config.get("timezone",
                                                                   "UTC"))

    # Rooms are usually joined after this plugin's on_load hook has already
    # published the avatar. Re-broadcast here so every joined MUC receives a
    # directed XEP-0153 presence hash too. That makes the avatar visible to
    # participants who do not have the bot as a roster contact.
    if hasattr(bot, "presence"):
        bot.presence.broadcast()
