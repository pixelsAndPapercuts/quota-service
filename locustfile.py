"""
Load test harness for the quota service.

Four user classes cover different access patterns. Run any of them with:

  locust -f locustfile.py --host http://localhost:8000 \\
      --users <N> --spawn-rate <N> --run-time 60s --headless \\
      --processes 4 <UserClassName>

  BroadFanoutUser  - fan-out across 50 orgs, 2 features (normal per-instance load)
  BurstUser        - same shape, higher density (fleet-wide load concentrated)
  SingleOrgUser    - all traffic on one (org, feature) counter (worst-case contention)
  LaunchScaleUser  - uniform access across 5,000 orgs x 30 features (requires seed.py)

Quotas are configured very high (1_000_000 units) so we measure throughput
and latency of the enforcement path, not quota-exhaustion handling. Those
cases are covered by the pytest concurrency suite.
"""

import random
from uuid import uuid4

from locust import HttpUser, between, events, task


BIG_THRESHOLD = 1_000_000

LAUNCH_ORGS = [f"org-{i:05d}" for i in range(5000)]
LAUNCH_FEATURES = [f"feature-{i:02d}" for i in range(30)]

BROAD_ORGS = LAUNCH_ORGS[:50]
FEATURES = LAUNCH_FEATURES[:2]
SINGLE_ORG = LAUNCH_ORGS[0]
SINGLE_FEATURE = LAUNCH_FEATURES[0]


@events.request.add_listener
def record_server_time(**kwargs):
    """Record X-Processing-Time-Ms as a separate stat so we can see
    server-side overhead distinct from wall-clock latency, which includes
    network and load-generator queueing."""
    if kwargs.get("exception") is not None:
        return
    name = kwargs.get("name") or ""
    if name.endswith(" [server]"):
        return
    response = kwargs.get("response")
    if response is None:
        return
    header = response.headers.get("X-Processing-Time-Ms")
    if not header:
        return
    try:
        server_ms = float(header)
    except ValueError:
        return
    events.request.fire(
        request_type=kwargs.get("request_type"),
        name=f"{name} [server]",
        response_time=server_ms,
        response_length=kwargs.get("response_length", 0),
        exception=None,
        context=kwargs.get("context"),
        response=None,
        start_time=kwargs.get("start_time"),
        url=kwargs.get("url"),
    )


class BroadFanoutUser(HttpUser):
    """Many orgs, many features. No single hot counter.
    Assumes the keyspace is pre-seeded by seed.py."""

    wait_time = between(0.0, 0.01)

    @task(10)
    def consume(self):
        org = random.choice(BROAD_ORGS)
        feature = random.choice(FEATURES)
        n = random.choice([1, 1, 1, 5, 10])
        self.client.post(
            "/quota/consume",
            json={
                "org_id": org,
                "feature": feature,
                "n": n,
                "idempotency_key": str(uuid4()),
            },
            name="/quota/consume",
        )

    @task(1)
    def check_usage(self):
        org = random.choice(BROAD_ORGS)
        feature = random.choice(FEATURES)
        self.client.get(
            f"/quota/usage?org_id={org}&feature={feature}",
            name="/quota/usage",
        )


class BurstUser(BroadFanoutUser):
    """Same shape as broad fanout; launch with higher --users for 10k rps peak."""

    wait_time = between(0.0, 0.001)


class SingleOrgUser(HttpUser):
    """All users hammer the same (org, feature) counter. Worst-case contention.
    Assumes the keyspace is pre-seeded by seed.py."""

    wait_time = between(0.0, 0.01)

    @task(10)
    def consume(self):
        n = random.choice([1, 1, 1, 5, 10])
        self.client.post(
            "/quota/consume",
            json={
                "org_id": SINGLE_ORG,
                "feature": SINGLE_FEATURE,
                "n": n,
                "idempotency_key": str(uuid4()),
            },
            name="/quota/consume",
        )

    @task(1)
    def check_usage(self):
        self.client.get(
            f"/quota/usage?org_id={SINGLE_ORG}&feature={SINGLE_FEATURE}",
            name="/quota/usage",
        )


class LaunchScaleUser(HttpUser):
    """Launch-scale key cardinality: 5,000 orgs x 30 features = 150,000 pairs.

    Requires the keyspace to be pre-seeded (via seed.py). Does NOT seed on_start,
    since seeding 150k pairs per user is impractical. Access pattern is uniform
    random across the full keyspace, which is the worst case for the in-process
    LRU config cache (10,000 slots out of 150,000 pairs = ~7% hit rate).
    Real workloads are Zipfian-skewed, so this is a conservative stress test.
    """

    wait_time = between(0.0, 0.01)

    @task(10)
    def consume(self):
        org = random.choice(LAUNCH_ORGS)
        feature = random.choice(LAUNCH_FEATURES)
        n = random.choice([1, 1, 1, 5, 10])
        self.client.post(
            "/quota/consume",
            json={
                "org_id": org,
                "feature": feature,
                "n": n,
                "idempotency_key": str(uuid4()),
            },
            name="/quota/consume",
        )

    @task(1)
    def check_usage(self):
        org = random.choice(LAUNCH_ORGS)
        feature = random.choice(LAUNCH_FEATURES)
        self.client.get(
            f"/quota/usage?org_id={org}&feature={feature}",
            name="/quota/usage",
        )
