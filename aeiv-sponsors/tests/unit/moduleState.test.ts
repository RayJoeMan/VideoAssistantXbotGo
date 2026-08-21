import { describe, expect, it } from 'vitest'
import { isFeatureEnabled, resolveModuleState } from '../../src/config/module'
import { moduleManifest } from '../../module.manifest'

describe('resolveModuleState (module toggle + feature flags)', () => {
  it('defaults to enabled with manifest feature defaults when no config exists', () => {
    const state = resolveModuleState(null)
    expect(state.moduleId).toBe('aeiv-sponsors')
    expect(state.enabled).toBe(moduleManifest.defaultEnabled)
    expect(state.features.publicPage).toBe(true)
    expect(state.features.payments).toBe(false)
    expect(isFeatureEnabled(state, 'publicPage')).toBe(true)
  })

  it('disables the module when moduleEnabled=false', () => {
    const state = resolveModuleState({ moduleEnabled: false, displayName: 'X' })
    expect(state.enabled).toBe(false)
    // Disabled module ⇒ every feature is effectively off.
    expect(isFeatureEnabled(state, 'publicPage')).toBe(false)
  })

  it('merges tenant feature flags over the manifest defaults', () => {
    const state = resolveModuleState({
      displayName: 'X',
      features: { payments: true, publicPage: false },
    })
    expect(state.features.payments).toBe(true)
    expect(state.features.publicPage).toBe(false)
    expect(isFeatureEnabled(state, 'payments')).toBe(true)
  })

  it('keeps flags not mentioned in config at their manifest defaults', () => {
    const state = resolveModuleState({ displayName: 'X', features: {} })
    expect(state.features.analytics).toBe(moduleManifest.features.analytics.defaultEnabled)
  })
})
