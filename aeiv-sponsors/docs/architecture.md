# Architecture — AEIV Sponsors Module

Phase 1 output.

## System overview

```
                    ┌─────────────────────────────────────────────┐
                    │              AEIV host website              │
                    │  (owns the public URL, e.g. guardianelitelax.com)│
                    └──────────────────────┬──────────────────────┘
                                           │ module.manifest.ts (discovery,
                                           │ config, toggles, permissions)
                    ┌──────────────────────▼──────────────────────┐
                    │              AEIV Sponsors module            │
                    │  React 18 + TS + Vite (src/)                 │
                    │  - public components  - admin components     │
                    │  - hooks / services   - schemas (Zod)        │
                    └──────────────────────┬──────────────────────┘
                                           │ callables (httpsCallable)
                    ┌──────────────────────▼──────────────────────┐
                    │          Cloud Functions (functions/)        │
                    │  callable/ · http/ · triggers/ · scheduled/  │
                    │  security/ (auth, tenant, rbac, audit, rate) │
                    └──────────────────────┬──────────────────────┘
                                           │ admin SDK
                    ┌──────────────────────▼──────────────────────┐
                    │   Firebase: Firestore · Auth · Storage       │
                    │   rules: firebase/firestore.rules            │
                    └─────────────────────────────────────────────┘
```

Key rules from the master build prompt honored here:

- The module is an **independent application/service** (own repo, own Firebase
  resources, own rules, own CI/CD).
- It connects to host websites through the module manifest; nothing
  customer-specific is hard-coded (tenant config only).
- Host website owns the URL; no iframes.
- Module toggle + feature flags are enforced **in authorization** (functions +
  rules), not only by hiding UI.

## Component architecture (frontend)

- `src/config/` — env, Firebase bootstrap, module toggle + feature resolution
  (`resolveModuleState`).
- `src/schemas/` — Zod schemas (validated client-side for UX).
- `src/services/` — repository layer over Firestore + callables.
- `src/api/client.ts` — typed callable wrapper + error normalization.
- `src/hooks/` — `useAuth`, `useModuleState`, `usePermissions`,
  `usePublicSponsors`, `useAdminSponsors`, mutations.
- `src/components/public/` — sponsor directory, detail, inquiry form.
- `src/components/admin/` — admin shell, CRUD, settings, reporting.
- `src/components/ui/` — Loading/Empty/Error states.
- `src/analytics/events.ts` — documented business events.

The frontend is intentionally thin: **no sensitive operations from the
client**. All writes and admin reads go through callable functions.

## Tenant architecture

- Every module document lives under `tenants/{tenantId}/...`.
- Tenant identity comes from the host (env var `VITE_TENANT_ID` or host
  routing); every function re-validates authorization against that tenant —
  never trusts a client-supplied tenant ID.
- Tenant config doc: `tenants/{tenantId}/moduleConfig/module` (module toggle +
  feature flags + display/content). This is the per-tenant knob the host uses
  to enable/disable and configure the module.

## Backend architecture

- **Callable functions** (`functions/src/callable/`): sponsors CRUD, inquiry
  creation, module config get/update, health. Flow:
  authenticate → authorize (`requirePermission`) → tenant/module check
  (`assertModuleEnabled`) → validate input (Zod) → act → audit → structured log.
- **HTTP endpoints** (`functions/src/http/health.ts`): unauthenticated health
  check for monitors/load balancers.
- **Triggers** (`functions/src/triggers/inquiryNotifications.ts`): email
  notification stub on inquiry creation (feature-gated).
- **Scheduled** (`functions/src/scheduled/cleanup.ts`): audit-log retention
  cleanup (daily, bounded batch).
- **Security helpers** (`functions/src/security/`): auth, tenant, permissions,
  rate limiting, audit, validation, logging.

## Data architecture

See `docs/data-model.md` for entities, separation of public/private data,
indexes, retention, and audit requirements.

## Security model

See `docs/security.md` for the threat model and controls.

## API design

See `docs/api.md` for endpoints, payloads, and the error model.

## Permission model

See `docs/permissions.md` for the RBAC matrix.

## Module manifest & toggle strategy

- `module.manifest.ts` is the contract: id, version, compatibility, routes,
  admin routes, navigation, permissions, roles, features (with defaults),
  configuration schema, dependencies, health check.
- `src/config/module.ts` resolves per-tenant state:
  `moduleEnabled` (default from manifest) + `features.*` merged over manifest
  defaults.
- Enforcement layers:
  1. **Routing**: `ModuleRouteGuard` returns not-found when disabled.
  2. **Navigation**: hidden when disabled.
  3. **Data**: hooks disabled when the module is off.
  4. **Backend**: `assertModuleEnabled` / `assertFeatureEnabled` reject calls.
  5. **Rules**: public reads of sponsor/config docs require `moduleEnabled`.

## Observability

Structured logs (functions): `{ timestamp, environment, module, version,
tenantId, operation, correlationId, severity, message }`. No secrets/PII.
`scripts/smoke.ts` verifies health after deployment.

## Cost control (initial)

- Public directory: one bounded Firestore query (orderBy sortOrder, limit
  configured via `maxSponsorsPerPage`).
- Admin list: single callable returning public+admin (one read each).
- No uncontrolled real-time listeners; the only listener is the admin settings
  page (one doc, admin-only).
- Functions are small and infrequent; triggers fire once per inquiry.
- Analytics events are log-only in v0.1 (no analytics billing).
- Mitigation: rate limiting on the public write path; retention cleanup for
  audit logs.
