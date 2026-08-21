import { Link, NavLink } from 'react-router-dom'
import { moduleManifest } from '../module.manifest'
import { useAuth } from './hooks/useAuth'
import { useTenantId } from './hooks/useTenant'
import { useModuleState } from './hooks/useModuleState'
import { usePermissions } from './hooks/usePermissions'
import { AppRoutes } from './routes/AppRoutes'
import './styles.css'

/**
 * Application shell.
 *
 * The host website owns the public URL; this shell demonstrates how a host
 * integrates the module: navigation is rendered only when the module is
 * enabled, and the admin entry only when the user has permission.
 */
export default function App() {
  const tenantId = useTenantId()
  const { state, isLoading } = useModuleState(tenantId)
  const { user, initializing, signOut } = useAuth()
  const { hasPermission } = usePermissions(tenantId)

  const moduleEnabled = !isLoading && state.enabled
  const canAdmin = hasPermission('sponsors.view')

  return (
    <div className="app-shell">
      <header className="app-header">
        <Link to="/" className="app-header__brand">
          {moduleEnabled ? state.config.displayName || 'AEIV Sponsors' : 'AEIV Sponsors'}
        </Link>
        <nav className="app-nav" aria-label="Main">
          <ul>
            {moduleEnabled
              ? moduleManifest.navigation.map((item) => (
                  <li key={item.href}>
                    <NavLink
                      to={item.href}
                      className={({ isActive }) => (isActive ? 'is-active' : undefined)}
                    >
                      {item.label}
                    </NavLink>
                  </li>
                ))
              : null}
            {moduleEnabled && canAdmin ? (
              <li>
                <NavLink
                  to="/admin/sponsors"
                  className={({ isActive }) => (isActive ? 'is-active' : undefined)}
                >
                  Admin
                </NavLink>
              </li>
            ) : null}
          </ul>
        </nav>
        <div className="app-header__auth">
          {initializing ? null : user ? (
            <>
              <span className="app-header__user">{user.email ?? 'Signed in'}</span>
              <button type="button" className="button button--small" onClick={() => void signOut()}>
                Sign out
              </button>
            </>
          ) : (
            <Link className="button button--small" to="/login">
              Sign in
            </Link>
          )}
        </div>
      </header>

      <main className="app-main">
        <AppRoutes />
      </main>

      <footer className="app-footer">
        <p>
          {moduleManifest.name} module v{moduleManifest.version} · API {moduleManifest.apiVersion}
        </p>
      </footer>
    </div>
  )
}
