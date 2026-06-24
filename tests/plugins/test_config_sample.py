from __future__ import annotations

import importlib


def test_config_sample_imports_and_exposes_safe_defaults():
    sample = importlib.import_module("config_sample")

    assert sample.JID == "envsbot@domain.tld"
    assert sample.PASSWORD == "yourpassword"
    assert sample.NICK == "EnvsBot"
    assert sample.RESOURCE == "service"
    assert sample.CONNECT_HOST is None
    assert sample.CONNECT_PORT == 5222
    assert sample.CONNECT_DIRECT_TLS is False
    assert sample.COMMAND_PREFIX == ","
    assert sample.TIMEZONE == "Europe/Berlin"
    assert sample.BACKUP_ON_START is True
    assert sample.DUCKS["min_messages"] < sample.DUCKS["max_messages"]
    assert sample.PIN_PAGE_SIZE > 0
    assert sample.XKCD_CHECK_INTERVAL > 0
