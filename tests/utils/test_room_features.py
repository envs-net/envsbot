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


@pytest.mark.asyncio
async def test_get_room_feature_rejects_unknown_feature(monkeypatch):
    monkeypatch.setattr(
        room_features,
        "_rooms_module",
        lambda: SimpleNamespace(PLUGIN_STORE_CONFIG={}),
    )

    with pytest.raises(KeyError, match="urlcheck"):
        await room_features.get_room_feature(_bot_with_store(DummyStore()), "room@conf", "urlcheck")


@pytest.mark.asyncio
async def test_room_feature_defaults_handle_missing_defaults(monkeypatch):
    monkeypatch.setattr(
        room_features,
        "_rooms_module",
        lambda: SimpleNamespace(
            PLUGIN_STORE_CONFIG={"urlcheck": {"type": "dict", "key": "enabled_rooms"}},
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
