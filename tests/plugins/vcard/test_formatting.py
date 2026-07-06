from .helpers import *  # noqa: F401,F403


@pytest.mark.asyncio
async def test_format_vcard_field_for_nick_all_value_shapes():
    assert await vcard._format_vcard_field_for_nick(
        "URL", "URLs", ["https%3A//example.org/a%20b"], "Alice"
    ) == ["URLs - Alice:", "    • https://example.org/a b"]
    assert await vcard._format_vcard_field_for_nick("URL", "URLs", [], "Alice") == [
        "URLs - Alice:",
        "    • —",
    ]

    note_lines = await vcard._format_vcard_field_for_nick(
        "NOTE", "Notes", ["first line\nsecond line"], "Alice", ["room@conf"]
    )
    assert note_lines[0] == "Notes - Alice in room@conf:"
    assert "    • first line" in note_lines
    assert "      second line" in note_lines

    assert await vcard._format_vcard_field_for_nick("EMAIL", "Emails", ["a@example.org"], "Alice") == [
        "Emails - Alice:",
        "    • a@example.org",
    ]
    assert await vcard._format_vcard_field_for_nick("FN", "Full Name", "Alice Example", "Alice") == [
        "Full Name - Alice:",
        "    • Alice Example",
    ]
    assert await vcard._format_vcard_field_for_nick("ORG", "Orgs", None, "Alice") == [
        "Orgs - Alice:",
        "    • —",
    ]


def test_vcard_reply_helpers_and_empty_checks(fake_bot):
    m = msg(from_jid="room@x/Alice")
    vcard._vcard_reply_missing_nick(fake_bot, m, "Alice", "room@x", own=False)
    vcard._vcard_reply_missing_nick(fake_bot, m, "Alice", "room@x", own=True)
    vcard._vcard_reply_missing_field(fake_bot, m, "Full Name", "Alice", "room@x")
    vcard._vcard_reply_empty_requested_user(fake_bot, m, "Full Name", "Alice")
    replies = [entry[0] for entry in fake_bot._replies]
    assert "Nick 'Alice' not found" in replies[0]
    assert "Your Nick 'Alice' not found" in replies[1]
    assert "No Full Name found" in replies[2]
    assert "No Full Name set" in replies[3]

    assert vcard._vcard_value_is_empty(None) is True
    assert vcard._vcard_value_is_empty("") is True
    assert vcard._vcard_value_is_empty([]) is True
    assert vcard._vcard_value_is_empty("x") is False
    assert vcard._vcard_should_format_field("FN") is True
    assert vcard._vcard_should_format_field("LOCALITY") is False


def test_append_vcard_list_values_adds_each_value():
    lines = []
    vcard._append_vcard_list_values(lines, ["one", "two"])
    assert lines == ["    • one", "    • two"]
