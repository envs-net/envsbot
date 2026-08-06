"""Split module for utils/config.py: logging setup."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_MANAGED_HANDLER_ATTR = "_envsbot_managed_handler"


def _remove_managed_handlers(root: logging.Logger) -> None:
    """Detach and close handlers created by an earlier setup call."""
    for handler in tuple(root.handlers):
        if not getattr(handler, _MANAGED_HANDLER_ATTR, False):
            continue
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass


def setup_logging(log_dir: Path | str = "logs") -> None:
    """Initialize envsbot logging without leaking handlers on reloads.

    ``log_dir`` is injectable for tests. Pytest and embedding applications may
    already own root handlers, so only handlers created by this function are
    replaced; unrelated capture or application handlers remain attached.
    """
    from . import config as runtime_config

    log_level = getattr(
        logging,
        str(runtime_config.get("loglevel", "INFO")).upper(),
        logging.INFO,
    )

    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    log_file = directory / "envsbot.log"

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    console = logging.StreamHandler()
    console.setLevel(log_level)
    console.setFormatter(formatter)
    setattr(console, _MANAGED_HANDLER_ATTR, True)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=2_000_000,
        backupCount=5,
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    setattr(file_handler, _MANAGED_HANDLER_ATTR, True)

    root = logging.getLogger()
    _remove_managed_handlers(root)
    root.setLevel(log_level)
    root.addHandler(console)
    root.addHandler(file_handler)
