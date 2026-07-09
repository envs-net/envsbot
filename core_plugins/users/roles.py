"""Split module for core_plugins/users.py: roles."""

import logging
from utils.config import config
from utils.command import Role


log = logging.getLogger(__name__)


prefix = str(config.get("prefix", ",") or ",")


def _command_prefix(bot=None) -> str:
    """Return the currently configured command prefix for user replies."""
    return str(
        getattr(bot, "prefix", None)
        or config.get("prefix", None)
        or prefix
        or ","
    )


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

__all__ = [
    'log',
    'prefix',
    '_command_prefix',
    'MAX_ROOM_NICKS',
    'ASSIGNABLE_ROLES',
    'ROLE_NAMES',
    'GRANTABLE_PLUGINS',
    'GRANTS_FIELD',
    'PLUGIN_META',
]
