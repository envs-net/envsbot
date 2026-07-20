"""Mutable runtime state for the reminder plugin."""

from __future__ import annotations

import asyncio
import logging

from utils.config import config

log = logging.getLogger(__name__)
ACTIVE_REMINDERS: dict[int, asyncio.Task] = {}
REMINDER_ENABLED = bool(config.get("reminder_enabled", True))
REMINDER_DB_READY = False
