"""Split module for plugins/vcard.py: config."""

import logging
import textwrap
import pytz
import datetime
import urllib
from slixmpp.exceptions import IqError
from core_plugins import _core
from utils.command import command, Role
from utils.config import config
from core_plugins.rooms import JOINED_ROOMS


VCARD_KEY = "VCARD"


PLUGIN_META = {
    "name": "vcard",
    "version": "0.5.0",
    "description":
    "Lookup and display vCard of a MUC occupant by MUC JID only",
    "category": "info",
    "requires": ["rooms", "_core"],
}


log = logging.getLogger(__name__)
