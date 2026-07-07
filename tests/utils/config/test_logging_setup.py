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
