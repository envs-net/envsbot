"""Split module for utils/config.py: errors."""

from __future__ import annotations
import importlib.util
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import available_timezones
import slixmpp


class ConfigError(Exception):
    """Raised when EnvsBot configuration is invalid or incomplete."""


def exit_on_config_error(error):
    """Print a readable config error and terminate startup."""
    print(f"[CONFIG] {error}", file=sys.stderr)
    raise SystemExit(1) from error
