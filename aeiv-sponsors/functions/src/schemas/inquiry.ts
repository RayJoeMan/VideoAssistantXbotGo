import { z } from 'zod'

/** Inquiries — server-side mirror of src/schemas/inquiry.ts. */

export const inquiryStatusSchema = z.enum(['new', 'contacted', 'closed'])
export type InquiryStatus = z.infer<typeof inquiryStatusSchema>

export const inquirySchema = z.object({
  id: z.string().min(1),
  tenantId: z.string().min(1),
  sponsorId: z.string().optional(),
  sponsorName: z.string().max(120).optional(),
  name: z.string().min(1).max(120),
  email: z.string().email(),
  company: z.string().max(120).optional().default(''),
  message: z.string().min(10).max(4000),
  status: inquiryStatusSchema.default('new'),
  createdAt: z.string().min(1),
})
export type Inquiry = z.infer<typeof inquirySchema>

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
    website: z.string().max(0).optional().default(''),
  })
export type CreateInquiryInput = z.infer<typeof createInquiryInputSchema>
