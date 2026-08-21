import { HttpsError } from 'firebase-functions/v2/https'
import type { ZodType } from 'zod'

/**
 * Server-side input validation.
 *
 * Client validation is UX only — every function re-validates its input with
 * the shared Zod schema and rejects unexpected/malformed data.
 */
export function parseInput<T>(schema: ZodType<T>, data: unknown): T {
  const result = schema.safeParse(data)
  if (!result.success) {
    const issues = result.error.issues.map((issue) => ({
      path: issue.path.join('.'),
      message: issue.message,
    }))
    throw new HttpsError('invalid-argument', 'Invalid request data.', issues)
  }
  return result.data
}
