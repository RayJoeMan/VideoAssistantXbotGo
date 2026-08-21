# API — AEIV Sponsors Module

## Conventions

- **Callables** (`httpsCallable`) for client-invoked operations. Function names
  are prefixed `aeiv_`.
- **HTTP** for the health endpoint (unauthenticated, monitor-friendly).
- Every callable: authenticate → authorize → tenant/module check → Zod
  validation → act → audit → structured log.
- Errors use Firebase `HttpsError` codes; the client wrapper (`src/api/client.ts`)
  normalizes them to `ApiError { code, message }`.

## Error codes

| Code                  | Meaning                                     |
| --------------------- | ------------------------------------------- |
| `unauthenticated`     | Missing/invalid session                     |
| `permission-denied`   | Authenticated but lacking the permission    |
| `failed-precondition` | Module or feature disabled for the tenant   |
| `invalid-argument`    | Schema validation failed (details included) |
| `not-found`           | Target resource/config missing              |
| `resource-exhausted`  | Rate limit exceeded                         |
| `internal`            | Unexpected failure (sanitized)              |

## Callable functions

### `aeiv_healthCheck`

Input: `{}` — Output: `{ status: 'ok'|'degraded', module, version, checks[] }`
Auth: none.

### `aeiv_sponsorsList`

Permission: `sponsors.view`
Input: `{ tenantId }` — Output: `{ sponsors: Array<{ public, admin }> }`

### `aeiv_sponsorsCreate`

Permission: `sponsors.create`
Input: `{ tenantId, public: {...}, admin?: {...} }` — Output: `{ sponsor: { public, admin } }`
Writes: public + admin docs, audit log.

### `aeiv_sponsorsUpdate`

Permission: `sponsors.edit`
Input: `{ tenantId, sponsorId, public?: {...}, admin?: {...} }` — Output: `{ sponsor }`
Writes: merged updates, audit log (sanitized diff).

### `aeiv_sponsorsDelete`

Permission: `sponsors.delete`
Input: `{ tenantId, sponsorId }` — Output: `{ deleted: true }`
Writes: deletes both docs, audit log.

### `aeiv_inquiriesCreate`

Permission: none (public) — but module + `inquiryForm` feature must be enabled.
Input: `{ tenantId, name, email, company?, message, sponsorId?, sponsorName?, website? }`
`website` is the honeypot (must be empty). Rate-limited.
Output: `{ inquiryId }`

### `aeiv_moduleConfigGet`

Input: `{ tenantId }` — Output: `{ config }`
Public (config is public while module enabled).

### `aeiv_moduleConfigUpdate`

Permission: `sponsors.settings`
Input: `{ tenantId, update: Partial<moduleConfig> }` — Output: `{ config }`
Writes: merged config, audit log.

## HTTP endpoints

### `GET /apiHealth`

Output: `{ status, module, version, timestamp, checks[] }` (200 ok / 503 degraded).
Used by the smoke test and monitors. No sensitive infrastructure details.

## Client mapping

| Client service                    | Function                  |
| --------------------------------- | ------------------------- |
| `functionsApi.healthCheck`        | `aeiv_healthCheck`        |
| `functionsApi.listSponsors`       | `aeiv_sponsorsList`       |
| `functionsApi.createSponsor`      | `aeiv_sponsorsCreate`     |
| `functionsApi.updateSponsor`      | `aeiv_sponsorsUpdate`     |
| `functionsApi.deleteSponsor`      | `aeiv_sponsorsDelete`     |
| `functionsApi.createInquiry`      | `aeiv_inquiriesCreate`    |
| `functionsApi.getModuleConfig`    | `aeiv_moduleConfigGet`    |
| `functionsApi.updateModuleConfig` | `aeiv_moduleConfigUpdate` |

## Direct Firestore reads (rules-gated)

- Public directory + detail: `tenants/{tenantId}/sponsors/public/...`
  (public read, module must be enabled).
- Module config: `tenants/{tenantId}/moduleConfig/module` (public read while
  enabled).
- Member roles: `tenants/{tenantId}/members/{uid}` (self-read).
