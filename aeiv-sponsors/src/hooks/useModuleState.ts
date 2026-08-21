import { useQuery } from '@tanstack/react-query'
import { resolveModuleState, isFeatureEnabled, type ModuleState } from '../config/module'
import { fetchModuleConfig } from '../services/tenant'

export const moduleQueryKey = (tenantId: string) => ['module', 'config', tenantId] as const

export interface UseModuleStateResult {
  state: ModuleState
  isLoading: boolean
  isError: boolean
  error: Error | null
  refetch: () => void
}

/**
 * Loads the tenant's module configuration and resolves the module toggle +
 * feature flags against the manifest defaults.
 *
 * When the module is disabled, consumers must stop rendering routes/nav and
 * stop issuing API calls — the backend independently blocks access.
 */
export function useModuleState(tenantId: string | null | undefined): UseModuleStateResult {
  const query = useQuery({
    queryKey: moduleQueryKey(tenantId ?? ''),
    queryFn: () => fetchModuleConfig(tenantId ?? ''),
    enabled: Boolean(tenantId),
    staleTime: 30_000,
  })

  return {
    state: resolveModuleState(query.data),
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error instanceof Error ? query.error : null,
    refetch: () => {
      void query.refetch()
    },
  }
}

export function useFeatureEnabled(tenantId: string | null | undefined, feature: string): boolean {
  const { state } = useModuleState(tenantId)
  return isFeatureEnabled(state, feature)
}
