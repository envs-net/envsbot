"""Audit helper mixin for envsbot."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class AuditMixin:
    """Best-effort audit event writer."""

    async def audit(self, event: str, *, actor: Any = None, target: Any = None, details: dict[str, Any] | None = None) -> None:
        """Write an audit event if the audit log is available."""
        try:
            audit_log = getattr(getattr(self, "db", None), "audit", None)
            if audit_log is None:
                return
            await audit_log.append(
                event,
                actor=str(actor) if actor is not None else None,
                target=str(target) if target is not None else None,
                details=details or {},
            )
        except Exception:
            log.debug("[AUDIT] Failed to write audit event", exc_info=True)
