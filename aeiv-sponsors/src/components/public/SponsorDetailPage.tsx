import { useEffect } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useTenantId } from '../../hooks/useTenant'
import { useModuleState } from '../../hooks/useModuleState'
import { usePublicSponsor } from '../../hooks/useSponsors'
import { isFeatureEnabled } from '../../config/module'
import { trackEvent } from '../../analytics/events'
import { LoadingState } from '../ui/LoadingState'
import { ErrorState } from '../ui/ErrorState'
import { InquiryForm } from './InquiryForm'

export function SponsorDetailPage() {
  const tenantId = useTenantId()
  const { sponsorId } = useParams<{ sponsorId: string }>()
  const { state, isLoading: moduleLoading } = useModuleState(tenantId)
  const sponsorQuery = usePublicSponsor(tenantId, sponsorId)

  useEffect(() => {
    if (state.enabled && sponsorId) {
      trackEvent(tenantId, 'sponsor_detail_view', { sponsorId })
    }
  }, [tenantId, state.enabled, sponsorId])

  if (moduleLoading) return <LoadingState label="Loading module…" />

  if (sponsorQuery.isLoading) return <LoadingState label="Loading sponsor…" />
  if (sponsorQuery.isError || !sponsorQuery.data) {
    return <ErrorState message="We couldn’t find that sponsor." />
  }

  const sponsor = sponsorQuery.data
  const inquiryEnabled = state.config.inquiryEnabled && isFeatureEnabled(state, 'inquiryForm')

  return (
    <article className="sponsor-detail" aria-labelledby="sponsor-name">
      <nav aria-label="Breadcrumb" className="breadcrumb">
        <Link to="/sponsors">Sponsors</Link>
        <span aria-hidden="true"> / </span>
        <span>{sponsor.name}</span>
      </nav>
      <header className="sponsor-detail__header">
        {sponsor.logoUrl ? (
          <img
            src={sponsor.logoUrl}
            alt={`${sponsor.name} logo`}
            className="sponsor-detail__logo"
          />
        ) : null}
        <h1 id="sponsor-name">{sponsor.name}</h1>
        <p className="sponsor-detail__tier">Tier: {sponsor.tier}</p>
      </header>
      {sponsor.tagline ? <p className="sponsor-detail__tagline">{sponsor.tagline}</p> : null}
      {sponsor.description ? (
        <p className="sponsor-detail__description">{sponsor.description}</p>
      ) : null}
      {sponsor.websiteUrl ? (
        <a
          className="button"
          href={sponsor.websiteUrl}
          target="_blank"
          rel="noopener noreferrer"
          onClick={() => trackEvent(tenantId, 'sponsor_link_click', { sponsorId: sponsor.id })}
        >
          Visit website
        </a>
      ) : null}

      {inquiryEnabled ? <InquiryForm tenantId={tenantId} sponsor={sponsor} /> : null}
    </article>
  )
}
