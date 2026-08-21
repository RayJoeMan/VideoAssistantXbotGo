# Integration & security tests (scaffold)

These layers run against the **Firebase Emulator Suite** and are filled out in
the Phase 9 testing pass. This README documents how to run them.

## Prerequisites

```bash
npm install
npm run emulators   # starts Auth/Firestore/Functions/Storage on demo-aeiv-sponsors
```

## Integration tests

Target: callable functions + Firestore behavior (writes, tenant scoping,
module gating, audit records).

Planned coverage:

- `aeiv_sponsorsCreate` writes public + admin docs under the tenant boundary.
- `aeiv_inquiriesCreate` writes only when `inquiryForm` is enabled.
- Update/delete mutate both docs and write an audit record.

## Security tests

Security-rule/function tests must **explicitly attempt unauthorized access**:

Planned coverage:

- Unauthenticated callable → `unauthenticated`.
- `public` user calling admin functions → `permission-denied`.
- Cross-tenant read of another tenant's sponsors → denied.
- Direct client write to `tenants/{t}/inquiries` or `.../sponsors/admin` → denied by rules.
- Reading sponsor/admin docs as non-admin → denied by rules.
- Module disabled → all operations rejected.

These use the Firestore rules test runner
(`@firebase/rules-unit-testing`) against the emulator and require the rules
file to be imported before assertions.
