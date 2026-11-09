import time
from collections import OrderedDict
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException, status

from .config import settings
from .db import get_db
from .models import (
    ConsumeResponse,
    Duration,
    QuotaResponse,
    RefundResponse,
    UsageResponse,
)
from .redis_client import get_consume_script, get_redis, get_refund_script


def _used_key(org_id: str, feature: str, duration: Duration) -> str:
    return f"quota:used:{org_id}:{feature}:{duration.value}"


def _idem_key(key: str) -> str:
    return f"quota:idem:{key}"


def _config_key(org_id: str, feature: str, duration: Duration) -> str:
    return f"quota:config:{org_id}:{feature}:{duration.value}"


class _ConfigCache:
    """In-process LRU with TTL for quota config lookups."""

    def __init__(self, max_entries: int, ttl_seconds: int) -> None:
        self._max = max_entries
        self._ttl = ttl_seconds
        self._data: OrderedDict[tuple[str, str, str], tuple[int, float]] = OrderedDict()

    def get(self, org_id: str, feature: str, duration: Duration) -> int | None:
        k = (org_id, feature, duration.value)
        entry = self._data.get(k)
        if entry is None:
            return None
        threshold, inserted_at = entry
        if time.monotonic() - inserted_at > self._ttl:
            del self._data[k]
            return None
        self._data.move_to_end(k)
        return threshold

    def put(self, org_id: str, feature: str, duration: Duration, threshold: int) -> None:
        k = (org_id, feature, duration.value)
        self._data[k] = (threshold, time.monotonic())
        self._data.move_to_end(k)
        while len(self._data) > self._max:
            self._data.popitem(last=False)


_config_cache = _ConfigCache(
    settings.config_cache_max_entries,
    settings.config_cache_ttl_seconds,
)


class QuotaService:
    """
    Integration surface for quota metering.

    Orchestrates:
      - config lookup (SQLite source of truth, Redis mirror, in-process LRU)
      - atomic counter ops via Lua scripts
      - idempotency and refund semantics
    """

    async def set_quota(
        self,
        org_id: str,
        feature: str,
        duration: Duration,
        threshold: int,
    ) -> QuotaResponse:
        db = get_db()
        now = datetime.now(timezone.utc).isoformat()

        async with db.execute(
            "SELECT id, created_at FROM quota_config "
            "WHERE org_id = ? AND feature = ? AND duration = ? AND is_active = 1",
            (org_id, feature, duration.value),
        ) as cur:
            existing = await cur.fetchone()

        if existing is None:
            await db.execute(
                "INSERT INTO quota_config "
                "(org_id, feature, duration, threshold, is_active, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 1, ?, ?)",
                (org_id, feature, duration.value, threshold, now, now),
            )
            await db.commit()
            async with db.execute(
                "SELECT id, created_at FROM quota_config "
                "WHERE org_id = ? AND feature = ? AND duration = ? AND is_active = 1",
                (org_id, feature, duration.value),
            ) as cur:
                row = await cur.fetchone()
            row_id = row["id"]
            created_at = row["created_at"]
        else:
            row_id = existing["id"]
            created_at = existing["created_at"]
            await db.execute(
                "UPDATE quota_config SET threshold = ?, updated_at = ? WHERE id = ?",
                (threshold, now, row_id),
            )
            await db.commit()

        r = get_redis()
        await r.set(_config_key(org_id, feature, duration), threshold)
        _config_cache.put(org_id, feature, duration, threshold)

        return QuotaResponse(
            id=row_id,
            org_id=org_id,
            feature=feature,
            duration=duration,
            threshold=threshold,
            is_active=True,
            created_at=created_at,
            updated_at=now,
        )

    async def consume(
        self,
        org_id: str,
        feature: str,
        n: int,
        idempotency_key: str | None = None,
    ) -> ConsumeResponse:
        duration = Duration.MONTHLY
        limit = await self._get_limit(org_id, feature, duration)

        key = idempotency_key or str(uuid4())

        script = get_consume_script()
        result = await script(
            keys=[_used_key(org_id, feature, duration), _idem_key(key)],
            args=[
                limit,
                n,
                settings.monthly_window_seconds,
                settings.idem_ttl_seconds,
                key,
                org_id,
                feature,
                duration.value,
            ],
        )
        allowed, remaining, _n_consumed = result
        return ConsumeResponse(
            allowed=bool(allowed),
            remaining=int(remaining),
            idempotency_key=key,
        )

    async def refund(self, idempotency_key: str) -> RefundResponse:
        r = get_redis()
        ctx = await r.hmget(
            _idem_key(idempotency_key),
            "org",
            "feature",
            "durations",
        )
        org_raw, feature_raw, durations_raw = ctx
        if org_raw is None:
            return RefundResponse(refunded=False, remaining=0)

        org_id = org_raw.decode()
        feature = feature_raw.decode()
        durations = durations_raw.decode().split(",")

        last_remaining = 0
        any_refunded = False
        script = get_refund_script()

        for duration_str in durations:
            duration = Duration(duration_str)
            limit = await self._get_limit(org_id, feature, duration)
            refunded, remaining = await script(
                keys=[_used_key(org_id, feature, duration), _idem_key(idempotency_key)],
                args=[limit],
            )
            last_remaining = int(remaining)
            if refunded == 1:
                any_refunded = True

        return RefundResponse(refunded=any_refunded, remaining=last_remaining)

    async def usage(
        self,
        org_id: str,
        feature: str,
        duration: Duration = Duration.MONTHLY,
    ) -> UsageResponse:
        limit = await self._get_limit(org_id, feature, duration)
        r = get_redis()
        used_raw = await r.get(_used_key(org_id, feature, duration))
        used = int(used_raw) if used_raw is not None else 0

        resets_at: str | None = None
        if used_raw is not None:
            pttl_ms = await r.pttl(_used_key(org_id, feature, duration))
            if pttl_ms > 0:
                ts = datetime.now(timezone.utc).timestamp() + pttl_ms / 1000
                resets_at = datetime.fromtimestamp(ts, timezone.utc).isoformat()

        return UsageResponse(
            org_id=org_id,
            feature=feature,
            duration=duration,
            quota=limit,
            used=used,
            remaining=limit - used,
            resets_at=resets_at,
        )

    async def _get_limit(
        self,
        org_id: str,
        feature: str,
        duration: Duration,
    ) -> int:
        cached = _config_cache.get(org_id, feature, duration)
        if cached is not None:
            return cached

        r = get_redis()
        raw = await r.get(_config_key(org_id, feature, duration))
        if raw is not None:
            threshold = int(raw)
            _config_cache.put(org_id, feature, duration, threshold)
            return threshold

        db = get_db()
        async with db.execute(
            "SELECT threshold FROM quota_config "
            "WHERE org_id = ? AND feature = ? AND duration = ? AND is_active = 1",
            (org_id, feature, duration.value),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"no active quota configured for {org_id}/{feature}/{duration.value}",
            )

        threshold = row["threshold"]
        await r.set(_config_key(org_id, feature, duration), threshold)
        _config_cache.put(org_id, feature, duration, threshold)
        return threshold


quota_service = QuotaService()
