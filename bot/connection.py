"""XMPP connection and JID helpers for envsbot."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Mapping
from typing import Any

log = logging.getLogger(__name__)


def get_configured_resource(config: Mapping[str, Any]) -> str | None:
    """Return the optional configured XMPP resource."""
    resource = config.get("resource")
    if resource is None:
        return None
    resource = str(resource).strip()
    return resource or None


def build_client_jid(jid: object, resource: object | None = None) -> str:
    """Build the login JID, optionally replacing/adding a resource."""
    jid_text = str(jid)
    if not resource:
        return jid_text
    bare_jid = jid_text.split("/", 1)[0]
    return f"{bare_jid}/{resource}"


def configured_jid_domain(config: Mapping[str, Any]) -> str | None:
    """Return the domain part of the configured bot JID if available."""
    jid = str(config.get("jid", ""))
    if "@" not in jid:
        return None
    domain = jid.split("@", 1)[1].split("/", 1)[0].strip()
    return domain or None


def boundjid_domain(xmpp: Any) -> str | None:
    """Return a best-effort domain from Slixmpp's bound JID object."""
    boundjid = getattr(xmpp, "boundjid", None)
    if boundjid is None:
        return None

    for attribute in ("domain", "host"):
        value = getattr(boundjid, attribute, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def connect_signature_parameters(connect_method: Any) -> Mapping[str, inspect.Parameter]:
    """Return inspectable connect() parameters, or an empty mapping."""
    try:
        return inspect.signature(connect_method).parameters
    except (TypeError, ValueError):
        return {}


def connect_kwargs(xmpp: Any, config: Mapping[str, Any]) -> dict[str, Any]:
    """Build kwargs for xmpp.connect() without passing unsupported names."""
    host = config.get("host") or configured_jid_domain(config) or boundjid_domain(xmpp)
    port = config.get("port")
    direct_tls = bool(config.get("direct_tls", False))

    parameters = connect_signature_parameters(xmpp.connect)
    kwargs: dict[str, Any] = {}

    if "address" in parameters and host and port is not None:
        kwargs["address"] = (host, int(port))
    else:
        if "host" in parameters and host:
            kwargs["host"] = host
        if "port" in parameters and port is not None:
            kwargs["port"] = int(port)

    if "use_ssl" in parameters:
        kwargs["use_ssl"] = direct_tls
    if direct_tls and "force_starttls" in parameters:
        kwargs["force_starttls"] = False

    return kwargs


def connection_target(kwargs: Mapping[str, Any], config: Mapping[str, Any]) -> tuple[object, object, str]:
    """Return host, port and mode for connection logging."""
    host = (
        kwargs.get("host")
        or (kwargs.get("address") or (None, None))[0]
        or configured_jid_domain(config)
        or "auto"
    )
    port = kwargs.get("port") or (kwargs.get("address") or (None, None))[1] or "auto"
    mode = "direct TLS" if config.get("direct_tls", False) else "STARTTLS"
    return host, port, mode


async def connect_xmpp(xmpp: Any, config: Mapping[str, Any]) -> Any:
    """Connect using optional host, port and direct-TLS config."""
    kwargs = connect_kwargs(xmpp, config)
    host, port, mode = connection_target(kwargs, config)
    log.info(
        "[XMPP] event=connect target=%s:%s mode=%s",
        host,
        port,
        mode,
    )
    result = xmpp.connect(**kwargs)
    if inspect.isawaitable(result):
        return await result
    return result
