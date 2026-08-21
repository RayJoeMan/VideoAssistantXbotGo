import { createContext } from 'react'
import type { User } from 'firebase/auth'

export interface AuthContextValue {
  user: User | null
  /** True until the initial auth state has been resolved. */
  initializing: boolean
  signInWithEmail: (email: string, password: string) => Promise<void>
  signUpWithEmail: (email: string, password: string) => Promise<void>
  signInWithGoogle: () => Promise<void>
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)
