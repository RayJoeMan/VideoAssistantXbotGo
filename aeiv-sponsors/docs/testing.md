# Testing — AEIV Sponsors Module

## Test layers

| Layer                      | Location                     | Tool                        | Requires emulator |
| -------------------------- | ---------------------------- | --------------------------- | ----------------- |
| Unit (web)                 | `tests/unit/`                | Vitest (jsdom)              | no                |
| Unit (functions)           | `functions/src/**/*.test.ts` | Vitest (node)               | no                |
| Integration                | `tests/integration/`         | Vitest + emulator SDK       | yes               |
| Security (rules/functions) | `tests/security/`            | Firestore rules test runner | yes               |
| E2E                        | `tests/e2e/`                 | Playwright                  | partial (smoke)   |
| Smoke                      | `scripts/smoke.ts`           | Node                        | functions         |

## Unit tests

Cover the pure logic: module toggle/feature resolution
(`tests/unit/moduleState.test.ts`), RBAC (`tests/unit/permissions.test.ts`),
and schema validation (`tests/unit/schemas.test.ts`). Functions-side RBAC is
covered by `functions/src/security/permissions.test.ts`.

```bash
npm test                          # web
npm --prefix functions run test   # functions
```

## Integration & security tests

- **Integration**: exercise callables + Firestore against the emulator
  (`demo-aeiv-sponsors`) to verify writes, tenant scoping, and module gating.
- **Security**: explicitly attempt unauthorized access — public caller hitting
  admin functions, cross-tenant reads, writes to server-only collections —
  and assert they are denied.

Both layers require `npm run emulators` running. Setup (rule/schema import and
emulator project wiring) is documented in `tests/integration/README.md` and
`tests/security/README.md`; they are scaffolded and are filled out in the
Phase 9 testing pass.

## E2E (Playwright)

```bash
npx playwright install chromium
npm run test:e2e
```

`tests/e2e/smoke.spec.ts` covers the app shell, navigation, login page, and
not-found behavior without requiring emulator data. Data-dependent e2e flows
(create/edit sponsor, toggle features) run against the emulator in later
phases.

## Smoke

```bash
npm run smoke                 # emulator functions
FUNCTIONS_BASE_URL=https://us-central1-aeiv-sponsors.cloudfunctions.net npm run smoke
```

Fails when the health endpoint or build artifact is broken.

## What every change must verify

- [ ] `npm run typecheck`
- [ ] `npm run lint` and `npm run format:check`
- [ ] `npm test` (web) and `npm --prefix functions run test`
- [ ] `npm run build` and `npm --prefix functions run build`
- [ ] Feature toggle + module toggle behavior
- [ ] Permission boundaries (attempt denied paths)
- [ ] Loading / empty / error states
- [ ] Responsive layout and keyboard navigation
