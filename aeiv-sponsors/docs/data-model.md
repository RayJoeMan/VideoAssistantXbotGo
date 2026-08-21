# Data Model — AEIV Sponsors Module

## Principles

1. **Tenant boundary on every entity** — all documents live under
   `tenants/{tenantId}/...`.
2. **Public vs. private separation** — public-facing sponsor data and
   admin-only data are stored in **separate documents** because their access
   requirements differ. Never merge contact/contract data into the public doc.
3. **Server-only writes** — all mutations happen through Cloud Functions (admin
   SDK); Firestore rules deny direct client writes for module collections.
4. **Audit + retention** — admin mutations write audit records; audit logs are
   retained 90 days and purged by a scheduled function.

## Entities

### `tenants/{tenantId}/moduleConfig/module`

Per-tenant module configuration (single document).

| Field                | Type             | Notes                                           |
| -------------------- | ---------------- | ----------------------------------------------- |
| `moduleEnabled`      | bool             | Module toggle (default true)                    |
| `features`           | map<string,bool> | Feature flags (keys from manifest)              |
| `displayName`        | string           | Public heading (required)                       |
| `tagline`            | string           | Subtitle                                        |
| `heroText`           | string           | Hero copy                                       |
| `contactEmail`       | string           | Notification recipient (feature: notifications) |
| `maxSponsorsPerPage` | int              | Page size cap                                   |
| `inquiryEnabled`     | bool             | Inquiry form master switch                      |

Access: **public read while enabled**; writes server-only.

### `tenants/{tenantId}/sponsors/public/{sponsorId}`

Public sponsor document (rendered on the site).

| Field                    | Type    | Notes                                 |
| ------------------------ | ------- | ------------------------------------- |
| `id`, `tenantId`         | string  | Identity                              |
| `name`                   | string  | Display name (required)               |
| `tier`                   | enum    | platinum/gold/silver/bronze/community |
| `websiteUrl`, `logoUrl`  | string? | URLs                                  |
| `tagline`, `description` | string  | Copy                                  |
| `sortOrder`              | int     | Directory ordering                    |
| `published`              | bool    | Visibility on public page             |
| `createdAt`, `updatedAt` | string  | ISO timestamps                        |

Access: **public read while module enabled**; writes server-only.

### `tenants/{tenantId}/sponsors/admin/{sponsorId}`

Admin-only sponsor document (same id as the public doc).

| Field                                         | Type    | Notes                       |
| --------------------------------------------- | ------- | --------------------------- |
| `id`, `tenantId`                              | string  | Identity                    |
| `status`                                      | enum    | active/inactive/pending     |
| `contactName`, `contactEmail`, `contactPhone` | string? | Contact info                |
| `contractStart`, `contractEnd`                | string? | Contract window             |
| `monthlyAmount`                               | number? | Monetary value (admin-only) |
| `notes`                                       | string  | Internal notes              |
| `createdAt`, `updatedAt`                      | string  | ISO timestamps              |

Access: **admin read only**; writes server-only.

### `tenants/{tenantId}/inquiries/{inquiryId}`

Inquiry submitted via the public form.

| Field                                 | Type    | Notes                           |
| ------------------------------------- | ------- | ------------------------------- |
| `id`, `tenantId`                      | string  | Identity                        |
| `sponsorId`, `sponsorName`            | string? | Optional target sponsor         |
| `name`, `email`, `company`, `message` | string  | Submission (PII — kept private) |
| `status`                              | enum    | new/contacted/closed            |
| `createdAt`                           | string  | ISO timestamp                   |

Access: **no direct client access** (write via callable, read via admin
functions). PII is minimized and never logged.

### `tenants/{tenantId}/members/{uid}`

Membership/roles (owned by the platform, read by this module).

| Field                  | Type     | Notes                              |
| ---------------------- | -------- | ---------------------------------- |
| `roles`                | string[] | org.owner / org.admin / org.member |
| `email`, `displayName` | string   | Identity                           |

Access: self-read or admin-read; writes managed by the platform.

### `tenants/{tenantId}/auditLogs/{entryId}`

Append-only audit records for admin mutations.

| Field                        | Type   | Notes                                   |
| ---------------------------- | ------ | --------------------------------------- |
| `actor`                      | string | UID of the actor                        |
| `tenantId`                   | string | Tenant                                  |
| `action`                     | string | e.g. sponsor.create/update/delete       |
| `resourceType`, `resourceId` | string | Target                                  |
| `timestamp`                  | string | ISO timestamp                           |
| `changes`                    | map    | Sanitized before/after (no secrets/PII) |

Access: **admin read only**; writes server-only (functions); retention 90 days.

## Relationships

```
tenant (1) ──< moduleConfig (1)
tenant (1) ──< sponsors/public (N)  ── 1:1 ── sponsors/admin (N)
tenant (1) ──< inquiries (N)  ── sponsor (0..1) ── sponsors/public
tenant (1) ──< members (N)
tenant (1) ──< auditLogs (N)
```

## Indexes

`firebase/firestore.indexes.json`:

- `sponsors` collection: `published ASC, sortOrder ASC` (published directory
  queries).
- `inquiries` collection: `tenantId ASC, createdAt DESC` (recent inquiries per
  tenant).
- Single-field queries (e.g. audit `timestamp`) need no composite index.

## Read/write patterns & cost notes

- Public directory: one query (`orderBy sortOrder`, filtered to published in
  code), bounded by `maxSponsorsPerPage` in future pagination.
- Admin list: one callable → two collection reads (public + admin).
- Real-time listeners: **one** (admin settings page, single doc). No
  uncontrolled listeners anywhere else.
- Writes: each sponsor mutation = 2 writes + 1 audit write; each inquiry =
  1 write. Rate-limited.

## Retention

- Audit logs: 90 days (scheduled cleanup, daily 03:00 UTC, bounded batch).
- Inquiries: kept; admins close them manually (future retention policy).
- No PII beyond what is needed; emails are required for inquiry replies only.
