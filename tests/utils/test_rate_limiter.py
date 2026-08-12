import pytest
import asyncio
from utils import rate_limiter as rate_limiter_module
from utils.rate_limiter import TokenBucketRateLimiter


@pytest.mark.asyncio
async def test_token_bucket_basic_allows_right_away():
    limiter = TokenBucketRateLimiter(capacity=2)
    allowed, retry = await limiter.allow("u1")
    assert allowed
    allowed, retry = await limiter.allow("u1")
    assert allowed
    allowed, retry = await limiter.allow("u1")
    assert not allowed
    assert retry > 0


@pytest.mark.asyncio
async def test_token_bucket_refills_tokens_after_interval():
    limiter = TokenBucketRateLimiter(capacity=1, refill_interval=0.1)
    allowed, _ = await limiter.allow("A")
    assert allowed
    allowed, retry = await limiter.allow("A")
    assert not allowed
    await asyncio.sleep(0.11)
    allowed, _ = await limiter.allow("A")
    assert allowed


@pytest.mark.asyncio
async def test_multiple_clients_independent_buckets():
    limiter = TokenBucketRateLimiter(capacity=1)
    a1, _ = await limiter.allow("A")
    b1, _ = await limiter.allow("B")
    assert a1 and b1
    a2, _ = await limiter.allow("A")
    b2, _ = await limiter.allow("B")
    assert not a2 and not b2


@pytest.mark.asyncio
async def test_exponential_backoff_and_block(monkeypatch):
    # simulate fast denials to trigger block
    limiter = TokenBucketRateLimiter(
        capacity=1, deny_threshold=2, deny_window=0.5, base_block_seconds=0.2,
        max_block_seconds=0.5
    )
    # Deny first (bucket empty after 1 request)
    await limiter.allow("zz")
    await limiter.allow("zz")  # bucket is empty
    await limiter.allow("zz")  # denial #1
    await limiter.allow("zz")  # denial #2: triggers block
    allowed, retry = await limiter.allow("zz")
    assert not allowed
    assert 0.1 <= retry <= 0.5  # Should be blocked at least a bit


@pytest.mark.asyncio
async def test_token_bucket_blocks_and_refills():
    # Small capacity for fast test, quick refill
    limiter = TokenBucketRateLimiter(capacity=1, refill_interval=0.2)
    client = "user-blocking"

    # Use up the only token
    allowed, retry = await limiter.allow(client)
    assert allowed

    # Now bucket should be empty, so the next call should block
    allowed, retry = await limiter.allow(client)
    assert not allowed
    assert retry > 0

    # Wait for just less than the refill time: should *still* be blocked
    await asyncio.sleep(0.1)
    allowed, retry = await limiter.allow(client)
    assert not allowed

    # Wait further, to allow token to refill
    await asyncio.sleep(0.15)
    allowed, retry = await limiter.allow(client)
    assert allowed


def test_notify_allowed_cooldown_and_force_reset(monkeypatch):
    limiter = TokenBucketRateLimiter(notify_cooldown=5.0)
    current = {"value": 100.0}
    monkeypatch.setattr(limiter, "_now", lambda: current["value"])

    assert limiter.notify_allowed("alice") is True
    assert limiter.notify_allowed("alice") is False
    current["value"] += 5.1
    assert limiter.notify_allowed("alice") is True

    limiter._state["alice"] = {"tokens": 0, "last_refill": 1, "lock": object()}
    limiter._denials["alice"].append(1.0)
    limiter._block_info["alice"] = (current["value"] + 30, 1)
    assert limiter.get_block_time("alice") > 0
    limiter.force_reset("alice")
    assert limiter.get_block_time("alice") == 0
    assert "alice" not in limiter._state
    assert "alice" not in limiter._denials
    assert "alice" not in limiter._last_notify


def test_denial_pruning_and_escalating_block(monkeypatch):
    limiter = TokenBucketRateLimiter(
        deny_window=10.0,
        deny_threshold=2,
        base_block_seconds=10.0,
        backoff_multiplier=3.0,
        max_block_seconds=25.0,
    )

    limiter._record_denial("bob", 100.0)
    limiter._record_denial("bob", 111.0)
    assert list(limiter._denials["bob"]) == [111.0]
    assert limiter._check_and_apply_block("bob", 111.0) is False
    limiter._record_denial("bob", 112.0)
    assert limiter._check_and_apply_block("bob", 112.0) is True
    assert limiter._block_info["bob"] == (122.0, 1)
    limiter._record_denial("bob", 123.0)
    limiter._record_denial("bob", 124.0)
    assert limiter._check_and_apply_block("bob", 124.0) is True
    assert limiter._block_info["bob"] == (149.0, 2)


@pytest.mark.asyncio
async def test_runtime_state_is_bounded_and_evicts_oldest_client(monkeypatch):
    monkeypatch.setattr(rate_limiter_module, "_MAX_CLIENT_STATES", 2)
    limiter = TokenBucketRateLimiter(
        idle_ttl_seconds=3600,
        prune_interval_seconds=60,
    )
    current = {"value": 100.0}
    monkeypatch.setattr(limiter, "_now", lambda: current["value"])

    assert (await limiter.allow("first"))[0] is True
    current["value"] = 101.0
    assert (await limiter.allow("second"))[0] is True
    current["value"] = 102.0
    assert (await limiter.allow("third"))[0] is True

    state = limiter.runtime_state()
    assert state["clients"] == 2
    assert state["capacity_evictions"] == 1
    assert "first" not in limiter._state
    assert set(limiter._state) == {"second", "third"}


@pytest.mark.asyncio
async def test_idle_prune_removes_all_client_state(monkeypatch):
    limiter = TokenBucketRateLimiter(
        idle_ttl_seconds=10,
        prune_interval_seconds=60,
    )
    current = {"value": 100.0}
    monkeypatch.setattr(limiter, "_now", lambda: current["value"])

    await limiter.allow("alice")
    limiter._denials["alice"].append(100.0)
    limiter._last_notify["alice"] = 100.0
    current["value"] = 111.0

    assert limiter.prune() == 1
    assert "alice" not in limiter._tracked_clients()
    assert limiter.runtime_state()["stale_pruned"] == 1


def test_expired_block_keeps_backoff_history_until_idle_prune(monkeypatch):
    limiter = TokenBucketRateLimiter(
        deny_threshold=2,
        base_block_seconds=10,
        backoff_multiplier=3,
        max_block_seconds=100,
    )
    current = {"value": 100.0}
    monkeypatch.setattr(limiter, "_now", lambda: current["value"])

    limiter._record_denial("bob", 100.0)
    limiter._record_denial("bob", 101.0)
    assert limiter._check_and_apply_block("bob", 101.0) is True
    assert limiter._block_info["bob"] == (111.0, 1)

    current["value"] = 112.0
    assert limiter.get_block_time("bob") == 0.0
    limiter._record_denial("bob", 112.0)
    limiter._record_denial("bob", 113.0)
    assert limiter._check_and_apply_block("bob", 113.0) is True
    assert limiter._block_info["bob"] == (143.0, 2)


@pytest.mark.asyncio
async def test_hot_path_does_not_force_full_prune_without_capacity_pressure(monkeypatch):
    limiter = TokenBucketRateLimiter()
    calls = []
    original = limiter._prune_stale

    def tracked(now, *, force=False):
        calls.append(force)
        return original(now, force=force)

    monkeypatch.setattr(limiter, "_prune_stale", tracked)

    await limiter.allow("alice")
    await limiter.allow("alice")

    assert True not in calls
