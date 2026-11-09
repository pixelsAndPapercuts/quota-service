-- Atomic check-and-decrement with idempotency.
--
-- KEYS[1] = used-counter key   (quota:used:{org}:{feature}:{duration})
-- KEYS[2] = idempotency key    (quota:idem:{key})  -- may be empty string
--
-- ARGV[1] = limit              (integer, from SQLite config)
-- ARGV[2] = n                  (units to consume, > 0)
-- ARGV[3] = window_ttl_seconds (TTL for used-counter on first write)
-- ARGV[4] = idem_ttl_seconds   (TTL for idempotency record)
-- ARGV[5] = idempotency_key    (string; "" means no idempotency)
-- ARGV[6] = org_id             (stamped on idem hash for refund lookup)
-- ARGV[7] = feature            (stamped on idem hash for refund lookup)
-- ARGV[8] = durations          (comma-joined; today one value, e.g. "MONTHLY")
--
-- Returns: {allowed, remaining, n_consumed}
--   allowed      = 1 or 0
--   remaining    = limit - used (after this call)
--   n_consumed   = how many units were actually deducted (0 if denied)

local used_key  = KEYS[1]
local idem_key  = KEYS[2]

local limit     = tonumber(ARGV[1])
local n         = tonumber(ARGV[2])
local win_ttl   = tonumber(ARGV[3])
local idem_ttl  = tonumber(ARGV[4])
local idem_val  = ARGV[5]
local org       = ARGV[6]
local feature   = ARGV[7]
local durations = ARGV[8]

-- 1. Idempotency replay: if we've seen this key, return the cached answer
--    without touching the counter.
if idem_val ~= "" then
  local cached = redis.call("HMGET", idem_key, "allowed", "remaining", "n_consumed")
  if cached[1] ~= false then
    return { tonumber(cached[1]), tonumber(cached[2]), tonumber(cached[3]) }
  end
end

-- 2. Read current usage. Missing key = 0 (fresh window).
local used = tonumber(redis.call("GET", used_key)) or 0

-- 3. All-or-nothing check. If the full batch doesn't fit, deny the whole thing.
if used + n > limit then
  local remaining = limit - used
  if idem_val ~= "" then
    redis.call("HSET", idem_key,
      "allowed", 0,
      "remaining", remaining,
      "n_consumed", 0,
      "org", org,
      "feature", feature,
      "durations", durations)
    redis.call("EXPIRE", idem_key, idem_ttl)
  end
  return { 0, remaining, 0 }
end

-- 4. Deduct. INCRBY auto-creates the key at 0 if missing.
local new_used = redis.call("INCRBY", used_key, n)

-- 5. Anchor the rolling window on first write. TTL(-1) means key exists
--    but has no TTL yet — set it. On subsequent writes PTTL is positive,
--    so we don't extend it (that would make the window slide forever).
if redis.call("PTTL", used_key) == -1 then
  redis.call("EXPIRE", used_key, win_ttl)
end

local remaining = limit - new_used

-- 6. Record the outcome for idempotent retries.
if idem_val ~= "" then
  redis.call("HSET", idem_key,
    "allowed", 1,
    "remaining", remaining,
    "n_consumed", n,
    "org", org,
    "feature", feature,
    "durations", durations)
  redis.call("EXPIRE", idem_key, idem_ttl)
end

return { 1, remaining, n }
