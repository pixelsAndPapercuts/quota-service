# Portcast Quota Metering

Per-customer, per-feature quota metering service with atomic check-and-decrement,
idempotent retries, and refunds.

Redis holds counters and idempotency records on the hot path. SQLite is the
durable source of truth for quota configs. A Lua script on Redis provides the
atomic primitive.

## Bring up

```bash
docker compose up --build
```

- Service: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- Health: http://localhost:8000/healthz

## Verify

End-to-end smoke test (admin → consume → replay → usage → refund → demo routes):

```bash
./smoke.sh
```

Concurrency correctness (1000 concurrent consumes on a 500-unit quota, plus five others):

```bash
docker compose exec quota uv run pytest tests/test_concurrency.py -v
```

## Load testing

Seed launch-scale keyspace (5000 orgs × 30 features = 150k configs):

```bash
uv run python seed.py
```

Run a load scenario (see `locustfile.py` for the four user classes):

```bash
locust -f locustfile.py --host http://localhost:8000 \
    --users 15 --spawn-rate 3 --run-time 60s --headless \
    --processes 4 BroadFanoutUser
```

## Shut down

```bash
docker compose down
docker compose down -v && rm -rf data/   # wipe state
```

## More

Design rationale, trade-offs, rejected alternatives, and load-test numbers live
in [DESIGN.md](./DESIGN.md).
