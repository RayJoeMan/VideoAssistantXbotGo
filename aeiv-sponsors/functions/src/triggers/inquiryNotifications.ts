import { getFirestore } from 'firebase-admin/firestore'
import { onDocumentCreated } from 'firebase-functions/v2/firestore'
import { getModuleConfig } from '../security/tenant'
import { logInfo } from '../security/logging'

/**
 * Notification trigger: fires when an inquiry is created.
 *
 * Only acts when the tenant has the `notifications` feature enabled AND has
 * configured a contactEmail. Email delivery is a stub — integrate an email
 * provider (e.g. Resend, SendGrid, nodemailer) here; docs/architecture.md
 * covers the integration point.
 */
export const onInquiryCreated = onDocumentCreated(
  'tenants/{tenantId}/inquiries/{inquiryId}',
  async (event) => {
    const tenantId = event.params.tenantId
    const inquiryId = event.params.inquiryId
    const inquiry = event.data?.data()
    if (!inquiry) return

    const config = await getModuleConfig(tenantId)
    if (config?.features?.notifications !== true || !config.contactEmail) return

    // TODO(notifications): send email to config.contactEmail with inquiry summary.
    logInfo(
      { operation: 'inquiry.notification', tenantId },
      'Inquiry notification dispatched (stub)',
      { inquiryId, to: config.contactEmail },
    )

    // Keep a reference for future retry/dead-letter handling.
    await getFirestore()
      .doc(`tenants/${tenantId}/inquiries/${inquiryId}`)
      .update({ notifiedAt: new Date().toISOString() })
  },
)
