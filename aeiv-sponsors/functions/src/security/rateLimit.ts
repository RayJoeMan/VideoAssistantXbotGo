import { HttpsError } from 'firebase-functions/v2/https'

/**
 * Lightweight in-memory rate limiter.
 *
 * Guards public/abuse-prone endpoints (inquiry submission). This is a per
 * instance, per process limiter — adequate for a module scaffold; for
 * multi-instance enforcement, back it with Firestore counters or App Check
 * (documented in docs/security.md).
 */
interface Bucket {
  count: number
  resetAt: number
}

const buckets = new Map<string, Bucket>()

function prune(now: number): void {
  for (const [key, bucket] of buckets) {
    if (bucket.resetAt <= now) buckets.delete(key)
  }
}

/**
 * Returns true when the key is within limits; throws HttpsError otherwise.
 *
 * @param key identity of the caller (e.g. `ip:<ip>` or `uid:<uid>`)
 * @param limit max requests per window
 * @param windowMs sliding window length
 */
export function enforceRateLimit(key: string, limit: number, windowMs: number): void {
  const now = Date.now()
  prune(now)
  const bucket = buckets.get(key)
  if (!bucket || bucket.resetAt <= now) {
    buckets.set(key, { count: 1, resetAt: now + windowMs })
    return
  }
  if (bucket.count >= limit) {
    throw new HttpsError('resource-exhausted', 'Too many requests. Please try again later.')
  }
  bucket.count += 1
}
