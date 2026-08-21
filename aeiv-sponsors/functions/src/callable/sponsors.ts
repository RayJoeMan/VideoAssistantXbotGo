import { randomUUID } from 'node:crypto'
import { getFirestore } from 'firebase-admin/firestore'
import { HttpsError, onCall } from 'firebase-functions/v2/https'
import {
  createSponsorInputSchema,
  deleteSponsorInputSchema,
  sponsorsListInputSchema,
  updateSponsorInputSchema,
  type PublicSponsor,
  type SponsorAdmin,
} from '../schemas/sponsor'
import { requirePermission } from '../security/auth'
import { writeAuditLog, sanitizeSponsorChanges } from '../security/audit'
import { logInfo } from '../security/logging'
import { parseInput } from '../security/validation'
import { pickDefined } from '../security/sanitize'

const PUBLIC_PATH = (tenantId: string) => `tenants/${tenantId}/sponsorPublic`
const ADMIN_PATH = (tenantId: string) => `tenants/${tenantId}/sponsorAdmin`

/**
 * Admin sponsor listing — joins public + admin documents.
 * Requires sponsors.view.
 */
export const aeiv_sponsorsList = onCall(async (request) => {
  const input = parseInput(sponsorsListInputSchema, request.data)
  const context = await requirePermission(request, input.tenantId, 'sponsors.view')
  const db = getFirestore()

  const [publicSnap, adminSnap] = await Promise.all([
    db.collection(PUBLIC_PATH(input.tenantId)).orderBy('sortOrder', 'asc').get(),
    db.collection(ADMIN_PATH(input.tenantId)).get(),
  ])

  const adminById = new Map<string, SponsorAdmin>()
  for (const doc of adminSnap.docs) {
    adminById.set(doc.id, doc.data() as SponsorAdmin)
  }

  const sponsors = publicSnap.docs.map((doc) => {
    const pub = doc.data() as PublicSponsor
    const admin = adminById.get(doc.id)
    return {
      public: pub,
      admin:
        admin ??
        ({
          id: doc.id,
          tenantId: input.tenantId,
          status: 'pending',
          notes: '',
          createdAt: pub.createdAt,
          updatedAt: pub.updatedAt,
        } as SponsorAdmin),
    }
  })

  logInfo({ ...context, operation: 'sponsors.list' }, 'Listed sponsors', {
    tenantId: input.tenantId,
    count: sponsors.length,
  })
  return { sponsors }
})

/** Create sponsor (public + admin docs). Requires sponsors.create. */
export const aeiv_sponsorsCreate = onCall(async (request) => {
  const input = parseInput(createSponsorInputSchema, request.data)
  const context = await requirePermission(request, input.tenantId, 'sponsors.create')
  const db = getFirestore()

  const now = new Date().toISOString()
  const id = randomUUID()

  const publicDoc: PublicSponsor = {
    id,
    tenantId: input.tenantId,
    name: input.public.name,
    tier: input.public.tier,
    websiteUrl: input.public.websiteUrl,
    logoUrl: input.public.logoUrl,
    tagline: input.public.tagline ?? '',
    description: input.public.description ?? '',
    sortOrder: input.public.sortOrder ?? 0,
    published: input.public.published ?? false,
    createdAt: now,
    updatedAt: now,
  }

  const adminDoc: SponsorAdmin = {
    id,
    tenantId: input.tenantId,
    status: input.admin?.status ?? 'pending',
    contactName: input.admin?.contactName,
    contactEmail: input.admin?.contactEmail,
    contactPhone: input.admin?.contactPhone,
    contractStart: input.admin?.contractStart,
    contractEnd: input.admin?.contractEnd,
    monthlyAmount: input.admin?.monthlyAmount,
    notes: input.admin?.notes ?? '',
    createdAt: now,
    updatedAt: now,
  }

  await db
    .doc(`${PUBLIC_PATH(input.tenantId)}/${id}`)
    .set(pickDefined({ ...publicDoc }) as PublicSponsor)
  await db
    .doc(`${ADMIN_PATH(input.tenantId)}/${id}`)
    .set(pickDefined({ ...adminDoc }) as SponsorAdmin)

  await writeAuditLog(context, {
    actor: context.uid,
    action: 'sponsor.create',
    resourceType: 'sponsor',
    resourceId: id,
    changes: sanitizeSponsorChanges(undefined, publicDoc),
  })

  logInfo({ ...context, operation: 'sponsors.create' }, 'Created sponsor', {
    tenantId: input.tenantId,
    sponsorId: id,
  })
  return { sponsor: { public: publicDoc, admin: adminDoc } }
})

/** Update sponsor (partial, both docs). Requires sponsors.edit. */
export const aeiv_sponsorsUpdate = onCall(async (request) => {
  const input = parseInput(updateSponsorInputSchema, request.data)
  const context = await requirePermission(request, input.tenantId, 'sponsors.edit')
  const db = getFirestore()

  const publicRef = db.doc(`${PUBLIC_PATH(input.tenantId)}/${input.sponsorId}`)
  const adminRef = db.doc(`${ADMIN_PATH(input.tenantId)}/${input.sponsorId}`)

  const [publicSnap, adminSnap] = await Promise.all([publicRef.get(), adminRef.get()])
  if (!publicSnap.exists) {
    throw new HttpsError('not-found', 'Sponsor not found.')
  }

  const beforePublic = publicSnap.data() as PublicSponsor
  const beforeAdmin = adminSnap.exists ? (adminSnap.data() as SponsorAdmin) : undefined
  const now = new Date().toISOString()

  const afterPublic: PublicSponsor = {
    ...beforePublic,
    ...input.public,
    updatedAt: now,
  }
  const afterAdmin: SponsorAdmin = {
    id: input.sponsorId,
    tenantId: input.tenantId,
    status: beforeAdmin?.status ?? 'pending',
    notes: beforeAdmin?.notes ?? '',
    ...input.admin,
    createdAt: beforeAdmin?.createdAt ?? now,
    updatedAt: now,
  }

  await publicRef.set(pickDefined({ ...afterPublic }) as PublicSponsor)
  await adminRef.set(pickDefined({ ...afterAdmin }) as SponsorAdmin)

  await writeAuditLog(context, {
    actor: context.uid,
    action: 'sponsor.update',
    resourceType: 'sponsor',
    resourceId: input.sponsorId,
    changes: sanitizeSponsorChanges(beforePublic, afterPublic),
  })

  logInfo({ ...context, operation: 'sponsors.update' }, 'Updated sponsor', {
    tenantId: input.tenantId,
    sponsorId: input.sponsorId,
  })
  return { sponsor: { public: afterPublic, admin: afterAdmin } }
})

/** Delete sponsor (both docs) + audit. Requires sponsors.delete. */
export const aeiv_sponsorsDelete = onCall(async (request) => {
  const input = parseInput(deleteSponsorInputSchema, request.data)
  const context = await requirePermission(request, input.tenantId, 'sponsors.delete')
  const db = getFirestore()

  await db.doc(`${PUBLIC_PATH(input.tenantId)}/${input.sponsorId}`).delete()
  await db.doc(`${ADMIN_PATH(input.tenantId)}/${input.sponsorId}`).delete()

  await writeAuditLog(context, {
    actor: context.uid,
    action: 'sponsor.delete',
    resourceType: 'sponsor',
    resourceId: input.sponsorId,
  })

  logInfo({ ...context, operation: 'sponsors.delete' }, 'Deleted sponsor', {
    tenantId: input.tenantId,
    sponsorId: input.sponsorId,
  })
  return { deleted: true }
})
