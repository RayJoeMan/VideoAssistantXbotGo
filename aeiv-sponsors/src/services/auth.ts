import {
  createUserWithEmailAndPassword,
  GoogleAuthProvider,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut as fbSignOut,
  type User,
} from 'firebase/auth'
import { getFirebaseAuth } from '../config/firebase'

/**
 * Authentication service.
 *
 * The module authenticates users against the host platform's Firebase Auth.
 * In local development this is the Auth emulator (demo project).
 */

export type AuthStateListener = (user: User | null) => void

export function subscribeToAuth(listener: AuthStateListener): () => void {
  const auth = getFirebaseAuth()
  return onAuthStateChanged(auth, listener)
}

export async function signInWithEmail(email: string, password: string): Promise<User> {
  const auth = getFirebaseAuth()
  const credential = await signInWithEmailAndPassword(auth, email, password)
  return credential.user
}

export async function signUpWithEmail(email: string, password: string): Promise<User> {
  const auth = getFirebaseAuth()
  const credential = await createUserWithEmailAndPassword(auth, email, password)
  return credential.user
}

export async function signInWithGoogle(): Promise<User> {
  const auth = getFirebaseAuth()
  const provider = new GoogleAuthProvider()
  const credential = await signInWithPopup(auth, provider)
  return credential.user
}

export async function signOut(): Promise<void> {
  const auth = getFirebaseAuth()
  await fbSignOut(auth)
}

export function getCurrentUser(): User | null {
  const auth = getFirebaseAuth()
  return auth.currentUser
}
