import { getFirestore } from 'firebase-admin/firestore'
import { logInfo, type LogContext } from '../security/logging'

/**
 * Audit logging.
 *
 * Every admin operation that modifies important data writes an audit record to
 * `tenants/{tenantId}/auditLogs/{id}`. Records are append-only: Firestore
 * rules deny client writes/deletes, so ordinary administrators cannot edit
 * them. Stored data is sanitized (no payment data, no secrets).
 */

export interface AuditRecord {
  actor: string
  tenantId: string
  action: string
  resourceType: string
  resourceId: string
  timestamp: string
  /** Sanitized before/after summary — never raw secrets or PII. */
  changes?: Record<string, unknown>
}

export async function writeAuditLog(
  context: Pick<LogContext, 'tenantId' | 'uid' | 'correlationId'>,
  record: Omit<AuditRecord, 'tenantId' | 'timestamp'>,
): Promise<void> {
  const entry: AuditRecord = {
    ...record,
    tenantId: context.tenantId ?? '',
    timestamp: new Date().toISOString(),
  }
  await getFirestore().collection(`tenants/${entry.tenantId}/auditLogs`).add(entry)
  logInfo({ ...context, operation: `audit:${record.action}` }, 'Audit record written', {
    resourceType: record.resourceType,
    resourceId: record.resourceId,
  })
}

/** Builds a sanitized diff between two sponsor states for audit records. */
export function sanitizeSponsorChanges(
  before: { name?: string; tier?: string; published?: boolean; status?: string } | undefined,
  after: { name?: string; tier?: string; published?: boolean; status?: string } | undefined,
): Record<string, unknown> {
  const changes: Record<string, unknown> = {}
  if (before?.name !== after?.name) changes.name = { from: before?.name, to: after?.name }
  if (before?.tier !== after?.tier) changes.tier = { from: before?.tier, to: after?.tier }
  if (before?.published !== after?.published)
    changes.published = { from: before?.published, to: after?.published }
  if (before?.status !== after?.status) changes.status = { from: before?.status, to: after?.status }
  return changes
}
