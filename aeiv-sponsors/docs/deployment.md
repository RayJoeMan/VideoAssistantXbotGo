# Deployment — AEIV Sponsors Module

## Environments

| Environment | Firebase project     | Purpose                                           |
| ----------- | -------------------- | ------------------------------------------------- |
| Emulator    | `demo-aeiv-sponsors` | Local development (default alias)                 |
| Dev / Prod  | `aeiv-sponsors`      | Real module deployment (owner: joermnd@gmail.com) |

`.firebaserc` aliases keep them separate; `firebase.json` targets functions,
firestore rules/indexes, and storage rules.

## Prerequisites

1. `npx firebase login` (module owner account).
2. `npx firebase use aeiv-sponsors` (or pass `--project`).
3. If the project does not exist: `npx firebase projects:create aeiv-sponsors`.
4. Enable required APIs in the Firebase console: Authentication (Email/Password,
   Google), Firestore, Storage, Functions (Cloud Scheduler for the scheduled
   function), App Check.

## Build

```bash
npm ci
npm run build                  # web
npm --prefix functions run build
```

## Deploy

```bash
npm run deploy                 # all (functions, rules, storage)
npm run deploy:rules           # rules only
npm run deploy:functions       # functions only
```

All deploys target `aeiv-sponsors`; CI runs quality gates first (see
`.github/workflows/ci.yml`) and production deployment should not occur if
critical tests fail.

## Post-deploy smoke

```bash
FUNCTIONS_BASE_URL=https://us-central1-aeiv-sponsors.cloudfunctions.net npm run smoke
```

The smoke test fails (non-zero) when the health endpoint is broken or the web
build artifact is missing.

## App Check

App Check should be enabled for production to harden callables against abuse
(attestation providers: reCAPTCHA Enterprise for web). Enabling it requires
registering the app and adding a provider — planned for a later phase. Until
then, rate limiting + honeypot protect the public path.

## Rollback

1. **Functions**: redeploy the previous release —
   `npx firebase functions:delete <fn> --project aeiv-sponsors` for individual
   functions, or redeploy from the previous tag:
   ```bash
   git checkout <previous-tag>
   npm ci && npm --prefix functions run build
   npm run deploy
   ```
2. **Rules**: rules are versioned in git; redeploy `firebase/firestore.rules`
   from the previous tag (`npm run deploy:rules`). Rule changes take effect
   immediately — review before deploying.
3. **Web**: host the built `dist/` from the previous tag (static hosting or
   wherever the host site serves the module).
4. **Data**: no destructive migrations in v0.1. If a bad scheduled cleanup runs,
   restore audit logs from backups if enabled; otherwise the impact is limited
   to the retention window (90 days).
