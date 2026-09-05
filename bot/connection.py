"""XMPP connection and JID compatibility facade for envsbot."""
from __future__ import annotations

import inspect
import logging
from collections.abc import Mapping
from typing import Any

from envs_xmpp_core.xmpp.connection import (
    connect_kwargs_from_mapping,
    maybe_await,
)
from envs_xmpp_core.xmpp.connection import (
    connection_target as _core_connection_target,
)
from envs_xmpp_core.xmpp.jid import (
    boundjid_domain,
    build_client_jid,
    configured_jid_domain,
)

log = logging.getLogger(__name__)

__all__ = [
    "boundjid_domain",
    "build_client_jid",
    "configured_jid_domain",
    "connect_kwargs",
    "connect_signature_parameters",
    "connect_xmpp",
    "connection_target",
    "get_configured_resource",
    "session_is_ready",
]


def get_configured_resource(config: Mapping[str, Any]) -> str | None:
    resource = config.get("resource")
    if resource is None:
        return None
    value = str(resource).strip()
    return value or None


def connect_signature_parameters(connect_method: Any) -> Mapping[str, inspect.Parameter]:
    """Return inspectable connect() parameters, preserving envsbot monkeypatch hooks."""
    try:
        return inspect.signature(connect_method).parameters
    except (TypeError, ValueError):
        return {}


def session_is_ready(xmpp: Any) -> bool:
    marker = getattr(xmpp, "session_ready", None)
    if marker is None:
        return True
    is_set = getattr(marker, "is_set", None)
    return bool(is_set()) if callable(is_set) else True


def connect_kwargs(xmpp: Any, config: Mapping[str, Any]) -> dict[str, Any]:
    return connect_kwargs_from_mapping(
        xmpp,
        config,
        parameters=connect_signature_parameters(xmpp.connect),
    )


def connection_target(kwargs: Mapping[str, Any], config: Mapping[str, Any]) -> tuple[object, object, str]:
    return _core_connection_target(
        kwargs,
        fallback_host=configured_jid_domain(config) or "auto",
        fallback_port="auto",
        direct_tls=bool(config.get("direct_tls", False)),
    )


async def connect_xmpp(xmpp: Any, config: Mapping[str, Any]) -> Any:
    kwargs = connect_kwargs(xmpp, config)
    host, port, mode = connection_target(kwargs, config)
    log.info("[XMPP] event=connect target=%s:%s mode=%s", host, port, mode)
    return await maybe_await(xmpp.connect(**kwargs))
