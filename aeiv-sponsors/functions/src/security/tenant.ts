import { getFirestore } from 'firebase-admin/firestore'
import { HttpsError } from 'firebase-functions/v2/https'
import { moduleConfigurationSchema, type ModuleConfiguration } from '../schemas/moduleConfig'
import { PUBLIC_ROLE } from './permissions'

/**
 * Tenant isolation helpers.
 *
 * Every backend operation validates the tenant and never trusts a
 * client-supplied tenant id without verifying authorization. All module data
 * lives under `tenants/{tenantId}/...`.
 */

export const MODULE_CONFIG_DOC_PATH = (tenantId: string) =>
  `tenants/${tenantId}/moduleConfig/module`

export const MEMBER_DOC_PATH = (tenantId: string, uid: string) =>
  `tenants/${tenantId}/members/${uid}`

export async function getModuleConfig(tenantId: string): Promise<ModuleConfiguration | null> {
  const snapshot = await getFirestore().doc(MODULE_CONFIG_DOC_PATH(tenantId)).get()
  if (!snapshot.exists) return null
  const parsed = moduleConfigurationSchema.safeParse(snapshot.data())
  return parsed.success ? parsed.data : null
}

/**
 * Enforces the module toggle server-side. When the module is disabled, all
 * module operations are rejected — not merely hidden in the UI.
 */
export async function assertModuleEnabled(tenantId: string): Promise<ModuleConfiguration> {
  const config = await getModuleConfig(tenantId)
  if (!config || config.moduleEnabled !== true) {
    throw new HttpsError('failed-precondition', 'This module is not enabled for this tenant.')
  }
  return config
}

/** Enforces a single feature flag server-side. */
export async function assertFeatureEnabled(
  tenantId: string,
  feature: string,
): Promise<ModuleConfiguration> {
  const config = await assertModuleEnabled(tenantId)
  if (config.features?.[feature] !== true) {
    throw new HttpsError(
      'failed-precondition',
      `This feature (${feature}) is not enabled for this tenant.`,
    )
  }
  return config
}

/** Returns the caller's roles within a tenant (falls back to public). */
export async function getMemberRoles(tenantId: string, uid: string): Promise<string[]> {
  const snapshot = await getFirestore().doc(MEMBER_DOC_PATH(tenantId, uid)).get()
  const roles = snapshot.exists ? ((snapshot.data()?.roles as string[] | undefined) ?? []) : []
  return roles.length > 0 ? roles : [PUBLIC_ROLE]
}
