import { z } from 'zod'

/**
 * Tenant-level configuration for this module.
 *
 * Stored at `tenants/{tenantId}/moduleConfig` and validated by this schema on
 * both client and server. All values are tenant-specific — the core module
 * contains no customer data. Adding a new key is backwards-compatible
 * (defaults are applied); removing/renaming a key is a breaking change and
 * requires a migration (see docs/configuration.md).
 */
export const moduleConfigurationSchema = z.object({
  /** Whether the module is enabled for this tenant. */
  moduleEnabled: z.boolean().optional().default(true),
  /** Feature flags — keys must match moduleManifest.features. */
  features: z.record(z.string(), z.boolean()).optional(),
  /** Display name shown in the public UI (e.g. "Our Sponsors"). */
  displayName: z.string().min(1).max(120),
  tagline: z.string().max(280).optional().default(''),
  heroText: z.string().max(500).optional().default(''),
  /** Email that receives inquiry notifications (feature: notifications). */
  contactEmail: z.string().email().optional(),
  maxSponsorsPerPage: z.number().int().min(1).max(100).optional().default(24),
  /** Whether the inquiry form is enabled (feature: inquiryForm). */
  inquiryEnabled: z.boolean().optional().default(true),
})

export type ModuleConfiguration = z.infer<typeof moduleConfigurationSchema>

/** Keys that may be updated by a tenant admin via the settings UI. */
export const moduleConfigurationUpdateSchema = moduleConfigurationSchema.partial()

export type ModuleConfigurationUpdate = z.infer<typeof moduleConfigurationUpdateSchema>
