"""Bounded per-client command rate limiter."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import TypedDict

_MAX_CLIENT_STATES = 2048


class _ClientState(TypedDict):
    tokens: float
    last_refill: float
    last_seen: float
    lock: asyncio.Lock


class TokenBucketRateLimiter:
    """Per-client token bucket with flood blocks and bounded idle state."""

    def __init__(
        self,
        capacity: int = 4,
        refill_amount: int = 1,
        refill_interval: float = 0.5,
        deny_window: float = 10.0,
        deny_threshold: int = 5,
        base_block_seconds: float = 30.0,
        backoff_multiplier: float = 2.0,
        max_block_seconds: float = 3600.0,
        notify_cooldown: float = 10.0,
        idle_ttl_seconds: float = 3600.0,
        prune_interval_seconds: float = 60.0,
    ) -> None:
        self.capacity = float(capacity)
        self.refill_amount = float(refill_amount)
        self.refill_interval = float(refill_interval)
        self.deny_window = float(deny_window)
        self.deny_threshold = int(deny_threshold)
        self.base_block_seconds = float(base_block_seconds)
        self.backoff_multiplier = float(backoff_multiplier)
        self.max_block_seconds = float(max_block_seconds)
        self.notify_cooldown = float(notify_cooldown)
        self.max_clients = _MAX_CLIENT_STATES
        self.idle_ttl_seconds = max(0.0, float(idle_ttl_seconds))
        self.prune_interval_seconds = max(1.0, float(prune_interval_seconds))

        self._state: dict[str, _ClientState] = {}
        self._denials: defaultdict[str, deque[float]] = defaultdict(deque)
        self._block_info: dict[str, tuple[float, int]] = {}
        self._last_notify: dict[str, float] = {}
        self._last_activity: dict[str, float] = {}
        self._last_prune_at = 0.0
        self._capacity_evictions = 0
        self._stale_pruned = 0
        self._global_lock = asyncio.Lock()

    def _now(self) -> float:
        return time.monotonic()

    def _tracked_clients(self) -> set[str]:
        return (
            set(self._state)
            | set(self._denials)
            | set(self._block_info)
            | set(self._last_notify)
            | set(self._last_activity)
        )

    def _touch(self, client_id: str, now: float) -> None:
        self._last_activity[client_id] = now
        state = self._state.get(client_id)
        if state is not None:
            state["last_seen"] = now

    def _drop_client(self, client_id: str) -> None:
        self._state.pop(client_id, None)
        self._denials.pop(client_id, None)
        self._block_info.pop(client_id, None)
        self._last_notify.pop(client_id, None)
        self._last_activity.pop(client_id, None)

    def _prune_stale(self, now: float, *, force: bool = False) -> int:
        if not force and now - self._last_prune_at < self.prune_interval_seconds:
            return 0
        self._last_prune_at = now

        if self.idle_ttl_seconds <= 0:
            return 0

        removed = 0
        cutoff = now - self.idle_ttl_seconds
        for client_id, last_seen in tuple(self._last_activity.items()):
            blocked_until, _count = self._block_info.get(client_id, (0.0, 0))
            if last_seen <= cutoff and blocked_until <= now:
                self._drop_client(client_id)
                removed += 1
        self._stale_pruned += removed
        return removed

    def _ensure_capacity(self, now: float, incoming: str) -> None:
        tracked = self._tracked_clients()
        if incoming in tracked or len(tracked) < self.max_clients:
            return

        # Capacity pressure is uncommon. Only then force a full idle sweep; the
        # normal hot path relies on the configured prune interval instead of
        # scanning all tracked clients for every command.
        self._prune_stale(now, force=True)
        tracked = self._tracked_clients()
        if incoming in tracked or len(tracked) < self.max_clients:
            return

        candidates = sorted(
            (
                (last_seen, client_id)
                for client_id, last_seen in self._last_activity.items()
                if self._block_info.get(client_id, (0.0, 0))[0] <= now
            ),
            key=lambda item: item[0],
        )
        if not candidates:
            candidates = sorted(
                (last_seen, client_id)
                for client_id, last_seen in self._last_activity.items()
            )
        if not candidates:
            candidates = [(0.0, client_id) for client_id in sorted(tracked)]
        if candidates:
            self._drop_client(candidates[0][1])
            self._capacity_evictions += 1

    async def _ensure_client(self, client_id: str) -> _ClientState:
        async with self._global_lock:
            now = self._now()
            self._prune_stale(now)
            self._ensure_capacity(now, client_id)
            state = self._state.get(client_id)
            if state is None:
                state = {
                    "tokens": self.capacity,
                    "last_refill": now,
                    "last_seen": now,
                    "lock": asyncio.Lock(),
                }
                self._state[client_id] = state
            self._touch(client_id, now)
            return state

    async def allow(self, client_id: str) -> tuple[bool, float]:
        """Attempt one action and return ``(allowed, retry_after_seconds)``."""
        state = await self._ensure_client(client_id)
        lock = state["lock"]
        now = self._now()
        self._touch(client_id, now)

        blocked_until, _ = self._block_info.get(client_id, (0.0, 0))
        if now < blocked_until:
            return False, blocked_until - now

        async with lock:
            elapsed = now - state["last_refill"]
            if elapsed >= self.refill_interval:
                steps = int(elapsed / self.refill_interval)
                add = steps * self.refill_amount
                state["tokens"] = min(self.capacity, state["tokens"] + add)
                state["last_refill"] += steps * self.refill_interval

            if state["tokens"] >= 1.0:
                state["tokens"] -= 1.0
                dq = self._denials.get(client_id)
                if dq:
                    while dq and dq[0] + self.deny_window < now:
                        dq.popleft()
                    if not dq:
                        self._denials.pop(client_id, None)
                return True, 0.0

            self._record_denial(client_id, now)
            blocked = self._check_and_apply_block(client_id, now)
            if blocked:
                blocked_until, _ = self._block_info.get(client_id, (0.0, 0))
                return False, max(0.0, blocked_until - now)
            time_since_refill = now - state["last_refill"]
            return False, max(0.0, self.refill_interval - time_since_refill)

    def _record_denial(self, client_id: str, now: float) -> None:
        self._touch(client_id, now)
        dq = self._denials[client_id]
        dq.append(now)
        while dq and dq[0] + self.deny_window < now:
            dq.popleft()

    def _check_and_apply_block(self, client_id: str, now: float) -> bool:
        dq = self._denials.get(client_id)
        if not dq or len(dq) < self.deny_threshold:
            return False
        _blocked_until, block_count = self._block_info.get(client_id, (0.0, 0))
        next_block = min(
            self.max_block_seconds,
            self.base_block_seconds * (self.backoff_multiplier**block_count),
        )
        self._block_info[client_id] = (now + next_block, block_count + 1)
        self._denials[client_id].clear()
        self._touch(client_id, now)
        return True

    def get_block_time(self, client_id: str) -> float:
        """Return seconds remaining in a temporary block, or 0."""
        now = self._now()
        blocked_until, _ = self._block_info.get(client_id, (0.0, 0))
        if blocked_until <= now:
            # Keep the historical block_count while the client remains active
            # so repeated floods still receive exponential backoff. Idle
            # pruning removes the whole client state eventually.
            return 0.0
        return blocked_until - now

    def notify_allowed(self, client_id: str) -> bool:
        """Rate-limit human-facing denial notifications per client."""
        now = self._now()
        self._prune_stale(now)
        self._ensure_capacity(now, client_id)
        self._touch(client_id, now)
        last = self._last_notify.get(client_id, 0.0)
        if now - last >= self.notify_cooldown:
            self._last_notify[client_id] = now
            return True
        return False

    def prune(self) -> int:
        """Force an idle-state prune and return the number of removed clients."""
        return self._prune_stale(self._now(), force=True)

    def runtime_state(self) -> dict[str, int | float]:
        """Return privacy-safe bounded-cache diagnostics."""
        now = self._now()
        self._prune_stale(now)
        tracked = self._tracked_clients()
        blocked = sum(1 for until, _count in self._block_info.values() if until > now)
        return {
            "clients": len(tracked),
            "max_clients": self.max_clients,
            "blocked_clients": blocked,
            "denial_clients": sum(1 for values in self._denials.values() if values),
            "notify_clients": len(self._last_notify),
            "idle_ttl_seconds": self.idle_ttl_seconds,
            "capacity_evictions": self._capacity_evictions,
            "stale_pruned": self._stale_pruned,
        }

    def force_reset(self, client_id: str) -> None:
        """Reset all limiter state for one client."""
        self._drop_client(client_id)
