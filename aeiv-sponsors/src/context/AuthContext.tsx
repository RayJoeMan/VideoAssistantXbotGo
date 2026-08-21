import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { User } from 'firebase/auth'
import {
  getCurrentUser,
  signInWithEmail as doSignIn,
  signInWithGoogle as doGoogle,
  signOut as doSignOut,
  signUpWithEmail as doSignUp,
  subscribeToAuth,
} from '../services/auth'
import { AuthContext, type AuthContextValue } from './authContext'

/**
 * Authentication provider for the module.
 *
 * The host platform owns authentication (Firebase Auth). In local development
 * this is the Auth emulator (demo project).
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => getCurrentUser())
  const [initializing, setInitializing] = useState(true)

  useEffect(() => {
    const unsubscribe = subscribeToAuth((nextUser) => {
      setUser(nextUser)
      setInitializing(false)
    })
    return unsubscribe
  }, [])

  const signInWithEmail = useCallback(async (email: string, password: string) => {
    await doSignIn(email, password)
  }, [])

  const signUpWithEmail = useCallback(async (email: string, password: string) => {
    await doSignUp(email, password)
  }, [])

  const signInWithGoogle = useCallback(async () => {
    await doGoogle()
  }, [])

  const signOut = useCallback(async () => {
    await doSignOut()
  }, [])

  const value: AuthContextValue = useMemo(
    () => ({ user, initializing, signInWithEmail, signUpWithEmail, signInWithGoogle, signOut }),
    [user, initializing, signInWithEmail, signUpWithEmail, signInWithGoogle, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
