# AGENTS.md — AEIV Sponsors Module

This file governs how AI coding agents (and humans) should work inside this
repository. It is part of the module deliverable and must be kept up to date.

## Module purpose

AEIV Sponsors is an **independently deployable, multi-tenant web module**: a
sponsor directory with a public listing page, a public inquiry form, and a
permission-gated admin interface. It integrates into AEIV platform websites via
the module manifest (`module.manifest.ts`) and tenant configuration. It is **not**
coupled to any single customer website — Guardian Elite Lacrosse is only the
first tenant, supplied as configuration.

## Architecture

- **Frontend**: React 18 + TypeScript + Vite, React Router, TanStack Query.
- **Backend**: Firebase Cloud Functions (v2, Node 20), Firebase Auth, Firestore,
  Cloud Storage, App Check.
- **Shared schemas**: Zod — validated in the browser (UX) and again on the
  server (security). Never trust client validation.
- **Multi-tenancy**: every document lives under `tenants/{tenantId}/...`. Every
  backend operation validates the tenant and the caller's authorization.
- **Toggles**: `module.enabled` + `features.*` come from tenant config and are
  enforced in backend authorization, not just hidden in the UI.

## Folder structure

```
aeiv-sponsors/
├── module.manifest.ts      # AEIV module contract (do not break without a major version bump)
├── firebase.json           # Emulator + deploy config
├── firebase/               # firestore.rules, indexes, storage.rules
├── functions/              # Cloud Functions (own package)
│   └── src/
│       ├── callable/       # Callable functions (client-invoked, authz-enforced)
│       ├── http/           # HTTP endpoints (health check)
│       ├── triggers/       # Firestore/Storage triggers
│       ├── scheduled/      # Scheduled functions
│       └── security/       # Auth, permissions, tenant enforcement
├── src/
│   ├── config/             # env, firebase client, module/feature toggles
│   ├── schemas/            # Zod schemas (single source of truth on client)
│   ├── services/           # Firebase data access (repository layer)
│   ├── hooks/              # React hooks (auth, module state, data)
│   ├── api/                # Callable-function client wrappers
│   ├── components/
│   │   ├── public/         # Public-facing components (inherit host theme)
│   │   └── admin/          # Admin interface (permission-gated)
│   └── test/               # Test setup
├── tests/
│   ├── unit/               # Unit tests (vitest)
│   ├── integration/        # Integration tests (emulator)
│   ├── security/           # Security-rule tests (attempt unauthorized access)
│   └── e2e/                # Playwright end-to-end tests
└── scripts/                # dev/test/seed/smoke helpers
```

## Module boundaries

- The module owns `tenants/{tenantId}/sponsors/**`, `.../inquiries/**`,
  `.../moduleConfig` and `.../auditLogs/**`. It must not read or write
  collections owned by other modules.
- Public sponsor data and private admin data live in **separate documents**
  (see `docs/data-model.md`) so access requirements can differ.
- The module must never hard-code a customer name, domain, or email.

## Shared platform contracts

- `module.manifest.ts` is the contract. Changes to routes/permissions/features
  require a **minor** version bump; breaking changes (removing a permission,
  changing route paths, renaming config keys without migration) require a
  **major** bump and must be documented in `docs/configuration.md` migrations.
- Configuration schema changes must ship with a migration or
  backwards-compatible defaults.

## Coding conventions

- TypeScript strict mode. No `any` unless justified and documented.
- Prettier (`.prettierrc.json`) + ESLint flat config. Run `npm run lint`,
  `npm run format:check`, `npm run typecheck` before committing.
- React function components; hooks over classes.
- Zod schemas live in `src/schemas/` and are mirrored in `functions/src/schemas/`
  (separate packages — keep them in sync; a shared package is a future refactor).
- Structured logging on the backend: `{ timestamp, environment, module, version,
tenantId, operation, correlationId, severity }`. Never log passwords, tokens,
  payment data, or unnecessary PII.

## Security constraints

- Never store secrets in frontend source code or committed files. `.env*` is
  gitignored (see `.env.example`).
- Every function: authenticate → authorize (`requirePermission`) → validate the
  tenant (never trust a client-supplied tenant id) → validate input (Zod) →
  rate-limit where applicable.
- Do not weaken `firebase/firestore.rules`. Rule changes must be covered by
  `tests/security/` rule tests that explicitly attempt unauthorized access.

## Files AI agents may modify

- `src/**`, `functions/src/**`, `tests/**`, `scripts/**`, `docs/**`,
  `firebase/**` (rules/indexes), `.github/workflows/ci.yml`, root config
  (`package.json`, `tsconfig.json`, `vite.config.ts`, `vitest.config.ts`,
  `playwright.config.ts`, `eslint.config.js`, `.prettierrc.json`).

## Files AI agents must NOT modify without explicit authorization

- `module.manifest.ts` (contract — only via a documented version/migration
  process).
- `.firebaserc`, `.env*`, `firebase.json` deploy targets — Firebase project
  bindings are owner-controlled.
- `AGENTS.md` itself, except for maintenance of this guidance.
- Any file belonging to a **different module or repository** that may be visible
  in a multi-root workspace. Never modify unrelated modules merely because their
  repo is open.
