import { z } from 'zod'

/**
 * Sponsor entities.
 *
 * IMPORTANT — data separation: each sponsor is represented by TWO documents
 * with different access requirements:
 *
 *  - `tenants/{tenantId}/sponsors/public/{id}` — read by anyone (public UI).
 *  - `tenants/{tenantId}/sponsors/admin/{id}`  — admin-only (contact details,
 *    contract, amounts). Never merged into the public document.
 *
 * Keeping them separate lets Firestore rules grant public reads on one and
 * deny them on the other.
 */

export const sponsorStatusSchema = z.enum(['active', 'inactive', 'pending'])
export type SponsorStatus = z.infer<typeof sponsorStatusSchema>

export const sponsorTierSchema = z.enum(['platinum', 'gold', 'silver', 'bronze', 'community'])
export type SponsorTier = z.infer<typeof sponsorTierSchema>

/** Public-facing sponsor document (read by everyone). */
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

/** Admin-only sponsor document (contact/contract data). */
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

const publicSponsorInputSchema = publicSponsorSchema.omit({
  id: true,
  tenantId: true,
  createdAt: true,
  updatedAt: true,
})

const sponsorAdminInputSchema = sponsorAdminSchema.omit({
  id: true,
  tenantId: true,
  createdAt: true,
  updatedAt: true,
})

/** Input for creating a sponsor (validated client-side and server-side). */
export const createSponsorInputSchema = z.object({
  tenantId: z.string().min(1),
  public: publicSponsorInputSchema,
  admin: sponsorAdminInputSchema.partial(),
})
export type CreateSponsorInput = z.infer<typeof createSponsorInputSchema>

/** Input for updating a sponsor. */
export const updateSponsorInputSchema = z.object({
  tenantId: z.string().min(1),
  sponsorId: z.string().min(1),
  public: publicSponsorInputSchema.partial(),
  admin: sponsorAdminInputSchema.partial().optional(),
})
export type UpdateSponsorInput = z.infer<typeof updateSponsorInputSchema>

/** Input for deleting a sponsor. */
export const deleteSponsorInputSchema = z.object({
  tenantId: z.string().min(1),
  sponsorId: z.string().min(1),
})
export type DeleteSponsorInput = z.infer<typeof deleteSponsorInputSchema>

/** Combined sponsor view for the admin UI. */
export interface SponsorAdminView {
  public: PublicSponsor
  admin: SponsorAdmin
}
