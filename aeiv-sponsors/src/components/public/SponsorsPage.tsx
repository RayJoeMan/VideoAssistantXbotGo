import { useEffect } from 'react'
import { useTenantId } from '../../hooks/useTenant'
import { useModuleState } from '../../hooks/useModuleState'
import { usePublicSponsors } from '../../hooks/useSponsors'
import { trackEvent } from '../../analytics/events'
import { LoadingState } from '../ui/LoadingState'
import { EmptyState } from '../ui/EmptyState'
import { ErrorState } from '../ui/ErrorState'
import { SponsorCard } from './SponsorCard'

/**
 * Public sponsor directory page.
 *
 * Route is guarded by ModuleRouteGuard (module toggle + publicPage feature).
 * Data is fetched from Firestore under the tenant boundary and only rendered
 * when the module is enabled.
 */
export function SponsorsPage() {
  const tenantId = useTenantId()
  const { state, isLoading: moduleLoading } = useModuleState(tenantId)
  const sponsorsQuery = usePublicSponsors(tenantId, state.enabled)

  useEffect(() => {
    if (state.enabled) trackEvent(tenantId, 'sponsors_page_view')
  }, [tenantId, state.enabled])

  if (moduleLoading) return <LoadingState label="Loading module…" />

  const { config } = state

  return (
    <section className="sponsors-page" aria-labelledby="sponsors-heading">
      <header className="sponsors-page__header">
        <h1 id="sponsors-heading">{config.displayName || 'Our Sponsors'}</h1>
        {config.tagline ? <p className="sponsors-page__tagline">{config.tagline}</p> : null}
        {config.heroText ? <p className="sponsors-page__hero">{config.heroText}</p> : null}
      </header>

      {sponsorsQuery.isLoading ? (
        <LoadingState label="Loading sponsors…" />
      ) : sponsorsQuery.isError ? (
        <ErrorState
          message="We couldn’t load the sponsors list. Please try again."
          onRetry={() => void sponsorsQuery.refetch()}
        />
      ) : (sponsorsQuery.data?.length ?? 0) === 0 ? (
        <EmptyState title="No sponsors yet" description="Sponsor listings will appear here." />
      ) : (
        <ul className="sponsor-grid" aria-label="Sponsors">
          {sponsorsQuery.data?.map((sponsor) => (
            <li key={sponsor.id}>
              <SponsorCard tenantId={tenantId} sponsor={sponsor} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
