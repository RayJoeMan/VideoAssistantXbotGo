# Installation — AEIV Sponsors Module

## Prerequisites

- Node.js ≥ 20
- npm ≥ 10
- A Firebase account (the module owner) for the production project
- (Optional) Google Chrome for Playwright e2e

## 1. Install

```bash
cd aeiv-sponsors
npm install
```

## 2. Environment

Copy the example and adjust:

```bash
cp .env.example .env.local
```

`VITE_USE_EMULATORS=true` (default) points every Firebase SDK at the local
emulator suite, so no real credentials are needed for development.

## 3. Firebase login (one-time)

The module's production project is bound to the owner account
(`joermnd@gmail.com`):

```bash
npx firebase login
npx firebase login:list   # verify the account
```

If the production project does not exist yet:

```bash
npx firebase projects:create aeiv-sponsors
npx firebase use aeiv-sponsors
```

> The `.firebaserc` aliases `dev`/`prod` to `aeiv-sponsors` and `default` to the
> emulator project `demo-aeiv-sponsors`, so emulators never touch production.

## 4. Run locally (emulator-first)

```bash
# Terminal 1 — emulators
npm run emulators          # Auth :9099, Firestore :8080, Functions :5001, Storage :9199, UI :4000

# Terminal 2 — web app
npm run dev                # http://localhost:5173

# Terminal 3 — seed demo data (optional)
npm run seed
```

## 5. Verify

```bash
npm run typecheck
npm run lint
npm run format:check
npm test
npm run build
npm --prefix functions run build
```

## 6. End-to-end

```bash
npm run test:e2e           # requires browsers: npx playwright install chromium
```

## Troubleshooting

See `docs/troubleshooting.md`.
