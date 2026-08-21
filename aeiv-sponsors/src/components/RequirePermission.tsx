import { usePermissions } from '../hooks/usePermissions'
import { LoadingState } from './ui/LoadingState'
import { ErrorState } from './ui/ErrorState'

interface RequirePermissionProps {
  tenantId: string
  permission: string
  children: React.ReactNode
}

/**
 * Client-side permission gate. Renders the children only when the caller
 * holds the required permission. The backend independently enforces the same
 * permission on every operation — this is UX, not security.
 */
export function RequirePermission({ tenantId, permission, children }: RequirePermissionProps) {
  const { hasPermission, loading } = usePermissions(tenantId)

  if (loading) return <LoadingState label="Checking permissions…" />
  if (!hasPermission(permission)) {
    return (
      <ErrorState
        title="Not authorized"
        message={`You need the "${permission}" permission to view this page.`}
      />
    )
  }
  return <>{children}</>
}
