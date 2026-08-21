import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

type Mode = 'signin' | 'signup'

/** Sign-in / sign-up page. Authentication is provided by the host platform. */
export function LoginPage() {
  const { signInWithEmail, signUpWithEmail, signInWithGoogle } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState<Mode>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      if (mode === 'signin') {
        await signInWithEmail(email, password)
      } else {
        await signUpWithEmail(email, password)
      }
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleGoogle = async () => {
    setError(null)
    setSubmitting(true)
    try {
      await signInWithGoogle()
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Google sign-in failed.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="login-page" aria-labelledby="login-heading">
      <h1 id="login-heading">{mode === 'signin' ? 'Sign in' : 'Create account'}</h1>
      <form className="login-form" onSubmit={handleSubmit} noValidate>
        <div className="form-field">
          <label htmlFor="login-email">Email</label>
          <input
            id="login-email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="form-field">
          <label htmlFor="login-password">Password</label>
          <input
            id="login-password"
            type="password"
            autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
            required
            minLength={6}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {error ? (
          <p className="form-error" role="alert">
            {error}
          </p>
        ) : null}
        <button type="submit" className="button button--primary" disabled={submitting}>
          {submitting ? 'Please wait…' : mode === 'signin' ? 'Sign in' : 'Create account'}
        </button>
      </form>

      <button
        type="button"
        className="button"
        onClick={() => void handleGoogle()}
        disabled={submitting}
      >
        Continue with Google
      </button>

      <p className="login-switch">
        {mode === 'signin' ? "Don't have an account?" : 'Already have an account?'}{' '}
        <button
          type="button"
          className="link-button"
          onClick={() => setMode(mode === 'signin' ? 'signup' : 'signin')}
        >
          {mode === 'signin' ? 'Create one' : 'Sign in'}
        </button>
      </p>
    </section>
  )
}
