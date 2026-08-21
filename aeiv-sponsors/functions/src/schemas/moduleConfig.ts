import { z } from 'zod'

/** Tenant module configuration — server-side mirror of src/schemas/moduleConfig. */
export const moduleConfigurationSchema = z.object({
  moduleEnabled: z.boolean().optional().default(true),
  features: z.record(z.string(), z.boolean()).optional(),
  displayName: z.string().min(1).max(120),
  tagline: z.string().max(280).optional().default(''),
  heroText: z.string().max(500).optional().default(''),
  contactEmail: z.string().email().optional(),
  maxSponsorsPerPage: z.number().int().min(1).max(100).optional().default(24),
  inquiryEnabled: z.boolean().optional().default(true),
})

export type ModuleConfiguration = z.infer<typeof moduleConfigurationSchema>

export const moduleConfigUpdateSchema = moduleConfigurationSchema.partial()
export type ModuleConfigUpdate = z.infer<typeof moduleConfigUpdateSchema>
