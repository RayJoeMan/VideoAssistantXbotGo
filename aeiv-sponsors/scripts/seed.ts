/**
 * Seed script — writes demo data into the Firestore EMULATOR only.
 *
 * Usage:  npm run seed   (with `npm run emulators` already running)
 *
 * Safety: connects exclusively to the emulator host (FIRESTORE_EMULATOR_HOST),
 * so it can never touch a real project.
 */
process.env.FIRESTORE_EMULATOR_HOST = '127.0.0.1:8080'

import { initializeApp } from 'firebase-admin/app'
import { initializeFirestore } from 'firebase-admin/firestore'

const PROJECT_ID = 'demo-aeiv-sponsors'
const TENANT_ID = 'demo-tenant'

const app = initializeApp({ projectId: PROJECT_ID })
const db = initializeFirestore(app)

/** Firestore rejects undefined values — drop them explicitly. */
function pickDefined<T extends Record<string, unknown>>(obj: T): Record<string, unknown> {
  return Object.fromEntries(Object.entries(obj).filter(([, value]) => value !== undefined))
}

async function main(): Promise<void> {
  const now = new Date().toISOString()

  // 1) Tenant module configuration (module toggle + feature flags + display).
  await db.doc(`tenants/${TENANT_ID}/moduleConfig/module`).set({
    moduleEnabled: true,
    features: {
      publicPage: true,
      inquiryForm: true,
      homepage: false,
      footer: false,
      analytics: true,
      notifications: false,
      payments: false,
    },
    displayName: 'Our Sponsors',
    tagline: 'Proudly supported by our community partners',
    heroText: 'Support the businesses that support our teams.',
    contactEmail: 'sponsors@demo.example',
    inquiryEnabled: true,
    maxSponsorsPerPage: 24,
  })

  // 2) Sample sponsors (public + admin documents kept separate).
  const sponsors = [
    {
      name: 'Guardian Elite Lacrosse',
      tier: 'platinum',
      tagline: 'Proudly supporting youth lacrosse',
      websiteUrl: 'https://example.com/guardian',
      sortOrder: 0,
      published: true,
      status: 'active',
    },
    {
      name: 'Acme Sporting Goods',
      tier: 'gold',
      tagline: 'Gear for every player',
      websiteUrl: 'https://example.com/acme',
      sortOrder: 1,
      published: true,
      status: 'active',
    },
    {
      name: 'Lakeside Dental',
      tier: 'silver',
      tagline: 'Healthy smiles',
      sortOrder: 2,
      published: true,
      status: 'active',
    },
    {
      name: 'Draft Sponsor (unpublished)',
      tier: 'bronze',
      sortOrder: 3,
      published: false,
      status: 'pending',
    },
  ]

  for (const sponsor of sponsors) {
    const id = sponsor.name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/(^-|-$)/g, '')
    await db.doc(`tenants/${TENANT_ID}/sponsorPublic/${id}`).set(
      pickDefined({
        id,
        tenantId: TENANT_ID,
        name: sponsor.name,
        tier: sponsor.tier,
        tagline: sponsor.tagline ?? '',
        websiteUrl: sponsor.websiteUrl,
        description: '',
        sortOrder: sponsor.sortOrder,
        published: sponsor.published,
        createdAt: now,
        updatedAt: now,
      }),
    )
    await db.doc(`tenants/${TENANT_ID}/sponsorAdmin/${id}`).set(
      pickDefined({
        id,
        tenantId: TENANT_ID,
        status: sponsor.status,
        contactName: '',
        notes: '',
        createdAt: now,
        updatedAt: now,
      }),
    )
  }

  // 3) Demo admin member (for local login tests via the Auth emulator).
  // Roles grant every module permission. The uid below must match the
  // emulator user created manually (or by a future auth trigger).
  await db.doc(`tenants/${TENANT_ID}/members/demo-admin`).set({
    roles: ['org.owner'],
    email: 'admin@demo.example',
    displayName: 'Demo Admin',
  })

  console.log(`Seeded project "${PROJECT_ID}" tenant "${TENANT_ID}" (${sponsors.length} sponsors).`)
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error('Seed failed:', err)
    process.exit(1)
  })
