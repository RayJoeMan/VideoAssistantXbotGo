import { env } from '../config/env'

/**
 * Resolves the tenant this deployment serves.
 *
 * Host sites pass the tenant id via `VITE_TENANT_ID` (single-tenant host) or
 * supply it through their own routing/context (multi-tenant host). The
 * fallback is a neutral demo tenant used only for local emulator development —
 * no customer is hard-coded into the module.
 */
export const DEFAULT_TENANT_ID = 'demo-tenant'

export function resolveTenantId(): string {
  return env.tenantId || DEFAULT_TENANT_ID
}

export function useTenantId(): string {
  return resolveTenantId()
}
