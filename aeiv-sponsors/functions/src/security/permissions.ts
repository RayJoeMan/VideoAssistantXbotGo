/**
 * RBAC permissions (backend).
 *
 * Mirrors `moduleManifest.roles` in the root module — keep in sync. This is
 * the authoritative enforcement point; the client view is informational only.
 */

export const MODULE_PERMISSIONS = [
  'sponsors.view',
  'sponsors.create',
  'sponsors.edit',
  'sponsors.delete',
  'sponsors.settings',
  'sponsors.reporting',
] as const

export type ModulePermission = (typeof MODULE_PERMISSIONS)[number]

export const ROLE_PERMISSIONS: Record<string, ModulePermission[]> = {
  'org.owner': [
    'sponsors.view',
    'sponsors.create',
    'sponsors.edit',
    'sponsors.delete',
    'sponsors.settings',
    'sponsors.reporting',
  ],
  'org.admin': [
    'sponsors.view',
    'sponsors.create',
    'sponsors.edit',
    'sponsors.delete',
    'sponsors.settings',
  ],
  'org.member': ['sponsors.view'],
  /** Public access is handled by Firestore rules, not RBAC. */
  public: [],
}

export const PUBLIC_ROLE = 'public'

export function rolesGrantPermission(roles: string[], permission: string): boolean {
  return roles.some((role) =>
    (ROLE_PERMISSIONS[role] as readonly string[] | undefined)?.includes(permission),
  )
}
