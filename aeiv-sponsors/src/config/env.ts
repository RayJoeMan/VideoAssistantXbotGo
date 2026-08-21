/**
 * Runtime environment configuration.
 *
 * Values are read from Vite env vars (`.env.local`, see `.env.example`).
 * Real Firebase credentials are NEVER committed — in local development the app
 * connects to the Firebase Emulator Suite, which requires no credentials.
 */
export interface AppEnv {
  firebaseApiKey: string
  firebaseAuthDomain: string
  firebaseProjectId: string
  firebaseStorageBucket: string
  firebaseMessagingSenderId: string
  firebaseAppId: string
  firebaseMeasurementId: string
  /** When true, all Firebase SDKs connect to the local emulator suite. */
  useEmulators: boolean
  /** Optional pinned tenant for single-tenant host deployments. */
  tenantId: string
  appVersion: string
}

function boolFromEnv(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined) return fallback
  return value.toLowerCase() === 'true'
}

export const env: AppEnv = {
  firebaseApiKey: import.meta.env.VITE_FIREBASE_API_KEY ?? '',
  firebaseAuthDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN ?? 'aeiv-sponsors.firebaseapp.com',
  firebaseProjectId: import.meta.env.VITE_FIREBASE_PROJECT_ID ?? 'aeiv-sponsors',
  firebaseStorageBucket:
    import.meta.env.VITE_FIREBASE_STORAGE_BUCKET ?? 'aeiv-sponsors.appspot.com',
  firebaseMessagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID ?? '',
  firebaseAppId: import.meta.env.VITE_FIREBASE_APP_ID ?? '',
  firebaseMeasurementId: import.meta.env.VITE_FIREBASE_MEASUREMENT_ID ?? '',
  useEmulators: boolFromEnv(import.meta.env.VITE_USE_EMULATORS, true),
  tenantId: import.meta.env.VITE_TENANT_ID ?? '',
  appVersion: import.meta.env.VITE_APP_VERSION ?? '0.1.0',
}
