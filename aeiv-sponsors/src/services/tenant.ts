import { doc, getDoc, onSnapshot } from 'firebase/firestore'
import { getFirebaseFirestore } from '../config/firebase'
import { moduleConfigurationSchema, type ModuleConfiguration } from '../schemas/moduleConfig'
import { functionsApi } from './functions'

/**
 * Tenant service — reads the module's per-tenant configuration and the
 * caller's membership (roles) for a tenant.
 *
 * Public configuration reads come straight from Firestore (rules-gated). The
 * update path goes through a callable function (permission-enforced).
 */

const MODULE_CONFIG_PATH = (tenantId: string) => `tenants/${tenantId}/moduleConfig/module` as const

export async function fetchModuleConfig(tenantId: string): Promise<ModuleConfiguration | null> {
  const db = getFirebaseFirestore()
  const snapshot = await getDoc(doc(db, MODULE_CONFIG_PATH(tenantId)))
  if (!snapshot.exists()) return null
  const parsed = moduleConfigurationSchema.safeParse(snapshot.data())
  return parsed.success ? parsed.data : null
}

/** Subscribe to tenant module config (real-time for admin settings page). */
export function subscribeModuleConfig(
  tenantId: string,
  onChange: (config: ModuleConfiguration | null) => void,
): () => void {
  const db = getFirebaseFirestore()
  return onSnapshot(doc(db, MODULE_CONFIG_PATH(tenantId)), (snapshot) => {
    if (!snapshot.exists()) {
      onChange(null)
      return
    }
    const parsed = moduleConfigurationSchema.safeParse(snapshot.data())
    onChange(parsed.success ? parsed.data : null)
  })
}

/** Server-validated update path (requires sponsors.settings permission). */
export async function updateModuleConfig(
  tenantId: string,
  update: Partial<ModuleConfiguration>,
): Promise<ModuleConfiguration> {
  const result = await functionsApi.updateModuleConfig({ tenantId, update })
  return result.config
}

export const MODULE_CONFIG_DOC_PATH = MODULE_CONFIG_PATH
