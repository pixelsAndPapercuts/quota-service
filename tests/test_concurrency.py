import asyncio

from quota.models import Duration
from quota.service import quota_service


ORG = "acme"
FEATURE = "container-tracking"


async def test_never_overserves_under_contention():
    """1000 concurrent consumers against a 500-unit quota: exactly 500 win."""
    await quota_service.set_quota(ORG, FEATURE, Duration.MONTHLY, 500)

    tasks = [
        quota_service.consume(ORG, FEATURE, n=1)
        for _ in range(1000)
    ]
    results = await asyncio.gather(*tasks)

    allowed = sum(1 for r in results if r.allowed)
    denied = sum(1 for r in results if not r.allowed)

    assert allowed == 500, f"over/under-served: {allowed} allowed (expected 500)"
    assert denied == 500

    usage = await quota_service.usage(ORG, FEATURE, Duration.MONTHLY)
    assert usage.used == 500
    assert usage.remaining == 0


async def test_mixed_batch_sizes_never_overserve():
    """Mixed n sizes: total successful units must not exceed the quota."""
    await quota_service.set_quota(ORG, FEATURE, Duration.MONTHLY, 500)

    tasks = (
        [quota_service.consume(ORG, FEATURE, n=10) for _ in range(100)]
        + [quota_service.consume(ORG, FEATURE, n=1) for _ in range(500)]
    )
    results = await asyncio.gather(*tasks)

    allowed_n = [
        n for r, n in zip(results, [10] * 100 + [1] * 500) if r.allowed
    ]
    total_consumed = sum(allowed_n)

    assert total_consumed <= 500, f"over-served: {total_consumed} units"

    usage = await quota_service.usage(ORG, FEATURE, Duration.MONTHLY)
    assert usage.used == total_consumed
    assert usage.remaining == 500 - total_consumed
    assert usage.remaining >= 0


async def test_batch_overflow_denies_whole_batch():
    """n=600 on a 500 quota: single denial, counter untouched."""
    await quota_service.set_quota(ORG, FEATURE, Duration.MONTHLY, 500)

    result = await quota_service.consume(ORG, FEATURE, n=600)

    assert result.allowed is False
    assert result.remaining == 500

    usage = await quota_service.usage(ORG, FEATURE, Duration.MONTHLY)
    assert usage.used == 0


async def test_exact_fit_leaves_zero_remaining():
    """A single n=500 consume on a 500 quota: allowed, zero remaining."""
    await quota_service.set_quota(ORG, FEATURE, Duration.MONTHLY, 500)

    first = await quota_service.consume(ORG, FEATURE, n=500)
    assert first.allowed is True
    assert first.remaining == 0

    second = await quota_service.consume(ORG, FEATURE, n=1)
    assert second.allowed is False
    assert second.remaining == 0


async def test_idempotency_replay_under_contention():
    """100 concurrent calls with the same idempotency key: counter moves once."""
    await quota_service.set_quota(ORG, FEATURE, Duration.MONTHLY, 500)

    tasks = [
        quota_service.consume(ORG, FEATURE, n=10, idempotency_key="shared-key")
        for _ in range(100)
    ]
    results = await asyncio.gather(*tasks)

    assert all(r.allowed for r in results)
    assert all(r.remaining == 490 for r in results)

    usage = await quota_service.usage(ORG, FEATURE, Duration.MONTHLY)
    assert usage.used == 10


async def test_refund_restores_counter():
    """Consume then refund: counter back to zero, idempotent on repeat."""
    await quota_service.set_quota(ORG, FEATURE, Duration.MONTHLY, 500)

    consume_result = await quota_service.consume(
        ORG, FEATURE, n=100, idempotency_key="refund-test"
    )
    assert consume_result.allowed

    first_refund = await quota_service.refund("refund-test")
    assert first_refund.refunded is True
    assert first_refund.remaining == 500

    second_refund = await quota_service.refund("refund-test")
    assert second_refund.refunded is False
    assert second_refund.remaining == 500

    usage = await quota_service.usage(ORG, FEATURE, Duration.MONTHLY)
    assert usage.used == 0
