from .helpers import (
    config_mod,
    pytest,
)
from utils.config import validation as config_validation


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
        "rss_trusted_max_feeds": "10",
        "rss_list_page_size": "10",
        "rss_max_entries_per_poll": "10",
        "rss_template_max_length": "1000",
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(cfg, require_required_keys=True)

    msg = str(exc.value)
    assert "rss_global_query_interval: expected int" in msg
    assert "max_new_feed_entries: expected int" in msg
    assert "rss_trusted_max_feeds: expected int" in msg
    assert "rss_list_page_size: expected int" in msg
    assert "rss_max_entries_per_poll: expected int" in msg
    assert "rss_template_max_length: expected int" in msg


def test_validate_config_accepts_translate_defaults_and_rejects_bad_types():
    config_mod.validate_config(
        {
            "translate_from": "auto",
            "translate_to": None,
        }
    )
    config_mod.validate_config(
        {
            "translate_from": "en",
            "translate_to": "de",
        }
    )

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config({"translate_to": 123})

    assert "translate_to: expected str" in str(exc.value)


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


def test_validate_config_rejects_bool_for_integer_options():
    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config({"port": True, "backup_keep": False})

    msg = str(exc.value)
    assert "port: expected int" in msg
    assert "backup_keep: expected int" in msg


def test_validate_config_rejects_bool_for_number_options():
    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config({"rss_similarity_threshold": True})

    assert "rss_similarity_threshold: expected int or float" in str(exc.value)


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


def test_validate_config_checks_reminder_default_timezone():
    base = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
    }

    config_mod.validate_config(
        {**base, "reminder_default_timezone": "Europe/Berlin"},
        require_required_keys=True,
    )

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(
            {**base, "reminder_default_timezone": "CEST"},
            require_required_keys=True,
        )

    assert "reminder_default_timezone: must be a valid IANA timezone" in str(exc.value)


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


def test_validate_config_checks_rss_list_template_and_trusted_limits():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "rss_trusted_max_feeds": -1,
        "rss_list_page_size": 0,
        "rss_template_max_length": 0,
        "rss_broken_error_threshold": 0,
        "rss_startup_stagger_seconds": -0.1,
    }

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(cfg, require_required_keys=True)

    message = str(exc.value)
    assert "rss_trusted_max_feeds: must be 0 or greater" in message
    assert "rss_list_page_size: must be greater than 0" in message
    assert "rss_template_max_length: must be greater than 0" in message
    assert "rss_broken_error_threshold: must be greater than 0" in message
    assert "rss_startup_stagger_seconds: must be 0 or greater" in message


def test_collect_config_warnings_for_missing_avatar(tmp_path, monkeypatch):
    monkeypatch.setattr(config_validation, "BASE_DIR", tmp_path)

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
    monkeypatch.setattr(config_validation, "BASE_DIR", tmp_path)

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


def test_validate_config_rejects_invalid_plugin_tuning_values():
    cfg = {
        "http_timeout_seconds": 0,
        "urlcheck_max_redirects": 0,
        "rss_max_entries_per_poll": 0,
        "rss_similarity_threshold": 1.5,
        "message_cache_size": 0,
        "poll_max_options": 0,
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
    assert "message_cache_size: must be greater than 0" in msg
    assert "poll_max_options: must be greater than 0" in msg
    assert "karma_delay_seconds: must be greater than 0" in msg
    assert "tell_delivery_delay_seconds: must be greater than 0" in msg
    assert "xkcd_index_request_delay_seconds: must be greater than 0" in msg
    assert "backup_keep: must be greater than 0" in msg
    assert "room_plugin_defaults.pin: expected bool, got str" in msg


def test_validate_config_accepts_default_pagination_values():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "default_pagination": "all",
    }
    config_mod.validate_config(cfg, require_required_keys=True)

    cfg["default_pagination"] = 20
    config_mod.validate_config(cfg, require_required_keys=True)


def test_validate_config_rejects_invalid_default_pagination():
    cfg = {
        "jid": "bot@example.org",
        "password": "secret",
        "owner": "owner@example.org",
        "nick": "envsbot",
        "default_pagination": 0,
    }
    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(cfg, require_required_keys=True)

    assert "default_pagination: expected 'all' or positive integer" in str(exc.value)


def test_validate_config_checks_declared_nested_settings():
    config_mod.validate_config({"idlerpg": {"event_chance": 0.25}})
    config_mod.validate_config({"idlerpg": {"export_public_base_url": ""}})

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config({"idlerpg": {"event_chance": "often"}})
    assert "idlerpg.event_chance: expected int or float" in str(exc.value)

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config({"ducks": {"count_commands": "yes"}})
    assert "ducks.count_commands: expected bool" in str(exc.value)


def test_validate_config_rejects_unknown_nested_settings():
    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config(
            {"idlerpg": {"export_full_season_eventz": True}}
        )

    assert "idlerpg.export_full_season_eventz: unknown setting" in str(exc.value)


def test_validate_config_rejects_too_short_task_stale_threshold():
    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.validate_config({"task_stale_after_seconds": 30})

    assert "task_stale_after_seconds" in str(exc.value)
