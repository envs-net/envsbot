"""Split module for plugins/vcard.py: config."""

import logging

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

__all__ = [
    'VCARD_KEY',
    'PLUGIN_META',
    'log',
]
