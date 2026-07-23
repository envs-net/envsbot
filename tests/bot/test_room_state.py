from types import SimpleNamespace

from bot import room_state


def setup_function():
    room_state.JOINED_ROOMS.clear()


def teardown_function():
    room_state.JOINED_ROOMS.clear()


def test_joined_room_jids_merges_and_normalizes_sources():
    bot = SimpleNamespace(
        presence=SimpleNamespace(
            joined_rooms={"Presence@Conf.Test/Bot": "Bot"},
        )
    )
    room_state.JOINED_ROOMS["runtime@conf.test"] = {"nick": "RuntimeBot"}

    assert room_state.joined_room_jids(
        bot,
        {"Extra@Conf.Test": {}},
    ) == {
        "presence@conf.test",
        "runtime@conf.test",
        "extra@conf.test",
    }


def test_joined_room_jids_accepts_iterables_and_ignores_empty_values():
    class BareJID:
        bare = "Object@Conf.Test/Resource"

    class BrokenRooms:
        def keys(self):
            raise TypeError("broken")

    assert room_state.joined_room_jids(
        None,
        ["", None, "room@conf.test/resource", BareJID()],
    ) == {"room@conf.test", "object@conf.test"}
    assert room_state.joined_room_jids(None, BrokenRooms()) == set()


def test_known_room_jids_adds_stored_row_shapes():
    stored_rows = [
        ("Tuple@Conf.Test", "Bot", True, None),
        {"room_jid": "Mapping@Conf.Test/Resource"},
        ["List@Conf.Test", "Bot"],
        "Plain@Conf.Test",
        (),
        {},
    ]

    assert room_state.known_room_jids(
        None,
        {"Joined@Conf.Test": {}},
        stored_rows,
    ) == {
        "joined@conf.test",
        "tuple@conf.test",
        "mapping@conf.test",
        "list@conf.test",
        "plain@conf.test",
    }


def test_known_room_jids_handles_broken_stored_room_mapping():
    class BrokenStoredRooms:
        def keys(self):
            raise TypeError("broken")

    assert room_state.known_room_jids(
        None,
        {"Joined@Conf.Test": {}},
        BrokenStoredRooms(),
    ) == {"joined@conf.test"}
