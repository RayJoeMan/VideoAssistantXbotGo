# AEIV Sponsors Module

A multi-tenant sponsor directory and inquiry module for the AEIV modular
website platform. Independently deployable; integrates into host websites via
`module.manifest.ts` and tenant configuration.

> First implementation tenant: **Guardian Elite Lacrosse** (supplied as
> configuration only — never hard-coded).

## Status

| Phase | Deliverable                                                                                                         | Status    |
| ----- | ------------------------------------------------------------------------------------------------------------------- | --------- |
| 0     | Discovery (`docs/discovery.md`)                                                                                     | ✅        |
| 1     | Architecture (`docs/architecture.md` + related)                                                                     | ✅        |
| 2     | Scaffold + Firebase wiring                                                                                          | ✅        |
| 3–13  | Data layer, backend, admin, public UI, integration, reporting, testing, security review, performance, docs, release | ⏳ queued |

## Quick start (emulator-first)

```bash
npm install

# 1) Authenticate Firebase as the module owner (one-time, browser OAuth)
npx firebase login

# 2) Start the emulator suite (demo project — never touches production)
npm run emulators

# 3) In another terminal, start the web app (auto-connects to emulators)
npm run dev
# → http://localhost:5173

# 4) Seed demo data (tenant config + sample sponsors)
npm run seed
```

## Scripts

| Command                                       | Purpose                                |
| --------------------------------------------- | -------------------------------------- |
| `npm run dev`                                 | Vite dev server (:5173)                |
| `npm run build`                               | Type-check + production build          |
| `npm run typecheck` / `lint` / `format:check` | Quality gates                          |
| `npm test`                                    | Vitest unit tests                      |
| `npm run test:e2e`                            | Playwright end-to-end tests            |
| `npm run emulators`                           | Firebase Emulator Suite (demo project) |
| `npm run seed`                                | Seed emulator demo data                |
| `npm run smoke`                               | Post-deploy smoke checks               |
| `npm run deploy`                              | Deploy to production (`aeiv-sponsors`) |

## Documentation

- `docs/architecture.md` — system, component, tenant architecture
- `docs/data-model.md` — entities, relationships, indexes, retention
- `docs/security.md` — threat model and controls
- `docs/api.md` — function APIs and error model
- `docs/permissions.md` — RBAC model
- `docs/installation.md`, `docs/configuration.md`, `docs/deployment.md`,
  `docs/testing.md`, `docs/troubleshooting.md`
- `AGENTS.md` — guidance for AI agents working in this repo
- `module.manifest.ts` — the AEIV module contract

## License

UNLICENSED (proprietary module).
