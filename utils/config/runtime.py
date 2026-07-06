"""Split module for utils/config.py: runtime."""

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


# This module is intentionally small; public names are re-exported by the package facade.
