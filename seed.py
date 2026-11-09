"""
One-shot seeder: POST 5,000 orgs x 30 features = 150,000 quota configs
to /admin/quotas. Used to populate launch-scale key cardinality before
running load tests against a realistic keyspace.

Run after the service is up, before a load test:
    uv run python seed.py

Uses httpx with bounded concurrency so it finishes in ~1-2 minutes.
"""

import asyncio
import os
import time

import httpx


BASE_URL = os.environ.get("QUOTA_URL", "http://localhost:8000")
N_ORGS = int(os.environ.get("N_ORGS", 5000))
N_FEATURES = int(os.environ.get("N_FEATURES", 30))
THRESHOLD = int(os.environ.get("THRESHOLD", 1_000_000))
CONCURRENCY = int(os.environ.get("CONCURRENCY", 64))


async def seed_one(client, sem, org, feature, counter):
    async with sem:
        try:
            r = await client.post(
                f"{BASE_URL}/admin/quotas",
                json={"org_id": org, "feature": feature, "threshold": THRESHOLD},
                timeout=10.0,
            )
            counter[0] += 1
            if r.status_code >= 400:
                counter[1] += 1
                if counter[1] <= 5:
                    print(f"  error {r.status_code} on {org}/{feature}: {r.text[:120]}")
        except Exception as e:
            counter[1] += 1
            if counter[1] <= 5:
                print(f"  exception on {org}/{feature}: {e}")


async def _progress(counter, total, start):
    while True:
        await asyncio.sleep(2)
        done, failed = counter
        elapsed = time.perf_counter() - start
        rate = done / elapsed if elapsed > 0 else 0
        pct = 100.0 * done / total
        eta = (total - done) / rate if rate > 0 else 0
        print(
            f"  {done:,}/{total:,} ({pct:.1f}%) in {elapsed:.0f}s "
            f"- {rate:,.0f}/s - ETA {eta:.0f}s - fails={failed}"
        )


async def main():
    orgs = [f"org-{i:05d}" for i in range(N_ORGS)]
    features = [f"feature-{i:02d}" for i in range(N_FEATURES)]
    total = N_ORGS * N_FEATURES

    print(f"Seeding {total:,} quota configs to {BASE_URL}")
    print(
        f"  orgs={N_ORGS}, features={N_FEATURES}, "
        f"threshold={THRESHOLD:,}, concurrency={CONCURRENCY}"
    )

    sem = asyncio.Semaphore(CONCURRENCY)
    counter = [0, 0]
    start = time.perf_counter()

    async with httpx.AsyncClient() as client:
        tasks = [
            seed_one(client, sem, org, feature, counter)
            for org in orgs
            for feature in features
        ]

        progress_task = asyncio.create_task(_progress(counter, total, start))
        try:
            await asyncio.gather(*tasks)
        finally:
            progress_task.cancel()

    elapsed = time.perf_counter() - start
    print(f"\nDone in {elapsed:.1f}s. {counter[0]:,} requests, {counter[1]:,} failures.")
    if elapsed > 0:
        print(f"Rate: {counter[0] / elapsed:,.0f} req/s")


if __name__ == "__main__":
    asyncio.run(main())
