import { getFirestore } from 'firebase-admin/firestore'
import { onCall } from 'firebase-functions/v2/https'

/**
 * Callable health check (client-invoked, e.g. from the admin dashboard).
 *
 * Reports module load + Firestore reachability without exposing sensitive
 * infrastructure details.
 */
export const aeiv_healthCheck = onCall(async () => {
  const checks: Array<{ name: string; ok: boolean }> = []
  checks.push({ name: 'function', ok: true })

  try {
    await getFirestore().doc('module-health/probe').get()
    checks.push({ name: 'firestore', ok: true })
  } catch {
    checks.push({ name: 'firestore', ok: false })
  }

  const status = checks.every((check) => check.ok) ? 'ok' : 'degraded'
  return {
    status,
    module: 'aeiv-sponsors',
    version: '0.1.0',
    checks,
  }
})
