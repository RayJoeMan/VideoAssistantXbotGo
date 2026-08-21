import { z } from 'zod'
import { getFirestore } from 'firebase-admin/firestore'
import { HttpsError, onCall } from 'firebase-functions/v2/https'
import {
  moduleConfigUpdateSchema,
  moduleConfigurationSchema,
  type ModuleConfiguration,
} from '../schemas/moduleConfig'
import { requirePermission } from '../security/auth'
import { getModuleConfig, MODULE_CONFIG_DOC_PATH } from '../security/tenant'
import { writeAuditLog } from '../security/audit'
import { logInfo } from '../security/logging'
import { parseInput } from '../security/validation'

const tenantInputSchema = z.object({ tenantId: z.string().min(1) })

/** Read the tenant's module configuration (public — drives the UI). */
export const aeiv_moduleConfigGet = onCall(async (request) => {
  const input = parseInput(tenantInputSchema, request.data)
  const config = await getModuleConfig(input.tenantId)
  if (!config) {
    throw new HttpsError('not-found', 'Module configuration not found for this tenant.')
  }
  return { config }
})

const updateInputSchema = z.object({
  tenantId: z.string().min(1),
  update: moduleConfigUpdateSchema,
})

/** Update tenant module configuration. Requires sponsors.settings. */
export const aeiv_moduleConfigUpdate = onCall(async (request) => {
  const input = parseInput(updateInputSchema, request.data)
  const context = await requirePermission(request, input.tenantId, 'sponsors.settings')

  const current = (await getModuleConfig(input.tenantId)) ?? emptyConfig()
  const merged: ModuleConfiguration = {
    ...current,
    ...input.update,
    features: { ...(current.features ?? {}), ...(input.update.features ?? {}) },
  }
  const parsed = moduleConfigurationSchema.parse(merged)

  await getFirestore().doc(MODULE_CONFIG_DOC_PATH(input.tenantId)).set(parsed, { merge: true })

  await writeAuditLog(context, {
    actor: context.uid,
    action: 'moduleConfig.update',
    resourceType: 'moduleConfig',
    resourceId: input.tenantId,
    changes: {
      moduleEnabled: parsed.moduleEnabled,
      features: parsed.features,
      displayName: parsed.displayName,
    },
  })

  logInfo({ ...context, operation: 'moduleConfig.update' }, 'Updated module config', {
    tenantId: input.tenantId,
  })
  return { config: parsed }
})

function emptyConfig(): ModuleConfiguration {
  return moduleConfigurationSchema.parse({
    moduleEnabled: true,
    displayName: 'Our Sponsors',
  })
}
