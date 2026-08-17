"""Split module for core_plugins/rooms.py: lifecycle."""

from __future__ import annotations

import asyncio
import time
from functools import partial

from utils.config import config
from utils.task_supervisor import (
    create_plugin_task,
    create_resilient_plugin_task,
    sleep_with_heartbeat,
)

from .invites import (
    cleanup_expired_room_invites,
    load_pending_room_invites,
    on_room_invite,
    on_room_invite_message,
)
from .presence import on_muc_presence
from .state import (
    _LEAVING_ROOMS,
    JOINED_ROOMS,
    _jid_bare,
    _join_muc_with_timeout,
    _maybe_await_result,
    log,
)

_ROOM_HEALTH_TASK = None
_ROOM_HEALTH_TASK_NAME = "rooms-autojoin-health"
_ROOM_HEALTH_CHECK_INTERVAL_SECONDS = 60.0
_ROOM_REJOIN_BACKOFF_SECONDS = (60.0, 120.0, 240.0, 300.0)
_REJOIN_STATE: dict[str, dict[str, object]] = {}


def _state_int(value: object, default: int = 0) -> int:
    if isinstance(value, (str, bytes, bytearray, int, float)):
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    return default


def _state_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (str, bytes, bytearray, int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
    return default


def _rejoin_backoff(failures: int) -> float:
    """Return the fixed retry delay for a consecutive join failure."""
    index = min(
        max(1, int(failures)) - 1,
        len(_ROOM_REJOIN_BACKOFF_SECONDS) - 1,
    )
    return _ROOM_REJOIN_BACKOFF_SECONDS[index]


def _record_join_failure(
    room_jid: str,
    error: BaseException,
    *,
    now: float | None = None,
) -> float:
    """Record one failed room join and return its retry delay."""
    current = _REJOIN_STATE.get(room_jid, {})
    failures = _state_int(current.get("failures", 0)) + 1
    delay = _rejoin_backoff(failures)
    timestamp = time.time() if now is None else float(now)
    _REJOIN_STATE[room_jid] = {
        "failures": failures,
        "next_attempt": timestamp + delay,
        "last_error": f"{type(error).__name__}: {error}",
    }
    return delay


def _clear_join_failure(room_jid: str) -> None:
    """Clear automatic rejoin state after a confirmed join."""
    _REJOIN_STATE.pop(room_jid, None)


def _mark_room_joined(
    bot,
    room_jid: str,
    nick: str,
    autojoin: bool | None,
    status,
) -> None:
    """Refresh both runtime room mirrors after a successful join."""
    room_info = JOINED_ROOMS.get(room_jid)
    if not isinstance(room_info, dict):
        room_info = {
            "nick": nick,
            "autojoin": autojoin,
            "status": status,
            "affiliation": "unknown",
            "role": "unknown",
            "nicks": {},
        }
        JOINED_ROOMS[room_jid] = room_info

    room_info["nick"] = str(room_info.get("nick") or nick)
    room_info["autojoin"] = autojoin
    room_info["status"] = status
    room_info["confirmed"] = True
    room_info.setdefault("affiliation", "unknown")
    room_info.setdefault("role", "unknown")
    room_info.setdefault("nicks", {})

    bot.presence.joined_rooms[room_jid] = str(room_info["nick"])
    _clear_join_failure(room_jid)


async def _join_room(
    bot,
    muc,
    room_jid: str,
    nick: str,
    autojoin: bool | None,
    status,
) -> None:
    """Join one room and update all runtime mirrors on success."""
    _LEAVING_ROOMS.discard(room_jid)
    await _join_muc_with_timeout(bot, muc, room_jid, nick)
    _mark_room_joined(bot, room_jid, nick, autojoin, status)


async def _muc_joined_room_snapshot(muc) -> set[str] | None:
    """Return Slixmpp's current joined-room keys when available."""
    getter = getattr(muc, "get_joined_rooms", None)
    if not callable(getter):
        return None
    try:
        joined = await _maybe_await_result(getter())
    except Exception:
        log.debug("[ROOMS] Could not read XEP-0045 joined-room state", exc_info=True)
        return None
    if not isinstance(joined, (list, tuple, set, frozenset)):
        return None
    return {_jid_bare(room) for room in joined if _jid_bare(room)}


def _room_join_is_confirmed(
    bot,
    room_jid: str,
    muc_joined_rooms: set[str] | None,
) -> bool:
    """Return True when all available runtime mirrors confirm membership."""
    room_info = JOINED_ROOMS.get(room_jid)
    if not isinstance(room_info, dict):
        return False

    presence_rooms = getattr(getattr(bot, "presence", None), "joined_rooms", {})
    if not isinstance(presence_rooms, dict) or room_jid not in presence_rooms:
        return False

    runtime_nick = str(room_info.get("nick") or "")
    presence_nick = str(presence_rooms.get(room_jid) or "")
    if runtime_nick and presence_nick and runtime_nick != presence_nick:
        return False
    if room_info.get("confirmed") is False:
        return False
    if muc_joined_rooms is not None and room_jid not in muc_joined_rooms:
        return False
    return True


async def autojoin_rooms(bot):
    """Join all database rooms that are marked for automatic joining."""
    muc = bot.plugin["xep_0045"]
    rooms_db = bot.db.rooms
    if muc is None or rooms_db is None:
        log.warning(
            "[ROOMS] 🟡️ missing dependencies: rooms_db=%s xep_0045=%s",
            "OK" if rooms_db is not None else "missing",
            "OK" if muc is not None else "missing",
        )
        return

    async def join_one(room_jid: str, nick: str, autojoin: bool, status) -> None:
        log.info("[MUC] Autojoining room %s as %s", room_jid, nick)
        try:
            await _join_room(bot, muc, room_jid, nick, autojoin, status)
        except TimeoutError as exc:
            delay = _record_join_failure(room_jid, exc)
            log.warning(
                "[ROOMS] 🟡️ Autojoin timed out for %s; automatic retry in %ds",
                room_jid,
                int(delay),
            )
        except Exception as exc:
            delay = _record_join_failure(room_jid, exc)
            log.exception(
                "[ROOMS] 🔴 Couldn't join room %s; automatic retry in %ds",
                room_jid,
                int(delay),
            )

    rows = await rooms_db.list()
    attempts = []
    for raw_room_jid, nick, autojoin, status in rows:
        room_jid = _jid_bare(raw_room_jid)
        if autojoin and room_jid:
            attempts.append(
                join_one(room_jid, str(nick), autojoin, status)
            )
    if attempts:
        await asyncio.gather(*attempts)


async def reconcile_autojoin_rooms(bot, *, now: float | None = None) -> dict[str, int]:
    """Repair missing memberships for rooms configured with autojoin enabled."""
    summary = {
        "configured": 0,
        "healthy": 0,
        "rejoined": 0,
        "failed": 0,
        "deferred": 0,
        "intentional": 0,
    }
    muc = bot.plugin["xep_0045"]
    rooms_db = bot.db.rooms
    if muc is None or rooms_db is None:
        return summary

    rows = await rooms_db.list()
    autojoin_rows = []
    for raw_room_jid, nick, autojoin, status in rows:
        room_jid = _jid_bare(raw_room_jid)
        if autojoin and room_jid:
            autojoin_rows.append((room_jid, str(nick), autojoin, status))

    configured_rooms = {row[0] for row in autojoin_rows}
    summary["configured"] = len(autojoin_rows)
    for room_jid in tuple(_REJOIN_STATE):
        if room_jid not in configured_rooms:
            _REJOIN_STATE.pop(room_jid, None)

    muc_joined_rooms = await _muc_joined_room_snapshot(muc)
    timestamp = time.time() if now is None else float(now)

    for room_jid, nick, autojoin, status in autojoin_rows:
        if room_jid in _LEAVING_ROOMS:
            summary["intentional"] += 1
            continue

        if _room_join_is_confirmed(bot, room_jid, muc_joined_rooms):
            summary["healthy"] += 1
            _clear_join_failure(room_jid)
            continue

        # Remove incomplete or stale mirrors so delivery code does not treat
        # the room as usable while a repair attempt is still pending.
        JOINED_ROOMS.pop(room_jid, None)
        presence_rooms = getattr(getattr(bot, "presence", None), "joined_rooms", None)
        if isinstance(presence_rooms, dict):
            presence_rooms.pop(room_jid, None)

        retry_state = _REJOIN_STATE.get(room_jid, {})
        next_attempt = _state_float(retry_state.get("next_attempt", 0))
        if timestamp < next_attempt:
            summary["deferred"] += 1
            continue

        failures = _state_int(retry_state.get("failures", 0))
        log.warning(
            "[ROOMS] 🟡️ Autojoin membership missing for %s; "
            "attempting rejoin as %s (previous_failures=%d)",
            room_jid,
            nick,
            failures,
        )
        try:
            await _join_room(bot, muc, room_jid, nick, autojoin, status)
        except TimeoutError as exc:
            delay = _record_join_failure(room_jid, exc, now=timestamp)
            summary["failed"] += 1
            log.warning(
                "[ROOMS] 🟡️ Rejoin timed out for %s; next retry in %ds",
                room_jid,
                int(delay),
            )
        except Exception as exc:
            delay = _record_join_failure(room_jid, exc, now=timestamp)
            summary["failed"] += 1
            log.exception(
                "[ROOMS] 🔴 Rejoin failed for %s; next retry in %ds",
                room_jid,
                int(delay),
            )
        else:
            summary["rejoined"] += 1
            log.info("[ROOMS] ✅ Rejoined autojoin room %s as %s", room_jid, nick)

    return summary


def _touch_room_health_task(bot) -> None:
    """Refresh the supervisor heartbeat for the room health worker."""
    supervisor = getattr(bot, "tasks", None)
    heartbeat = getattr(supervisor, "heartbeat", None)
    if callable(heartbeat):
        heartbeat("rooms", _ROOM_HEALTH_TASK_NAME)


async def room_join_health_loop(bot) -> None:
    """Periodically verify autojoin coverage and repair missing rooms."""
    while True:
        await sleep_with_heartbeat(
            bot,
            "rooms",
            _ROOM_HEALTH_TASK_NAME,
            _ROOM_HEALTH_CHECK_INTERVAL_SECONDS,
        )
        try:
            summary = await reconcile_autojoin_rooms(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[ROOMS] Automatic room membership check failed")
        else:
            missing = summary["rejoined"] + summary["failed"] + summary["deferred"]
            if missing:
                log.info(
                    "[ROOMS] Join health: configured=%d healthy=%d rejoined=%d "
                    "failed=%d deferred=%d intentional=%d",
                    summary["configured"],
                    summary["healthy"],
                    summary["rejoined"],
                    summary["failed"],
                    summary["deferred"],
                    summary["intentional"],
                )
        _touch_room_health_task(bot)


def start_room_join_health_task(bot):
    """Ensure the supervised room membership worker is running."""
    global _ROOM_HEALTH_TASK
    if _ROOM_HEALTH_TASK is not None and not _ROOM_HEALTH_TASK.done():
        return _ROOM_HEALTH_TASK
    _ROOM_HEALTH_TASK = create_resilient_plugin_task(
        bot,
        "rooms",
        lambda: room_join_health_loop(bot),
        name=_ROOM_HEALTH_TASK_NAME,
        fallback_creator=create_plugin_task,
    )
    return _ROOM_HEALTH_TASK


async def restart_tasks(bot):
    """Restore the automatic room membership health worker."""
    start_room_join_health_task(bot)


async def on_ready(bot):
    """Load pending invites and start automatic room membership repair."""
    await load_pending_room_invites(bot)
    await cleanup_expired_room_invites(bot)
    start_room_join_health_task(bot)


async def on_load(bot):
    # --- add event handlers ---
    bot.bot_plugins.register_event(
        "rooms",
        "groupchat_presence",
        partial(on_muc_presence, bot),
    )
    bot.bot_plugins.register_event(
        "rooms",
        "message",
        partial(on_room_invite_message, bot),
    )
    bot.bot_plugins.register_event(
        "rooms",
        "groupchat_invite",
        partial(on_room_invite, bot),
    )
    bot.bot_plugins.register_event(
        "rooms",
        "groupchat_direct_invite",
        partial(on_room_invite, bot),
    )

    muc = bot.plugin["xep_0045"]
    rooms_db = bot.db.rooms
    if muc is None or rooms_db is None:
        detail = (
            f"rooms_db={'OK' if rooms_db is not None else 'missing'} "
            f"xep_0045={'OK' if muc is not None else 'missing'}"
        )
        log.error("[ROOMS] 🔴 missing runtime dependencies: %s", detail)
        raise RuntimeError(f"rooms plugin dependencies unavailable: {detail}")

    reload_rooms = getattr(bot, "_reload_rooms", None)
    if reload_rooms is not None:
        del bot._reload_rooms
        for room, data in tuple(reload_rooms.items()):
            room_jid = _jid_bare(room)
            db_room = await rooms_db.get(room_jid)
            if db_room:
                _, db_nick, db_autojoin, db_status = db_room
            else:
                db_nick = None
                db_autojoin = None
                db_status = None

            nick = str(
                data.get("nick")
                or db_nick
                or config.get("nick")
                or "envsbot"
            )
            autojoin = data.get("autojoin")
            if autojoin is None:
                autojoin = db_autojoin
            status = data.get("status") or db_status or None

            try:
                await _join_room(bot, muc, room_jid, nick, autojoin, status)
            except Exception as exc:
                if autojoin:
                    delay = _record_join_failure(room_jid, exc)
                    log.warning(
                        "[ROOMS] Reload join failed for %s; automatic retry in %ds",
                        room_jid,
                        int(delay),
                        exc_info=True,
                    )
                else:
                    log.warning(
                        "[ROOMS] Reload join failed for non-autojoin room %s",
                        room_jid,
                        exc_info=True,
                    )
    else:
        await autojoin_rooms(bot)


async def on_unload(bot):
    global _ROOM_HEALTH_TASK
    bot._reload_rooms = dict(JOINED_ROOMS)

    health_task = _ROOM_HEALTH_TASK
    _ROOM_HEALTH_TASK = None
    if health_task is not None and not health_task.done():
        health_task.cancel()
        results = await asyncio.gather(health_task, return_exceptions=True)
        result: object = results[0]
        if isinstance(result, BaseException) and not isinstance(
            result,
            asyncio.CancelledError,
        ):
            log.warning(
                "[ROOMS] Room health task failed while unloading",
                exc_info=(type(result), result, result.__traceback__),
            )

    for room_jid, data in tuple(JOINED_ROOMS.items()):
        try:
            await _maybe_await_result(
                bot.plugin["xep_0045"].leave_muc(room_jid, data["nick"])
            )
        except Exception:
            log.warning("[ROOMS] Error leaving room %s during unload", room_jid, exc_info=True)

    JOINED_ROOMS.clear()
    bot.presence.joined_rooms.clear()
    _REJOIN_STATE.clear()
