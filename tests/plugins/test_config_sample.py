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
    assert sample.ALLOW_PRIVATE_FETCH_URLS is False
    assert sample.RSS_FETCH_TIMEOUT_SECONDS == sample.HTTP_TIMEOUT_SECONDS
    assert sample.RSS_MAX_REDIRECTS > 0
    assert sample.RSS_MAX_READ_BYTES > 0
    assert sample.RSS_MAX_ENTRIES_PER_POLL == 10
    assert sample.DUCKS["min_messages"] < sample.DUCKS["max_messages"]
    assert sample.PIN_PAGE_SIZE > 0
    assert sample.IDLERPG["tick_seconds"] > 0
    assert sample.IDLERPG["rp_base"] > 0
    assert sample.TRANSLATE_TIMEOUT_SECONDS > 0
    assert sample.TRANSLATE_MAX_INPUT_LENGTH > 0
    assert sample.TRANSLATE_MAX_OUTPUT_LENGTH > 0
    assert sample.TRANSLATE_MAX_RESPONSE_BYTES > 0
    assert sample.TRANSLATE_RECENT_CACHE_SIZE > 0
    assert sample.XKCD_CHECK_INTERVAL > 0
    assert sample.ROOM_PLUGIN_DEFAULTS == {
        "birthday_notify": False,
        "dice": True,
        "ducks": False,
        "help": False,
        "information": True,
        "karma": False,
        "idlerpg": False,
        "pin": True,
        "poll": False,
        "presence": True,
        "reminder": True,
        "sed": True,
        "tell": True,
        "tools": True,
        "translate": True,
        "urlcheck": True,
        "vcard": True,
        "weather": True,
        "xkcd": False,
        "xmpp": True,
    }
