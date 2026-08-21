# Troubleshooting — AEIV Sponsors Module

## Dev server / build

| Symptom                                 | Cause / fix                                                                                              |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `vite` won't start                      | Node < 20 or missing `npm install`. Check `node --version`.                                              |
| Type errors in `module.manifest.ts`     | The manifest imports `src/schemas/moduleConfig` — keep the file path stable (it is the module contract). |
| `tsc` complains about `import.meta.env` | Ensure `"types": ["vite/client", "node"]` in `tsconfig.json`.                                            |
| Lint errors after editing               | Run `npm run lint`; auto-fix with `npx eslint . --fix`; keep imports grouped.                            |

## Firebase / emulator

| Symptom                                                     | Cause / fix                                                                                                                                                                                            |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `firebase: command not found`                               | Use `npx firebase ...` or install `firebase-tools` globally.                                                                                                                                           |
| Emulator fails to start                                     | Ports in use (9099/8080/5001/9199/4000). Kill the stale process or change ports in `firebase.json`.                                                                                                    |
| `FirebaseError: ... project 'aeiv-sponsors' does not exist` | You are targeting the real project before it is created. For local dev run `npm run emulators` (uses `demo-aeiv-sponsors`); create the real project with `npx firebase projects:create aeiv-sponsors`. |
| Auth emulator "already connected"                           | Only call the emulator connect helpers once (see `src/config/firebase.ts`); the app already handles this.                                                                                              |
| Seed script can't connect                                   | Start emulators first; seed targets `FIRESTORE_EMULATOR_HOST=127.0.0.1:8080` only.                                                                                                                     |
| Firestore index errors in emulator                          | The emulator enforces composite indexes; add the query pattern to `firebase/firestore.indexes.json` and restart the emulator.                                                                          |
| Functions `process is undefined`                            | Only occurs in browser bundling — functions code is Node-only; don't import `functions/src` from the web app.                                                                                          |

## Auth

| Symptom                            | Cause / fix                                                                                                                                                                     |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Sign-in fails in the browser       | Emulator must be running and `VITE_USE_EMULATORS=true` (default).                                                                                                               |
| No member roles → "Not authorized" | Seed/create a member doc: `tenants/{tenantId}/members/{uid}` with `roles: ["org.owner"]`. In the emulator, sign in and use that uid, or run `npm run seed` (adds `demo-admin`). |

## Data / permissions

| Symptom                                 | Cause / fix                                                                                                                                     |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Public page shows not-found             | Module config missing/disabled for the tenant — set `moduleEnabled: true` in `tenants/{tenantId}/moduleConfig/module` (admin Settings or seed). |
| Sponsors not visible on the public page | They must have `published: true` (public doc). Admin page shows all.                                                                            |
| Admin ops return `permission-denied`    | The caller's member doc lacks the role for the permission; grant `org.owner`/`org.admin` roles.                                                 |
| Admin ops return `failed-precondition`  | The module is disabled for the tenant (module toggle is enforced server-side).                                                                  |

## E2E / CI

| Symptom                            | Cause / fix                                                                                                                                  |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Playwright can't launch            | `npx playwright install --with-deps chromium`.                                                                                               |
| E2E home test fails on navigation  | Without emulators the module config fetch errors, but defaults keep the module enabled; ensure `VITE_USE_EMULATORS` matches the environment. |
| CI `firebase emulators:exec` hangs | Give it `--only firestore` and a project flag; see `.github/workflows/ci.yml`.                                                               |

## Logging

- Backend logs are structured JSON (`functions/src/security/logging.ts`).
  Search Cloud Logging / emulator output for `"module":"aeiv-sponsors"` plus
  the `operation` field.
- Client analytics events print to the console in dev (`src/analytics/events.ts`).
