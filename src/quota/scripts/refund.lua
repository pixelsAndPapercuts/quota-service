-- Idempotent refund keyed by idempotency_key.
--
-- KEYS[1] = used-counter key   (quota:used:{org}:{feature}:{duration})
-- KEYS[2] = idempotency key    (quota:idem:{key})
--
-- ARGV[1] = limit              (integer, from SQLite config)
--
-- Returns: {refunded, remaining}
--   refunded  = 1 if units were given back on this call, 0 otherwise
--   remaining = limit - used (after this call)
--
-- No-op cases (return {0, remaining}):
--   - idempotency key doesn't exist (expired, or never consumed)
--   - original consume was denied (nothing to refund)
--   - already refunded (second refund for same key)

local used_key = KEYS[1]
local idem_key = KEYS[2]
local limit    = tonumber(ARGV[1])

-- 1. Read the original consume record.
local cached = redis.call("HMGET", idem_key, "allowed", "n_consumed", "refunded")
local allowed    = cached[1]
local n_consumed = cached[2]
local refunded   = cached[3]

-- 2. If no record exists, there's nothing to refund.
--    Return current state based on the counter.
if allowed == false then
  local used = tonumber(redis.call("GET", used_key)) or 0
  return { 0, limit - used }
end

-- 3. If the original consume was denied or already refunded, no-op.
if allowed == "0" or refunded ~= false then
  local used = tonumber(redis.call("GET", used_key)) or 0
  return { 0, limit - used }
end

-- 4. Refund: give back n_consumed units.
--    If the counter is gone (window reset after the consume), there's
--    nothing to give back. Still stamp refunded so repeated calls are no-ops.
local used = tonumber(redis.call("GET", used_key))
if used == nil then
  redis.call("HSET", idem_key, "refunded", 1)
  return { 0, limit }
end

local n = tonumber(n_consumed)
local new_used = redis.call("DECRBY", used_key, n)

-- 5. Stamp the refund so subsequent calls for this key are no-ops.
redis.call("HSET", idem_key, "refunded", 1)

return { 1, limit - new_used }
