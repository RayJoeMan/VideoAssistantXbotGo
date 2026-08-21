import { httpsCallable } from 'firebase/functions'
import { getFirebaseFunctions } from '../config/firebase'

/**
 * Typed wrapper around Firebase callable functions.
 *
 * Normalizes errors into a small surface the UI can react to, and surfaces
 * the `code` returned by the backend (HttpsError codes).
 */
export class ApiError extends Error {
  readonly code: string
  readonly status?: number

  constructor(code: string, message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

export interface CallOptions {
  /** Timeout in milliseconds before the call is aborted. */
  timeoutMs?: number
}

export async function callFunction<TInput, TOutput>(
  name: string,
  input: TInput,
  options: CallOptions = {},
): Promise<TOutput> {
  const functions = getFirebaseFunctions()
  const callable = httpsCallable<TInput, TOutput>(functions, name, {
    timeout: options.timeoutMs ?? 15_000,
  })
  try {
    const result = await callable(input)
    return result.data
  } catch (err) {
    const code =
      err instanceof Error && 'code' in err ? String((err as { code?: unknown }).code) : 'unknown'
    const message =
      err instanceof Error ? err.message : 'An unexpected error occurred. Please try again.'
    throw new ApiError(code, message)
  }
}
