import { Link } from 'react-router-dom'
import { moduleManifest } from '../../module.manifest'
import { useAuth } from '../hooks/useAuth'
import { useTenantId } from '../hooks/useTenant'
import { useModuleState } from '../hooks/useModuleState'
import { usePermissions } from '../hooks/usePermissions'

/**
 * Host-integration landing page (demo of how a host site surfaces the module).
 *
 * Shows the module toggle state, feature flags, and entry points. This page
 * itself is not part of the module's public surface — a host website would
 * replace it — but it doubles as a development/health view.
 */
export function HomePage() {
  const tenantId = useTenantId()
  const { state, isLoading, isError, error, refetch } = useModuleState(tenantId)
  const { user } = useAuth()
  const { hasPermission } = usePermissions(tenantId)

  return (
    <section className="home-page" aria-labelledby="home-heading">
      <h1 id="home-heading">AEIV Sponsors module</h1>
      <p className="settings-version">
        Module {moduleManifest.id} v{moduleManifest.version} · API {moduleManifest.apiVersion} ·
        Tenant {tenantId}
      </p>

      <div className="metric-grid">
        <div className="metric-card">
          <span className="metric-card__value">
            {isLoading ? '…' : state.enabled ? 'On' : 'Off'}
          </span>
          <span className="metric-card__label">Module toggle</span>
        </div>
        <div className="metric-card">
          <span className="metric-card__value">
            {Object.keys(moduleManifest.features).filter((f) => state.features[f]).length}
          </span>
          <span className="metric-card__label">Features enabled</span>
        </div>
        <div className="metric-card">
          <span className="metric-card__value">{user ? 'Signed in' : 'Guest'}</span>
          <span className="metric-card__label">Auth state</span>
        </div>
      </div>

      {isError ? (
        <p className="form-error" role="alert">
          Couldn’t load module config: {error?.message ?? 'unknown error'}.{' '}
          <button type="button" className="link-button" onClick={() => void refetch()}>
            Retry
          </button>
        </p>
      ) : null}

      {state.enabled ? (
        <>
          <h2>Entry points</h2>
          <ul className="stat-list">
            <li>
              <Link to="/sponsors">Public sponsor directory</Link>
            </li>
            {hasPermission('sponsors.view') ? (
              <li>
                <Link to="/admin/sponsors">Admin</Link>
              </li>
            ) : null}
          </ul>
        </>
      ) : (
        <p>The module is currently disabled for this tenant. Routes and navigation are hidden.</p>
      )}
    </section>
  )
}
