import { describe, expect, it } from 'vitest'
import { createSponsorInputSchema, updateSponsorInputSchema } from '../../src/schemas/sponsor'
import { createInquiryInputSchema } from '../../src/schemas/inquiry'
import { moduleConfigurationSchema } from '../../src/schemas/moduleConfig'

describe('sponsor schemas', () => {
  it('accepts a valid create input (public + admin)', () => {
    const result = createSponsorInputSchema.safeParse({
      tenantId: 'tenant-1',
      public: { name: 'Acme', tier: 'gold', published: true },
      admin: { contactEmail: 'contact@acme.example', status: 'active' },
    })
    expect(result.success).toBe(true)
  })

  it('rejects a create input without a name', () => {
    const result = createSponsorInputSchema.safeParse({
      tenantId: 'tenant-1',
      public: { tier: 'gold' },
    })
    expect(result.success).toBe(false)
  })

  it('rejects an invalid tier', () => {
    const result = createSponsorInputSchema.safeParse({
      tenantId: 'tenant-1',
      public: { name: 'Acme', tier: 'diamond' },
    })
    expect(result.success).toBe(false)
  })

  it('rejects an invalid website URL', () => {
    const result = createSponsorInputSchema.safeParse({
      tenantId: 'tenant-1',
      public: { name: 'Acme', tier: 'gold', websiteUrl: 'not-a-url' },
    })
    expect(result.success).toBe(false)
  })

  it('rejects an invalid contact email in admin data', () => {
    const result = createSponsorInputSchema.safeParse({
      tenantId: 'tenant-1',
      public: { name: 'Acme', tier: 'gold' },
      admin: { contactEmail: 'nope' },
    })
    expect(result.success).toBe(false)
  })

  it('accepts a partial update input', () => {
    const result = updateSponsorInputSchema.safeParse({
      tenantId: 'tenant-1',
      sponsorId: 'sp-1',
      public: { tier: 'platinum' },
    })
    expect(result.success).toBe(true)
  })
})

describe('inquiry schema', () => {
  it('accepts a valid inquiry', () => {
    const result = createInquiryInputSchema.safeParse({
      tenantId: 'tenant-1',
      name: 'Jane Doe',
      email: 'jane@example.com',
      message: 'We would love to sponsor a team this season.',
    })
    expect(result.success).toBe(true)
  })

  it('rejects a message that is too short', () => {
    const result = createInquiryInputSchema.safeParse({
      tenantId: 'tenant-1',
      name: 'Jane',
      email: 'jane@example.com',
      message: 'hi',
    })
    expect(result.success).toBe(false)
  })

  it('rejects a honeypot value (bot detection)', () => {
    const result = createInquiryInputSchema.safeParse({
      tenantId: 'tenant-1',
      name: 'Jane',
      email: 'jane@example.com',
      message: 'A real message of sufficient length.',
      website: 'http://spam.example',
    })
    expect(result.success).toBe(false)
  })
})

describe('module configuration schema', () => {
  it('accepts a valid config', () => {
    const result = moduleConfigurationSchema.safeParse({
      moduleEnabled: true,
      displayName: 'Our Sponsors',
      contactEmail: 'sponsors@example.org',
    })
    expect(result.success).toBe(true)
  })

  it('requires displayName', () => {
    const result = moduleConfigurationSchema.safeParse({})
    expect(result.success).toBe(false)
  })

  it('rejects an invalid email', () => {
    const result = moduleConfigurationSchema.safeParse({
      displayName: 'X',
      contactEmail: 'not-an-email',
    })
    expect(result.success).toBe(false)
  })
})
