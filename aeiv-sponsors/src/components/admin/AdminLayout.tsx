import { NavLink, Outlet } from 'react-router-dom'
import { moduleManifest } from '../../../module.manifest'
import { usePermissions } from '../../hooks/usePermissions'

interface AdminLayoutProps {
  tenantId: string
}

/** Admin shell — nav items filtered by the caller's permissions. */
export function AdminLayout({ tenantId }: AdminLayoutProps) {
  const { hasPermission } = usePermissions(tenantId)

  const visibleRoutes = moduleManifest.adminRoutes.filter((route) =>
    hasPermission(route.permission),
  )

  return (
    <div className="admin-layout">
      <nav className="admin-nav" aria-label="Sponsors admin">
        <ul>
          {visibleRoutes.map((route) => (
            <li key={route.path}>
              <NavLink
                to={route.path}
                className={({ isActive }) =>
                  isActive ? 'admin-nav__link is-active' : 'admin-nav__link'
                }
                end={route.path === '/admin/sponsors'}
              >
                {route.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <main className="admin-content">
        <Outlet />
      </main>
    </div>
  )
}
