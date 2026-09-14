"""Split module for plugins/vcard.py: fetch."""

from envs_xmpp_core.runtime import KeyedCooldown, exception_summary
from envs_xmpp_core.xmpp import iq_error_condition, iq_error_summary
from slixmpp.exceptions import IqError, IqTimeout

from bot.room_state import JOINED_ROOMS
from core_plugins import _core
from utils.config import config

from .config import log
from .formatting import _format_vcard_reply

_VCARD_FAILURE_LOG_GATE = KeyedCooldown(cooldown_seconds=15 * 60, max_keys=4096)


def _vcard_log_key(jid, kind: str) -> str:
    return f"{kind}:{str(jid or '').strip().casefold()}"


def _vcard_repeat_suffix(suppressed: int) -> str:
    return (
        f" ({suppressed} repeated log event(s) suppressed)"
        if suppressed
        else ""
    )


def _log_vcard_timeout(jid, timeout: float) -> None:
    decision = _VCARD_FAILURE_LOG_GATE.check(_vcard_log_key(jid, "timeout"))
    if decision.allowed:
        log.info(
            "[VCARD] vCard fetch for '%s' timed out after %gs%s",
            jid,
            timeout,
            _vcard_repeat_suffix(decision.suppressed),
        )
    else:
        log.debug("[VCARD] Repeated vCard timeout for '%s' suppressed at INFO", jid)


def _log_vcard_iq_error(jid, exc: IqError) -> None:
    condition = iq_error_condition(exc) or "unknown"
    detail = iq_error_summary(exc)

    # A MUC occupant can disappear between presence and the vCard IQ (for
    # example because BanBot kicked it).  That is expected churn, not an
    # operator-level failure.
    if condition in {"item-not-found", "recipient-unavailable"}:
        log.debug("[VCARD] vCard fetch for '%s' failed: %s", jid, detail)
        return

    decision = _VCARD_FAILURE_LOG_GATE.check(_vcard_log_key(jid, condition))
    if decision.allowed:
        log.info(
            "[VCARD] vCard fetch for '%s' failed: %s%s",
            jid,
            detail,
            _vcard_repeat_suffix(decision.suppressed),
        )
    else:
        log.debug("[VCARD] Repeated vCard IQ failure for '%s' suppressed at INFO: %s", jid, detail)


def _log_vcard_unexpected_error(jid, exc: Exception) -> None:
    kind = type(exc).__name__
    decision = _VCARD_FAILURE_LOG_GATE.check(_vcard_log_key(jid, f"error:{kind}"))
    summary = exception_summary(exc, max_length=180)
    if decision.allowed:
        log.warning(
            "[VCARD] Unexpected vCard fetch error for '%s': %s%s",
            jid,
            summary,
            _vcard_repeat_suffix(decision.suppressed),
        )
    else:
        log.debug("[VCARD] Repeated unexpected vCard error for '%s' suppressed: %s", jid, summary)


async def get_vcard(bot, msg, jid=None, *, raise_on_error: bool = False):
    """Fetch a vCard, optionally propagating transport/IQ lookup failures.

    The default remains best-effort for user-facing commands.  Callers that
    must distinguish "no vCard" from a transient lookup failure can opt into
    ``raise_on_error=True``.
    """
    if jid is None:
        jid, _, _ = await _core.get_real_jid(bot, msg)

    vcard_plugin = bot.plugin.get("xep_0054", None)
    if not vcard_plugin:
        raise RuntimeError("vCard support (xep_0054) is not enabled in this bot.")

    timeout = float(config.get("vcard_fetch_timeout_seconds", 10) or 10)
    try:
        result = await vcard_plugin.get_vcard(
            jid=str(jid),
            cached=False,
            timeout=timeout,
        )
    except IqTimeout:
        _log_vcard_timeout(jid, timeout)
        if raise_on_error:
            raise
        return None
    except IqError as exc:
        _log_vcard_iq_error(jid, exc)
        if raise_on_error:
            raise
        return None
    except Exception as exc:
        _log_vcard_unexpected_error(jid, exc)
        if raise_on_error:
            raise
        return None

    log.debug("[VCARD] vCard fetch for '%s' completed", jid)
    if not result:
        log.debug("[VCARD] No vCard result for '%s'.", jid)
        return None
    log.debug("[VCARD] vCard for '%s' received.", jid)
    return result["vcard_temp"]

async def get_info(bot, msg, jid=None):
    try:
        vcard = await get_user_vcard(bot, msg, jid)
        if not vcard:
            log.debug(f"[VCARD] No vCard found for '{jid}'.")
            return None

    except Exception as e:
        log.error(f"[VCARD] Exception during vCard lookup for '{jid}': {e}")
        raise
    return vcard


async def get_user_vcard(bot, msg, jid=None, *, raise_on_error: bool = False):
    """Fetch and return vCard data plus the target user's stored timezone.

    When an explicit *jid* is supplied, both the vCard and timezone lookup use
    that target.  ``raise_on_error`` is intended for internal callers such as
    birthday caching that must not confuse transient lookup failures with an
    explicit empty vCard.
    """
    target_jid = jid
    if target_jid is None:
        target_jid, _, _ = await _core.get_real_jid(bot, msg)

    vcard_info = await get_vcard(
        bot,
        msg,
        target_jid,
        raise_on_error=raise_on_error,
    )
    _, rendered = _format_vcard_reply(vcard_info, None, None)

    timezone = None
    if target_jid is not None:
        timezone = await _core._get_user_timezone(bot, str(target_jid))
    rendered["TZ"] = timezone
    return rendered


async def vcard_field(bot, msg, target_nick, field, is_room=False):
    """
    Helper to fetch a specific vCard field(s) for a given nick.
    Must be called from MUC PM or groupchat context with a valid
    target_nick present in the room.

    Supports fields: "FN", "NICKNAME", "BDAY", "TIMEZONE", "URL", "ORG",
    "NOTE", "EMAIL".
    Returns "None" if field is not present.
    """
    if field not in ["FN", "NICKNAME", "BDAY", "TIMEZONE", "URL",
                     "ORG", "NOTE", "EMAIL", "LOCALITY", "CTRY"]:
        log.warning("[VCARD] 🔴  Invalid vCard field requested: %s", field)
        return None
    if not is_room and not _core._is_muc_pm(msg):
        jid = msg["from"].bare
    else:
        jid = _core.get_real_jid_from_occupant(bot, msg, target_nick)

    if not jid:
        log.warning(
            "[VCARD] 🔴  Nick '%s' not found in room '%s' for field '%s' lookup",
            target_nick,
            msg["from"].bare,
            field,
        )
        return None

    if field == "TIMEZONE":
        value = await _core._get_user_timezone(bot, str(jid))
        if jid == msg["from"].bare:
            log.info(
                "[VCARD] TIMEZONE lookup for sender's own JID '%s': %s",
                jid,
                value,
            )
        else:
            log.info(
                "[VCARD] TIMEZONE lookup for nick '%s' with JID '%s' in room '%s': %s",
                target_nick,
                jid,
                msg["from"].bare,
                value,
            )
        if not value:
            return None
        return value
    vcard_info = await get_vcard(bot, msg, jid=jid)
    _, vcard = _format_vcard_reply(vcard_info, None, None)
    return vcard[field]


def _vcard_get_joined_nick_info(room, target_nick):
    joined = JOINED_ROOMS.get(room, {})
    nicks = joined.get("nicks", {})
    return nicks.get(target_nick)


async def _vcard_fetch_value(bot, msg, field, jid):
    if field == "TIMEZONE":
        return await _core._get_user_timezone(bot, str(jid))
    vcard = await get_user_vcard(bot, msg, jid)
    return vcard[field]
