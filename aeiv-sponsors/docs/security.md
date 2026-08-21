# Security — AEIV Sponsors Module

## Threat model

| Threat                | Vector                                | Control                                                                                                                   |
| --------------------- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Authentication bypass | Call functions without a session      | `requireAuth` on all protected callables; unauthenticated → error                                                         |
| Authorization bypass  | Call admin functions with a weak role | `requirePermission` (roles → permissions) on every callable                                                               |
| Tenant escape         | Supply another tenant's id            | Every function validates membership for the supplied tenant; data paths always scoped `tenants/{tenantId}/...`            |
| IDOR                  | Guess/iterate sponsor ids             | Sponsor ids are UUIDs; mutations re-check tenant + permission; reads are rule-gated                                       |
| Injection (NoSQL)     | Malformed queries                     | Zod validation on every input; no raw query strings from clients                                                          |
| XSS                   | Malicious sponsor content             | React escapes rendered content; URLs validated as `z.string().url()`; `rel="noopener noreferrer"` on external links       |
| CSRF                  | Cross-site mutation                   | Callable functions require auth tokens (Bearer), not cookies                                                              |
| Spam / bot abuse      | Inquiry floods                        | Honeypot field + server-side rate limiting (per uid/IP)                                                                   |
| Unrestricted uploads  | Logo upload abuse                     | Storage rules deny direct writes; uploads deferred to a server-validated phase                                            |
| Secrets exposure      | Committed credentials                 | `.env*` gitignored; only `.env.example` committed; App Check + env-based config                                           |
| PII exposure          | Inquiry data leak                     | Inquiries are private (rules deny direct reads); PII not logged                                                           |
| Insecure logging      | Password/token in logs                | Structured logger never logs auth data; inputs are sanitized                                                              |
| Privilege escalation  | Role tampering                        | Membership docs are platform-owned (module rules deny writes); backend reads roles from Firestore, not from client claims |
| Module-toggle bypass  | Access disabled module                | `assertModuleEnabled`/`assertFeatureEnabled` server-side; rules require `moduleEnabled` for public reads                  |

## Controls

### Authentication

- Firebase Auth (email/password + Google). Emulator-first in dev
  (`demo-aeiv-sponsors`).
- Callables use `request.auth` (verified server-side).

### Authorization

- RBAC permissions `[module].[resource].[action]` (see `docs/permissions.md`).
- Enforcement: `functions/src/security/auth.ts` + `permissions.ts`. The
  client-side `RequirePermission` is UX only.
- Least privilege: `org.member` can view; `org.admin` manages sponsors but not
  reporting; `org.owner` full.

### Tenant isolation

- All data under `tenants/{tenantId}`.
- `functions/src/security/tenant.ts`: `assertModuleEnabled`,
  `getMemberRoles`. Tenant id is never trusted without membership validation.
- Firestore rules scope every read/write under the tenant path.

### Input validation

- Shared Zod schemas (client + server). Server re-validates every payload
  (`parseInput`) and rejects unexpected/malformed data.
- Public data is normalized (URLs validated, strings bounded).

### Firestore & Storage rules

- `firebase/firestore.rules`: public reads only while module enabled; admin
  docs/inquiries/audit logs denied to clients; module writes server-only.
- `firebase/storage.rules`: logos readable; writes denied (uploads deferred).
- Rule changes must be covered by `tests/security/`.

### Rate limiting & abuse protection

- `enforceRateLimit` (in-memory, per instance): inquiries limited per uid/IP.
- Honeypot field on the inquiry form.
- App Check: intended for production (see docs/deployment.md); emulator-first
  development does not enforce it.

### Secrets

- No secrets in frontend source. Firebase config via env vars
  (`src/config/env.ts`), gitignored `.env*`.
- Deployment credentials live in CI secrets, never in the repo.

### Audit

- Every admin mutation writes an audit record (append-only; rules deny client
  writes/deletes). Ordinary administrators cannot edit audit logs.

## Verification

- `tests/unit/` — permission/schema/toggle logic.
- `tests/security/` — rule + function tests that **attempt unauthorized
  access** (documented; run against the emulator).
- `scripts/smoke.ts` — post-deploy health.
- CI runs lint/typecheck/unit/build for both web and functions.
