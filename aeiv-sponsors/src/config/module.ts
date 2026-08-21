import { moduleManifest } from '../../module.manifest'
import type { ModuleConfiguration } from '../schemas/moduleConfig'

/**
 * Module toggle + feature flag resolution.
 *
 * Single source of truth for whether this module (and each of its features)
 * is active for a tenant. `enabled`/`features` come from tenant configuration
 * with defaults from the module manifest.
 *
 * IMPORTANT: this is the UI-facing view. The backend enforces the same state
 * in authorization, so disabling the module also blocks access server-side.
 */
export interface ModuleState {
  moduleId: string
  version: string
  enabled: boolean
  features: Record<string, boolean>
  config: ModuleConfiguration
}

const DEFAULT_FEATURES: Record<string, boolean> = Object.fromEntries(
  Object.entries(moduleManifest.features).map(([key, flag]) => [key, flag.defaultEnabled]),
)

/** Merge partial tenant config with manifest defaults. Pure and testable. */
export function resolveModuleState(
  config: Partial<ModuleConfiguration> | null | undefined,
): ModuleState {
  const merged = { ...(config ?? {}) }
  const enabled = merged.moduleEnabled ?? moduleManifest.defaultEnabled
  const features = { ...DEFAULT_FEATURES, ...(merged.features ?? {}) }
  return {
    moduleId: moduleManifest.id,
    version: moduleManifest.version,
    enabled,
    features,
    config: merged as ModuleConfiguration,
  }
}

export function isFeatureEnabled(state: ModuleState, feature: string): boolean {
  return state.enabled && state.features[feature] === true
}
