import { z } from 'zod'

/** Sponsor entities — server-side mirror of src/schemas/sponsor.ts. */

export const sponsorStatusSchema = z.enum(['active', 'inactive', 'pending'])
export type SponsorStatus = z.infer<typeof sponsorStatusSchema>

export const sponsorTierSchema = z.enum(['platinum', 'gold', 'silver', 'bronze', 'community'])
export type SponsorTier = z.infer<typeof sponsorTierSchema>

export const publicSponsorSchema = z.object({
  id: z.string().min(1),
  tenantId: z.string().min(1),
  name: z.string().min(1).max(120),
  tier: sponsorTierSchema,
  websiteUrl: z.string().url().optional(),
  logoUrl: z.string().url().optional(),
  tagline: z.string().max(280).optional().default(''),
  description: z.string().max(2000).optional().default(''),
  sortOrder: z.number().int().min(0).optional().default(0),
  published: z.boolean().default(false),
  createdAt: z.string().min(1),
  updatedAt: z.string().min(1),
})
export type PublicSponsor = z.infer<typeof publicSponsorSchema>

export const sponsorAdminSchema = z.object({
  id: z.string().min(1),
  tenantId: z.string().min(1),
  status: sponsorStatusSchema.default('pending'),
  contactName: z.string().max(200).optional(),
  contactEmail: z.string().email().optional(),
  contactPhone: z.string().max(60).optional(),
  contractStart: z.string().optional(),
  contractEnd: z.string().optional(),
  monthlyAmount: z.number().nonnegative().optional(),
  notes: z.string().max(2000).optional().default(''),
  createdAt: z.string().min(1),
  updatedAt: z.string().min(1),
})
export type SponsorAdmin = z.infer<typeof sponsorAdminSchema>

const publicInput = publicSponsorSchema.omit({
  id: true,
  tenantId: true,
  createdAt: true,
  updatedAt: true,
})
const adminInput = sponsorAdminSchema.omit({
  id: true,
  tenantId: true,
  createdAt: true,
  updatedAt: true,
})

export const sponsorsListInputSchema = z.object({ tenantId: z.string().min(1) })
export type SponsorsListInput = z.infer<typeof sponsorsListInputSchema>

export const createSponsorInputSchema = z.object({
  tenantId: z.string().min(1),
  public: publicInput,
  admin: adminInput.partial().optional(),
})
export type CreateSponsorInput = z.infer<typeof createSponsorInputSchema>

export const updateSponsorInputSchema = z.object({
  tenantId: z.string().min(1),
  sponsorId: z.string().min(1),
  public: publicInput.partial(),
  admin: adminInput.partial().optional(),
})
export type UpdateSponsorInput = z.infer<typeof updateSponsorInputSchema>

export const deleteSponsorInputSchema = z.object({
  tenantId: z.string().min(1),
  sponsorId: z.string().min(1),
})
export type DeleteSponsorInput = z.infer<typeof deleteSponsorInputSchema>
