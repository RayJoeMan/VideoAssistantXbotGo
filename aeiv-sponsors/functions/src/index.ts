import { initializeApp } from 'firebase-admin/app'
import { setGlobalOptions } from 'firebase-functions/v2'

setGlobalOptions({ region: 'us-central1' })

// When running under the emulator, point the admin SDK at the local emulators
// even if the CLI did not inject the env vars (robustness for local dev).
if (process.env.FUNCTIONS_EMULATOR === 'true') {
  process.env.FIRESTORE_EMULATOR_HOST = process.env.FIRESTORE_EMULATOR_HOST || '127.0.0.1:8080'
}

initializeApp()

// Callable functions
export * from './callable/healthCheck'
export * from './callable/sponsors'
export * from './callable/inquiries'
export * from './callable/moduleConfig'

// HTTP endpoints
export * from './http/health'

// Triggers
export * from './triggers/inquiryNotifications'

// Scheduled functions
export * from './scheduled/cleanup'
