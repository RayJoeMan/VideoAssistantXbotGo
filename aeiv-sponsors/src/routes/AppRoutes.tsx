import { Route, Routes } from 'react-router-dom'
import { useTenantId } from '../hooks/useTenant'
import { ModuleRouteGuard } from '../components/ModuleRouteGuard'
import { RequirePermission } from '../components/RequirePermission'
import { HomePage } from '../components/HomePage'
import { LoginPage } from '../components/LoginPage'
import { SponsorsPage } from '../components/public/SponsorsPage'
import { SponsorDetailPage } from '../components/public/SponsorDetailPage'
import { AdminLayout } from '../components/admin/AdminLayout'
import { AdminSponsorsPage } from '../components/admin/AdminSponsorsPage'
import { SponsorFormPage } from '../components/admin/SponsorFormPage'
import { ModuleSettingsPage } from '../components/admin/ModuleSettingsPage'
import { ReportingPage } from '../components/admin/ReportingPage'
import { NotFoundPage } from '../components/NotFoundPage'

/**
 * Module routes.
 *
 * Public routes are wrapped in ModuleRouteGuard (module toggle + feature
 * flags). Admin routes additionally require the matching permission. When the
 * module is disabled, every route resolves to the not-found page.
 */
export function AppRoutes() {
  const tenantId = useTenantId()

  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/login" element={<LoginPage />} />

      <Route
        path="/sponsors"
        element={
          <ModuleRouteGuard tenantId={tenantId} requireFeature="publicPage">
            <SponsorsPage />
          </ModuleRouteGuard>
        }
      />
      <Route
        path="/sponsors/:sponsorId"
        element={
          <ModuleRouteGuard tenantId={tenantId} requireFeature="publicPage">
            <SponsorDetailPage />
          </ModuleRouteGuard>
        }
      />

      <Route
        path="/admin/sponsors"
        element={
          <ModuleRouteGuard tenantId={tenantId}>
            <RequirePermission tenantId={tenantId} permission="sponsors.view">
              <AdminLayout tenantId={tenantId} />
            </RequirePermission>
          </ModuleRouteGuard>
        }
      >
        <Route index element={<AdminSponsorsPage />} />
        <Route
          path="new"
          element={
            <RequirePermission tenantId={tenantId} permission="sponsors.create">
              <SponsorFormPage />
            </RequirePermission>
          }
        />
        <Route
          path=":sponsorId"
          element={
            <RequirePermission tenantId={tenantId} permission="sponsors.edit">
              <SponsorFormPage />
            </RequirePermission>
          }
        />
        <Route
          path="settings"
          element={
            <RequirePermission tenantId={tenantId} permission="sponsors.settings">
              <ModuleSettingsPage />
            </RequirePermission>
          }
        />
        <Route
          path="reporting"
          element={
            <RequirePermission tenantId={tenantId} permission="sponsors.reporting">
              <ReportingPage />
            </RequirePermission>
          }
        />
      </Route>

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
