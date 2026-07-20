from .helpers import (
    config_mod,
    json,
    pytest,
)
from utils.config import loader as config_loader
from utils.config import display as config_display


def test_load_config_returns_defaults_when_missing_and_not_strict(tmp_path,
                                                                  monkeypatch):
    monkeypatch.setattr(config_loader, "BASE_DIR", tmp_path)

    result = config_mod.load_config()

    assert result == config_mod.DEFAULT_CONFIG


def test_load_config_missing_file_strict_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(config_loader, "BASE_DIR", tmp_path)

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

    monkeypatch.setattr(config_loader, "BASE_DIR", tmp_path)

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

    monkeypatch.setattr(config_loader, "BASE_DIR", tmp_path)

    result = config_mod.load_config()

    assert result["prefix"] == ";"
    assert result["loglevel"] == "INFO"
    assert result["db"] == "bot.db"


def test_load_config_bad_python_raises(tmp_path, monkeypatch):
    (tmp_path / "config.py").write_text("JID = \"broken\" +\n")

    monkeypatch.setattr(config_loader, "BASE_DIR", tmp_path)

    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.load_config()

    msg = str(exc.value)
    assert "Failed to parse config.py" in msg
    assert "line" in msg
    assert "column" in msg


def test_load_config_legacy_json_top_level_must_be_object(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text(json.dumps(["not", "an", "object"]))

    monkeypatch.setattr(config_loader, "BASE_DIR", tmp_path)

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
    monkeypatch.setattr(config_loader, "BASE_DIR", tmp_path)

    result = config_mod.load_config(require_required_keys=True)

    assert result["jid"] == "bot@example.org"
    assert result["prefix"] == ";"


def test_load_config_env_override_accepts_python_file(tmp_path, monkeypatch):
    custom_path = tmp_path / "custom_config.py"
    custom_path.write_text('COMMAND_PREFIX = "?"\n')
    monkeypatch.setenv("ENVSBOT_CONFIG", str(custom_path))
    monkeypatch.setattr(config_loader, "BASE_DIR", tmp_path)

    result = config_mod.load_config()

    assert result["prefix"] == "?"


def test_exit_on_config_error_exits(capsys):
    with pytest.raises(SystemExit) as exc:
        config_mod.exit_on_config_error(
            config_mod.ConfigError("broken config"))

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "[CONFIG] broken config" in err


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
    monkeypatch.setattr(config_loader, "BASE_DIR", tmp_path)

    result = config_mod.load_config(require_required_keys=True)

    assert result["resource"] == "service"
    assert result["host"] == "xmpp.example.org"
    assert result["port"] == 5223
    assert result["direct_tls"] is True


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
            'MESSAGE_CACHE_SIZE = 40',
            'POLL_MAX_OPTIONS = 7',
            'KARMA_DELAY_SECONDS = 10',
            'TELL_DELIVERY_DELAY_SECONDS = 2',
            'XKCD_INDEX_REQUEST_DELAY_SECONDS = 0.2',
            'ROOM_PLUGIN_DEFAULTS = {"pin": False, "xkcd": True}',
            'BACKUP_DIR = "data/backups"',
            'BACKUP_KEEP = 8',
            'BACKUP_ON_START = False',
        ])
    )
    monkeypatch.setattr(config_loader, "BASE_DIR", tmp_path)

    result = config_mod.load_config(require_required_keys=True)

    assert result["http_timeout_seconds"] == 12
    assert result["xmpp_query_timeout_seconds"] == 9
    assert result["urlcheck_wait_seconds"] == 30
    assert result["rss_max_entries_per_poll"] == 3
    assert result["rss_similarity_threshold"] == 0.75
    assert result["birthday_cache_ttl_seconds"] == 3600
    assert result["message_cache_size"] == 40
    assert result["poll_max_options"] == 7
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
    monkeypatch.setattr(config_loader, "BASE_DIR", tmp_path)

    result = config_mod.load_config()

    assert result["room_plugin_defaults"]["pin"] is False
    assert result["room_plugin_defaults"]["xkcd"] is False
    assert result["room_plugin_defaults"]["dice"] is True


def test_sample_config_path_and_load_default_config_for_diff(tmp_path, monkeypatch):
    sample = tmp_path / "config_sample.py"
    sample.write_text('COMMAND_PREFIX = "!"\nURLCHECK_WAIT_SECONDS = 7\n')
    monkeypatch.setattr(config_loader, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config_display, "BASE_DIR", tmp_path)

    assert config_mod._sample_config_path() == sample
    defaults = config_mod.load_default_config_for_diff()

    assert defaults["prefix"] == "!"
    assert defaults["urlcheck_wait_seconds"] == 7


def test_load_default_config_for_diff_without_sample(tmp_path, monkeypatch):
    monkeypatch.setattr(config_loader, "BASE_DIR", tmp_path)

    defaults = config_mod.load_default_config_for_diff()

    assert defaults["prefix"] == config_mod.DEFAULT_CONFIG["prefix"]
