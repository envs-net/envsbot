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


def test_direct_roster_contacts_excludes_rooms_self_and_removed_entries():
    class JID:
        def __init__(self, bare):
            self.bare = bare

    own = JID("bot@example.org")
    friend = JID("Friend@Example.org/Phone")
    stored_room = JID("Stored@Conference.Example.org")
    joined_room = JID("Joined@Conference.Example.org")
    removed = JID("removed@example.org")
    bot = SimpleNamespace(
        boundjid=own,
        presence=SimpleNamespace(
            joined_rooms={"joined@conference.example.org": "Bot"},
        ),
        client_roster={
            own: {"subscription": "both"},
            friend: {"subscription": "both"},
            stored_room: {"subscription": "both"},
            joined_room: {"subscription": "both"},
            removed: {"subscription": "remove"},
        },
    )

    contacts = room_state.direct_roster_contacts(
        bot,
        [("stored@conference.example.org", "Bot", True, None)],
    )

    assert contacts == [("Friend@Example.org", bot.client_roster[friend])]


def test_direct_roster_contacts_handles_missing_roster_and_object_items():
    class RosterItem:
        subscription = "from"

    bot = SimpleNamespace(
        boundjid=SimpleNamespace(bare="bot@example.org"),
        presence=SimpleNamespace(joined_rooms={}),
        client_roster={"alice@example.org": RosterItem()},
    )

    assert room_state.direct_roster_contacts(None) == []
    assert room_state.direct_roster_contacts(bot) == [
        ("alice@example.org", bot.client_roster["alice@example.org"]),
    ]
