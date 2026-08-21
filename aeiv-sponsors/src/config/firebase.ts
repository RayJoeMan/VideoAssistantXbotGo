import { getApps, initializeApp, type FirebaseApp } from 'firebase/app'
import { connectAuthEmulator, getAuth, type Auth } from 'firebase/auth'
import { connectFirestoreEmulator, getFirestore, type Firestore } from 'firebase/firestore'
import { connectFunctionsEmulator, getFunctions, type Functions } from 'firebase/functions'
import { connectStorageEmulator, getStorage, type FirebaseStorage } from 'firebase/storage'
import { env } from './env'

/**
 * Firebase client bootstrap.
 *
 * When `env.useEmulators` is true (default in local dev) every SDK is wired to
 * the Firebase Emulator Suite (project demo-aeiv-sponsors). No production data
 * is ever touched during development.
 *
 * All accessors are lazy so importing this module has no side effects until a
 * service is actually used. The module reuses an already-registered app (e.g.
 * after a hot reload) instead of calling initializeApp twice.
 */

let app: FirebaseApp | null = null
let emulatorsConnected = false
let auth: Auth | null = null
let db: Firestore | null = null
let storage: FirebaseStorage | null = null
let functions: Functions | null = null

/** Emulator project used for all local development (never a real project). */
const EMULATOR_PROJECT_ID = 'demo-aeiv-sponsors'

export function getFirebaseApp(): FirebaseApp {
  if (!app) {
    // In emulator mode, use the emulator project id — the emulator only knows
    // that project and will reject reads addressed to any other project id.
    const projectId = env.useEmulators ? EMULATOR_PROJECT_ID : env.firebaseProjectId
    app =
      getApps()[0] ??
      initializeApp({
        // The emulator ignores the API key, but the SDK requires a non-empty value.
        apiKey: env.firebaseApiKey || (env.useEmulators ? 'demoapikey' : ''),
        authDomain: env.firebaseAuthDomain,
        projectId,
        storageBucket: env.firebaseStorageBucket,
        messagingSenderId: env.firebaseMessagingSenderId,
        appId: env.firebaseAppId,
        measurementId: env.firebaseMeasurementId,
      })
  }
  if (env.useEmulators && !emulatorsConnected) {
    const authInstance = getAuth(app)
    const dbInstance = getFirestore(app)
    const storageInstance = getStorage(app)
    const functionsInstance = getFunctions(app)
    connectAuthEmulator(authInstance, 'http://127.0.0.1:9099', { disableWarnings: true })
    connectFirestoreEmulator(dbInstance, '127.0.0.1', 8080)
    connectStorageEmulator(storageInstance, '127.0.0.1', 9199)
    connectFunctionsEmulator(functionsInstance, '127.0.0.1', 5001)
    auth = authInstance
    db = dbInstance
    storage = storageInstance
    functions = functionsInstance
    emulatorsConnected = true
  }
  return app
}

export function getFirebaseAuth(): Auth {
  getFirebaseApp()
  if (!auth) auth = getAuth(app!)
  return auth
}

export function getFirebaseFirestore(): Firestore {
  getFirebaseApp()
  if (!db) db = getFirestore(app!)
  return db
}

export function getFirebaseStorage(): FirebaseStorage {
  getFirebaseApp()
  if (!storage) storage = getStorage(app!)
  return storage
}

export function getFirebaseFunctions(): Functions {
  getFirebaseApp()
  if (!functions) functions = getFunctions(app!)
  return functions
}
