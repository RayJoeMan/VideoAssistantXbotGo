import type { CallableRequest } from 'firebase-functions/v2/https'
import { HttpsError } from 'firebase-functions/v2/https'
import { assertModuleEnabled, getMemberRoles } from './tenant'
import { rolesGrantPermission } from './permissions'

/**
 * Authentication + authorization for callable functions.
 *
 * Every callable flow is: authenticate → authorize (permission) → validate the
 * tenant (module must be enabled) → validate input → act. The permission
 * checks below mirror `moduleManifest.roles` and are the authoritative
 * enforcement — never rely on the client hiding UI.
 */

export interface TenantContext {
  tenantId: string
  uid: string
  roles: string[]
}

export function requireAuth(request: CallableRequest): { uid: string } {
  if (!request.auth) {
    throw new HttpsError('unauthenticated', 'You must be signed in to perform this action.')
  }
  return { uid: request.auth.uid }
}

/**
 * Authenticates and authorizes a tenant-scoped operation. Also enforces the
 * module toggle (disabled module ⇒ every operation rejected).
 */
export async function requirePermission(
  request: CallableRequest,
  tenantId: string,
  permission: string,
): Promise<TenantContext> {
  const { uid } = requireAuth(request)
  await assertModuleEnabled(tenantId)
  const roles = await getMemberRoles(tenantId, uid)
  if (!rolesGrantPermission(roles, permission)) {
    throw new HttpsError('permission-denied', `Missing required permission: ${permission}`)
  }
  return { tenantId, uid, roles }
}
