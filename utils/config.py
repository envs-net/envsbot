import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# project root
BASE_DIR = Path(__file__).resolve().parents[1]

DEFAULT_CONFIG = {
    "prefix": ",",
    "loglevel": "INFO",
}


def load_config():
    cfg = DEFAULT_CONFIG.copy()

    config_path = BASE_DIR / "config.json"

    if config_path.exists():
        try:
            with open(config_path) as f:
                cfg.update(json.load(f))
        except Exception as e:
            print(f"🟡️ Failed to load config.json: {e}")

    return cfg


# global config object (backwards compatible)
config = load_config()


def setup_logging():
    """
    Initialize the logging system.

    Parameters
    ----------
    debug : bool
        Enable debug logging if True.
    """
    log_level = getattr(logging, config.get("loglevel", "INFO").upper(),
                        logging.INFO)
    log_dir = Path("logs")
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
        maxBytes=2_000_000,   # 2 MB
        backupCount=5
    )

    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    logging.basicConfig(
        level=log_level,
        handlers=[console, file_handler]
    )
