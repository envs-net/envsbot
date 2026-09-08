"""Compatibility imports for the shared durable XMPP outbox."""

from envs_xmpp_core.storage.outbox import (
    OutboxCapacityError,
    OutboxMessage,
    OutboxStore,
)

__all__ = ["OutboxCapacityError", "OutboxMessage", "OutboxStore"]
