/**
 * Module analytics — business events (not page-view noise).
 *
 * Events are documented here so the list is explicit and reviewable. They are
 * intentionally independent of site-wide analytics and include only the data
 * needed for the event: tenantId, module, eventName, timestamp, and small
 * context properties. No unnecessary personal information is collected.
 *
 * The current sink logs structured events to the console (dev) and can be
 * swapped for a real pipeline (e.g. a Cloud Function or GA4) without touching
 * call sites.
 */
export type AnalyticsEventName =
  | 'sponsors_page_view'
  | 'sponsor_detail_view'
  | 'sponsor_link_click'
  | 'inquiry_form_view'
  | 'inquiry_submitted'
  | 'inquiry_submit_failed'

export interface AnalyticsEvent {
  tenantId: string
  module: string
  eventName: AnalyticsEventName
  timestamp: string
  [key: string]: unknown
}

const MODULE_ID = 'aeiv-sponsors'

export function trackEvent(
  tenantId: string,
  eventName: AnalyticsEventName,
  props: Record<string, unknown> = {},
): void {
  const event: AnalyticsEvent = {
    tenantId,
    module: MODULE_ID,
    eventName,
    timestamp: new Date().toISOString(),
    ...props,
  }
  // Structured, sanitized log. Do not add PII beyond what the event requires.
  if (import.meta.env.DEV) {
    console.info('[analytics]', JSON.stringify(event))
  }
}
