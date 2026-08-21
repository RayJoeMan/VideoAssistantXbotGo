import { useModuleState } from '../hooks/useModuleState'
import { isFeatureEnabled } from '../config/module'
import { LoadingState } from './ui/LoadingState'
import { ErrorState } from './ui/ErrorState'

interface ModuleRouteGuardProps {
  tenantId: string
  /** When set, the route additionally requires this feature flag. */
  requireFeature?: string
  children: React.ReactNode
}

/**
 * Enforces the module toggle and feature flags at the routing layer.
 *
 * When the module (or the required feature) is disabled, the route resolves to
 * a 404-style page rather than rendering content — users cannot reach module
 * functionality by manually entering routes. The backend blocks access
 * independently of this guard.
 */
export function ModuleRouteGuard({ tenantId, requireFeature, children }: ModuleRouteGuardProps) {
  const { state, isLoading, isError } = useModuleState(tenantId)

  if (isLoading) return <LoadingState label="Loading module…" />
  if (isError || !state.enabled || (requireFeature && !isFeatureEnabled(state, requireFeature))) {
    return (
      <ErrorState
        title="Page not found"
        message="The page you requested does not exist or is not available."
      />
    )
  }
  return <>{children}</>
}
