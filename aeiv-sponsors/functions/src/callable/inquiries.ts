import { getFirestore } from 'firebase-admin/firestore'
import { HttpsError, onCall } from 'firebase-functions/v2/https'
import { createInquiryInputSchema, type Inquiry } from '../schemas/inquiry'
import { assertFeatureEnabled } from '../security/tenant'
import { enforceRateLimit } from '../security/rateLimit'
import { logInfo, logWarn } from '../security/logging'
import { parseInput } from '../security/validation'
import { pickDefined } from '../security/sanitize'

/**
 * Public inquiry submission (abuse-protected).
 *
 * Written exclusively through this function — the Firestore rules deny direct
 * client writes to the inquiries collection. Re-validates input server-side,
 * enforces the inquiryForm feature flag, and rate-limits per caller.
 */
export const aeiv_inquiriesCreate = onCall(async (request) => {
  const input = parseInput(createInquiryInputSchema, request.data)

  // Honeypot: bots fill the hidden "website" field; humans leave it empty.
  if (input.website) {
    logWarn(
      { operation: 'inquiries.create', tenantId: input.tenantId },
      'Inquiry rejected (honeypot triggered)',
    )
    throw new HttpsError('invalid-argument', 'Submission rejected.')
  }

  // Tenant + feature enforcement (module must be enabled, inquiryForm on).
  const config = await assertFeatureEnabled(input.tenantId, 'inquiryForm')

  // Rate limit by caller identity (uid when signed in, else IP).
  const callerKey = request.auth
    ? `uid:${request.auth.uid}`
    : `ip:${request.rawRequest?.ip ?? 'unknown'}`
  enforceRateLimit(`inquiry:${callerKey}`, 5, 60_000)

  const db = getFirestore()
  const ref = db.collection(`tenants/${input.tenantId}/inquiries`).doc()
  const now = new Date().toISOString()

  const inquiry: Inquiry = {
    id: ref.id,
    tenantId: input.tenantId,
    sponsorId: input.sponsorId,
    sponsorName: input.sponsorName,
    name: input.name,
    email: input.email,
    company: input.company ?? '',
    message: input.message,
    status: 'new',
    createdAt: now,
  }
  await ref.set(pickDefined({ ...inquiry }))

  logInfo({ operation: 'inquiries.create', tenantId: input.tenantId }, 'Inquiry created', {
    inquiryId: ref.id,
    sponsorId: input.sponsorId,
  })

  // Notifications are handled by the onInquiryCreated trigger (feature: notifications).
  void config
  return { inquiryId: ref.id }
})
