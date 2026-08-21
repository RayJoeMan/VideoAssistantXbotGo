# Discovery — AEIV Sponsors Module

Phase 0 output for the AEIV Sponsors module.

## Module

- **Name:** AEIV Sponsors
- **ID:** `aeiv-sponsors`
- **Version:** 0.1.0
- **Purpose:** A multi-tenant sponsor directory with a public listing page, a
  public inquiry form, and a permission-gated administrative interface.
- **First tenant (configuration only):** Guardian Elite Lacrosse.

## Requirements

1. Module operates independently and integrates into AEIV host websites via
   `module.manifest.ts` and tenant configuration.
2. Multi-tenant with strict logical isolation; every document/query/function
   enforces tenant boundaries. Never trust a client-supplied tenant ID.
3. Full module toggle (`enabled`), enforced in authorization — not just hidden
   UI. Individual capabilities gated by feature flags.
4. Public UI inherits the host site's theme; no iframes; responsive, keyboard
   navigable, accessible (WCAG-conscious).
5. Complete admin interface (CRUD, search, filters, status, settings,
   reporting, audit history, confirmation dialogs for destructive actions).
6. RBAC with granular `[module].[resource].[action]` permissions enforced on
   the backend.
7. Public and private data stored in separate documents with different rules.
8. Server-side APIs for all sensitive operations: auth, authz, tenant
   validation, schema validation, rate limiting, abuse protection, structured
   logging, App Check where appropriate.
9. Observability: structured logs with tenant/module/version/correlation ids.
10. Health check endpoint; independent analytics (documented events); audit
    logging for admin mutations.
11. Testing: unit, integration, security (attempt unauthorized access),
    Playwright e2e, smoke. CI/CD gates. Emulator-first development.
12. Documentation maintained in-repo; semantic versioning; backward-compatible
    config changes with migrations.
13. Firebase wired to the module owner's account (joermnd@gmail.com) for the
    production project, emulator (demo-aeiv-sponsors) for development.

## Assumptions

- React + TypeScript + Vite frontend; Firebase (Auth, Firestore, Functions,
  Storage, App Check) backend — per the master build prompt.
- Host platform provides auth (Firebase Auth) and org-level roles
  (`org.owner`, `org.admin`, `org.member`) stored at
  `tenants/{tenantId}/members/{uid}`.
- Email delivery (inquiry notifications) is a stub in this phase; a provider is
  integrated in a later phase.
- Payments (Stripe) is out of scope for v0.1 and is a feature flag only.

## Unanswered questions

- Exact production Firebase project ID to create under joermnd@gmail.com
  (default proposal: `aeiv-sponsors`).
- Email provider for inquiry notifications.
- Whether App Check will be enforced in production at v1.

## User stories

- As a **visitor**, I can browse sponsors on the host site's URL and submit an
  inquiry about sponsorship.
- As a **tenant admin**, I can manage sponsors, publish/unpublish, view
  inquiries, configure module settings/features, and see reports.
- As a **host platform**, I can discover the module via its manifest, enable or
  disable it per tenant, and rely on server-side enforcement of permissions.

## Functional requirements (v0.1)

- FR-1 Public sponsor directory (`/sponsors`) + detail view
- FR-2 Public inquiry form (callable, rate-limited, honeypot)
- FR-3 Admin CRUD for sponsors (public + admin docs)
- FR-4 Module settings (toggle, feature flags, display/content)
- FR-5 Reporting page (metrics from sponsor data + event definitions)
- FR-6 Health check (HTTP + callable)
- FR-7 Audit logging on admin mutations
- FR-8 Structured logging across functions
- FR-9 RBAC enforcement on every function

## Non-functional requirements

- NFR-1 Tenant isolation on every operation (no cross-tenant leakage)
- NFR-2 Accessibility (keyboard, labels, focus, contrast, semantic HTML)
- NFR-3 Responsive (mobile/tablet/desktop)
- NFR-4 Loading/empty/error/retry states everywhere
- NFR-5 Emulator-first development; no accidental production writes
- NFR-6 Cost controls: minimal Firestore reads, lazy loading, no uncontrolled
  listeners (documented read patterns)
- NFR-7 CI gates: lint, typecheck, tests, build, security tests
- NFR-8 Do not log secrets/PII

## Risks

- Cross-tenant data leakage → mitigated by tenant validation on every function
  and rules that scope all reads under `tenants/{tenantId}`.
- Module toggle bypass → mitigated by server-side enforcement
  (`assertModuleEnabled`) and route guards.
- IDOR on sponsor updates → sponsor IDs are validated against tenant-scoped
  paths; functions re-check membership.
- Abuse of the public inquiry form → rate limiting + honeypot + server
  validation.
- Cost blowup from Firestore reads → public list is a single bounded query;
  admin list through one callable; no uncontrolled real-time listeners
  (settings page uses one listener, admin-only).
- Rules/function drift → shared Zod schemas mirrored; security tests attempt
  unauthorized access.
