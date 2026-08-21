# Permissions — AEIV Sponsors Module

## Pattern

`[module].[resource].[action]` — e.g. `sponsors.create`.

## Permission list

| Permission           | Description                                      |
| -------------------- | ------------------------------------------------ |
| `sponsors.view`      | View public directory + admin list               |
| `sponsors.create`    | Create sponsors                                  |
| `sponsors.edit`      | Edit sponsors                                    |
| `sponsors.delete`    | Delete sponsors                                  |
| `sponsors.settings`  | Change module config (toggle, features, display) |
| `sponsors.reporting` | View reporting                                   |

## Role → permission matrix

| Role         | view | create | edit | delete | settings | reporting |
| ------------ | ---- | ------ | ---- | ------ | -------- | --------- |
| `org.owner`  | ✅   | ✅     | ✅   | ✅     | ✅       | ✅        |
| `org.admin`  | ✅   | ✅     | ✅   | ✅     | ✅       | ❌        |
| `org.member` | ✅   | ❌     | ❌   | ❌     | ❌       | ❌        |
| `public`     | ❌   | ❌     | ❌   | ❌     | ❌       | ❌        |

The `public` role holds **no module permissions**: public access to the sponsor
directory is granted by Firestore rules (module-enabled gate), not by RBAC, so
guests never see the admin surface.

The matrix lives in two mirrored places that must stay in sync:

- Client UI view: `src/utils/permissions.ts` + `module.manifest.ts` `roles`.
- Backend enforcement: `functions/src/security/permissions.ts`.

## Enforcement

1. **Backend (authoritative)** — every callable calls
   `requirePermission(request, tenantId, permission)`:
   authenticate → assert module enabled → read the caller's roles from
   `tenants/{tenantId}/members/{uid}` → check the matrix → act.
2. **Rules** — admin-only collections (`sponsors/admin`, `auditLogs`) are
   readable only by `org.owner`/`org.admin`; inquiries are not directly
   readable by clients.
3. **Client (UX only)** — `RequirePermission` gates routes; nav items and
   buttons are filtered. This is never security.

## Notes

- Roles are supplied by the platform (host) at `tenants/{tenantId}/members/{uid}`.
  The module reads them; it never trusts client-claimed roles.
- Public (unauthenticated) callers hold only the `public` role.
- Disabling the module (`moduleEnabled: false`) disables all permissions
  server-side via `assertModuleEnabled`.
