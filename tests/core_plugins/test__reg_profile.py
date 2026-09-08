import pytest
import types
import builtins

import core_plugins._reg_profile as _reg_profile


# --- HASH HELPERS ---

def test_sha1_bytes_and_consistency():
    data = b"hello world"
    result = _reg_profile.sha1(data)

    assert isinstance(result, str)
    # SHA1 of "hello world" in hex:
    assert result == "2aae6c35c94fcfb415dbe95f408b9ce91ee846ed"


def test_read_hash_file_exists(tmp_path):
    path = tmp_path / "hashfile"
    path.write_text(" hashvalue \n")

    # Should read and strip whitespace
    assert _reg_profile.read_hash(str(path)) == "hashvalue"


def test_read_hash_file_not_exists(tmp_path):
    path = tmp_path / "doesnotexist"

    assert _reg_profile.read_hash(str(path)) is None


def test_read_hash_file_error(monkeypatch, tmp_path):
    # Patch open to raise exception
    path = tmp_path / "hashfile"
    path.write_text("somevalue")

    def raise_ioerror_read(*a, **k):
        raise IOError("READ")

    monkeypatch.setattr(builtins, "open", raise_ioerror_read)

    assert _reg_profile.read_hash(str(path)) is None


def test_write_hash_file_success(tmp_path):
    path = tmp_path / "writefile"

    _reg_profile.write_hash(str(path), "xyz")

    assert path.read_text() == "xyz"


def test_write_hash_file_error(monkeypatch, tmp_path):
    path = tmp_path / "cannotwrite"

    def raise_ioerror_write(*a, **k):
        raise IOError("WRITE")

    monkeypatch.setattr(builtins, "open", raise_ioerror_write)

    # Should not raise, swallows error
    _reg_profile.write_hash(str(path), "abc")


def test_load_vcard_xml_does_not_create_bytecode_cache(tmp_path):
    vcard_py = tmp_path / "vcard.py"
    vcard_py.write_text('VCARD = "<vCard/>"\n', encoding="utf-8")

    assert _reg_profile._load_vcard_xml(vcard_py) == "<vCard/>"
    assert not (tmp_path / "__pycache__").exists()


# --- VCARD BUILDER ---

def test_build_vcard_basic_and_nested():
    # Fake card like slixmpp.xmlstream.stanzabase.ElementBase API
    class FakeCard(dict):
        def __getitem__(self, k):
            if k not in self:
                self[k] = FakeCard()
            return super().__getitem__(k)

        def __setitem__(self, k, v):
            super().__setitem__(k, v)

    card = FakeCard()
    data = {
        "FN": "Test Bot",
        "NICKNAME": "envsbot",
        "ADR": {"COUNTRY": "Wonderland", "CITY": "Imaginaria"},
    }

    _reg_profile.build_vcard(card, data)

    assert card["FN"] == "Test Bot"
    assert card["NICKNAME"] == "envsbot"
    assert isinstance(card["ADR"], dict)
    assert card["ADR"]["COUNTRY"] == "Wonderland"
    assert card["ADR"]["CITY"] == "Imaginaria"


# --- update_vcard ---

@pytest.mark.asyncio
async def test_profile_network_updates_skip_when_session_is_not_ready(monkeypatch):
    warnings = []
    bot = types.SimpleNamespace(
        session_ready=types.SimpleNamespace(is_set=lambda: False),
    )
    monkeypatch.setattr(
        _reg_profile,
        "log",
        types.SimpleNamespace(warning=lambda msg: warnings.append(msg)),
    )
    monkeypatch.setattr(
        _reg_profile,
        "vcard_file",
        lambda _config: (_ for _ in ()).throw(AssertionError("vcard_file called")),
    )

    await _reg_profile.update_vcard(bot)
    await _reg_profile.update_avatar(bot)

    assert len(warnings) == 2
    assert all("XMPP session is not ready" in message for message in warnings)


@pytest.mark.asyncio
async def test_update_vcard_py_missing(monkeypatch):
    log_msgs = []

    monkeypatch.setattr(_reg_profile.os.path, "exists", lambda p: False)
    monkeypatch.setattr(_reg_profile.log, "warning",
                        lambda msg: log_msgs.append(msg))

    bot = object()

    await _reg_profile.update_vcard(bot)

    assert log_msgs and "vcard.py does not exist" in log_msgs[0]


@pytest.mark.asyncio
async def test_update_vcard_import_error(monkeypatch, tmp_path):
    vcard_py = tmp_path / "vcard.py"
    vcard_py.write_text("raise Exception('fail')")
    monkeypatch.setattr(_reg_profile, "vcard_file", lambda _config: vcard_py)

    monkeypatch.setattr(_reg_profile.os.path, "exists", lambda p: True)
    monkeypatch.setattr(_reg_profile.os.path, "abspath",
                        lambda p: str(vcard_py.parent))
    monkeypatch.setattr(_reg_profile.os.path, "dirname",
                        lambda p: str(vcard_py.parent))

    error_msgs = []
    monkeypatch.setattr(
        _reg_profile,
        "log",
        types.SimpleNamespace(error=lambda msg: error_msgs.append(msg)),
    )

    await _reg_profile.update_vcard(object())

    assert any("Error importing vcard.py" in m for m in error_msgs)


@pytest.mark.asyncio
async def test_update_vcard_not_str(monkeypatch, tmp_path):
    vcard_py = tmp_path / "vcard.py"
    vcard_py.write_text("VCARD = 12345")
    monkeypatch.setattr(_reg_profile, "vcard_file", lambda _config: vcard_py)

    monkeypatch.setattr(_reg_profile.os.path, "exists", lambda p: True)
    monkeypatch.setattr(_reg_profile.os.path, "abspath",
                        lambda p: str(vcard_py.parent))
    monkeypatch.setattr(_reg_profile.os.path, "dirname",
                        lambda p: str(vcard_py.parent))

    error_msgs = []
    monkeypatch.setattr(
        _reg_profile,
        "log",
        types.SimpleNamespace(error=lambda msg: error_msgs.append(msg)),
    )

    await _reg_profile.update_vcard(object())

    assert any(
        "VCARD variable in vcard.py is not a string" in m for m in error_msgs)


@pytest.mark.asyncio
async def test_update_vcard_no_change(monkeypatch, tmp_path):
    vcard_py = tmp_path / "vcard.py"
    vcard_text = "bot"
    vcard_py.write_text(f"VCARD = '''{vcard_text}'''")
    monkeypatch.setattr(_reg_profile, "vcard_file", lambda _config: vcard_py)

    # patch file system lookups
    monkeypatch.setattr(_reg_profile.os.path, "exists", lambda p: True)
    monkeypatch.setattr(_reg_profile.os.path, "abspath",
                        lambda p: str(vcard_py.parent))
    monkeypatch.setattr(_reg_profile.os.path, "dirname",
                        lambda p: str(vcard_py.parent))

    # patch SHA1 to return fixed; patch read_hash to match
    fixed_hash = "deadbeef"
    monkeypatch.setattr(_reg_profile, "sha1", lambda data: fixed_hash)
    monkeypatch.setattr(_reg_profile, "read_hash", lambda path: fixed_hash)

    debug_msgs = []
    monkeypatch.setattr(
        _reg_profile,
        "log",
        types.SimpleNamespace(debug=lambda msg: debug_msgs.append(msg)),
    )

    await _reg_profile.update_vcard(object())

    assert any("unchanged" in m for m in debug_msgs)


@pytest.mark.asyncio
async def test_update_vcard_success(monkeypatch, tmp_path):
    vcard_py = tmp_path / "vcard.py"
    vcard_text = "<vCard xmlns='vcard-temp'><FN>bot</FN></vCard>"
    vcard_py.write_text(f"VCARD = '''{vcard_text}'''")
    monkeypatch.setattr(_reg_profile, "vcard_file", lambda _config: vcard_py)

    monkeypatch.setattr(_reg_profile.os.path, "exists", lambda p: True)
    monkeypatch.setattr(_reg_profile.os.path, "abspath",
                        lambda p: str(vcard_py.parent))
    monkeypatch.setattr(_reg_profile.os.path, "dirname",
                        lambda p: str(vcard_py.parent))

    # simulate hash changed
    monkeypatch.setattr(_reg_profile, "sha1", lambda b: "newhash12")
    monkeypatch.setattr(_reg_profile, "read_hash", lambda p: "different_hash")

    write_called = []
    monkeypatch.setattr(
        _reg_profile,
        "write_hash",
        lambda path, value: write_called.append((path, value)),
    )

    class Bot:
        def make_iq_set(self):
            class IQ:
                def __init__(self):
                    self.elem = None
                    self.sent = False

                def append(self, elem):
                    self.elem = elem

                async def send(self):
                    self.sent = True

            return IQ()

    info_msgs = []
    error_msgs = []
    monkeypatch.setattr(
        _reg_profile,
        "log",
        types.SimpleNamespace(
            info=lambda msg: info_msgs.append(msg),
            error=lambda msg: error_msgs.append(msg),
        ),
    )

    await _reg_profile.update_vcard(Bot())

    assert not error_msgs
    assert any("updated" in m for m in info_msgs)
    assert write_called
    assert write_called[0][1] == "newhash12"


# More: update_avatar setup_profile, on_load, on_ready

@pytest.mark.asyncio
async def test_cache_xep0153_hash_supports_async_api_and_missing_api():
    calls = []

    async def set_hash(jid, *, args):
        calls.append((jid, args))

    boundjid = types.SimpleNamespace(
        bare="bot@example.org",
        full="bot@example.org/envsbot",
    )

    class AvatarBot(dict):
        def __init__(self, plugins):
            super().__init__(plugins)
            self.boundjid = boundjid

    bot = AvatarBot({
        "xep_0153": types.SimpleNamespace(api={"set_hash": set_hash}),
    })

    assert await _reg_profile.cache_xep0153_hash(bot, "abc123") is True
    assert calls == [(boundjid, "abc123")]

    bot["xep_0153"] = types.SimpleNamespace()
    assert await _reg_profile.cache_xep0153_hash(bot, "abc123") is False


class _AvatarBot(dict):
    def __init__(self, plugins):
        super().__init__(plugins)
        self.boundjid = types.SimpleNamespace(bare="bot@example.org")
        self.avatar_hash = None
        self.presence_calls = 0
        self.presence = types.SimpleNamespace(broadcast=self._broadcast)

    def _broadcast(self):
        self.presence_calls += 1


@pytest.mark.asyncio
async def test_update_avatar_unchanged_seeds_hash_and_broadcasts(monkeypatch):
    payload = types.SimpleNamespace(
        data=b"avatar-bytes",
        media_type="image/jpeg",
        sha1="hash1",
    )
    bot = _AvatarBot({"xep_0153": types.SimpleNamespace()})
    published = []

    monkeypatch.setattr(
        _reg_profile,
        "config",
        {"avatar": "avatar.jpg", "avatar_type": "image/jpeg"},
    )
    monkeypatch.setattr(_reg_profile, "resolve_bundled_asset", lambda path: path)
    monkeypatch.setattr(
        _reg_profile,
        "load_avatar_payload",
        lambda path, *, media_type: payload,
    )
    monkeypatch.setattr(_reg_profile, "read_hash", lambda path: "v2:hash1")

    async def cache_hash(current_bot, image_hash):
        assert current_bot is bot
        assert image_hash == "hash1"
        return True

    async def publish(*args, **kwargs):
        published.append((args, kwargs))

    monkeypatch.setattr(_reg_profile, "cache_xep0153_hash", cache_hash)
    monkeypatch.setattr(_reg_profile, "publish_xep0084_avatar", publish)

    await _reg_profile.update_avatar(bot)

    assert published == []
    assert bot.avatar_hash == "hash1"
    assert bot.presence_calls == 1


@pytest.mark.asyncio
async def test_update_avatar_happy_path_uses_shared_payload(monkeypatch):
    payload = types.SimpleNamespace(
        data=b"avatar-bytes",
        media_type="image/png",
        sha1="newhash",
    )
    xep0084_calls = []
    xep0153_calls = []
    writes = []

    async def set_avatar(**kwargs):
        xep0153_calls.append(kwargs)

    bot = _AvatarBot({
        "xep_0153": types.SimpleNamespace(set_avatar=set_avatar),
    })

    monkeypatch.setattr(
        _reg_profile,
        "config",
        {"avatar": "avatar.png", "avatar_type": "image/png"},
    )
    monkeypatch.setattr(_reg_profile, "resolve_bundled_asset", lambda path: path)
    monkeypatch.setattr(
        _reg_profile,
        "load_avatar_payload",
        lambda path, *, media_type: payload,
    )
    monkeypatch.setattr(_reg_profile, "read_hash", lambda path: "oldhash")
    monkeypatch.setattr(
        _reg_profile,
        "write_hash",
        lambda path, value: writes.append((path, value)),
    )

    async def publish(current_bot, current_payload):
        xep0084_calls.append((current_bot, current_payload))

    async def cache_hash(current_bot, image_hash):
        assert current_bot is bot
        assert image_hash == "newhash"
        return True

    monkeypatch.setattr(_reg_profile, "publish_xep0084_avatar", publish)
    monkeypatch.setattr(_reg_profile, "cache_xep0153_hash", cache_hash)

    await _reg_profile.update_avatar(bot)

    assert xep0084_calls == [(bot, payload)]
    assert xep0153_calls == [
        {
            "jid": "bot@example.org",
            "avatar": b"avatar-bytes",
            "mtype": "image/png",
        }
    ]
    assert writes == [(_reg_profile.AVATAR_HASH_FILE, "v2:newhash")]
    assert bot.avatar_hash == "newhash"
    assert bot.presence_calls == 1


@pytest.mark.asyncio
async def test_update_avatar_xep0084_failure_does_not_block_legacy_path(monkeypatch):
    payload = types.SimpleNamespace(
        data=b"avatar-bytes",
        media_type="image/jpeg",
        sha1="newhash",
    )
    xep0153_calls = []
    writes = []

    async def set_avatar(**kwargs):
        xep0153_calls.append(kwargs)

    bot = _AvatarBot({
        "xep_0153": types.SimpleNamespace(set_avatar=set_avatar),
    })

    monkeypatch.setattr(
        _reg_profile,
        "config",
        {"avatar": "avatar.jpg", "avatar_type": "image/jpeg"},
    )
    monkeypatch.setattr(_reg_profile, "resolve_bundled_asset", lambda path: path)
    monkeypatch.setattr(
        _reg_profile,
        "load_avatar_payload",
        lambda path, *, media_type: payload,
    )
    monkeypatch.setattr(_reg_profile, "read_hash", lambda path: "oldhash")
    monkeypatch.setattr(
        _reg_profile,
        "write_hash",
        lambda path, value: writes.append((path, value)),
    )

    async def fail_modern(_bot, _payload):
        raise RuntimeError("pep unavailable")

    async def cache_hash(_bot, _image_hash):
        return True

    monkeypatch.setattr(_reg_profile, "publish_xep0084_avatar", fail_modern)
    monkeypatch.setattr(_reg_profile, "cache_xep0153_hash", cache_hash)

    await _reg_profile.update_avatar(bot)

    assert len(xep0153_calls) == 1
    assert bot.avatar_hash == "newhash"
    assert bot.presence_calls == 1
    assert writes == []


@pytest.mark.asyncio
async def test_update_avatar_does_not_advertise_hash_when_cache_seed_fails(monkeypatch):
    payload = types.SimpleNamespace(
        data=b"avatar-bytes",
        media_type="image/png",
        sha1="newhash",
    )

    async def set_avatar(**_kwargs):
        return None

    bot = _AvatarBot({
        "xep_0153": types.SimpleNamespace(set_avatar=set_avatar),
    })

    monkeypatch.setattr(
        _reg_profile,
        "config",
        {"avatar": "avatar.png", "avatar_type": "image/png"},
    )
    monkeypatch.setattr(_reg_profile, "resolve_bundled_asset", lambda path: path)
    monkeypatch.setattr(
        _reg_profile,
        "load_avatar_payload",
        lambda path, *, media_type: payload,
    )
    monkeypatch.setattr(_reg_profile, "read_hash", lambda path: "oldhash")
    monkeypatch.setattr(_reg_profile, "write_hash", lambda path, value: None)

    async def publish(_bot, _payload):
        return None

    async def reject_cache(_bot, _image_hash):
        return False

    monkeypatch.setattr(_reg_profile, "publish_xep0084_avatar", publish)
    monkeypatch.setattr(_reg_profile, "cache_xep0153_hash", reject_cache)

    await _reg_profile.update_avatar(bot)

    assert bot.avatar_hash is None
    assert bot.presence_calls == 0


@pytest.mark.asyncio
async def test_update_avatar_handles_missing_and_invalid_avatar(monkeypatch, tmp_path):
    bot = _AvatarBot({})

    monkeypatch.setattr(_reg_profile, "config", {})
    await _reg_profile.update_avatar(bot)

    monkeypatch.setattr(
        _reg_profile,
        "config",
        {"avatar": "missing.png", "avatar_type": "image/png"},
    )

    def missing(_path):
        raise FileNotFoundError

    monkeypatch.setattr(_reg_profile, "resolve_bundled_asset", missing)
    await _reg_profile.update_avatar(bot)

    avatar = tmp_path / "avatar.webp"
    avatar.write_bytes(b"webp")
    monkeypatch.setattr(
        _reg_profile,
        "config",
        {"avatar": str(avatar), "avatar_type": "image/webp"},
    )
    monkeypatch.setattr(_reg_profile, "resolve_bundled_asset", lambda path: path)

    def invalid(_path, *, media_type):
        assert media_type == "image/webp"
        raise ValueError("avatar must use image/png or image/jpeg")

    monkeypatch.setattr(_reg_profile, "load_avatar_payload", invalid)
    await _reg_profile.update_avatar(bot)


@pytest.mark.asyncio
async def test_setup_profile_user_entry(monkeypatch):
    # happy path: user exists
    class FakeDBUsers:
        async def get(self, jid):
            return {"jid": jid}

        async def create(self, jid, nick):
            assert False

    class FakeBot:
        boundjid = type("bjid", (), {"bare": "jidval"})()
        db = types.SimpleNamespace(users=FakeDBUsers())

    wrote = []

    monkeypatch.setattr(_reg_profile, "update_vcard",
                        lambda bot: _awaitable(None))
    monkeypatch.setattr(_reg_profile, "update_avatar",
                        lambda bot: _awaitable(None))
    monkeypatch.setattr(
        _reg_profile,
        "log",
        types.SimpleNamespace(
            info=lambda m: wrote.append(m),
            error=lambda m: None,
        ),
    )
    monkeypatch.setattr(_reg_profile, "config", {"nick": "botnick"})

    await _reg_profile.setup_profile(FakeBot())

    assert wrote


@pytest.mark.asyncio
async def test_setup_profile_user_created(monkeypatch):
    # happy path: user missing, creation succeeds
    called = []

    class FakeDBUsers:
        async def get(self, jid):
            return None

        async def create(self, jid, nick):
            called.append(("create", jid, nick))

    class FakeBot:
        boundjid = type("bjid", (), {"bare": "jidval"})()
        db = types.SimpleNamespace(users=FakeDBUsers())

    monkeypatch.setattr(_reg_profile, "update_vcard",
                        lambda bot: _awaitable(None))
    monkeypatch.setattr(_reg_profile, "update_avatar",
                        lambda bot: _awaitable(None))
    monkeypatch.setattr(
        _reg_profile,
        "log",
        types.SimpleNamespace(
            info=lambda m: called.append(m),
            error=lambda m: None,
        ),
    )
    monkeypatch.setattr(_reg_profile, "config", {"nick": "nick"})

    await _reg_profile.setup_profile(FakeBot())

    assert any("create" in str(x) for x in called)


@pytest.mark.asyncio
async def test_setup_profile_user_create_error(monkeypatch):
    # error creating
    called = []

    class FakeDBUsers:
        async def get(self, jid):
            return None

        async def create(self, jid, nick):
            raise Exception("fail!")

    class FakeBot:
        boundjid = type("bjid", (), {"bare": "jidval"})()
        db = types.SimpleNamespace(users=FakeDBUsers())

    monkeypatch.setattr(_reg_profile, "update_vcard",
                        lambda bot: _awaitable(None))
    monkeypatch.setattr(_reg_profile, "update_avatar",
                        lambda bot: _awaitable(None))
    monkeypatch.setattr(
        _reg_profile,
        "log",
        types.SimpleNamespace(
            info=lambda m: called.append(m),
            error=lambda m: called.append("error"),
        ),
    )
    monkeypatch.setattr(_reg_profile, "config", {"nick": "nick"})

    await _reg_profile.setup_profile(FakeBot())

    assert "error" in called


@pytest.mark.asyncio
async def test_on_load_and_on_ready(monkeypatch):
    called = []

    class DummyStore:
        async def set(self, jid, k, v):
            called.append((jid, k, v))

    class DummyUsers:
        def plugin(self, name):
            return DummyStore()

    class Bot:
        def register_plugin(self, name):
            called.append(name)

        boundjid = type("Jid", (), {"bare": "jidval"})()
        db = types.SimpleNamespace(users=DummyUsers())

    async def fake_setup_profile(bot):
        called.append("setup_profile")

    monkeypatch.setattr(_reg_profile, "setup_profile", fake_setup_profile)

    await _reg_profile.on_load(Bot())

    assert "setup_profile" not in called
    assert "xep_0054" in called
    assert "xep_0084" in called
    assert "xep_0153" in called
    assert "xep_0163" in called

    monkeypatch.setattr(_reg_profile, "config", {
                        "timezone": "Europe/Stockholm"})

    await _reg_profile.on_ready(Bot())

    assert "setup_profile" in called
    assert any(isinstance(x, tuple) and x[1] == "TIMEZONE" for x in called)


def _awaitable(val):
    async def awt(*a, **k):
        return val

    return awt()
