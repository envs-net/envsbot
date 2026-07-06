"""Split module for core_plugins/users.py: roles."""

import logging
import asyncio
import inspect
from functools import partial
from datetime import datetime, timezone
from slixmpp import JID
from utils.config import config
from utils.command import command, Role, role_from_int
from utils.formatting import format_page, parse_page_args
from utils.audit import audit_event


log = logging.getLogger(__name__)


prefix = str(config.get("prefix", ",") or ",")


MAX_ROOM_NICKS = config.get("users", {}).get("max_room_nicks", 5)


ASSIGNABLE_ROLES = (
    Role.SUPERADMIN,
    Role.ADMIN,
    Role.MODERATOR,
    Role.TRUSTED,
    Role.USER,
    Role.NEW,
    Role.BANNED,
)


ROLE_NAMES = {role.name.lower(): role for role in ASSIGNABLE_ROLES}


GRANTABLE_PLUGINS = ("rss", "pin", "poll")


GRANTS_FIELD = "plugin_grants"


PLUGIN_META = {
    "name": "users",
    "version": "0.1.0",
    "description": "User management with caching, nick lookup and logging",
    "category": "core",
}
