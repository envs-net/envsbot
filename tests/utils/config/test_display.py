from .helpers import *  # noqa: F401,F403


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
    assert ("Duck Game", [("DUCKS", {"spawn_chance": 20})]) in sections
    assert (
        "Room Plugin Defaults",
        [("ROOM_PLUGIN_DEFAULTS", {"pin": True, "xkcd": False})],
    ) in sections


def test_config_display_sections_put_unknown_values_in_other():
    cfg = {"prefix": ",", "custom_feature": True}

    sections = config_mod.get_config_display_sections(cfg)

    assert sections[-1] == ("Other", [("CUSTOM_FEATURE", True)])


def test_get_config_diff_sections_groups_differences_by_sample_sections():
    current = config_mod.DEFAULT_CONFIG.copy()
    current.update({
        "jid": "bot@example.org",
        "prefix": "!",
        "ducks": {"spawn_chance": 10, "max_messages": 500},
        "room_plugin_defaults": {"pin": False, "xkcd": False},
    })
    defaults = config_mod.DEFAULT_CONFIG.copy()
    defaults.update({
        "jid": "envsbot@domain.tld",
        "prefix": ",",
        "ducks": {"spawn_chance": 20, "max_messages": 500},
        "room_plugin_defaults": {"pin": True, "xkcd": False},
    })

    sections = config_mod.get_config_diff_sections(current, defaults)

    by_title = {title: entries for title, entries in sections}
    assert ("JID", "bot@example.org", "envsbot@domain.tld") in by_title["XMPP Account"]
    assert ("COMMAND_PREFIX", "!", ",") in by_title["Bot Runtime"]
    assert ("DUCKS.spawn_chance", 10, 20) in by_title["Duck Game"]
    assert all(entry[0] != "DUCKS.max_messages" for entry in by_title["Duck Game"])
    assert (
        "ROOM_PLUGIN_DEFAULTS.pin",
        False,
        True,
    ) in by_title["Room Plugin Defaults"]


def test_get_config_diff_sections_returns_empty_for_matching_defaults():
    cfg = config_mod.DEFAULT_CONFIG.copy()

    assert config_mod.get_config_diff_sections(cfg, cfg.copy()) == []
