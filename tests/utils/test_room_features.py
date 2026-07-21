import asyncio
import logging
from types import SimpleNamespace

import pytest

from utils import room_features


@pytest.fixture(autouse=True)
def clear_room_feature_caches():
    previous_store_config = room_features._FEATURE_STORE_CONFIG
    previous_defaults_provider = room_features._FEATURE_DEFAULTS_PROVIDER
    room_features.configure_room_features({}, lambda: {})
    yield
    room_features.configure_room_features(previous_store_config, previous_defaults_provider)


class DummyStore:
    def __init__(self, data=None):
        self.data = data if data is not None else {}
        self._lock = asyncio.Lock()

    async def get_global(self, key, default=None):
        return self.data.get(key, default)

    async def set_global(self, key, value):
        self.data[key] = value

    async def update_global(self, key, updater, default=None):
        async with self._lock:
            current = await self.get_global(key, default)
            value = updater(current)
            await self.set_global(key, value)
            return value


class CopyingSlowStore(DummyStore):
    async def get_global(self, key, default=None):
        value = self.data.get(key, default)
        if isinstance(value, dict):
            return dict(value)
        return value

    async def set_global(self, key, value):
        await asyncio.sleep(0)
        if isinstance(value, dict):
            self.data[key] = dict(value)
        else:
            self.data[key] = value


@pytest.mark.asyncio
async def test_copying_slow_store_copies_dicts_on_set_and_get():
    store = CopyingSlowStore()

    original = {"enabled": True}
    await store.set_global("PIN", original)
    original["enabled"] = False

    assert store.data["PIN"] == {"enabled": True}

    read_value = await store.get_global("PIN")
    read_value["enabled"] = False

    assert store.data["PIN"] == {"enabled": True}


class DummyUsers:
    def __init__(self, store):
        self.store = store

    def plugin(self, name):
        return self.store


def _bot_with_store(store):
    return SimpleNamespace(db=SimpleNamespace(users=DummyUsers(store)))


def _install_room_features_module(
    monkeypatch,
    *,
    store_config=None,
    plugin_defaults=None,
    defaults_provider=None,
):
    provider = defaults_provider or (lambda: plugin_defaults or {})
    room_features.configure_room_features(store_config or {}, provider)
    return SimpleNamespace(
        PLUGIN_STORE_CONFIG=store_config or {},
        PLUGIN_DEFAULTS=plugin_defaults or {},
        get_room_plugin_defaults=provider,
    )


def _basic_store_config(plugin="pin", key="PIN"):
    return {plugin: {"type": "dict", "key": key}}


def test_available_features_handles_missing_or_invalid_config(monkeypatch):
    _install_room_features_module(
        monkeypatch,
        store_config=None,
    )

    assert room_features.available_features() == []
    assert not room_features.is_known_feature("urlcheck")


def test_available_features_validates_store_config_shape(monkeypatch):
    _install_room_features_module(
        monkeypatch,
        store_config={
            "info": {"type": "dict", "key": "INFO_ENABLED"},
            "missing_key": {"type": "dict"},
            "empty_key_value": {"type": "dict", "key": ""},
            "bad_type": {"type": object(), "key": "BAD_ENABLED"},
            "not_a_mapping": "bad",
            42: {"type": "dict", "key": "NUMERIC_ENABLED"},
            "legacy": {"type": "list", "key": "LEGACY_ENABLED"},
        },
    )

    assert room_features.available_features() == ["information", "legacy"]
    assert room_features.is_known_feature("roominfo")


@pytest.mark.asyncio
async def test_get_room_feature_rejects_unknown_feature(monkeypatch):
    _install_room_features_module(
        monkeypatch,
        store_config={
            "information": {"type": "dict", "key": "INFO_ENABLED"},
            "pin": {"type": "dict", "key": "PIN_ENABLED"},
        },
        plugin_defaults={},
    )

    with pytest.raises(KeyError) as exc_info:
        await room_features.get_room_feature(
            _bot_with_store(DummyStore()), "room@conf", "urlcheck"
        )

    message = str(exc_info.value)
    assert "Unknown plugin feature: urlcheck" in message
    assert "Available features: information, pin" in message
    assert "available_features()" in message


@pytest.mark.asyncio
async def test_room_feature_defaults_handle_missing_defaults(monkeypatch):
    _install_room_features_module(
        monkeypatch,
        store_config={"urlcheck": {"type": "dict", "key": "enabled_rooms"}},
    )

    state = await room_features.get_room_feature(
        _bot_with_store(DummyStore()),
        "room@conf",
        "urlcheck",
    )

    assert state.name == "urlcheck"
    assert state.enabled is False
    assert state.default is False
    assert state.modified is False


@pytest.mark.asyncio
async def test_room_feature_ignores_invalid_defaults(monkeypatch):
    _install_room_features_module(
        monkeypatch,
        store_config={
            "information": {"type": "dict", "key": "INFO"},
            "pin": {"type": "dict", "key": "PIN"},
        },
        defaults_provider=lambda: {
            "information": "yes",
            "pin": object(),
        },
    )

    info_state = await room_features.get_room_feature(
        _bot_with_store(DummyStore()),
        "room@conf",
        "information",
    )
    pin_state = await room_features.get_room_feature(
        _bot_with_store(DummyStore()),
        "room@conf",
        "pin",
    )

    assert info_state.enabled is True
    assert info_state.default is True
    assert pin_state.enabled is False
    assert pin_state.default is False


@pytest.mark.asyncio
async def test_room_feature_uses_effective_defaults(monkeypatch):
    _install_room_features_module(
        monkeypatch,
        store_config={"pin": {"type": "dict", "key": "PIN"}},
        plugin_defaults={"pin": True},
        defaults_provider=lambda: {"pin": False},
    )

    state = await room_features.get_room_feature(
        _bot_with_store(DummyStore({"PIN": {"room@conf": True}})),
        "room@conf",
        "pin",
    )

    assert state.name == "pin"
    assert state.enabled is True
    assert state.default is False
    assert state.modified is True


def test_room_feature_name_aliases_and_format(monkeypatch):
    _install_room_features_module(
        monkeypatch,
        store_config={
            "information": {"type": "dict", "key": "INFO_ENABLED"},
            "karma": {"type": "dict", "key": "KARMA_ENABLED"},
        },
        plugin_defaults={"information": True, "karma": False},
    )

    assert room_features.available_features() == ["information", "karma"]
    assert room_features.is_known_feature("infos")
    assert room_features.is_known_feature("roominfo")
    assert not room_features.is_known_feature("missing")

    line = room_features.format_room_feature_line(
        room_features.RoomFeatureState(
            name="karma",
            enabled=True,
            default=False,
            modified=True,
        )
    )
    assert line == "• karma: enabled | default: disabled (modified)"


@pytest.mark.parametrize(
    ("raw_default", "expected"),
    [
        pytest.param("yes", True, id="yes"),
        pytest.param("disabled", False, id="disabled"),
        pytest.param("", False, id="empty-string"),
        pytest.param("   ", False, id="blank-string"),
        pytest.param("1.5", True, id="numeric-string-true"),
        pytest.param("0.0", False, id="numeric-string-false"),
        pytest.param(1, True, id="integer-true"),
        pytest.param(0, False, id="integer-false"),
        pytest.param(True, True, id="bool-true"),
        pytest.param(False, False, id="bool-false"),
    ],
)
@pytest.mark.asyncio
async def test_room_feature_flag_defaults_are_normalized(
    monkeypatch, raw_default, expected
):
    _install_room_features_module(
        monkeypatch,
        store_config=_basic_store_config(),
        plugin_defaults={"pin": raw_default},
    )

    state = await room_features.get_room_feature(
        _bot_with_store(DummyStore()),
        "room@conf",
        "pin",
    )

    assert state.default is expected
    assert state.enabled is expected
    assert state.modified is False


@pytest.mark.asyncio
async def test_room_feature_missing_state_uses_default_fallback(monkeypatch):
    _install_room_features_module(
        monkeypatch,
        store_config=_basic_store_config(),
        plugin_defaults={"pin": True},
    )

    state = await room_features.get_room_feature(
        _bot_with_store(DummyStore({"PIN": {}})),
        "room@conf",
        "pin",
    )

    assert state.enabled is True
    assert state.default is True
    assert state.modified is False


@pytest.mark.parametrize(
    "bad_default",
    [
        pytest.param([], id="list"),
        pytest.param({}, id="dict"),
        pytest.param(object(), id="object"),
        pytest.param("maybe", id="unknown-string"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_room_feature_defaults_are_ignored(
    monkeypatch, caplog, bad_default
):
    _install_room_features_module(
        monkeypatch,
        store_config=_basic_store_config(),
        plugin_defaults={"pin": bad_default},
    )

    with caplog.at_level(logging.WARNING):
        state = await room_features.get_room_feature(
            _bot_with_store(DummyStore()),
            "room@conf",
            "pin",
        )

    assert state.default is False
    assert state.enabled is False
    assert "Ignoring invalid default for plugin 'pin'" in caplog.text


def test_is_known_feature_uses_unsorted_config(monkeypatch):
    _install_room_features_module(
        monkeypatch,
        store_config={
            "information": {"type": "dict", "key": "INFO_ENABLED"}
        },
    )
    monkeypatch.setattr(
        room_features,
        "available_features",
        lambda: pytest.fail("available_features should not be called"),
    )

    assert room_features.is_known_feature("info")


@pytest.mark.asyncio
async def test_room_feature_ignores_malformed_backend_state(monkeypatch):
    _install_room_features_module(
        monkeypatch,
        store_config={"pin": {"type": "dict", "key": "PIN"}},
        plugin_defaults={"pin": True},
    )
    store = DummyStore(
        {
            "PIN": {
                "room@conf": {"enabled": False},
                "other@conf": [],
                "bad@conf": object(),
                "invalid@conf": "maybe",
                42: False,
            }
        }
    )

    state = await room_features.get_room_feature(
        _bot_with_store(store),
        "room@conf",
        "pin",
    )

    assert state.enabled is True
    assert state.default is True
    assert state.modified is False


@pytest.mark.asyncio
async def test_list_room_features_reuses_defaults(monkeypatch):
    calls = 0

    def counting_defaults_provider():
        nonlocal calls
        calls += 1
        return {"information": True, "karma": False}

    _install_room_features_module(
        monkeypatch,
        store_config={
            "information": {"type": "dict", "key": "INFO_ENABLED"},
            "karma": {"type": "dict", "key": "KARMA_ENABLED"},
        },
        defaults_provider=counting_defaults_provider,
    )

    listed = await room_features.list_room_features(
        _bot_with_store(DummyStore()),
        "room@conf",
    )

    assert [item.name for item in listed] == ["information", "karma"]
    assert calls == 1


@pytest.mark.asyncio
async def test_set_room_feature_serializes_concurrent_updates(monkeypatch):
    _install_room_features_module(
        monkeypatch,
        store_config={"pin": {"type": "dict", "key": "PIN"}},
        plugin_defaults={"pin": False},
    )
    store = CopyingSlowStore({"PIN": {}})
    bot = _bot_with_store(store)

    await asyncio.gather(
        room_features.set_room_feature(bot, "room-a@conf", "pin", True),
        room_features.set_room_feature(bot, "room-b@conf", "pin", True),
    )

    assert store.data["PIN"] == {
        "room-a@conf": True,
        "room-b@conf": True,
    }


@pytest.mark.asyncio
async def test_list_room_features_reports_failing_feature(monkeypatch):
    _install_room_features_module(
        monkeypatch,
        store_config={
            "information": {"type": "dict", "key": "INFO_ENABLED"},
            "legacy": {"type": "list", "key": "LEGACY_ENABLED"},
        },
        plugin_defaults={},
    )

    with pytest.raises(RuntimeError) as exc_info:
        await room_features.list_room_features(
            _bot_with_store(DummyStore()),
            "room@conf",
        )

    assert str(exc_info.value) == (
        "Failed to fetch room feature state for 'legacy' "
        "in room 'room@conf'"
    )
    assert isinstance(exc_info.value.__cause__, ValueError)


@pytest.mark.asyncio
async def test_set_room_feature_sanitizes_current_state(monkeypatch):
    _install_room_features_module(
        monkeypatch,
        store_config=_basic_store_config(),
        plugin_defaults={"pin": False},
    )
    store = DummyStore(
        {
            "PIN": {
                "old@conf": "yes",
                "bad@conf": [],
                42: True,
            }
        }
    )

    await room_features.set_room_feature(
        _bot_with_store(store),
        "new@conf",
        "pin",
        True,
    )

    assert store.data["PIN"] == {
        "old@conf": True,
        "new@conf": True,
    }


@pytest.mark.asyncio
async def test_room_feature_set_replaces_invalid_storage(monkeypatch):
    _install_room_features_module(
        monkeypatch,
        store_config={
            "information": {"type": "dict", "key": "INFO_ENABLED"},
        },
        plugin_defaults={"information": False},
    )
    store = DummyStore({"INFO_ENABLED": "not-a-dict"})
    bot = _bot_with_store(store)

    state = await room_features.set_room_feature(
        bot,
        "room@conf",
        "info",
        True,
    )

    assert state.name == "information"
    assert state.enabled is True
    assert store.data["INFO_ENABLED"] == {"room@conf": True}


@pytest.mark.asyncio
async def test_room_feature_list_reads_existing_dict_storage(monkeypatch):
    _install_room_features_module(
        monkeypatch,
        store_config={
            "information": {"type": "dict", "key": "INFO_ENABLED"},
        },
        plugin_defaults={"information": False},
    )
    bot = _bot_with_store(
        DummyStore({"INFO_ENABLED": {"room@conf": True}})
    )

    listed = await room_features.list_room_features(bot, "room@conf")

    assert [item.name for item in listed] == ["information"]
    assert listed[0].enabled is True


@pytest.mark.asyncio
async def test_room_feature_get_rejects_unsupported_list_storage(
    monkeypatch,
):
    _install_room_features_module(
        monkeypatch,
        store_config={"legacy": {"type": "list", "key": "LEGACY_ENABLED"}},
        plugin_defaults={},
    )

    with pytest.raises(ValueError) as exc_info:
        await room_features.get_room_feature(
            _bot_with_store(DummyStore()),
            "room@conf",
            "legacy",
        )

    assert str(exc_info.value) == (
        "Unsupported room feature storage type: list. "
        "Only 'dict' is currently supported."
    )


@pytest.mark.asyncio
async def test_room_feature_set_rejects_unsupported_list_storage(
    monkeypatch,
):
    _install_room_features_module(
        monkeypatch,
        store_config={"legacy": {"type": "list", "key": "LEGACY_ENABLED"}},
        plugin_defaults={},
    )

    with pytest.raises(ValueError) as exc_info:
        await room_features.set_room_feature(
            _bot_with_store(DummyStore()),
            "room@conf",
            "legacy",
            True,
        )

    assert str(exc_info.value) == (
        "Unsupported room feature storage type: list. "
        "Only 'dict' is currently supported."
    )


@pytest.mark.asyncio
async def test_get_enabled_room_jids_combines_defaults_and_overrides(
    monkeypatch,
):
    _install_room_features_module(
        monkeypatch,
        store_config=_basic_store_config(),
        plugin_defaults={"pin": True},
    )
    bot = _bot_with_store(
        DummyStore(
            {
                "PIN": {
                    "disabled@conf": False,
                    "stored@conf": True,
                    "invalid@conf": "invalid",
                }
            }
        )
    )

    enabled = await room_features.get_enabled_room_jids(
        bot,
        "pin",
        ["default@conf", "disabled@conf", ""],
    )

    assert enabled == {
        "default@conf": True,
        "stored@conf": True,
    }


@pytest.mark.asyncio
async def test_get_enabled_room_jids_omits_missing_rooms_when_default_off(
    monkeypatch,
):
    _install_room_features_module(
        monkeypatch,
        store_config=_basic_store_config(),
        plugin_defaults={"pin": False},
    )
    bot = _bot_with_store(
        DummyStore({"PIN": {"enabled@conf": True, "disabled@conf": False}})
    )

    enabled = await room_features.get_enabled_room_jids(
        bot,
        "pin",
        ["missing@conf", "enabled@conf"],
    )

    assert enabled == {"enabled@conf": True}


@pytest.mark.asyncio
async def test_room_feature_room_ids_are_bare_casefolded_and_deduplicated(
    monkeypatch,
):
    _install_room_features_module(
        monkeypatch,
        store_config=_basic_store_config(),
        plugin_defaults={"pin": False},
    )
    store = DummyStore({"PIN": {"Room@Conference.Example/Nick": True}})
    bot = _bot_with_store(store)

    state = await room_features.get_room_feature(
        bot,
        " room@conference.example/OtherNick ",
        "pin",
    )
    enabled = await room_features.get_enabled_room_jids(
        bot,
        "pin",
        ["ROOM@CONFERENCE.EXAMPLE/ThirdNick"],
    )
    await room_features.set_room_feature(
        bot,
        "ROOM@CONFERENCE.EXAMPLE/NewNick",
        "pin",
        False,
    )

    assert state.enabled is True
    assert enabled == {"room@conference.example": True}
    assert store.data["PIN"] == {"room@conference.example": False}


@pytest.mark.asyncio
async def test_defaults_provider_overrides_static_defaults_and_validates_types(
    monkeypatch, caplog
):
    provider_calls = 0

    def counting_defaults_provider():
        nonlocal provider_calls
        provider_calls += 1
        return {"info": "yes", "karma": "0", "bad": object()}

    _install_room_features_module(
        monkeypatch,
        store_config={
            "info": {"type": "dict", "key": "INFO_ENABLED"},
            "karma": {"type": "dict", "key": "KARMA_ENABLED"},
        },
        plugin_defaults={"info": False},
        defaults_provider=counting_defaults_provider,
    )

    with caplog.at_level(logging.WARNING):
        states = await room_features.list_room_features(
            _bot_with_store(DummyStore()),
            "room@conf",
        )

    assert [(state.name, state.default) for state in states] == [
        ("information", True),
        ("karma", False),
    ]
    assert provider_calls == 1
    assert "Ignoring invalid default for plugin 'bad'" in caplog.text


@pytest.mark.asyncio
async def test_static_defaults_fallback_when_provider_invalid_or_fails(
    monkeypatch, caplog
):
    _install_room_features_module(
        monkeypatch,
        store_config=_basic_store_config(),
        plugin_defaults={"pin": 1},
    )
    state = await room_features.get_room_feature(
        _bot_with_store(DummyStore()),
        "room@conf",
        "pin",
    )
    assert state.default is True

    _install_room_features_module(
        monkeypatch,
        store_config=_basic_store_config(),
        plugin_defaults=["pin"],
    )
    with caplog.at_level(logging.WARNING):
        state = await room_features.get_room_feature(
            _bot_with_store(DummyStore()),
            "room@conf",
            "pin",
        )
    assert state.default is False
    assert "Ignoring defaults provider result with invalid type: list" in caplog.text

    def broken_defaults():
        raise RuntimeError("boom")

    _install_room_features_module(
        monkeypatch,
        store_config=_basic_store_config(),
        defaults_provider=broken_defaults,
    )
    with caplog.at_level(logging.ERROR):
        state = await room_features.get_room_feature(
            _bot_with_store(DummyStore()),
            "room@conf",
            "pin",
        )
    assert state.default is False
    assert "Defaults provider failed" in caplog.text
