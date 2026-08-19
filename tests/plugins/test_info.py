import pytest
import types
import csv
import json
from plugins import info as info_plugin
from unittest.mock import AsyncMock, MagicMock

# ---- AIOHTTP ASYNC CTX MOCKING HELPERS ----


class AsyncContextResp:
    """Simulates async context manager for aiohttp response."""

    def __init__(self, status, json_data):
        self.status = status
        self._json_data = json_data

    async def json(self):
        return self._json_data

    async def __aenter__(self): return self
    async def __aexit__(self, exc_type, exc, tb): pass


class DummyAioSession:
    """Simulate aiohttp.ClientSession with url -> AsyncContextResp map."""

    def __init__(self, resp_map=None):
        self.resp_map = resp_map or {}

    async def __aenter__(self): return self
    async def __aexit__(self, exc_type, exc, tb): pass

    def get(self, url, timeout=None, allow_redirects=False):
        for key in self.resp_map:
            if key in url:
                return self.resp_map[key]
        if self.resp_map:
            return list(self.resp_map.values())[0]
        else:
            return AsyncContextResp(500, {})


# ---- BOT/MSG FIXTURES ----

class DummyBot:
    def __init__(self):
        self.replies = []
        self.prefix = ","
        self.version = "test"
        self.db = types.SimpleNamespace()
        self.db.users = types.SimpleNamespace()
        self.bot_plugins = types.SimpleNamespace()
        self.bot_plugins.plugins = {"info": info_plugin}
        self.bot_plugins.register_event = lambda *a, **k: None
        self.bot_plugins.list = lambda: ["info"]

    def reply(self, msg, text, **kwargs):
        self.replies.append((msg, text))

    def reset(self):
        self.replies.clear()


@pytest.fixture
def dummy_bot(monkeypatch):
    bot = DummyBot()

    class DummyPlugin:
        def __init__(self):
            self._data = {}

        async def get_global(
            self, key, default=None): return self._data.get(key, default)

        async def set_global(self, key, value): self._data[key] = value
    dummy_plugin = DummyPlugin()
    bot.db.users.plugin = lambda plugin_name: dummy_plugin
    monkeypatch.setattr(info_plugin, "get_info_store",
                        lambda bot: dummy_plugin)
    return bot


@pytest.fixture
def fake_room_msg():
    return {
        "from": types.SimpleNamespace(bare="testroom@conf", resource="nick"),
        "body": "",
        "type": "groupchat"
    }


@pytest.fixture
def fake_dm_msg():
    return {
        "from": types.SimpleNamespace(bare="user@domain", resource=None),
        "body": "",
        "type": "chat"
    }


@pytest.fixture(autouse=True)
def patch_enabled_rooms(monkeypatch):
    async def enabled_rooms(bot, key, plugin):
        return {"testroom@conf": True}
    monkeypatch.setattr(info_plugin, "_get_enabled_rooms", enabled_rooms)

# ---- URBAN DICTIONARY ----


@pytest.mark.asyncio
async def test_udict_usage(dummy_bot, fake_room_msg):
    dummy_bot.prefix = "!"
    await info_plugin.udict_search(dummy_bot, "jid", "nick", [],
                                   fake_room_msg, True)
    text = "\n".join(str(x) for x in dummy_bot.replies)
    assert "Usage: !udict <term>" in text


@pytest.mark.asyncio
async def test_udict_flow_found(monkeypatch, dummy_bot, fake_room_msg):
    resp = AsyncContextResp(200, {"list": [{
        "definition": "some meaning", "example": "an example",
        "thumbs_up": 5, "thumbs_down": 1, "permalink": "url"
    }]})
    monkeypatch.setattr(info_plugin.aiohttp, "ClientSession",
                        lambda: DummyAioSession({"udict": resp}))
    dummy_bot.reset()
    await info_plugin.udict_search(dummy_bot, "jid", "nick", ["test"],
                                   fake_room_msg, True)
    text = "\n".join(map(str, dummy_bot.replies))
    assert "Definition:" in text and "Example:" in text and "👍" in text


@pytest.mark.asyncio
async def test_udict_flow_not_found(monkeypatch, dummy_bot, fake_room_msg):
    resp = AsyncContextResp(200, {"list": []})
    monkeypatch.setattr(info_plugin.aiohttp, "ClientSession",
                        lambda: DummyAioSession({"udict": resp}))
    dummy_bot.reset()
    await info_plugin.udict_search(dummy_bot, "jid", "nick", ["test"],
                                   fake_room_msg, True)
    text = "\n".join(map(str, dummy_bot.replies))
    assert "No definitions" in text


@pytest.mark.asyncio
async def test_udict_error(monkeypatch, dummy_bot, fake_room_msg):
    class BrokenSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def get(self, *a, **k): raise Exception("fail")
    monkeypatch.setattr(info_plugin.aiohttp,
                        "ClientSession", lambda: BrokenSession())
    dummy_bot.reset()
    await info_plugin.udict_search(dummy_bot, "jid", "nick", ["fail"],
                                   fake_room_msg, True)
    text = "\n".join(map(str, dummy_bot.replies))
    assert "Error fetching" in text


# ---- FEDIVERSE ----

@pytest.mark.asyncio
async def test_fediverse_usage(dummy_bot, fake_room_msg):
    dummy_bot.prefix = "!"
    await info_plugin.fediverse_latest(dummy_bot, "jid", "nick", [],
                                       fake_room_msg, True)
    text = "\n".join(str(x) for x in dummy_bot.replies)
    assert "Usage: !fediverse <@user@instance>" in text


def test_parse_fediverse_handle_rejects_url_syntax_and_normalizes_idna():
    assert info_plugin._parse_fediverse_handle("@user@example.org") == (
        "user",
        "example.org",
    )
    assert info_plugin._parse_fediverse_handle("@user@BÜCHER.example") == (
        "user",
        "xn--bcher-kva.example",
    )
    assert info_plugin._parse_fediverse_handle("@user@example.org/path") is None
    assert info_plugin._parse_fediverse_handle("@user@example.org:8443") is None
    assert info_plugin._parse_fediverse_handle("@user@localhost") is None
    assert info_plugin._parse_fediverse_handle("@bad user@example.org") is None


@pytest.mark.asyncio
async def test_fediverse_invalid_format(dummy_bot, fake_room_msg):
    await info_plugin.fediverse_latest(dummy_bot, "jid", "nick", ["invalid"],
                                       fake_room_msg, True)
    text = "\n".join(str(x) for x in dummy_bot.replies)
    assert "Please specify the user as" in text


@pytest.mark.asyncio
async def test_fediverse_error(monkeypatch, dummy_bot, fake_room_msg):
    monkeypatch.setattr(
        info_plugin,
        "fetch_json",
        AsyncMock(side_effect=RuntimeError("fail")),
    )
    dummy_bot.reset()
    await info_plugin.fediverse_latest(
        dummy_bot, "jid", "nick", ["@foo@bar.example"], fake_room_msg, True
    )
    text = "\n".join(str(x) for x in dummy_bot.replies)
    assert "Error fetching from Fediverse" in text


@pytest.mark.asyncio
async def test_fediverse_nomatches(monkeypatch, dummy_bot, fake_room_msg):
    fetch = AsyncMock(
        side_effect=[
            types.SimpleNamespace(status=200, data={"id": "42"}),
            types.SimpleNamespace(status=200, data=[]),
        ]
    )
    monkeypatch.setattr(info_plugin, "fetch_json", fetch)
    dummy_bot.reset()
    await info_plugin.fediverse_latest(
        dummy_bot, "jid", "nick", ["@someone@host.example"], fake_room_msg, True
    )
    text = "\n".join(str(x) for x in dummy_bot.replies).lower()
    assert "no public toots" in text
    assert fetch.await_args_list[0].args[0].startswith(
        "https://host.example/api/v1/accounts/lookup?acct=someone"
    )
    assert all("validator" not in call.kwargs for call in fetch.await_args_list)


@pytest.mark.asyncio
async def test_fediverse_success(monkeypatch, dummy_bot, fake_room_msg):
    timeline_content = [{
        "content": "<p>hello <a href=\"url\">link</a></p>",
        "url": "u", "reblogs_count": 1, "replies_count": 2,
        "favourites_count": 3
    }]
    fetch = AsyncMock(
        side_effect=[
            types.SimpleNamespace(status=200, data={"id": "42"}),
            types.SimpleNamespace(status=200, data=timeline_content),
        ]
    )
    monkeypatch.setattr(info_plugin, "fetch_json", fetch)
    dummy_bot.reset()
    await info_plugin.fediverse_latest(
        dummy_bot, "jid", "nick", ["@someone@host.example"], fake_room_msg, True
    )
    text = "\n".join(str(x) for x in dummy_bot.replies).lower()
    assert "toot" in text and "hello" in text
    assert all("validator" not in call.kwargs for call in fetch.await_args_list)


# ---- ACRONYMS (all variants) ----


@pytest.fixture
def tmp_slang_files(tmp_path, monkeypatch):
    main = tmp_path/"chat_slang.csv"
    add = tmp_path/"slang_additions.csv"
    rem = tmp_path/"slang_removals.csv"
    with main.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(["lgtm", "Looks good to me"])
    monkeypatch.setattr(info_plugin, "SLANG_CSV", str(main))
    monkeypatch.setattr(info_plugin, "SLANG_ADDITIONS_CSV", str(add))
    monkeypatch.setattr(info_plugin, "SLANG_REMOVALS_CSV", str(rem))
    return main, add, rem


@pytest.mark.asyncio
async def test_acronyms_cmd_found(tmp_slang_files, dummy_bot, fake_room_msg):
    main, _, _ = tmp_slang_files
    dummy_bot.reset()
    await info_plugin.acronyms_cmd(dummy_bot, "jid", "nick", ["lgtm"],
                                   fake_room_msg, True)
    text = "\n".join(str(x) for x in dummy_bot.replies)
    assert "LGTM:" in text


@pytest.mark.asyncio
async def test_acronyms_cmd_not_found(tmp_slang_files, dummy_bot,
                                      fake_room_msg):
    main, _, _ = tmp_slang_files
    with main.open("w", encoding="utf-8"):
        pass
    dummy_bot.reset()
    await info_plugin.acronyms_cmd(dummy_bot, "jid", "nick", ["NOSUCH"],
                                   fake_room_msg, True)
    out = "\n".join(str(x) for x in dummy_bot.replies)
    assert "not defined" in out


@pytest.mark.asyncio
async def test_acronyms_add_cmd(tmp_slang_files, dummy_bot, fake_room_msg):
    _, add, _ = tmp_slang_files
    dummy_bot.reset()
    await info_plugin.acronyms_add_cmd(dummy_bot, "jid", "nick",
                                       ["foo", "Bar baz"], fake_room_msg, True)
    out = "\n".join(str(x) for x in dummy_bot.replies)
    assert "queued" in out.lower() or "pending" in out.lower()
    with open(str(add), encoding="utf-8") as f:
        rows = [r for r in csv.reader(f)]
        assert any(row[0].lower() == "foo" for row in rows)


@pytest.mark.asyncio
async def test_acronyms_remove_cmd(tmp_slang_files, dummy_bot, fake_room_msg):
    main, _, rem = tmp_slang_files
    with main.open("a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(["foo", "to remove"])
    dummy_bot.reset()
    await info_plugin.acronyms_remove_cmd(dummy_bot, "jid", "nick",
                                          ["foo", "to remove"],
                                          fake_room_msg, True)
    out = "\n".join(str(x) for x in dummy_bot.replies)
    assert "queued" in out.lower()
    with open(str(rem), encoding="utf-8") as f:
        rows = [r for r in csv.reader(f)]
        assert any(row[0].lower() == "foo" for row in rows)


@pytest.mark.asyncio
async def test_acronyms_list_cmd(tmp_slang_files, dummy_bot, fake_room_msg):
    _, add, rem = tmp_slang_files
    with open(str(add), "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(["foo2", "bar2", "nick1"])
    with open(str(rem), "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(["foo2", "bar2", "nick1"])
    dummy_bot.reset()
    await info_plugin.acronyms_list_cmd(dummy_bot, "jid", "nick", [],
                                        fake_room_msg, True)
    out = "\n".join(x[1] for x in dummy_bot.replies)
    assert "Pending Additions" in out or "pending additions" in out
    assert "Pending Removals" in out or "pending removals" in out
    out = "\n".join(x[1] for x in dummy_bot.replies)
    assert "foo2" in out.lower()


@pytest.mark.asyncio
async def test_acronyms_merge_and_delete(monkeypatch, dummy_bot, fake_room_msg,
                                         tmp_slang_files):
    main, add, rem = tmp_slang_files
    with open(str(add), "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(["foo", "Bar baz", "testnick"])
    with open(str(rem), "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(["lgtm", "Looks good to me", "testnick"])
    dummy_bot.reset()
    await info_plugin.acronyms_merge_cmd(dummy_bot, "jid", "nick", [],
                                         fake_room_msg, True)
    messages = "\n".join(x[1] for x in dummy_bot.replies)
    assert "merged" in messages.lower()
    # Check that addition and removal queues are empty after merge
    assert not add.exists() and not rem.exists()
    with open(str(main), encoding="utf-8") as f:
        all_lines = f.read()
        assert "foo,Bar baz" in all_lines
        assert "lgtm,Looks good to me" not in all_lines


@pytest.mark.asyncio
async def test_acronyms_delete_by_desc_and_nick(tmp_slang_files, dummy_bot,
                                                fake_room_msg):
    _, add, rem = tmp_slang_files
    with open(str(add), "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(["abcd", "Desc1", "nickA"])
        csv.writer(f).writerow(["abcd", "Desc2", "nickB"])
    with open(str(rem), "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(["def", "Desc3", "nickA"])
        csv.writer(f).writerow(["def", "Desc4", "nickB"])
    dummy_bot.reset()
    await info_plugin.acronyms_delete_cmd(dummy_bot, "jid", "nick",
                                          ["abcd", "Desc1"],
                                          fake_room_msg, True)
    await info_plugin.acronyms_delete_cmd(dummy_bot, "jid", "nick",
                                          ["def", "Desc3"],
                                          fake_room_msg, True)
    with open(str(add), encoding="utf-8") as f:
        add_rows = list(csv.reader(f))
        assert len(add_rows) == 1 and add_rows[0][2] == "nickB"
    with open(str(rem), encoding="utf-8") as f:
        rem_rows = list(csv.reader(f))
        assert len(rem_rows) == 1 and rem_rows[0][2] == "nickB"
    await info_plugin.acronyms_delete_cmd(dummy_bot, "jid", "nick", ["nickB"],
                                          fake_room_msg, True)
    # Confirm files are now empty (not necessarily deleted)
    assert add.read_text().strip() == "" and rem.read_text().strip() == ""

# ---- WIKIPEDIA ----


@pytest.mark.asyncio
async def test_wikipedia_usage(dummy_bot, fake_room_msg):
    dummy_bot.prefix = "!"
    dummy_bot.reset()
    await info_plugin.wikipedia_command(dummy_bot, "jid", "nick", [],
                                        fake_room_msg, True)
    text = "\n".join(str(x) for x in dummy_bot.replies)
    assert "Usage: !wikipedia [en|de] <search term>" in text


@pytest.mark.asyncio
async def test_wikipedia_notfound(monkeypatch, dummy_bot, fake_room_msg):
    monkeypatch.setattr(
        info_plugin, "fetch_wikipedia_summary", lambda term, language=None: None)
    await info_plugin.wikipedia_command(dummy_bot, "jid", "nick",
                                        ["somethingunreal"],
                                        fake_room_msg, True)
    text = "\n".join(str(x) for x in dummy_bot.replies)
    assert "No Wikipedia summary found" in text


@pytest.mark.asyncio
async def test_wikipedia_found(monkeypatch, dummy_bot, fake_room_msg):
    monkeypatch.setattr(
        info_plugin,
        "fetch_wikipedia_summary",
        lambda term, language=None: ("Python", "A summary", "http://wiki/Python"),
    )
    await info_plugin.wikipedia_command(dummy_bot, "jid", "nick",
                                        ["Python"], fake_room_msg, True)
    text = "\n".join(str(x) for x in dummy_bot.replies)
    assert "Wikipedia" in text and "Python" in text


@pytest.mark.asyncio
async def test_wikipedia_language_override(monkeypatch, dummy_bot, fake_room_msg):
    calls = []

    def fake_summary(term, language=None):
        calls.append((term, language))
        return "XMPP", "Summary", f"https://{language}.wikipedia.org/wiki/XMPP"

    monkeypatch.setattr(info_plugin, "fetch_wikipedia_summary", fake_summary)
    monkeypatch.setattr(info_plugin, "WIKIPEDIA_LANGUAGE", "en")

    await info_plugin.wikipedia_command(
        dummy_bot, "jid", "nick", ["de", "XMPP"], fake_room_msg, True
    )

    assert calls == [("XMPP", "de")]
    assert "https://de.wikipedia.org/wiki/XMPP" in str(dummy_bot.replies[-1])


@pytest.mark.asyncio
async def test_wikipedia_uses_configured_default_language(
    monkeypatch, dummy_bot, fake_room_msg
):
    calls = []

    def fake_summary(term, language=None):
        calls.append((term, language))
        return "XMPP", "Summary", f"https://{language}.wikipedia.org/wiki/XMPP"

    monkeypatch.setattr(info_plugin, "fetch_wikipedia_summary", fake_summary)
    monkeypatch.setattr(info_plugin, "WIKIPEDIA_LANGUAGE", "de")

    await info_plugin.wikipedia_command(
        dummy_bot, "jid", "nick", ["XMPP"], fake_room_msg, True
    )

    assert calls == [("XMPP", "de")]


# ---- INFO ROOM TOGGLE ----

@pytest.mark.asyncio
async def test_information_command_toggle_on(dummy_bot, fake_room_msg):
    await info_plugin.information_command(dummy_bot, "jid", "nick", [],
                                          fake_room_msg, True)
    text = "\n".join(str(x) for x in dummy_bot.replies)
    assert "Usage" in text or "usage" in text


@pytest.mark.asyncio
async def test_fetch_wikipedia_summary_paths(monkeypatch):
    class FetchResult:
        def __init__(self, status, data, content_type="application/json"):
            self.status = status
            self.text = json.dumps(data)
            self.content_type = content_type

    calls = []

    async def fake_fetch_text(url, **kwargs):
        calls.append((url, kwargs))
        return FetchResult(200, {
            "title": "Example",
            "extract": "Summary text",
            "content_urls": {"desktop": {"page": "https://example.org/wiki/Example"}},
        })

    monkeypatch.setattr(info_plugin, "fetch_text", fake_fetch_text)
    assert await info_plugin.fetch_wikipedia_summary("Example Page") == (
        "Example", "Summary text", "https://example.org/wiki/Example"
    )
    assert "https://en.wikipedia.org/" in calls[0][0]
    assert "Example%20Page" in calls[0][0]
    assert calls[0][1]["headers"]["User-Agent"] == info_plugin.INFO_HTTP_USER_AGENT
    assert calls[0][1]["timeout_seconds"] == info_plugin.INFO_HTTP_TIMEOUT

    calls.clear()
    assert await info_plugin.fetch_wikipedia_summary("XMPP", "de") == (
        "Example", "Summary text", "https://example.org/wiki/Example"
    )
    assert "https://de.wikipedia.org/" in calls[0][0]

    async def disambiguation_fetch_text(*args, **kwargs):
        return FetchResult(200, {
            "type": "disambiguation",
            "titles": {"canonical": "Example_(disambiguation)"},
        })

    monkeypatch.setattr(info_plugin, "fetch_text", disambiguation_fetch_text)
    assert await info_plugin.fetch_wikipedia_summary("Example") == (
        "Example_(disambiguation)", "Disambiguation page", None
    )

    async def missing_fetch_text(*args, **kwargs):
        return FetchResult(404, {})

    monkeypatch.setattr(info_plugin, "fetch_text", missing_fetch_text)
    assert await info_plugin.fetch_wikipedia_summary("Missing") is None

    async def incomplete_fetch_text(*args, **kwargs):
        return FetchResult(200, {"title": "Incomplete"})

    monkeypatch.setattr(info_plugin, "fetch_text", incomplete_fetch_text)
    assert await info_plugin.fetch_wikipedia_summary("Incomplete") is None


@pytest.mark.asyncio
async def test_wikipedia_invalid_json_is_reported_as_temporary_failure(
    monkeypatch, dummy_bot, fake_room_msg
):
    class FetchResult:
        status = 200
        text = ""
        content_type = "text/html"

    async def fake_fetch_text(*args, **kwargs):
        return FetchResult()

    monkeypatch.setattr(info_plugin, "fetch_text", fake_fetch_text)

    await info_plugin.wikipedia_command(
        dummy_bot, "jid", "nick", ["XMPP"], fake_room_msg, False
    )

    assert "temporarily unavailable" in dummy_bot.replies[-1][1]

@pytest.mark.asyncio
async def test_info_store_getter_uses_information_store():
    marker = object()
    bot = MagicMock()
    bot.db.users.plugin.return_value = marker
    assert await info_plugin.get_info_store(bot) is marker
    bot.db.users.plugin.assert_called_once_with("information")


def test_acronym_removal_short_aliases_preserve_two_stage_workflow():
    remove_names = {
        name for name, _cmd in info_plugin.acronyms_remove_cmd.__commands__
    }
    delete_names = {
        name for name, _cmd in info_plugin.acronyms_delete_cmd.__commands__
    }

    assert {"acronyms remove", "acronyms rm"} <= remove_names
    assert {"acronyms delete", "acronyms del"} <= delete_names
