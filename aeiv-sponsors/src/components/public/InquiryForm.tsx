import { useEffect, useState, type FormEvent } from 'react'
import type { PublicSponsor } from '../../schemas/sponsor'
import { createInquiryInputSchema } from '../../schemas/inquiry'
import { useCreateInquiry } from '../../hooks/useSponsors'
import { trackEvent } from '../../analytics/events'

interface InquiryFormProps {
  tenantId: string
  sponsor?: PublicSponsor
}

interface InquiryFormValues {
  name: string
  email: string
  company: string
  message: string
  /** Honeypot field — humans leave it empty. */
  website: string
}

const EMPTY_VALUES: InquiryFormValues = {
  name: '',
  email: '',
  company: '',
  message: '',
  website: '',
}

/**
 * Public inquiry form.
 *
 * Submits through a callable Cloud Function (aeiv_inquiriesCreate) where the
 * input is re-validated, rate-limited, and tenant-checked. The `website`
 * honeypot field is hidden from humans to catch bots.
 */
export function InquiryForm({ tenantId, sponsor }: InquiryFormProps) {
  const [values, setValues] = useState<InquiryFormValues>(EMPTY_VALUES)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const inquiryMutation = useCreateInquiry()

  useEffect(() => {
    trackEvent(tenantId, 'inquiry_form_view', { sponsorId: sponsor?.id })
  }, [tenantId, sponsor?.id])

  const handleChange = (field: keyof InquiryFormValues, value: string) => {
    setValues((prev) => ({ ...prev, [field]: value }))
    setErrors((prev) => {
      if (!prev[field]) return prev
      const next = { ...prev }
      delete next[field]
      return next
    })
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    const parsed = createInquiryInputSchema.safeParse({
      tenantId,
      sponsorId: sponsor?.id,
      sponsorName: sponsor?.name,
      ...values,
    })
    if (!parsed.success) {
      const fieldErrors: Record<string, string> = {}
      for (const issue of parsed.error.issues) {
        const field = String(issue.path[0] ?? 'form')
        fieldErrors[field] = issue.message
      }
      setErrors(fieldErrors)
      return
    }
    try {
      await inquiryMutation.mutateAsync(parsed.data)
      trackEvent(tenantId, 'inquiry_submitted', { sponsorId: sponsor?.id })
      setValues(EMPTY_VALUES)
    } catch {
      trackEvent(tenantId, 'inquiry_submit_failed', { sponsorId: sponsor?.id })
    }
  }

  if (inquiryMutation.isSuccess) {
    return (
      <div className="inquiry-success" role="status">
        <h2>Thank you!</h2>
        <p>
          Your inquiry has been sent. {sponsor ? `The ${sponsor.name} team` : 'We'} will be in
          touch.
        </p>
      </div>
    )
  }

  return (
    <form
      className="inquiry-form"
      onSubmit={handleSubmit}
      noValidate
      aria-label="Sponsorship inquiry"
    >
      <h2>{sponsor ? `Contact ${sponsor.name}` : 'Get in touch'}</h2>

      <div className="form-field">
        <label htmlFor="inquiry-name">Name *</label>
        <input
          id="inquiry-name"
          type="text"
          autoComplete="name"
          required
          value={values.name}
          onChange={(e) => handleChange('name', e.target.value)}
          aria-invalid={Boolean(errors.name)}
          aria-describedby={errors.name ? 'inquiry-name-error' : undefined}
        />
        {errors.name ? (
          <p id="inquiry-name-error" className="form-error" role="alert">
            {errors.name}
          </p>
        ) : null}
      </div>

      <div className="form-field">
        <label htmlFor="inquiry-email">Email *</label>
        <input
          id="inquiry-email"
          type="email"
          autoComplete="email"
          required
          value={values.email}
          onChange={(e) => handleChange('email', e.target.value)}
          aria-invalid={Boolean(errors.email)}
          aria-describedby={errors.email ? 'inquiry-email-error' : undefined}
        />
        {errors.email ? (
          <p id="inquiry-email-error" className="form-error" role="alert">
            {errors.email}
          </p>
        ) : null}
      </div>

      <div className="form-field">
        <label htmlFor="inquiry-company">Company</label>
        <input
          id="inquiry-company"
          type="text"
          autoComplete="organization"
          value={values.company}
          onChange={(e) => handleChange('company', e.target.value)}
        />
      </div>

      <div className="form-field">
        <label htmlFor="inquiry-message">Message *</label>
        <textarea
          id="inquiry-message"
          rows={4}
          required
          minLength={10}
          value={values.message}
          onChange={(e) => handleChange('message', e.target.value)}
          aria-invalid={Boolean(errors.message)}
          aria-describedby={errors.message ? 'inquiry-message-error' : undefined}
        />
        {errors.message ? (
          <p id="inquiry-message-error" className="form-error" role="alert">
            {errors.message}
          </p>
        ) : null}
      </div>

      {/* Honeypot — hidden from humans, bots fill it in. */}
      <div className="form-field honeypot" aria-hidden="true">
        <label htmlFor="inquiry-website">Website</label>
        <input
          id="inquiry-website"
          type="text"
          tabIndex={-1}
          autoComplete="off"
          value={values.website}
          onChange={(e) => handleChange('website', e.target.value)}
        />
      </div>

      {inquiryMutation.isError ? (
        <p className="form-error" role="alert">
          {inquiryMutation.error instanceof Error
            ? inquiryMutation.error.message
            : 'Something went wrong sending your inquiry. Please try again.'}
        </p>
      ) : null}

      <button type="submit" className="button button--primary" disabled={inquiryMutation.isPending}>
        {inquiryMutation.isPending ? 'Sending…' : 'Send inquiry'}
      </button>
    </form>
  )
}
