import { moduleManifest } from '../../module.manifest'

/**
 * RBAC permission resolution.
 *
 * Permissions use the form `[module].[resource].[action]`, e.g.
 * `sponsors.create`. Roles are org-level (defined by the platform) and map to
 * module permissions via `moduleManifest.roles`. A public (unauthenticated)
 * caller holds only the `public` role.
 *
 * This is the client-side view used to render UI. The backend re-validates
 * every operation with the same rules — never rely on UI hiding alone.
 */
export function rolesGrantPermission(roles: string[], permission: string): boolean {
  return roles.some((role) => (moduleManifest.roles[role] ?? []).includes(permission))
}

export const PUBLIC_ROLE = 'public'

export function publicRoles(): string[] {
  return [PUBLIC_ROLE]
}
