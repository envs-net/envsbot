from __future__ import annotations

import importlib
import runpy
from pathlib import Path

from utils.config.spec import (
    CONFIG_DISPLAY_SECTIONS,
    CONFIG_FIELDS,
    NESTED_CONFIG_FIELDS,
    nested_config_defaults,
)


def _checkout_root(path: Path) -> Path:
    """Return the real checkout when tests run from mutmut's copy."""
    resolved = path.resolve()
    search_from = resolved if resolved.is_dir() else resolved.parent
    for candidate in (search_from, *search_from.parents):
        if (
            (candidate / "pyproject.toml").is_file()
            and (candidate / "scripts" / "generate_config_sample.py").is_file()
        ):
            return candidate
    return search_from


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
    assert sample.RSS_STARTUP_STAGGER_SECONDS == 2.0
    assert sample.RSS_MAX_REDIRECTS > 0
    assert sample.RSS_MAX_READ_BYTES > 0
    assert sample.RSS_TRUSTED_MAX_FEEDS == 10
    assert sample.RSS_LIST_PAGE_SIZE == 10
    assert sample.RSS_MAX_ENTRIES_PER_POLL == 10
    assert sample.RSS_TEMPLATE_MAX_LENGTH == 1000
    assert sample.DUCKS["min_messages"] < sample.DUCKS["max_messages"]
    assert sample.PIN_PAGE_SIZE > 0
    assert sample.IDLERPG["tick_seconds"] > 0
    assert sample.IDLERPG["export_interval_seconds"] == 300
    assert sample.IDLERPG["rp_base"] > 0
    assert sample.TRANSLATE_FROM == "auto"
    assert sample.TRANSLATE_TO is None
    assert sample.TRANSLATE_TIMEOUT_SECONDS > 0
    assert sample.TRANSLATE_MAX_INPUT_LENGTH > 0
    assert sample.TRANSLATE_MAX_OUTPUT_LENGTH > 0
    assert sample.TRANSLATE_MAX_RESPONSE_BYTES > 0
    assert sample.TRANSLATE_RATE_LIMIT_INITIAL_SECONDS == 60
    assert sample.TRANSLATE_RATE_LIMIT_BACKOFF_MULTIPLIER == 2.0
    assert sample.TRANSLATE_RATE_LIMIT_MAX_SECONDS == 900
    assert sample.MESSAGE_CACHE_SIZE > 0
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


def test_config_sample_matches_declarative_schema_exactly():
    sample = importlib.import_module("config_sample")
    schema_python_keys = {field.python_key for field in CONFIG_FIELDS.values()}
    sample_keys = {
        name
        for name in vars(sample)
        if name.isupper() and not name.startswith("_")
    }

    assert sample_keys == schema_python_keys


def test_config_display_sections_cover_declarative_schema_exactly_once():
    displayed = [key for _title, keys in CONFIG_DISPLAY_SECTIONS for key in keys]
    schema_python_keys = {field.python_key for field in CONFIG_FIELDS.values()}

    assert len(displayed) == len(set(displayed))
    assert set(displayed) == schema_python_keys


def test_config_display_sections_keep_operator_facing_order():
    assert [title for title, _keys in CONFIG_DISPLAY_SECTIONS] == [
        "XMPP Account",
        "Connection",
        "Bot Runtime",
        "Backups",
        "Persistent Outbox",
        "Immediate Admin Alerts",
        "Daily Admin Report",
        "Message Cache",
        "User Tracking",
        "Command Rate Limits",
        "HTTP Defaults",
        "vCard / Avatar",
        "Release Update Check",
        "Room Invites",
        "Room Plugin Defaults",
        "URL Check",
        "RSS / Atom",
        "Wikipedia",
        "Birthday Notify",
        "Reminders",
        "Sed Corrections",
        "Polls",
        "Pins",
        "Translate",
        "Karma / Tell",
        "XKCD",
        "Duck Game",
        "IdleRPG",
    ]


def test_new_operational_defaults_are_declared():
    fields = CONFIG_FIELDS
    assert fields["http_max_redirects"].python_key == "HTTP_MAX_REDIRECTS"
    assert fields["http_max_read_bytes"].python_key == "HTTP_MAX_READ_BYTES"
    assert fields["task_stale_after_seconds"].python_key == "TASK_STALE_AFTER_SECONDS"
    assert fields["outbox_max_pending"].minimum_exclusive is True
    assert fields["admin_report_mode"].choices == ("daily", "problems_only")


def test_declarative_schema_has_operator_metadata_for_every_field():
    assert all(field.section.strip() for field in CONFIG_FIELDS.values())
    assert all(field.description.strip() for field in CONFIG_FIELDS.values())
    assert CONFIG_FIELDS["password"].sensitive is True
    assert CONFIG_FIELDS["youtube_api_key"].sensitive is True


def test_nested_config_schema_has_operator_metadata_and_defaults():
    for group, fields in NESTED_CONFIG_FIELDS.items():
        assert fields
        assert all(field.description.strip() for field in fields.values())
        assert CONFIG_FIELDS[group].sample == nested_config_defaults(group)

    assert NESTED_CONFIG_FIELDS["idlerpg"]["export_full_season_events"].runtime_keys == (
        "EXPORT_FULL_SEASON_EVENTS",
    )


def test_checkout_root_uses_repository_outside_mutmut_copy(tmp_path):
    checkout = tmp_path / "checkout"
    script = checkout / "scripts" / "generate_config_sample.py"
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")
    (checkout / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    mutant_test = checkout / "mutants" / "tests" / "plugins" / "test_config_sample.py"
    mutant_test.parent.mkdir(parents=True)
    mutant_test.write_text("", encoding="utf-8")

    assert _checkout_root(mutant_test) == checkout
    assert _checkout_root(script) == checkout


def test_config_sample_is_generated_from_schema_exactly():
    root = _checkout_root(Path(__file__))
    namespace = runpy.run_path(str(root / "scripts" / "generate_config_sample.py"))
    rendered = namespace["render_config_sample"]()

    assert (root / "config_sample.py").read_text(encoding="utf-8") == rendered
