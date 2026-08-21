# Security tests (scaffold)

Security-rule and security-function tests **explicitly attempt unauthorized
access** against the Firebase Emulator Suite and assert that every attempt is
denied.

See `tests/integration/README.md` for the run prerequisites and the planned
unauthorized-access matrix (unauthenticated calls, permission-denied, tenant
escape, server-only collection writes, module-disabled behavior).

Coverage is filled out in the Phase 9 testing pass using
`@firebase/rules-unit-testing` and the imported `firebase/firestore.rules`.
