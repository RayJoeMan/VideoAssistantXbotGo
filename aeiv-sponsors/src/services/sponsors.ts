import { collection, doc, getDoc, getDocs, orderBy, query } from 'firebase/firestore'
import { getFirebaseFirestore } from '../config/firebase'
import type { PublicSponsor } from '../schemas/sponsor'
import { functionsApi } from './functions'

/**
 * Sponsor data access.
 *
 * Public reads hit Firestore directly (rules allow public reads of
 * `tenants/{tenantId}/sponsors/public`). All writes and admin reads go through
 * callable functions where authorization and tenant isolation are enforced.
 */

export function publicSponsorsCollectionPath(tenantId: string): string {
  return `tenants/${tenantId}/sponsorPublic`
}

export function adminSponsorsCollectionPath(tenantId: string): string {
  return `tenants/${tenantId}/sponsorAdmin`
}

export async function listPublicSponsors(tenantId: string): Promise<PublicSponsor[]> {
  const db = getFirebaseFirestore()
  const sponsorsRef = collection(db, publicSponsorsCollectionPath(tenantId))
  const q = query(sponsorsRef, orderBy('sortOrder', 'asc'))
  const snapshot = await getDocs(q)
  return snapshot.docs
    .map((d) => d.data() as PublicSponsor)
    .filter((sponsor) => sponsor.published === true)
}

export async function getPublicSponsor(
  tenantId: string,
  sponsorId: string,
): Promise<PublicSponsor | null> {
  const db = getFirebaseFirestore()
  const snapshot = await getDoc(doc(db, publicSponsorsCollectionPath(tenantId), sponsorId))
  if (!snapshot.exists()) return null
  return snapshot.data() as PublicSponsor
}

export const adminSponsorsApi = {
  list(tenantId: string) {
    return functionsApi.listSponsors({ tenantId })
  },
  create(input: Parameters<typeof functionsApi.createSponsor>[0]) {
    return functionsApi.createSponsor(input)
  },
  update(input: Parameters<typeof functionsApi.updateSponsor>[0]) {
    return functionsApi.updateSponsor(input)
  },
  remove(input: Parameters<typeof functionsApi.deleteSponsor>[0]) {
    return functionsApi.deleteSponsor(input)
  },
}
