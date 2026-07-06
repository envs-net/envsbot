"""Split module for utils/config.py: logging_setup."""

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


def setup_logging(log_dir: Path | str = "logs"):
    """
    Initialize the logging system.

    ``log_dir`` is injectable for tests so mutation tools can keep a stable
    project working directory while still verifying log-file creation.
    """
    log_level = getattr(logging, config.get(
        "loglevel", "INFO").upper(), logging.INFO)

    log_dir = Path(log_dir)
    log_dir.mkdir(exist_ok=True)

    log_file = log_dir / "envsbot.log"

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    console = logging.StreamHandler()
    console.setLevel(log_level)
    console.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=2_000_000,  # 2 MB
        backupCount=5,
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    logging.basicConfig(
        level=log_level,
        handlers=[console, file_handler],
    )
