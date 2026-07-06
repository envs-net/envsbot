"""Split module for utils/config.py: loader."""

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


def _config_path_from_env() -> Path | None:
    configured = os.environ.get("ENVSBOT_CONFIG")
    if not configured:
        return None

    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _default_config_path() -> Path:
    return BASE_DIR / CONFIG_FILENAME


def _legacy_config_path() -> Path:
    return BASE_DIR / LEGACY_CONFIG_FILENAME


def get_runtime_config_path() -> Path:
    """Return the config file path currently used by envsbot.

    ``config.py`` is preferred.  A custom ``ENVSBOT_CONFIG`` path is returned
    when set.  The legacy JSON path is returned only as a migration fallback.
    """
    configured_path = _config_path_from_env()
    if configured_path is not None:
        return configured_path

    config_path = _default_config_path()
    if config_path.exists():
        return config_path

    legacy_path = _legacy_config_path()
    if legacy_path.exists():
        return legacy_path

    return config_path


def _format_json_error(error: json.JSONDecodeError, path: Path) -> str:
    return (
        f"Failed to parse {path.name} at "
        f"line {error.lineno}, column {error.colno}: {error.msg}"
    )


def _format_python_error(error: SyntaxError, path: Path) -> str:
    line = error.lineno or "?"
    column = error.offset or "?"
    return f"Failed to parse {path.name} at line {line}, column {column}: {error.msg}"


def _load_python_config(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")

    module_name = "_envsbot_runtime_config"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ConfigError(f"Failed to load {path.name}: no import loader available")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except SyntaxError as e:
        raise ConfigError(_format_python_error(e, path)) from e
    except ConfigError:
        raise
    except Exception as e:
        raise ConfigError(f"Failed to load {path.name}: {e}") from e

    loaded = {}
    for name, value in vars(module).items():
        if name.startswith("_"):
            continue

        if name in PYTHON_CONFIG_KEY_MAP:
            loaded[PYTHON_CONFIG_KEY_MAP[name]] = value
            continue

        # Allow already-normalized lowercase keys for tests and small local
        # overrides, but keep the documented operator format uppercase.
        if name in NORMALIZED_CONFIG_KEYS:
            loaded[name] = value
            continue

        if name.isupper():
            loaded[name.lower()] = value

    return loaded


def _merge_room_plugin_default_config(base: dict, loaded: dict) -> dict:
    """Merge partial ROOM_PLUGIN_DEFAULTS over documented fallbacks."""
    configured = loaded.get("room_plugin_defaults")
    fallback = base.get("room_plugin_defaults")
    if not isinstance(configured, dict) or not isinstance(fallback, dict):
        return loaded

    merged = fallback.copy()
    merged.update(configured)
    result = loaded.copy()
    result["room_plugin_defaults"] = merged
    return result


def _load_legacy_json_config(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(_format_json_error(e, path)) from e
    except Exception as e:
        raise ConfigError(f"Failed to load {path.name}: {e}") from e

    if not isinstance(loaded, dict):
        raise ConfigError(f"{path.name} must contain a JSON object at top level")

    return {k: v for k, v in loaded.items() if not str(k).startswith("_comment")}


def load_config(require_required_keys=False):
    """
    Load config.py and validate it.

    ``config.py`` is the primary format.  If ``ENVSBOT_CONFIG`` is set, that
    exact file is used and may be either ``.py`` or legacy ``.json``.  If no
    ``config.py`` exists, a legacy ``config.json`` is still accepted as a
    migration fallback.
    """
    cfg = DEFAULT_CONFIG.copy()

    configured_path = _config_path_from_env()
    if configured_path is not None:
        config_path = configured_path
        loaded = (
            _load_legacy_json_config(config_path)
            if config_path.suffix.lower() == ".json"
            else _load_python_config(config_path)
        )
    else:
        config_path = _default_config_path()
        if config_path.exists():
            loaded = _load_python_config(config_path)
        else:
            legacy_path = _legacy_config_path()
            if not legacy_path.exists():
                if require_required_keys:
                    raise ConfigError(f"Missing config file: {config_path}")

                validate_config(cfg, require_required_keys=False)
                return cfg
            loaded = _load_legacy_json_config(legacy_path)

    loaded = _merge_room_plugin_default_config(cfg, loaded)
    cfg.update(loaded)
    validate_config(cfg, require_required_keys=require_required_keys)
    return cfg
