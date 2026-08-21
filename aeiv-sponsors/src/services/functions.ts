import { callFunction } from '../api/client'
import type { CreateInquiryInput } from '../schemas/inquiry'
import type {
  CreateSponsorInput,
  DeleteSponsorInput,
  SponsorAdminView,
  UpdateSponsorInput,
} from '../schemas/sponsor'
import type { ModuleConfiguration, ModuleConfigurationUpdate } from '../schemas/moduleConfig'

/**
 * Typed wrappers for the module's Cloud Functions.
 *
 * Function names must match `functions/src/index.ts` exports.
 */

export interface HealthReport {
  status: 'ok' | 'degraded'
  module: string
  version: string
  checks: Array<{ name: string; ok: boolean; detail?: string }>
}

export const functionsApi = {
  healthCheck(): Promise<HealthReport> {
    return callFunction<Record<string, never>, HealthReport>('aeiv_healthCheck', {})
  },

  listSponsors(input: { tenantId: string }): Promise<{ sponsors: SponsorAdminView[] }> {
    return callFunction('aeiv_sponsorsList', input)
  },

  createSponsor(input: CreateSponsorInput): Promise<{ sponsor: SponsorAdminView }> {
    return callFunction('aeiv_sponsorsCreate', input)
  },

  updateSponsor(input: UpdateSponsorInput): Promise<{ sponsor: SponsorAdminView }> {
    return callFunction('aeiv_sponsorsUpdate', input)
  },

  deleteSponsor(input: DeleteSponsorInput): Promise<{ deleted: true }> {
    return callFunction('aeiv_sponsorsDelete', input)
  },

  createInquiry(input: CreateInquiryInput): Promise<{ inquiryId: string }> {
    return callFunction('aeiv_inquiriesCreate', input)
  },

  getModuleConfig(input: { tenantId: string }): Promise<{ config: ModuleConfiguration }> {
    return callFunction('aeiv_moduleConfigGet', input)
  },

  updateModuleConfig(input: {
    tenantId: string
    update: ModuleConfigurationUpdate
  }): Promise<{ config: ModuleConfiguration }> {
    return callFunction('aeiv_moduleConfigUpdate', input)
  },
}
