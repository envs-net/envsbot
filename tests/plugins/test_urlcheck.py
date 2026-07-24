import pytest
from unittest.mock import MagicMock, AsyncMock
import types
from urllib.parse import urljoin

import plugins.urlcheck as urlcheck

# ---- msg class for all event handler tests ----


class MsgNS(types.SimpleNamespace):
    def __getitem__(self, key):
        return getattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)


@pytest.fixture(autouse=True)
def reset_urlcheck_runtime_state():
    """Keep URL check tests independent when mutmut reuses the process."""
    urlcheck._url_timestamps.clear()
    urlcheck.JOINED_ROOMS.clear()
    yield
    urlcheck._url_timestamps.clear()
    urlcheck.JOINED_ROOMS.clear()


@pytest.fixture
def fake_bot(monkeypatch):
    bot = MagicMock()

    class FakeDB:
        users = MagicMock()
    bot.db = FakeDB()
    # Simulate a real async DummyStore with async get_global/set_global

    class DummyStore:
        def __init__(self):
            self.data = {}

        async def get_global(self, key, default=None):
            return dict(self.data)

        async def set_global(self, key, value):
            self.data.update(value)
    dummy_store = DummyStore()

    def plugin_side_effect(key):
        assert key == "urlcheck"
        return dummy_store
    # <-- returns DummyStore, not AsyncMock/coroutine!
    bot.db.users.plugin = plugin_side_effect
    bot._test_urlcheck_store = dummy_store
    bot._replies = []
    bot.reply = lambda msg, body, **kwargs: bot._replies.append(
        (msg, body, kwargs))

    class DummyMsg:
        def __init__(self): self.sent = False
        def send(self): self.sent = True
        def __setitem__(self, k, v): setattr(self, k, v)
        def __getitem__(self, k): return getattr(self, k)
        xml = types.SimpleNamespace(findall=lambda self, *a, **k: [])
    bot.make_message = lambda **kwargs: DummyMsg()

    async def safe_send(message):
        message.send()
        return True

    bot._safe_send_message = AsyncMock(side_effect=safe_send)
    return bot


@pytest.mark.asyncio
async def test_urlcheck_toggle_commands(fake_bot):
    store = fake_bot._test_urlcheck_store
    store.data.clear()
    for cmd in [["on"], ["off"], ["status"]]:
        msg = {"from": type("F", (), {"bare": "room@conf"})
               (), "body": ",urlcheck " + (cmd[0] if cmd else "")}
        await urlcheck.urlcheck_command(fake_bot, "sender", "nick", cmd,
                                        msg, True)
    assert isinstance(await store.get_global("any"), dict)
    msg = {"from": type("F", (), {"bare": "room@conf"})
           (), "body": ",urlcheck "}
    await urlcheck.urlcheck_command(fake_bot, "sender", "nick", [], msg, True)


def test_resolve_url_with_urljoin():
    # Only test urljoin, since there is no urlcheck._normalize_url
    base = "https://foo.com/x/"
    assert urljoin(base, "/b") == "https://foo.com/b"
    assert urljoin("https://foo.com/",
                   "http://other.net") == "http://other.net"
    assert urljoin("https://site/root/",
                   "dir/page.html") == "https://site/root/dir/page.html"


@pytest.mark.asyncio
async def test_fetch_url_title_basic(monkeypatch):
    async def fake_fetch_preview(url, **kwargs):
        assert url == "https://xx"
        assert kwargs["stop_when"](
            b"<title>X</title><meta name='description' content='desc'>"
        )
        return types.SimpleNamespace(
            url="https://final",
            status=200,
            content_type="text/html",
            content_length=4096,
            body=b"<title>X</title><meta name='description' content='desc'>",
        )

    monkeypatch.setattr(urlcheck, "fetch_preview", fake_fetch_preview)
    final_url, status, ctype, title, content_size, desc = await urlcheck.fetch_url_title(
        "https://xx")
    assert final_url == "https://final"
    assert status == 200
    assert "text/html" in ctype
    assert title == "X"
    assert content_size == 4096
    assert desc == "desc"


def test_html_metadata_preview_complete_handles_title_and_head():
    assert not urlcheck._html_metadata_preview_complete(b"<html><title>X")
    assert urlcheck._html_metadata_preview_complete(b"<title>X</title></head>")
    assert urlcheck._html_metadata_preview_complete(
        b"<title>X</title><meta name=\"description\" content=\"d\">"
    )


@pytest.mark.asyncio
async def test_fetch_url_title_accepts_truncated_html_with_early_title(monkeypatch):
    async def fake_fetch_preview(url, **kwargs):
        return types.SimpleNamespace(
            url=url,
            status=200,
            content_type="text/html; charset=utf-8",
            content_length=800000,
            body=b"<html><head><title>Large page</title></head>",
        )

    monkeypatch.setattr(urlcheck, "fetch_preview", fake_fetch_preview)

    final_url, status, ctype, title, content_size, desc = await urlcheck.fetch_url_title(
        "https://example.org/large"
    )

    assert final_url == "https://example.org/large"
    assert status == 200
    assert "text/html" in ctype
    assert title == "Large page"
    assert content_size == 800000
    assert desc is None


@pytest.mark.asyncio
async def test_fetch_url_title_blocks_unsafe_initial_url():
    with pytest.raises(urlcheck.UnsafeFetchURL):
        await urlcheck.fetch_url_title("http://127.0.0.1/private")


@pytest.mark.asyncio
async def test_fetch_url_title_blocks_unsafe_redirect(monkeypatch):
    async def blocked_fetch_preview(*args, **kwargs):
        raise urlcheck.UnsafeFetchURL("blocked")

    monkeypatch.setattr(urlcheck, "fetch_preview", blocked_fetch_preview)

    with pytest.raises(urlcheck.UnsafeFetchURL):
        await urlcheck.fetch_url_title("https://example.org/feed")


def test_youtube_regex():
    m = urlcheck.YOUTUBE_RE.search("https://youtu.be/abcdefghijk")
    assert m
    assert m.group(1) == "abcdefghijk"
    m = urlcheck.YOUTUBE_RE.search("https://youtube.com/watch?v=abcdefghijk")
    assert m
    assert m.group(2) == "abcdefghijk"


@pytest.mark.asyncio
async def test_fetch_youtube_info(monkeypatch):
    urlcheck.config["youtube_api_key"] = "fake-api-key"

    async def fake_fetch_json(url, **kwargs):
        return types.SimpleNamespace(status=200, data={"items": [{
            "snippet": {"title": "t", "channelTitle": "ch",
                        "publishedAt": "2022-01-01T00:00:00Z"},
            "statistics": {"viewCount": "1"},
            "contentDetails": {"duration": "PT12M34S"}
        }]})

    monkeypatch.setattr(urlcheck, "fetch_json", fake_fetch_json)
    val = await urlcheck.fetch_youtube_info("https://youtu.be/12345678901")
    assert isinstance(val, tuple)
    assert "ch" in val[0]

# ---------- EVENT HANDLER (on_groupchat_message) TESTS ----------


def msg_ns_dict(**kwargs):
    class Msg(MsgNS):  # uses MsgNS with .get, __getitem__
        pass
    return Msg(**kwargs)


@pytest.mark.asyncio
async def test_on_groupchat_message_disabled_does_nothing(fake_bot,
                                                          monkeypatch):
    store = fake_bot._test_urlcheck_store
    store.data.clear()
    room_jid = "room1@conf"
    store.data[room_jid] = False
    urlcheck.JOINED_ROOMS[room_jid] = {"nick": "me"}
    msg = msg_ns_dict(
        **{"from": msg_ns_dict(bare=room_jid, resource="user1"),
           "mucnick": "user1",
           "body": "http://test.site",
           "type": "groupchat",
           "xml": types.SimpleNamespace(find=lambda p: None)}
    )
    monkeypatch.setattr(urlcheck, "fetch_url_title", lambda *a,
                        **k: pytest.fail("fetch_url_title called"
                                         " when feature off"))
    await urlcheck.on_groupchat_message(fake_bot, msg)
    assert fake_bot._replies == []


@pytest.mark.asyncio
async def test_on_groupchat_message_self_suppression(fake_bot, monkeypatch):
    store = fake_bot._test_urlcheck_store
    store.data["room2@conf"] = True
    urlcheck.JOINED_ROOMS["room2@conf"] = {"nick": "botnick"}
    msg = msg_ns_dict(
        **{"from": msg_ns_dict(bare="room2@conf", resource="botnick"),
           "mucnick": "botnick",
           "body": "https://some.url",
           "type": "groupchat",
           "xml": types.SimpleNamespace(find=lambda p: None)}
    )
    monkeypatch.setattr(urlcheck, "fetch_url_title", lambda *a, **
                        k: pytest.fail("bot's own messages should"
                                       " not be handled"))
    await urlcheck.on_groupchat_message(fake_bot, msg)
    assert fake_bot._replies == []


@pytest.mark.asyncio
async def test_on_groupchat_message_regular_url(fake_bot, monkeypatch):
    store = fake_bot._test_urlcheck_store
    store.data["room3@conf"] = True
    urlcheck.JOINED_ROOMS["room3@conf"] = {"nick": "someone"}
    monkeypatch.setattr(
        urlcheck,
        "fetch_url_title",
        AsyncMock(return_value=("http://real", 200, "text/html",
                                "HTML Title", 123, "mydesc")),
    )
    monkeypatch.setattr(urlcheck, "is_youtube_url", lambda url: False)
    monkeypatch.setattr(
        urlcheck, "has_xep_0392_link_metadata", lambda msg: False)
    called_send = []
    orig_make_message = fake_bot.make_message

    def fake_make_message(**kwargs):
        m = orig_make_message(**kwargs)

        def send():
            called_send.append(True)
        m.send = send
        return m
    fake_bot.make_message = fake_make_message
    msg = msg_ns_dict(
        **{"from": msg_ns_dict(bare="room3@conf", resource="alice"),
           "mucnick": "alice",
           "body": "https://with.ti.tle",
           "type": "groupchat",
           "xml": types.SimpleNamespace(find=lambda p: None)}
    )
    await urlcheck.on_groupchat_message(fake_bot, msg)
    assert called_send


@pytest.mark.asyncio
async def test_on_groupchat_message_youtube_url(fake_bot, monkeypatch):
    store = fake_bot._test_urlcheck_store
    store.data["room4@conf"] = True
    urlcheck.JOINED_ROOMS["room4@conf"] = {"nick": "someone"}
    monkeypatch.setattr(
        urlcheck,
        "fetch_url_title",
        AsyncMock(return_value=("http://yt.vid", 200, "text/html",
                                "Title", 321, "desc")),
    )
    monkeypatch.setattr(urlcheck, "is_youtube_url", lambda url: True)
    monkeypatch.setattr(urlcheck, "fetch_youtube_info", AsyncMock(
        return_value=("YOUTUBE DESC", "thetitle", "uploader", "4m3s", 123)))
    monkeypatch.setattr(
        urlcheck, "has_xep_0392_link_metadata", lambda msg: False)
    called_send = []
    orig_make_message = fake_bot.make_message

    def fake_make_message(**kwargs):
        m = orig_make_message(**kwargs)

        def send():
            called_send.append(True)
        m.send = send
        return m
    fake_bot.make_message = fake_make_message
    msg = msg_ns_dict(
        **{"from": msg_ns_dict(bare="room4@conf", resource="bob"),
           "mucnick": "bob",
           "body": "https://youtube.com/watch?v=ABCDEFGHIJK",
           "type": "groupchat",
           "xml": types.SimpleNamespace(find=lambda p: None)}
    )
    await urlcheck.on_groupchat_message(fake_bot, msg)
    assert called_send


@pytest.mark.asyncio
async def test_on_groupchat_message_codeblock_and_quote_suppression(
        fake_bot, monkeypatch):
    store = fake_bot._test_urlcheck_store
    store.data["room5@conf"] = True
    urlcheck.JOINED_ROOMS["room5@conf"] = {"nick": "notme"}
    monkeypatch.setattr(urlcheck, "fetch_url_title", lambda *a,
                        **k: pytest.fail("Should not fetch"
                                         " inside codeblock/quote"))
    body = "> quoted url\n"
    body += "```http://codeblock.url```\n"
    body += "    http://indented.url"
    msg = msg_ns_dict(
        **{"from": msg_ns_dict(bare="room5@conf", resource="dave"),
           "mucnick": "dave",
           "body": body,
           "type": "groupchat",
           "xml": types.SimpleNamespace(find=lambda p: None)}
    )
    await urlcheck.on_groupchat_message(fake_bot, msg)
    assert fake_bot._replies == []



def test_extract_urls_handles_multiple_code_blocks():
    text = "\n".join([
        "https://example.org/one",
        "```",
        "https://example.org/hidden-one",
        "```",
        "https://example.org/two",
        "```",
        "https://example.org/hidden-two",
        "```",
        "> https://example.org/quoted",
    ])

    assert urlcheck.extract_urls_from_message_text(text) == [
        "https://example.org/one",
        "https://example.org/two",
    ]


def test_extract_urls_strips_trailing_prose_punctuation():
    text = "See https://example.org/path, and https://example.net/end)."

    assert urlcheck.extract_urls_from_message_text(text) == [
        "https://example.org/path",
        "https://example.net/end",
    ]


def test_extract_urls_handles_inline_code_fences():
    text = "\n".join([
        "https://example.org/before ```https://example.org/hidden``` https://example.org/after",
        "```https://example.org/hidden-inline``` https://example.org/visible",
        "```",
        "https://example.org/hidden-block",
        "``` https://example.org/reopened",
    ])

    assert urlcheck.extract_urls_from_message_text(text) == [
        "https://example.org/before",
        "https://example.org/after",
        "https://example.org/visible",
        "https://example.org/reopened",
    ]


def test_urlcheck_small_helpers_and_on_load(fake_bot):
    assert urlcheck.is_youtube_url("https://youtube.com/watch?v=abcdefghijk")
    assert urlcheck.is_youtube_url("https://youtu.be/abcdefghijk")
    assert not urlcheck.is_youtube_url("https://example.org/watch?v=abcdefghijk")

    class Xml:
        def __init__(self, found):
            self.found = found

        def find(self, pattern):
            assert "rdf-syntax-ns" in pattern
            return object() if self.found else None

    assert urlcheck.has_xep_0392_link_metadata(types.SimpleNamespace(xml=Xml(True)))
    assert not urlcheck.has_xep_0392_link_metadata(types.SimpleNamespace(xml=Xml(False)))

    registered = []
    fake_bot.bot_plugins = MagicMock()
    fake_bot.bot_plugins.register_event.side_effect = lambda *args: registered.append(args)

    async def run():
        await urlcheck.on_load(fake_bot)

    import asyncio
    asyncio.run(run())
    assert registered and registered[0][0:2] == ("urlcheck", "groupchat_message")


@pytest.mark.asyncio
async def test_get_urlcheck_store_uses_exact_plugin_namespace():
    store = object()
    bot = types.SimpleNamespace(
        db=types.SimpleNamespace(
            users=types.SimpleNamespace(plugin=MagicMock(return_value=store)),
        ),
    )

    assert await urlcheck.get_urlcheck_store(bot) is store
    bot.db.users.plugin.assert_called_once_with("urlcheck")
