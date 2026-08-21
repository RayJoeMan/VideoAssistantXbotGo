/**
 * Firestore write sanitization.
 *
 * The Admin SDK throws when a document payload contains an `undefined` value.
 * Optional input fields (e.g. sponsorId, websiteUrl) may be undefined after
 * validation, so every document written to Firestore is passed through
 * `pickDefined` before the write.
 */
export function pickDefined<T extends Record<string, unknown>>(obj: T): Record<string, unknown> {
  return Object.fromEntries(Object.entries(obj).filter(([, value]) => value !== undefined))
}
