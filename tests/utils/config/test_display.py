import importlib

from .helpers import config_mod


def test_config_display_sections_follow_sample_order_and_names():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "nick": "EnvsBot",
        "owner": "owner@example.org",
        "prefix": ",",
        "db": "bot.db",
        "urlcheck_wait_seconds": 120,
        "backup_dir": "data/backups",
        "backup_keep": 15,
        "backup_on_start": True,
        "ducks": {"spawn_chance": 20},
        "room_plugin_defaults": {"pin": True, "xkcd": False},
    }

    sections = config_mod.get_config_display_sections(cfg)

    assert sections[0] == (
        "XMPP Account",
        [
            ("JID", "bot@example.org"),
            ("PASSWORD", "secret"),
            ("NICK", "EnvsBot"),
            ("OWNER", "owner@example.org"),
        ],
    )
    assert ("Bot Runtime", [("COMMAND_PREFIX", ","), ("DB_FILE", "bot.db")]) in sections
    assert (
        "Backups",
        [
            ("BACKUP_DIR", "data/backups"),
            ("BACKUP_KEEP", 15),
            ("BACKUP_ON_START", True),
        ],
    ) in sections
    assert ("URL Check", [("URLCHECK_WAIT_SECONDS", 120)]) in sections
    assert (
        "RSS / Atom",
        [
            ("RSS_TRUSTED_MAX_FEEDS", 0),
            ("RSS_LIST_PAGE_SIZE", 25),
            ("RSS_MAX_ENTRIES_PER_POLL", 3),
            ("RSS_TEMPLATE_MAX_LENGTH", 1500),
        ],
    ) in config_mod.get_config_display_sections({
        "rss_trusted_max_feeds": 0,
        "rss_list_page_size": 25,
        "rss_max_entries_per_poll": 3,
        "rss_template_max_length": 1500,
    })
    assert (
        "Translate",
        [("TRANSLATE_FROM", "auto"), ("TRANSLATE_TO", None)],
    ) in config_mod.get_config_display_sections({
        "translate_from": "auto",
        "translate_to": None,
    })
    assert ("Duck Game", [("DUCKS", {"spawn_chance": 20})]) in sections
    assert (
        "Room Plugin Defaults",
        [("ROOM_PLUGIN_DEFAULTS", {"pin": True, "xkcd": False})],
    ) in sections


def test_config_display_sections_put_unknown_values_in_other():
    cfg = {"prefix": ",", "custom_feature": True}

    sections = config_mod.get_config_display_sections(cfg)

    assert sections[-1] == ("Other", [("CUSTOM_FEATURE", True)])


def test_config_sample_keys_are_mapped_and_grouped_for_operator_commands():
    sample = importlib.import_module("config_sample")
    sample_keys = {
        name
        for name in vars(sample)
        if name.isupper() and not name.startswith("_")
    }
    displayed_keys = {
        key
        for _title, keys in config_mod.CONFIG_DISPLAY_SECTIONS
        for key in keys
    }

    assert sample_keys <= set(config_mod.PYTHON_CONFIG_KEY_MAP)
    assert sample_keys <= displayed_keys
    normalized_sample_keys = {
        config_mod.PYTHON_CONFIG_KEY_MAP[key]
        for key in sample_keys
    }
    assert normalized_sample_keys <= (
        set(config_mod.REQUIRED_CONFIG_KEYS)
        | set(config_mod.OPTIONAL_CONFIG_TYPES)
    )


def test_get_config_diff_sections_groups_differences_by_sample_sections():
    current = config_mod.DEFAULT_CONFIG.copy()
    current.update({
        "jid": "bot@example.org",
        "prefix": "!",
        "ducks": {"spawn_chance": 10, "max_messages": 500},
        "idlerpg": {
            "topic_custom_text": "Welcome to IdleRPG",
            "export_enabled": True,
            "nested": {"enabled": False, "unchanged": 1},
        },
        "room_plugin_defaults": {"pin": False, "xkcd": False},
    })
    defaults = config_mod.DEFAULT_CONFIG.copy()
    defaults.update({
        "jid": "envsbot@domain.tld",
        "prefix": ",",
        "ducks": {"spawn_chance": 20, "max_messages": 500},
        "idlerpg": {
            "topic_custom_text": "",
            "export_enabled": True,
            "nested": {"enabled": True, "unchanged": 1},
        },
        "room_plugin_defaults": {"pin": True, "xkcd": False},
    })

    sections = config_mod.get_config_diff_sections(current, defaults)

    by_title = {title: entries for title, entries in sections}
    assert ("JID", "bot@example.org", "envsbot@domain.tld") in by_title["XMPP Account"]
    assert ("COMMAND_PREFIX", "!", ",") in by_title["Bot Runtime"]
    assert ("DUCKS.spawn_chance", 10, 20) in by_title["Duck Game"]
    assert all(entry[0] != "DUCKS.max_messages" for entry in by_title["Duck Game"])
    assert (
        "IDLERPG.topic_custom_text",
        "Welcome to IdleRPG",
        "",
    ) in by_title["IdleRPG"]
    assert ("IDLERPG.nested.enabled", False, True) in by_title["IdleRPG"]
    assert all(entry[0] != "IDLERPG.export_enabled" for entry in by_title["IdleRPG"])
    assert all(entry[0] != "IDLERPG.nested.unchanged" for entry in by_title["IdleRPG"])
    assert (
        "ROOM_PLUGIN_DEFAULTS.pin",
        False,
        True,
    ) in by_title["Room Plugin Defaults"]


def test_get_config_diff_sections_returns_empty_for_matching_defaults():
    cfg = config_mod.DEFAULT_CONFIG.copy()

    assert config_mod.get_config_diff_sections(cfg, cfg.copy()) == []
