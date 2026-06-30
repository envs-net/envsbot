from types import SimpleNamespace

import pytest

from utils import room_features


class DummyStore:
    def __init__(self, data=None):
        self.data = data if data is not None else {}

    async def get_global(self, key, default=None):
        return self.data.get(key, default)

    async def set_global(self, key, value):
        self.data[key] = value


class DummyUsers:
    def __init__(self, store):
        self.store = store

    def plugin(self, name):
        return self.store


def _bot_with_store(store):
    return SimpleNamespace(db=SimpleNamespace(users=DummyUsers(store)))


def test_available_features_handles_missing_or_invalid_config(monkeypatch):
    monkeypatch.setattr(
        room_features,
        "_rooms_module",
        lambda: SimpleNamespace(PLUGIN_STORE_CONFIG=None),
    )

    assert room_features.available_features() == []
    assert not room_features.is_known_feature("urlcheck")


def test_available_features_validates_store_config_shape(monkeypatch):
    monkeypatch.setattr(
        room_features,
        "_rooms_module",
        lambda: SimpleNamespace(
            PLUGIN_STORE_CONFIG={
                "info": {"type": "dict", "key": "INFO_ENABLED"},
                "missing_key": {"type": "dict"},
                "empty_key": {"type": "dict", "key": ""},
                "bad_type": {"type": object(), "key": "BAD_ENABLED"},
                "not_a_mapping": "bad",
                42: {"type": "dict", "key": "NUMERIC_ENABLED"},
                "legacy": {"type": "list", "key": "LEGACY_ENABLED"},
            }
        ),
    )

    assert room_features.available_features() == ["information", "legacy"]
    assert room_features.is_known_feature("roominfo")


@pytest.mark.asyncio
async def test_get_room_feature_rejects_unknown_feature(monkeypatch):
    monkeypatch.setattr(
        room_features,
        "_rooms_module",
        lambda: SimpleNamespace(PLUGIN_STORE_CONFIG={}),
    )

    with pytest.raises(KeyError, match="urlcheck"):
        await room_features.get_room_feature(
            _bot_with_store(DummyStore()), "room@conf", "urlcheck"
        )


@pytest.mark.asyncio
async def test_room_feature_defaults_handle_missing_defaults(monkeypatch):
    monkeypatch.setattr(
        room_features,
        "_rooms_module",
        lambda: SimpleNamespace(
            PLUGIN_STORE_CONFIG={
                "urlcheck": {"type": "dict", "key": "enabled_rooms"}
            },
            PLUGIN_DEFAULTS=None,
        ),
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
async def test_room_feature_uses_effective_defaults(monkeypatch):
    monkeypatch.setattr(
        room_features,
        "_rooms_module",
        lambda: SimpleNamespace(
            PLUGIN_STORE_CONFIG={"pin": {"type": "dict", "key": "PIN"}},
            PLUGIN_DEFAULTS={"pin": True},
            get_room_plugin_defaults=lambda: {"pin": False},
        ),
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


def test_room_feature_name_aliases_flags_and_format(monkeypatch):
    monkeypatch.setattr(
        room_features,
        "_rooms_module",
        lambda: SimpleNamespace(
            PLUGIN_STORE_CONFIG={
                "information": {"type": "dict", "key": "INFO_ENABLED"},
                "karma": {"type": "dict", "key": "KARMA_ENABLED"},
            },
            PLUGIN_DEFAULTS={"information": True, "karma": False},
        ),
    )

    assert room_features.available_features() == ["information", "karma"]
    assert room_features.is_known_feature("infos")
    assert room_features.is_known_feature("roominfo")
    assert not room_features.is_known_feature("missing")
    assert room_features._coerce_feature_flag("yes") is True
    assert (
        room_features._coerce_feature_flag("disabled", fallback=True)
        is False
    )
    assert room_features._coerce_feature_flag(None, fallback=True) is True
    with pytest.raises(TypeError, match="Unsupported feature flag"):
        room_features._coerce_feature_flag([])
    with pytest.raises(TypeError, match="Unsupported feature flag"):
        room_features._coerce_feature_flag({})
    with pytest.raises(TypeError, match="Unsupported feature flag"):
        room_features._coerce_feature_flag(object())

    line = room_features.format_room_feature_line(
        room_features.RoomFeatureState(
            name="karma",
            enabled=True,
            default=False,
            modified=True,
        )
    )
    assert line == "• karma: enabled | default: off (modified)"


@pytest.mark.asyncio
async def test_room_feature_set_list_and_unsupported_storage(monkeypatch):
    monkeypatch.setattr(
        room_features,
        "_rooms_module",
        lambda: SimpleNamespace(
            PLUGIN_STORE_CONFIG={
                "information": {"type": "dict", "key": "INFO_ENABLED"},
                "legacy": {"type": "list", "key": "LEGACY_ENABLED"},
            },
            PLUGIN_DEFAULTS={"information": False},
        ),
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

    monkeypatch.setattr(
        room_features,
        "_rooms_module",
        lambda: SimpleNamespace(
            PLUGIN_STORE_CONFIG={
                "information": {"type": "dict", "key": "INFO_ENABLED"}
            },
            PLUGIN_DEFAULTS={"information": False},
        ),
    )
    listed = await room_features.list_room_features(bot, "room@conf")
    assert [item.name for item in listed] == ["information"]
    assert listed[0].enabled is True

    monkeypatch.setattr(
        room_features,
        "_rooms_module",
        lambda: SimpleNamespace(
            PLUGIN_STORE_CONFIG={
                "legacy": {"type": "list", "key": "LEGACY_ENABLED"}
            },
            PLUGIN_DEFAULTS={},
        ),
    )
    unsupported_storage = "Unsupported room feature storage type"
    with pytest.raises(ValueError, match=unsupported_storage):
        await room_features.get_room_feature(bot, "room@conf", "legacy")

    with pytest.raises(ValueError, match=unsupported_storage):
        await room_features.set_room_feature(
            bot,
            "room@conf",
            "legacy",
            True,
        )
