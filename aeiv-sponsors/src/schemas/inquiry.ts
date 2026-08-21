import { z } from 'zod'

/**
 * Sponsor inquiry entities.
 *
 * Stored at `tenants/{tenantId}/inquiries/{id}`. Written exclusively through a
 * callable function (rate-limited, spam-protected) — clients never write
 * directly to this collection.
 */

export const inquiryStatusSchema = z.enum(['new', 'contacted', 'closed'])
export type InquiryStatus = z.infer<typeof inquiryStatusSchema>

export const inquirySchema = z.object({
  id: z.string().min(1),
  tenantId: z.string().min(1),
  /** Optional target sponsor (null = general inquiry). */
  sponsorId: z.string().optional(),
  sponsorName: z.string().max(120).optional(),
  name: z.string().min(1).max(120),
  email: z.string().email(),
  company: z.string().max(120).optional().default(''),
  message: z.string().min(10).max(4000),
  status: inquiryStatusSchema.default('new'),
  /** Source (honeypot flag for abuse detection). */
  createdAt: z.string().min(1),
})
export type Inquiry = z.infer<typeof inquirySchema>

/** Client-submitted inquiry (validated again on the server). */
export const createInquiryInputSchema = inquirySchema
  .pick({
    name: true,
    email: true,
    company: true,
    message: true,
    sponsorId: true,
    sponsorName: true,
  })
  .extend({
    tenantId: z.string().min(1),
    /** Honeypot — must be empty for humans. */
    website: z.string().max(0).optional().default(''),
  })
export type CreateInquiryInput = z.infer<typeof createInquiryInputSchema>
