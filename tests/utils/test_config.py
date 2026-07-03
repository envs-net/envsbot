import json
import logging

import pytest

import utils.config as config_mod


def test_load_config_returns_defaults_when_missing_and_not_strict(tmp_path,
                                                                  monkeypatch):
    monkeypatch.setattr(config_mod, "BASE_DIR", tmp_path)

    result = config_mod.load_config()

    assert result == config_mod.DEFAULT_CONFIG


def test_load_config_missing_file_strict_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "BASE_DIR", tmp_path)

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.load_config(require_required_keys=True)

    assert "Missing config file" in str(exc.value)


def test_load_config_loads_python(tmp_path, monkeypatch):
    (tmp_path / "config.py").write_text(
        "\n".join([
            'JID = "bot@example.org"',
            'PASSWORD = "secret"',
            'OWNER = "owner@example.org"',
            'NICK = "envsbot"',
            'RESOURCE = "service"',
            'COMMAND_PREFIX = ";"',
            'LOG_LEVEL = "DEBUG"',
            'CUSTOM = "extra"',
        ])
    )

    monkeypatch.setattr(config_mod, "BASE_DIR", tmp_path)

    result = config_mod.load_config(require_required_keys=True)

    assert result["jid"] == "bot@example.org"
    assert result["password"] == "secret"
    assert result["owner"] == "owner@example.org"
    assert result["nick"] == "envsbot"
    assert result["resource"] == "service"
    assert result["prefix"] == ";"
    assert result["loglevel"] == "DEBUG"
    assert result["custom"] == "extra"


def test_load_config_with_partial_override_when_not_strict(tmp_path,
                                                           monkeypatch):
    (tmp_path / "config.py").write_text('COMMAND_PREFIX = ";"\n')

    monkeypatch.setattr(config_mod, "BASE_DIR", tmp_path)

    result = config_mod.load_config()

    assert result["prefix"] == ";"
    assert result["loglevel"] == "INFO"
    assert result["db"] == "bot.db"


def test_load_config_bad_python_raises(tmp_path, monkeypatch):
    (tmp_path / "config.py").write_text("JID = \"broken\" +\n")

    monkeypatch.setattr(config_mod, "BASE_DIR", tmp_path)

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.load_config()

    msg = str(exc.value)
    assert "Failed to parse config.py" in msg
    assert "line" in msg
    assert "column" in msg


def test_load_config_legacy_json_top_level_must_be_object(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text(json.dumps(["not", "an", "object"]))

    monkeypatch.setattr(config_mod, "BASE_DIR", tmp_path)

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.load_config()

    assert "must contain a JSON object" in str(exc.value)




def test_load_config_legacy_json_fallback(tmp_path, monkeypatch):
    data = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "prefix": ";",
    }
    (tmp_path / "config.json").write_text(json.dumps(data))
    monkeypatch.setattr(config_mod, "BASE_DIR", tmp_path)

    result = config_mod.load_config(require_required_keys=True)

    assert result["jid"] == "bot@example.org"
    assert result["prefix"] == ";"


def test_load_config_env_override_accepts_python_file(tmp_path, monkeypatch):
    custom_path = tmp_path / "custom_config.py"
    custom_path.write_text('COMMAND_PREFIX = "?"\n')
    monkeypatch.setenv("ENVSBOT_CONFIG", str(custom_path))
    monkeypatch.setattr(config_mod, "BASE_DIR", tmp_path)

    result = config_mod.load_config()

    assert result["prefix"] == "?"

def test_validate_startup_config_requires_runtime_keys():
    cfg = {
        "prefix": ",",
        "loglevel": "INFO",
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_startup_config(cfg)

    msg = str(exc.value)
    assert "Missing required key: jid" in msg
    assert "Missing required key: password" in msg
    assert "Missing required key: owner" in msg
    assert "Missing required key: nick" in msg


def test_validate_startup_config_accepts_valid_config():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "prefix": ",",
        "loglevel": "INFO",
        "db": "bot.db",
    }

    config_mod.validate_startup_config(cfg)


@pytest.mark.parametrize(
    "key,value,expected",
    [
        ("jid", "", "jid: must not be empty"),
        ("password", "", "password: must not be empty"),
        ("owner", "", "owner: must not be empty"),
        ("nick", "", "nick: must not be empty"),
    ],
)
def test_validate_startup_config_rejects_empty_required_strings(key, value,
                                                                expected):
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
    }
    cfg[key] = value

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_startup_config(cfg)

    assert expected in str(exc.value)


def test_validate_config_rejects_invalid_loglevel():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "loglevel": "VERBOSE",
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(cfg, require_required_keys=True)

    assert "loglevel: must be one of" in str(exc.value)


def test_validate_config_rejects_invalid_avatar_type():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "avatar_type": "image/gif",
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(cfg, require_required_keys=True)

    assert "avatar_type: must be image/png or image/jpeg" in str(exc.value)


def test_validate_config_rejects_invalid_admins_type():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "admins": "admin@example.org",
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(cfg, require_required_keys=True)

    assert "admins: expected list" in str(exc.value)


def test_validate_config_rejects_invalid_admin_entry():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "admins": ["admin@example.org", ""],
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(cfg, require_required_keys=True)

    assert "admins[1]: must be a non-empty string" in str(exc.value)


def test_validate_config_rejects_wrong_optional_types():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "rss_global_query_interval": "1200",
        "max_new_feed_entries": "5",
        "rss_max_entries_per_poll": "10",
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(cfg, require_required_keys=True)

    msg = str(exc.value)
    assert "rss_global_query_interval: expected int" in msg
    assert "max_new_feed_entries: expected int" in msg
    assert "rss_max_entries_per_poll: expected int" in msg


def test_exit_on_config_error_exits(capsys):
    with pytest.raises(SystemExit) as exc:
        config_mod.exit_on_config_error(
            config_mod.ConfigError("broken config"))

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "[CONFIG] broken config" in err


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


def test_validate_startup_config_rejects_invalid_bot_jid():
    cfg = {
        "jid": "not-a-jid",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_startup_config(cfg)

    assert "jid:" in str(exc.value)


def test_validate_startup_config_rejects_invalid_owner_jid():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "not-a-jid",
        "nick": "envsbot",
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_startup_config(cfg)

    assert "owner:" in str(exc.value)


def test_validate_config_rejects_invalid_admin_jid():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "admins": ["admin@example.org", "not-a-jid"],
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(cfg, require_required_keys=True)

    assert "admins[1]:" in str(exc.value)


def test_validate_config_accepts_connection_options():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "resource": "service",
        "host": "xmpp.example.org",
        "port": 5223,
        "direct_tls": True,
    }

    config_mod.validate_config(cfg, require_required_keys=True)




def test_load_config_maps_resource_and_direct_tls(tmp_path, monkeypatch):
    (tmp_path / "config.py").write_text(
        "\n".join([
            'JID = "bot@example.org"',
            'PASSWORD = "secret"',
            'OWNER = "owner@example.org"',
            'NICK = "envsbot"',
            'RESOURCE = "service"',
            'CONNECT_HOST = "xmpp.example.org"',
            'CONNECT_PORT = 5223',
            'CONNECT_DIRECT_TLS = True',
        ])
    )
    monkeypatch.setattr(config_mod, "BASE_DIR", tmp_path)

    result = config_mod.load_config(require_required_keys=True)

    assert result["resource"] == "service"
    assert result["host"] == "xmpp.example.org"
    assert result["port"] == 5223
    assert result["direct_tls"] is True


def test_validate_config_rejects_invalid_resource_and_direct_tls_types():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "resource": 123,
        "direct_tls": "yes",
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(cfg, require_required_keys=True)

    msg = str(exc.value)
    assert "resource: expected string" in msg
    assert "direct_tls: expected bool" in msg


def test_validate_config_rejects_invalid_host_type():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "host": 123,
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(cfg, require_required_keys=True)

    assert "host: expected string" in str(exc.value)


def test_validate_config_rejects_invalid_port_type():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "port": "5222",
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(cfg, require_required_keys=True)

    assert "port: expected int" in str(exc.value)


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_validate_config_rejects_invalid_port_range(port):
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "port": port,
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(cfg, require_required_keys=True)

    assert "port: must be between 1 and 65535" in str(exc.value)


def test_validate_config_rejects_invalid_timezone():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "timezone": "Mars/Olympus_Mons",
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(cfg, require_required_keys=True)

    assert "timezone: must be a valid IANA timezone" in str(exc.value)


def test_validate_config_accepts_valid_timezone():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "timezone": "Europe/Berlin",
    }

    config_mod.validate_config(cfg, require_required_keys=True)


def test_validate_config_rejects_non_positive_rss_interval():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "rss_global_query_interval": 0,
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(cfg, require_required_keys=True)

    assert "rss_global_query_interval: must be greater than 0" in str(
        exc.value)


def test_validate_config_rejects_negative_max_new_feed_entries():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "max_new_feed_entries": -1,
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(cfg, require_required_keys=True)

    assert "max_new_feed_entries: must be 0 or greater" in str(exc.value)


def test_validate_config_accepts_zero_max_new_feed_entries():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "max_new_feed_entries": 0,
    }

    config_mod.validate_config(cfg, require_required_keys=True)


def test_validate_config_rejects_non_positive_rss_max_entries_per_poll():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "rss_max_entries_per_poll": 0,
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(cfg, require_required_keys=True)

    assert "rss_max_entries_per_poll: must be greater than 0" in str(exc.value)


def test_collect_config_warnings_for_missing_avatar(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "BASE_DIR", tmp_path)

    cfg = {
        "avatar": "missing.png",
        "avatar_type": "image/png",
    }

    warnings = config_mod.collect_config_warnings(cfg)

    assert any("avatar: file does not exist"
               in warning for warning in warnings)


def test_collect_config_warnings_for_avatar_extension_mismatch():
    cfg = {
        "avatar": "avatar.jpg",
        "avatar_type": "image/png",
    }

    warnings = config_mod.collect_config_warnings(cfg)

    assert any(
        "file extension does not match avatar_type image/png"
        in warning for warning in warnings)


def test_validate_startup_config_prints_avatar_warnings(tmp_path, monkeypatch,
                                                        capsys):
    monkeypatch.setattr(config_mod, "BASE_DIR", tmp_path)

    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "avatar": "missing.png",
        "avatar_type": "image/png",
    }

    config_mod.validate_startup_config(cfg)

    captured = capsys.readouterr()
    assert "[CONFIG] Warning: avatar: file does not exist" in captured.err


def test_validate_config_accepts_empty_version_check_notify_jid():
    config_mod.validate_config({"version_check_notify_jid": ""})


def test_validate_config_rejects_too_short_version_check_interval():
    with pytest.raises(config_mod.ConfigError, match="version_check_interval"):
        config_mod.validate_config({"version_check_interval": 30})


def test_load_config_maps_operator_tuning_keys(tmp_path, monkeypatch):
    (tmp_path / "config.py").write_text(
        "\n".join([
            'JID = "bot@example.org"',
            'PASSWORD = "secret"',
            'OWNER = "owner@example.org"',
            'NICK = "envsbot"',
            'HTTP_TIMEOUT_SECONDS = 12',
            'XMPP_QUERY_TIMEOUT_SECONDS = 9',
            'URLCHECK_WAIT_SECONDS = 30',
            'RSS_MAX_ENTRIES_PER_POLL = 3',
            'RSS_SIMILARITY_THRESHOLD = 0.75',
            'BIRTHDAY_CACHE_TTL_SECONDS = 3600',
            'SED_CACHE_SIZE = 25',
            'POLL_MAX_OPTIONS = 7',
            'PIN_RECENT_CACHE_SIZE = 40',
            'KARMA_DELAY_SECONDS = 10',
            'TELL_DELIVERY_DELAY_SECONDS = 2',
            'XKCD_INDEX_REQUEST_DELAY_SECONDS = 0.2',
            'ROOM_PLUGIN_DEFAULTS = {"pin": False, "xkcd": True}',
            'BACKUP_DIR = "data/backups"',
            'BACKUP_KEEP = 8',
            'BACKUP_ON_START = False',
        ])
    )
    monkeypatch.setattr(config_mod, "BASE_DIR", tmp_path)

    result = config_mod.load_config(require_required_keys=True)

    assert result["http_timeout_seconds"] == 12
    assert result["xmpp_query_timeout_seconds"] == 9
    assert result["urlcheck_wait_seconds"] == 30
    assert result["rss_max_entries_per_poll"] == 3
    assert result["rss_similarity_threshold"] == 0.75
    assert result["birthday_cache_ttl_seconds"] == 3600
    assert result["sed_cache_size"] == 25
    assert result["poll_max_options"] == 7
    assert result["pin_recent_cache_size"] == 40
    assert result["karma_delay_seconds"] == 10
    assert result["tell_delivery_delay_seconds"] == 2
    assert result["xkcd_index_request_delay_seconds"] == 0.2
    assert result["room_plugin_defaults"]["pin"] is False
    assert result["room_plugin_defaults"]["xkcd"] is True
    assert result["room_plugin_defaults"]["dice"] is True
    assert result["backup_dir"] == "data/backups"
    assert result["backup_keep"] == 8
    assert result["backup_on_start"] is False


def test_load_config_merges_partial_room_plugin_defaults(tmp_path, monkeypatch):
    (tmp_path / "config.py").write_text(
        "\n".join([
            'ROOM_PLUGIN_DEFAULTS = {"pin": False}',
        ])
    )
    monkeypatch.setattr(config_mod, "BASE_DIR", tmp_path)

    result = config_mod.load_config()

    assert result["room_plugin_defaults"]["pin"] is False
    assert result["room_plugin_defaults"]["xkcd"] is False
    assert result["room_plugin_defaults"]["dice"] is True

def test_validate_config_rejects_invalid_plugin_tuning_values():
    cfg = {
        "http_timeout_seconds": 0,
        "urlcheck_max_redirects": 0,
        "rss_max_entries_per_poll": 0,
        "rss_similarity_threshold": 1.5,
        "sed_cache_size": 0,
        "poll_max_options": 0,
        "pin_recent_cache_size": 0,
        "karma_delay_seconds": 0,
        "tell_delivery_delay_seconds": 0,
        "xkcd_index_request_delay_seconds": 0,
        "backup_keep": 0,
        "room_plugin_defaults": {"pin": "yes"},
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(cfg)

    msg = str(exc.value)
    assert "http_timeout_seconds: must be greater than 0" in msg
    assert "urlcheck_max_redirects: must be greater than 0" in msg
    assert "rss_max_entries_per_poll: must be greater than 0" in msg
    assert "rss_similarity_threshold: must be greater than 0 and at most 1" in msg
    assert "sed_cache_size: must be greater than 0" in msg
    assert "poll_max_options: must be greater than 0" in msg
    assert "pin_recent_cache_size: must be greater than 0" in msg
    assert "karma_delay_seconds: must be greater than 0" in msg
    assert "tell_delivery_delay_seconds: must be greater than 0" in msg
    assert "xkcd_index_request_delay_seconds: must be greater than 0" in msg
    assert "backup_keep: must be greater than 0" in msg
    assert "room_plugin_defaults.pin: expected bool, got str" in msg


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


def test_sample_config_path_and_load_default_config_for_diff(tmp_path, monkeypatch):
    sample = tmp_path / "config_sample.py"
    sample.write_text('COMMAND_PREFIX = "!"\nURLCHECK_WAIT_SECONDS = 7\n')
    monkeypatch.setattr(config_mod, "BASE_DIR", tmp_path)

    assert config_mod._sample_config_path() == sample
    defaults = config_mod.load_default_config_for_diff()

    assert defaults["prefix"] == "!"
    assert defaults["urlcheck_wait_seconds"] == 7


def test_load_default_config_for_diff_without_sample(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "BASE_DIR", tmp_path)

    defaults = config_mod.load_default_config_for_diff()

    assert defaults["prefix"] == config_mod.DEFAULT_CONFIG["prefix"]
