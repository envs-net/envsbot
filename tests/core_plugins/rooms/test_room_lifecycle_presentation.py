"""Status and inventory must reuse core room lifecycle semantics."""

from __future__ import annotations

from types import SimpleNamespace

from envs_xmpp_core.runtime import RoomLifecycleRegistry

from core_plugins.rooms import commands


def test_room_list_uses_verified_runtime_not_optimistic_lifecycle(monkeypatch):
    registry = RoomLifecycleRegistry()
    room = "room@conference.example.test"
    registry.confirm_self_presence(room, "Bot")
    monkeypatch.setattr(commands, "ROOM_LIFECYCLE", registry)
    monkeypatch.setattr(commands, "JOINED_ROOMS", {})
    bot = SimpleNamespace(presence=SimpleNamespace(joined_rooms={}))
    rows = [(room, "Bot", True, None)]
    view = commands._muc_room_views(bot, rows)[0]
    assert view.joined is False
    assert view.needs_attention
    assert view.state == "attention"
    assert "lifecycle=joined" in view.details


def test_room_list_intentional_leave_does_not_raise_join_alert(monkeypatch):
    registry = RoomLifecycleRegistry()
    room = "room@conference.example.test"
    registry.begin_leave(room)
    monkeypatch.setattr(commands, "ROOM_LIFECYCLE", registry)
    monkeypatch.setattr(commands, "JOINED_ROOMS", {})
    bot = SimpleNamespace(presence=SimpleNamespace(joined_rooms={}))
    view = commands._muc_room_views(bot, [(room, "Bot", True, None)])[0]
    assert view.state == "leaving"
    assert not view.needs_attention


def test_full_status_room_issues_report_lifecycle_failure(monkeypatch):
    from core_plugins import _admin

    registry = RoomLifecycleRegistry()
    room = "failed@conference.example.test"
    registry.mark_failed(room, reason="join rejected")
    monkeypatch.setattr(_admin, "ROOM_LIFECYCLE", registry)
    bot = SimpleNamespace(presence=SimpleNamespace(joined_rooms={}), prefix=",")
    health = SimpleNamespace(check=lambda _name: SimpleNamespace(data={}))
    lines = _admin._room_problem_lines(bot, (), health)
    assert any(f"{room} | lifecycle=failed" in line for line in lines)


def test_full_status_room_issues_ignore_intentional_leave(monkeypatch):
    from core_plugins import _admin

    registry = RoomLifecycleRegistry()
    registry.begin_leave("leaving@conference.example.test")
    monkeypatch.setattr(_admin, "ROOM_LIFECYCLE", registry)
    bot = SimpleNamespace(presence=SimpleNamespace(joined_rooms={}), prefix=",")
    health = SimpleNamespace(check=lambda _name: SimpleNamespace(data={}))
    assert _admin._room_problem_lines(bot, (), health) == []
