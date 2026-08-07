from .helpers import (
    config_mod,
    logging,
)


def test_setup_logging_creates_log_dir_and_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "config", {"loglevel": "WARNING"})

    log_dir = tmp_path / "logs"
    log_file = log_dir / "envsbot.log"

    if log_dir.exists():
        for f in log_dir.iterdir():
            f.unlink()
        log_dir.rmdir()

    config_mod.setup_logging(log_dir=log_dir)

    assert log_dir.is_dir()
    assert log_file.exists()

    logger = logging.getLogger()
    assert any(
        h.level == logging.WARNING or h.level == logging.NOTSET
        for h in logger.handlers
    )


def test_setup_logging_uses_configured_log_dir(tmp_path, monkeypatch):
    log_dir = tmp_path / "configured-logs"
    monkeypatch.setattr(
        config_mod,
        "config",
        {"loglevel": "INFO", "log_dir": str(log_dir)},
    )

    config_mod.setup_logging()

    assert (log_dir / "envsbot.log").is_file()
