import { moduleManifest } from '../../../module.manifest'
import { useTenantId } from '../../hooks/useTenant'
import { useModuleState } from '../../hooks/useModuleState'
import { useAdminSponsors } from '../../hooks/useSponsors'
import { LoadingState } from '../ui/LoadingState'
import { EmptyState } from '../ui/EmptyState'

/**
 * Reporting — module-level business metrics.
 *
 * Scaffold for Phase 8. Current metrics are computed from the admin sponsor
 * list; the documented analytics events (src/analytics/events.ts) feed future
 * reporting pipelines. Requires `sponsors.reporting`.
 */
export function ReportingPage() {
  const tenantId = useTenantId()
  const { state } = useModuleState(tenantId)
  const sponsorsQuery = useAdminSponsors(tenantId)

  if (sponsorsQuery.isLoading) return <LoadingState label="Loading reporting data…" />

  const sponsors = sponsorsQuery.data ?? []
  const byStatus = sponsors.reduce<Record<string, number>>((acc, s) => {
    acc[s.admin.status] = (acc[s.admin.status] ?? 0) + 1
    return acc
  }, {})
  const byTier = sponsors.reduce<Record<string, number>>((acc, s) => {
    acc[s.public.tier] = (acc[s.public.tier] ?? 0) + 1
    return acc
  }, {})
  const publishedCount = sponsors.filter((s) => s.public.published).length

  return (
    <section className="admin-page" aria-labelledby="reporting-heading">
      <h1 id="reporting-heading">Reporting</h1>
      <p className="settings-version">
        Module v{state.version} · Events documented in <code>src/analytics/events.ts</code>
      </p>

      <div className="metric-grid">
        <div className="metric-card">
          <span className="metric-card__value">{sponsors.length}</span>
          <span className="metric-card__label">Total sponsors</span>
        </div>
        <div className="metric-card">
          <span className="metric-card__value">{publishedCount}</span>
          <span className="metric-card__label">Published</span>
        </div>
        <div className="metric-card">
          <span className="metric-card__value">{byStatus.active ?? 0}</span>
          <span className="metric-card__label">Active contracts</span>
        </div>
        <div className="metric-card">
          <span className="metric-card__value">
            {Object.keys(moduleManifest.features).filter((f) => state.features[f]).length}
          </span>
          <span className="metric-card__label">Features enabled</span>
        </div>
      </div>

      <h2>Sponsors by tier</h2>
      {Object.keys(byTier).length === 0 ? (
        <EmptyState title="No data yet" description="Create sponsors to populate reporting." />
      ) : (
        <ul className="stat-list">
          {Object.entries(byTier).map(([tier, count]) => (
            <li key={tier}>
              {tier}: <strong>{count}</strong>
            </li>
          ))}
        </ul>
      )}

      <h2>Sponsors by status</h2>
      {Object.keys(byStatus).length === 0 ? (
        <EmptyState title="No data yet" />
      ) : (
        <ul className="stat-list">
          {Object.entries(byStatus).map(([status, count]) => (
            <li key={status}>
              {status}: <strong>{count}</strong>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
