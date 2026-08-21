import { useEffect, useState, type FormEvent } from 'react'
import { moduleManifest } from '../../../module.manifest'
import { useTenantId } from '../../hooks/useTenant'
import { useModuleState } from '../../hooks/useModuleState'
import { subscribeModuleConfig, updateModuleConfig } from '../../services/tenant'
import { LoadingState } from '../ui/LoadingState'

/**
 * Module settings: module toggle, feature flags, and display/content config.
 * Requires `sponsors.settings` (enforced by the route and the backend).
 */
export function ModuleSettingsPage() {
  const tenantId = useTenantId()
  const { state, isLoading } = useModuleState(tenantId)

  const [moduleEnabled, setModuleEnabled] = useState(true)
  const [features, setFeatures] = useState<Record<string, boolean>>({})
  const [displayName, setDisplayName] = useState('')
  const [tagline, setTagline] = useState('')
  const [heroText, setHeroText] = useState('')
  const [contactEmail, setContactEmail] = useState('')
  const [inquiryEnabled, setInquiryEnabled] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hydrated, setHydrated] = useState(false)

  // Keep local state in sync with Firestore (real-time for this admin page).
  useEffect(() => {
    const unsubscribe = subscribeModuleConfig(tenantId, (config) => {
      if (!config) return
      setModuleEnabled(config.moduleEnabled ?? true)
      setFeatures(config.features ?? {})
      setDisplayName(config.displayName ?? '')
      setTagline(config.tagline ?? '')
      setHeroText(config.heroText ?? '')
      setContactEmail(config.contactEmail ?? '')
      setInquiryEnabled(config.inquiryEnabled ?? true)
      setHydrated(true)
    })
    return unsubscribe
  }, [tenantId])

  if (isLoading || !hydrated) return <LoadingState label="Loading settings…" />

  const toggleFeature = (key: string) => {
    setFeatures((prev) => ({
      ...prev,
      [key]: !(prev[key] ?? moduleManifest.features[key].defaultEnabled),
    }))
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      await updateModuleConfig(tenantId, {
        moduleEnabled,
        features,
        displayName,
        tagline,
        heroText,
        contactEmail: contactEmail || undefined,
        inquiryEnabled,
      })
      setSaved(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save settings.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="admin-page" aria-labelledby="settings-heading">
      <h1 id="settings-heading">Module settings</h1>
      <p className="settings-version">
        Module {moduleManifest.id} v{state.version} · API {moduleManifest.apiVersion}
      </p>

      <form className="settings-form" onSubmit={handleSubmit}>
        <fieldset>
          <legend>Module</legend>
          <div className="form-field form-field--check">
            <input
              id="set-module-enabled"
              type="checkbox"
              checked={moduleEnabled}
              onChange={(e) => setModuleEnabled(e.target.checked)}
            />
            <label htmlFor="set-module-enabled">
              Module enabled — when off, all public/admin routes, navigation, and API calls are
              disabled (enforced server-side).
            </label>
          </div>
        </fieldset>

        <fieldset>
          <legend>Features</legend>
          {Object.entries(moduleManifest.features).map(([key, flag]) => (
            <div className="form-field form-field--check" key={key}>
              <input
                id={`set-feature-${key}`}
                type="checkbox"
                checked={features[key] ?? flag.defaultEnabled}
                onChange={() => toggleFeature(key)}
              />
              <label htmlFor={`set-feature-${key}`}>
                <strong>{key}</strong> — {flag.description}
              </label>
            </div>
          ))}
        </fieldset>

        <fieldset>
          <legend>Display &amp; content</legend>
          <div className="form-field">
            <label htmlFor="set-display-name">Display name</label>
            <input
              id="set-display-name"
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
            />
          </div>
          <div className="form-field">
            <label htmlFor="set-tagline">Tagline</label>
            <input
              id="set-tagline"
              type="text"
              value={tagline}
              onChange={(e) => setTagline(e.target.value)}
            />
          </div>
          <div className="form-field">
            <label htmlFor="set-hero">Hero text</label>
            <textarea
              id="set-hero"
              rows={3}
              value={heroText}
              onChange={(e) => setHeroText(e.target.value)}
            />
          </div>
          <div className="form-field">
            <label htmlFor="set-email">Inquiry notification email</label>
            <input
              id="set-email"
              type="email"
              value={contactEmail}
              onChange={(e) => setContactEmail(e.target.value)}
            />
          </div>
          <div className="form-field form-field--check">
            <input
              id="set-inquiry"
              type="checkbox"
              checked={inquiryEnabled}
              onChange={(e) => setInquiryEnabled(e.target.checked)}
            />
            <label htmlFor="set-inquiry">Inquiry form enabled</label>
          </div>
        </fieldset>

        {error ? (
          <p className="form-error" role="alert">
            {error}
          </p>
        ) : null}
        {saved ? (
          <p className="form-success" role="status">
            Settings saved.
          </p>
        ) : null}

        <div className="form-actions">
          <button type="submit" className="button button--primary" disabled={saving}>
            {saving ? 'Saving…' : 'Save settings'}
          </button>
        </div>
      </form>
    </section>
  )
}
