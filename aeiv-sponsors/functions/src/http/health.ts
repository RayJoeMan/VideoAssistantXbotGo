import { getFirestore } from 'firebase-admin/firestore'
import { onRequest } from 'firebase-functions/v2/https'

/**
 * Health check endpoint (manifest: /api/health).
 *
 * Reports whether the module loads, the API is reachable, and Firestore is
 * reachable. Deliberately returns no sensitive infrastructure details.
 * Reachable without authentication so load balancers/monitors can probe it.
 */
export const apiHealth = onRequest({ cors: true }, async (_req, res) => {
  const checks: Array<{ name: string; ok: boolean }> = []

  // 1) Function itself is running.
  checks.push({ name: 'function', ok: true })

  // 2) Firestore reachable (lightweight probe).
  try {
    await getFirestore().doc('module-health/probe').get()
    checks.push({ name: 'firestore', ok: true })
  } catch {
    checks.push({ name: 'firestore', ok: false })
  }

  const status = checks.every((check) => check.ok) ? 'ok' : 'degraded'
  res.status(status === 'ok' ? 200 : 503).json({
    status,
    module: 'aeiv-sponsors',
    version: '0.1.0',
    timestamp: new Date().toISOString(),
    checks,
  })
})
