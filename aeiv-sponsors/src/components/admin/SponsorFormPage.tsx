import { useMemo, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTenantId } from '../../hooks/useTenant'
import { useAdminSponsors, useCreateSponsor, useUpdateSponsor } from '../../hooks/useSponsors'
import {
  createSponsorInputSchema,
  sponsorStatusSchema,
  sponsorTierSchema,
  updateSponsorInputSchema,
} from '../../schemas/sponsor'
import type { SponsorTier, SponsorStatus } from '../../schemas/sponsor'
import { LoadingState } from '../ui/LoadingState'
import { ErrorState } from '../ui/ErrorState'

interface SponsorFormValues {
  name: string
  tier: SponsorTier
  tagline: string
  websiteUrl: string
  logoUrl: string
  description: string
  sortOrder: string
  published: boolean
  status: SponsorStatus
  contactName: string
  contactEmail: string
  contactPhone: string
  monthlyAmount: string
  notes: string
}

const EMPTY_VALUES: SponsorFormValues = {
  name: '',
  tier: 'bronze',
  tagline: '',
  websiteUrl: '',
  logoUrl: '',
  description: '',
  sortOrder: '0',
  published: false,
  status: 'pending',
  contactName: '',
  contactEmail: '',
  contactPhone: '',
  monthlyAmount: '',
  notes: '',
}

/** New/edit sponsor form (public + admin data). */
export function SponsorFormPage() {
  const tenantId = useTenantId()
  const navigate = useNavigate()
  const { sponsorId } = useParams<{ sponsorId: string }>()
  const isEditing = Boolean(sponsorId)

  const adminQuery = useAdminSponsors(tenantId, isEditing)
  const existing = useMemo(
    () => adminQuery.data?.find((s) => s.public.id === sponsorId) ?? null,
    [adminQuery.data, sponsorId],
  )

  const [values, setValues] = useState<SponsorFormValues>(EMPTY_VALUES)
  const [loaded, setLoaded] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [submitError, setSubmitError] = useState<string | null>(null)

  // Populate form once when the existing sponsor loads (edit mode).
  if (isEditing && existing && !loaded) {
    setValues({
      name: existing.public.name,
      tier: existing.public.tier,
      tagline: existing.public.tagline ?? '',
      websiteUrl: existing.public.websiteUrl ?? '',
      logoUrl: existing.public.logoUrl ?? '',
      description: existing.public.description ?? '',
      sortOrder: String(existing.public.sortOrder ?? 0),
      published: existing.public.published,
      status: existing.admin.status,
      contactName: existing.admin.contactName ?? '',
      contactEmail: existing.admin.contactEmail ?? '',
      contactPhone: existing.admin.contactPhone ?? '',
      monthlyAmount:
        existing.admin.monthlyAmount !== undefined ? String(existing.admin.monthlyAmount) : '',
      notes: existing.admin.notes ?? '',
    })
    setLoaded(true)
  }

  const createMutation = useCreateSponsor(tenantId)
  const updateMutation = useUpdateSponsor(tenantId)
  const isSubmitting = createMutation.isPending || updateMutation.isPending

  const setField = (field: keyof SponsorFormValues, value: string | boolean) => {
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
    setSubmitError(null)

    const publicData = {
      name: values.name,
      tier: values.tier,
      tagline: values.tagline,
      websiteUrl: values.websiteUrl || undefined,
      logoUrl: values.logoUrl || undefined,
      description: values.description,
      sortOrder: Number(values.sortOrder || 0),
    }
    const adminData = {
      status: values.status,
      contactName: values.contactName || undefined,
      contactEmail: values.contactEmail || undefined,
      contactPhone: values.contactPhone || undefined,
      monthlyAmount: values.monthlyAmount ? Number(values.monthlyAmount) : undefined,
      notes: values.notes,
    }

    const input = isEditing
      ? { tenantId, sponsorId: sponsorId!, public: publicData, admin: adminData }
      : { tenantId, public: publicData, admin: adminData }

    const toFieldErrors = (parsed: {
      success: false
      error: { issues: Array<{ path: Array<string | number>; message: string }> }
    }): void => {
      const fieldErrors: Record<string, string> = {}
      for (const issue of parsed.error.issues) {
        const path = issue.path.filter((p) => p !== 'public' && p !== 'admin')
        const field = path[0] ?? 'form'
        fieldErrors[String(field)] = issue.message
      }
      setErrors(fieldErrors)
    }

    try {
      if (isEditing) {
        const parsed = updateSponsorInputSchema.safeParse(input)
        if (!parsed.success) {
          toFieldErrors(parsed)
          return
        }
        await updateMutation.mutateAsync(parsed.data)
      } else {
        const parsed = createSponsorInputSchema.safeParse(input)
        if (!parsed.success) {
          toFieldErrors(parsed)
          return
        }
        await createMutation.mutateAsync(parsed.data)
      }
      navigate('/admin/sponsors')
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to save sponsor.')
    }
  }

  if (isEditing && adminQuery.isLoading) return <LoadingState label="Loading sponsor…" />
  if (isEditing && adminQuery.isError) {
    return <ErrorState message="Couldn’t load the sponsor for editing." />
  }
  if (isEditing && !existing) {
    return <ErrorState message="Sponsor not found." />
  }

  return (
    <section className="admin-page" aria-labelledby="sponsor-form-heading">
      <h1 id="sponsor-form-heading">{isEditing ? 'Edit sponsor' : 'New sponsor'}</h1>

      <form className="sponsor-form" onSubmit={handleSubmit} noValidate>
        <fieldset>
          <legend>Public details</legend>

          <div className="form-field">
            <label htmlFor="sp-name">Name *</label>
            <input
              id="sp-name"
              type="text"
              required
              value={values.name}
              onChange={(e) => setField('name', e.target.value)}
              aria-invalid={Boolean(errors.name)}
              aria-describedby={errors.name ? 'sp-name-error' : undefined}
            />
            {errors.name ? (
              <p id="sp-name-error" className="form-error" role="alert">
                {errors.name}
              </p>
            ) : null}
          </div>

          <div className="form-field">
            <label htmlFor="sp-tier">Tier *</label>
            <select
              id="sp-tier"
              value={values.tier}
              onChange={(e) => setField('tier', e.target.value as SponsorTier)}
            >
              {sponsorTierSchema.options.map((tier) => (
                <option key={tier} value={tier}>
                  {tier}
                </option>
              ))}
            </select>
          </div>

          <div className="form-field">
            <label htmlFor="sp-tagline">Tagline</label>
            <input
              id="sp-tagline"
              type="text"
              value={values.tagline}
              onChange={(e) => setField('tagline', e.target.value)}
            />
          </div>

          <div className="form-field">
            <label htmlFor="sp-website">Website URL</label>
            <input
              id="sp-website"
              type="url"
              value={values.websiteUrl}
              onChange={(e) => setField('websiteUrl', e.target.value)}
              aria-invalid={Boolean(errors.websiteUrl)}
            />
            {errors.websiteUrl ? (
              <p className="form-error" role="alert">
                {errors.websiteUrl}
              </p>
            ) : null}
          </div>

          <div className="form-field">
            <label htmlFor="sp-logo">Logo URL</label>
            <input
              id="sp-logo"
              type="url"
              value={values.logoUrl}
              onChange={(e) => setField('logoUrl', e.target.value)}
              aria-invalid={Boolean(errors.logoUrl)}
            />
            {errors.logoUrl ? (
              <p className="form-error" role="alert">
                {errors.logoUrl}
              </p>
            ) : null}
          </div>

          <div className="form-field">
            <label htmlFor="sp-description">Description</label>
            <textarea
              id="sp-description"
              rows={4}
              value={values.description}
              onChange={(e) => setField('description', e.target.value)}
            />
          </div>

          <div className="form-field">
            <label htmlFor="sp-sort">Sort order</label>
            <input
              id="sp-sort"
              type="number"
              min={0}
              value={values.sortOrder}
              onChange={(e) => setField('sortOrder', e.target.value)}
            />
          </div>

          <div className="form-field form-field--check">
            <input
              id="sp-published"
              type="checkbox"
              checked={values.published}
              onChange={(e) => setField('published', e.target.checked)}
            />
            <label htmlFor="sp-published">Published (visible on public page)</label>
          </div>
        </fieldset>

        <fieldset>
          <legend>Admin details</legend>

          <div className="form-field">
            <label htmlFor="sp-status">Status</label>
            <select
              id="sp-status"
              value={values.status}
              onChange={(e) => setField('status', e.target.value as SponsorStatus)}
            >
              {sponsorStatusSchema.options.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </div>

          <div className="form-field">
            <label htmlFor="sp-contact-name">Contact name</label>
            <input
              id="sp-contact-name"
              type="text"
              autoComplete="name"
              value={values.contactName}
              onChange={(e) => setField('contactName', e.target.value)}
            />
          </div>

          <div className="form-field">
            <label htmlFor="sp-contact-email">Contact email</label>
            <input
              id="sp-contact-email"
              type="email"
              autoComplete="email"
              value={values.contactEmail}
              onChange={(e) => setField('contactEmail', e.target.value)}
              aria-invalid={Boolean(errors.contactEmail)}
            />
            {errors.contactEmail ? (
              <p className="form-error" role="alert">
                {errors.contactEmail}
              </p>
            ) : null}
          </div>

          <div className="form-field">
            <label htmlFor="sp-contact-phone">Contact phone</label>
            <input
              id="sp-contact-phone"
              type="tel"
              autoComplete="tel"
              value={values.contactPhone}
              onChange={(e) => setField('contactPhone', e.target.value)}
            />
          </div>

          <div className="form-field">
            <label htmlFor="sp-amount">Monthly amount (USD)</label>
            <input
              id="sp-amount"
              type="number"
              min={0}
              step="0.01"
              value={values.monthlyAmount}
              onChange={(e) => setField('monthlyAmount', e.target.value)}
              aria-invalid={Boolean(errors.monthlyAmount)}
            />
            {errors.monthlyAmount ? (
              <p className="form-error" role="alert">
                {errors.monthlyAmount}
              </p>
            ) : null}
          </div>

          <div className="form-field">
            <label htmlFor="sp-notes">Notes</label>
            <textarea
              id="sp-notes"
              rows={3}
              value={values.notes}
              onChange={(e) => setField('notes', e.target.value)}
            />
          </div>
        </fieldset>

        {submitError ? (
          <p className="form-error" role="alert">
            {submitError}
          </p>
        ) : null}

        <div className="form-actions">
          <button type="submit" className="button button--primary" disabled={isSubmitting}>
            {isSubmitting ? 'Saving…' : isEditing ? 'Save changes' : 'Create sponsor'}
          </button>
          <button type="button" className="button" onClick={() => navigate('/admin/sponsors')}>
            Cancel
          </button>
        </div>
      </form>
    </section>
  )
}
