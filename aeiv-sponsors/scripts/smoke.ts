/**
 * Smoke test — verifies critical module functionality after deployment.
 *
 * Exits non-zero when critical functionality is broken, so it can gate
 * deployment validation. Point FUNCTIONS_BASE_URL at the deployed/emulated
 * functions host.
 *
 * Usage:
 *   FUNCTIONS_BASE_URL=https://us-central1-aeiv-sponsors.cloudfunctions.net npm run smoke
 *   npm run smoke   # defaults to the local emulator
 */
const FUNCTIONS_BASE_URL =
  process.env.FUNCTIONS_BASE_URL ?? 'http://127.0.0.1:5001/demo-aeiv-sponsors/us-central1'

interface Check {
  name: string
  ok: boolean
  detail?: string
}

async function main(): Promise<void> {
  const checks: Check[] = []

  // 1) Health endpoint responds and reports ok.
  try {
    const response = await fetch(`${FUNCTIONS_BASE_URL}/apiHealth`)
    const body = (await response.json()) as { status?: string; module?: string }
    checks.push({
      name: 'health',
      ok: response.ok && body.status === 'ok' && body.module === 'aeiv-sponsors',
      detail: `status=${response.status} body=${JSON.stringify(body)}`,
    })
  } catch (err) {
    checks.push({ name: 'health', ok: false, detail: String(err) })
  }

  // 2) Module manifest is importable/built (static sanity check).
  try {
    const { moduleManifest } = await import('../module.manifest')
    checks.push({
      name: 'manifest',
      ok: moduleManifest.id === 'aeiv-sponsors' && moduleManifest.version.length > 0,
      detail: `id=${moduleManifest.id} v${moduleManifest.version}`,
    })
  } catch (err) {
    checks.push({ name: 'manifest', ok: false, detail: String(err) })
  }

  // 3) Build artifact exists (production build produced dist/index.html).
  const fs = await import('node:fs')
  const path = await import('node:path')
  const distIndex = path.resolve(process.cwd(), 'dist/index.html')
  checks.push({
    name: 'web-build',
    ok: fs.existsSync(distIndex),
    detail: distIndex,
  })

  const failed = checks.filter((check) => !check.ok)
  console.table(checks)
  if (failed.length > 0) {
    console.error(`SMOKE FAILED (${failed.length}/${checks.length} checks)`)
    process.exit(1)
  }
  console.log(`SMOKE PASSED (${checks.length}/${checks.length} checks)`)
}

main().catch((err) => {
  console.error('Smoke test crashed:', err)
  process.exit(1)
})
