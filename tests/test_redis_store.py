"""Tests for Redis-backed middleware store — rate limiting, audit, overrides.

All tests mock redis.asyncio to avoid requiring a real Redis instance.
Verifies: Redis operations, tenant namespacing, local fallback, graceful degradation.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import json
import pytest

import aion.middleware as mw


@pytest.fixture(autouse=True)
def reset_middleware_state():
    """Reset all middleware state between tests."""
    mw._redis_client = None
    mw._redis_available = False
    mw._redis_last_failure = 0.0  # reset circuit breaker
    mw._local_rate_limits.clear()
    mw._local_audit_log.clear()
    mw._local_overrides.clear()
    yield
    mw._redis_client = None
    mw._redis_available = False
    mw._redis_last_failure = 0.0
    mw._local_rate_limits.clear()
    mw._local_audit_log.clear()
    mw._local_overrides.clear()


def _mock_redis():
    """Create a mock async Redis client."""
    r = AsyncMock()
    r.ping = AsyncMock(return_value=True)

    # Pipeline mock
    pipe = AsyncMock()
    pipe.zremrangebyscore = MagicMock(return_value=pipe)
    pipe.zadd = MagicMock(return_value=pipe)
    pipe.zcard = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[0, 1, 1, True])  # default: 1 entry (under limit)
    r.pipeline = MagicMock(return_value=pipe)

    r.zrem = AsyncMock()
    r.lpush = AsyncMock()
    r.ltrim = AsyncMock()
    r.lrange = AsyncMock(return_value=[])
    r.hset = AsyncMock()
    r.hgetall = AsyncMock(return_value={})
    r.delete = AsyncMock()

    return r, pipe


# ══════════════════════════════════════════════
# Rate limiting
# ══════════════════════════════════════════════

class TestRateLimitRedis:

    @pytest.mark.asyncio
    async def test_allows_under_threshold(self):
        """Redis sorted set rate limit allows requests under threshold."""
        r, pipe = _mock_redis()
        pipe.execute = AsyncMock(return_value=[0, 1, 5, True])  # 5 entries, limit is 100

        mw._redis_client = r
        mw._redis_available = True

        result = await mw._check_rate_limit("chat:tenant-a:1.2.3.4", 100)
        assert result is True
        r.pipeline.assert_called_once()

    @pytest.mark.asyncio
    async def test_blocks_over_threshold(self):
        """Redis rate limit blocks when count exceeds limit."""
        r, pipe = _mock_redis()
        pipe.execute = AsyncMock(return_value=[0, 1, 101, True])  # 101 entries, limit 100

        mw._redis_client = r
        mw._redis_available = True

        result = await mw._check_rate_limit("chat:tenant-a:1.2.3.4", 100)
        assert result is False
        r.zrem.assert_called_once()  # Removed the just-added entry

    @pytest.mark.asyncio
    async def test_fallback_local_when_redis_down(self):
        """Falls back to local rate limit when Redis unavailable."""
        mw._redis_client = None
        mw._redis_available = False

        # Should use local — first 100 requests pass
        for i in range(100):
            assert await mw._check_rate_limit("test-key", 100) is True

        # 101st should be blocked
        assert await mw._check_rate_limit("test-key", 100) is False

    @pytest.mark.asyncio
    async def test_fallback_on_redis_error(self):
        """Falls back to local if Redis pipeline raises exception."""
        r, pipe = _mock_redis()
        pipe.execute = AsyncMock(side_effect=ConnectionError("Redis dead"))

        mw._redis_client = r
        mw._redis_available = True

        result = await mw._check_rate_limit("test-key", 100)
        assert result is True  # Local fallback allows

    @pytest.mark.asyncio
    async def test_key_contains_tenant_namespace(self):
        """Rate limit Redis key includes tenant for isolation."""
        r, pipe = _mock_redis()
        mw._redis_client = r
        mw._redis_available = True

        await mw._check_rate_limit("chat:acme-corp:1.2.3.4", 100)

        # Verify the pipeline was called — key should be prefixed
        r.pipeline.assert_called_once()
        # The key passed to zremrangebyscore should contain the tenant
        pipe.zremrangebyscore.assert_called_once()
        call_args = pipe.zremrangebyscore.call_args
        assert "acme-corp" in call_args[0][0]  # key contains tenant


# ══════════════════════════════════════════════
# Audit
# ══════════════════════════════════════════════

class TestAuditRedis:

    @pytest.fixture
    def mock_request(self):
        req = MagicMock()
        req.url.path = "/v1/killswitch"
        req.method = "PUT"
        req.client.host = "192.168.1.1"
        return req

    @pytest.mark.asyncio
    async def test_audit_persisted_to_redis(self, mock_request):
        """Audit event goes to Redis with tenant-namespaced key."""
        r, _ = _mock_redis()
        mw._redis_client = r
        mw._redis_available = True

        await mw.audit("PUT /v1/killswitch", mock_request, "acme-corp")

        r.lpush.assert_called_once()
        call_args = r.lpush.call_args[0]
        assert call_args[0] == "aion:audit:acme-corp"  # Tenant namespaced

        r.ltrim.assert_called_once()

    @pytest.mark.asyncio
    async def test_audit_read_from_redis(self):
        """Audit log reads from Redis when available."""
        r, _ = _mock_redis()
        entries = [json.dumps({"action": "test", "timestamp": 123})]
        r.lrange = AsyncMock(return_value=entries)
        mw._redis_client = r
        mw._redis_available = True

        result = await mw.get_audit_log(10, "acme-corp")
        assert len(result) == 1
        assert result[0]["action"] == "test"
        r.lrange.assert_called_once_with("aion:audit:acme-corp", 0, 9)

    @pytest.mark.asyncio
    async def test_audit_fallback_local(self, mock_request):
        """Audit falls back to local buffer when Redis down."""
        mw._redis_client = None
        mw._redis_available = False

        await mw.audit("test action", mock_request, "tenant-x")

        result = await mw.get_audit_log(10, "tenant-x")
        assert len(result) == 1
        assert result[0]["tenant"] == "tenant-x"

    @pytest.mark.asyncio
    async def test_audit_always_writes_local(self, mock_request):
        """Even with Redis, local buffer always gets the entry."""
        r, _ = _mock_redis()
        mw._redis_client = r
        mw._redis_available = True

        await mw.audit("test", mock_request, "t1")

        # Local buffer has it too
        assert len(mw._local_audit_log) == 1


# ══════════════════════════════════════════════
# Overrides
# ══════════════════════════════════════════════

class TestOverridesRedis:

    @pytest.mark.asyncio
    async def test_override_stored_in_redis(self):
        """Override writes to Redis with tenant namespace."""
        r, _ = _mock_redis()
        mw._redis_client = r
        mw._redis_available = True

        await mw.set_override("force_model", "gpt-4o", "acme-corp")

        r.hset.assert_called_once_with(
            "aion:overrides:acme-corp", "force_model", json.dumps("gpt-4o")
        )

    @pytest.mark.asyncio
    async def test_override_read_from_redis(self):
        """Overrides read from Redis when available."""
        r, _ = _mock_redis()
        r.hgetall = AsyncMock(return_value={"force_model": '"gpt-4o"'})
        mw._redis_client = r
        mw._redis_available = True

        result = await mw.get_overrides("acme-corp")
        assert result["force_model"] == "gpt-4o"
        r.hgetall.assert_called_once_with("aion:overrides:acme-corp")

    @pytest.mark.asyncio
    async def test_override_fallback_local(self):
        """Overrides fall back to local dict when Redis down."""
        mw._redis_client = None
        mw._redis_available = False

        await mw.set_override("force_model", "gpt-4o-mini", "t1")
        result = await mw.get_overrides("t1")
        assert result["force_model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_override_clear(self):
        """Clear removes both local and Redis."""
        r, _ = _mock_redis()
        mw._redis_client = r
        mw._redis_available = True

        await mw.set_override("x", "y", "t1")
        await mw.clear_overrides("t1")

        assert "t1" not in mw._local_overrides
        r.delete.assert_called_with("aion:overrides:t1")

    @pytest.mark.asyncio
    async def test_tenant_isolation(self):
        """Different tenants have separate overrides."""
        await mw.set_override("model", "a", "tenant-a")
        await mw.set_override("model", "b", "tenant-b")

        a = await mw.get_overrides("tenant-a")
        b = await mw.get_overrides("tenant-b")

        assert a["model"] == "a"
        assert b["model"] == "b"


# ══════════════════════════════════════════════
# Graceful degradation
# ══════════════════════════════════════════════

class TestGracefulDegradation:

    @pytest.mark.asyncio
    async def test_redis_dies_mid_operation(self):
        """If Redis fails during operation, falls back gracefully."""
        r, _ = _mock_redis()
        r.lpush = AsyncMock(side_effect=ConnectionError("Redis died"))
        mw._redis_client = r
        mw._redis_available = True

        req = MagicMock()
        req.url.path = "/v1/test"
        req.method = "GET"
        req.client.host = "1.2.3.4"

        # Should not raise — falls back to local
        await mw.audit("test", req, "t1")
        assert len(mw._local_audit_log) == 1  # Local buffer has it
