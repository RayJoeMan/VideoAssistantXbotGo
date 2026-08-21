# Configuration — AEIV Sponsors Module

## Module manifest

`module.manifest.ts` is the contract the host website uses to discover and
configure the module. It exposes: id, name, version, compatibility version,
public/admin routes, navigation, permissions, roles, features (with defaults),
configuration schema, dependencies, and health check.

## Module toggle

Per-tenant enable/disable lives in the tenant config document:

```
tenants/{tenantId}/moduleConfig/module
  moduleEnabled: true | false
```

When disabled:

- Public + admin navigation is removed.
- All public and admin routes resolve to a not-found page.
- Client hooks stop issuing module API calls.
- Backend functions reject operations (`failed-precondition`).
- Firestore rules deny public reads.

Set it via the admin UI (Settings → Module) or directly in the tenant config.

## Feature flags

Individual capabilities are independent flags under the same config document:

```
features:
  publicPage:    public sponsor directory
  inquiryForm:   public inquiry form
  homepage:      homepage integration slot
  footer:        footer integration slot
  analytics:     business-event tracking
  notifications: email notifications on new inquiries
  payments:      sponsorship payments (not implemented in v0.1)
```

Each flag defaults from the manifest. Flags are enforced server-side
(`assertFeatureEnabled`) where they gate an API (e.g. `inquiryForm`).

## Tenant display/content settings

| Key                  | Type   | Default      | Purpose                        |
| -------------------- | ------ | ------------ | ------------------------------ |
| `displayName`        | string | — (required) | Public heading                 |
| `tagline`            | string | ''           | Subtitle                       |
| `heroText`           | string | ''           | Hero copy                      |
| `contactEmail`       | string | —            | Inquiry notification recipient |
| `maxSponsorsPerPage` | int    | 24           | Page-size cap                  |
| `inquiryEnabled`     | bool   | true         | Inquiry form master switch     |

## Environment variables

See `.env.example`. `VITE_TENANT_ID` pins a single-tenant host deployment;
multi-tenant hosts supply the tenant through their own routing.

## Schema changes & migrations

- **Adding** a config key: backwards-compatible (defaults applied). Bump
  `version` (minor).
- **Renaming/removing** a key: breaking — requires a major version bump and a
  migration. Document the migration here and ship defaults so existing tenants
  keep working.

No migrations exist yet (v0.1). Future changes must be recorded in this file.
