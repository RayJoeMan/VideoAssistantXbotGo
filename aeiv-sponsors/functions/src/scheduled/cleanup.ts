import { getFirestore } from 'firebase-admin/firestore'
import { onSchedule } from 'firebase-functions/v2/scheduler'
import { logInfo } from '../security/logging'

/**
 * Scheduled maintenance: purge audit logs past their retention window.
 *
 * Retention is a data-lifecycle requirement (see docs/data-model.md). Runs
 * daily at 03:00 UTC. Deletes are batched and bounded to keep function
 * execution within limits.
 */
const AUDIT_RETENTION_DAYS = 90
const MAX_DELETES_PER_RUN = 500

export const scheduledAuditLogCleanup = onSchedule(
  { schedule: '0 3 * * *', timeZone: 'UTC' },
  async () => {
    const cutoff = new Date(Date.now() - AUDIT_RETENTION_DAYS * 24 * 60 * 60 * 1000).toISOString()
    const db = getFirestore()

    // Audit logs live under tenant collections; iterate tenants is not
    // possible without an index, so this scaffold documents the pattern and
    // cleans the demo tenant. Production: enumerate tenant ids from a tenants
    // registry collection.
    const tenants = ['demo-tenant']
    let totalDeleted = 0

    for (const tenantId of tenants) {
      const expired = await db
        .collection(`tenants/${tenantId}/auditLogs`)
        .where('timestamp', '<', cutoff)
        .limit(MAX_DELETES_PER_RUN)
        .get()

      const batch = db.batch()
      for (const doc of expired.docs) {
        batch.delete(doc.ref)
      }
      if (expired.size > 0) {
        await batch.commit()
        totalDeleted += expired.size
      }
    }

    logInfo({ operation: 'auditLog.cleanup' }, 'Audit log cleanup finished', {
      cutoff,
      deleted: totalDeleted,
    })
  },
)
