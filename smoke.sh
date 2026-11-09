#!/usr/bin/env bash
# End-to-end smoke test for the quota service.
# Run: bash smoke.sh

set -e

BASE=localhost:8000

step() {
  echo
  echo "=== $1 ==="
}

echo "resetting redis and sqlite for a clean run..."
docker compose exec -T redis redis-cli FLUSHDB > /dev/null
docker compose exec -T quota rm -f /app/data/quota.db
docker compose restart quota > /dev/null
sleep 1

step "1. create quota: acme / container-tracking = 500"
echo '{"org_id":"acme","feature":"container-tracking","threshold":500}' > /tmp/q1.json
curl -s -X POST $BASE/admin/quotas -H 'content-type: application/json' --data-binary @/tmp/q1.json | python3 -m json.tool

step "2. usage (fresh window)"
curl -s "$BASE/quota/usage?org_id=acme&feature=container-tracking" | python3 -m json.tool

step "3. consume 100 with idempotency_key=req-1"
echo '{"org_id":"acme","feature":"container-tracking","n":100,"idempotency_key":"req-1"}' > /tmp/q2.json
curl -s -X POST $BASE/quota/consume -H 'content-type: application/json' --data-binary @/tmp/q2.json | python3 -m json.tool

step "4. retry with same key (idempotency replay)"
curl -s -X POST $BASE/quota/consume -H 'content-type: application/json' --data-binary @/tmp/q2.json | python3 -m json.tool

step "5. usage (expect used=100, remaining=400)"
curl -s "$BASE/quota/usage?org_id=acme&feature=container-tracking" | python3 -m json.tool

step "6. refund req-1"
echo '{"idempotency_key":"req-1"}' > /tmp/q3.json
curl -s -X POST $BASE/quota/refund -H 'content-type: application/json' --data-binary @/tmp/q3.json | python3 -m json.tool

step "7. demo happy path (generates own key)"
echo '{"org_id":"acme","container_ids":["c1","c2","c3"]}' > /tmp/q4.json
curl -s -X POST $BASE/demo/track-containers -H 'content-type: application/json' --data-binary @/tmp/q4.json | python3 -m json.tool

step "8. demo retry (same demo_retry_key twice; counter deducts once)"
echo '{"org_id":"acme","container_ids":["c1","c2","c3","c4","c5"],"demo_retry_key":"demo-op-1"}' > /tmp/q5.json
echo "--- first call ---"
curl -s -X POST $BASE/demo/track-containers -H 'content-type: application/json' --data-binary @/tmp/q5.json | python3 -m json.tool
echo "--- retry ---"
curl -s -X POST $BASE/demo/track-containers -H 'content-type: application/json' --data-binary @/tmp/q5.json | python3 -m json.tool

step "9. demo failure (consume + simulated downstream fail + refund)"
echo '{"org_id":"acme","container_ids":["c1","c2","c3","c4","c5","c6","c7","c8","c9","c10"],"simulate_failure":true}' > /tmp/q6.json
curl -s -X POST $BASE/demo/track-containers -H 'content-type: application/json' --data-binary @/tmp/q6.json | python3 -m json.tool

step "10. usage after everything (used = 3 happy + 5 retry = 8)"
curl -s "$BASE/quota/usage?org_id=acme&feature=container-tracking" | python3 -m json.tool

echo
echo "done."
