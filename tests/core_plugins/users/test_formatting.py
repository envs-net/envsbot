from .helpers import *  # noqa: F401,F403


@pytest.mark.asyncio
async def test_on_load_initializes_or_skips(mock_bot):
    mock_bot.db = None
    await users_mod.on_load(mock_bot)

    store = AsyncMock()
    store.get_global = AsyncMock(return_value=None)
    mock_bot.db = types.SimpleNamespace(
        users=types.SimpleNamespace(plugin=MagicMock(return_value=store))
    )
    await users_mod.on_load(mock_bot)
    assert mock_bot.db.users._nick_index == {}
    assert mock_bot.bot_plugins.register_event.call_count >= 2


@pytest.mark.asyncio
async def test_user_audit_helper_is_best_effort(monkeypatch, mock_bot):
    async def broken_audit_event(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(users_mod, "audit_event", broken_audit_event)
    await users_mod._write_user_audit(
        mock_bot,
        "user_role_change_denied",
        actor="admin@example.org",
        target="target@example.org",
        details={"reason": "test"},
    )


def test_normalize_affiliation_result_accepts_dict_keys():
    assert users_mod._normalize_affiliation_result({
        "alice@example.org/resource": {},
    }) == {"alice@example.org"}
