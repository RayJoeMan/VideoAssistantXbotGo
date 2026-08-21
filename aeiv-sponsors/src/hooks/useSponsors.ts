import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { PublicSponsor, SponsorAdminView } from '../schemas/sponsor'
import { adminSponsorsApi, getPublicSponsor, listPublicSponsors } from '../services/sponsors'
import { functionsApi } from '../services/functions'

export const publicSponsorsKey = (tenantId: string) => ['sponsors', 'public', tenantId] as const
export const adminSponsorsKey = (tenantId: string) => ['sponsors', 'admin', tenantId] as const

/** Public directory (Firestore reads, rules-gated). */
export function usePublicSponsors(tenantId: string, enabled = true) {
  return useQuery({
    queryKey: publicSponsorsKey(tenantId),
    queryFn: () => listPublicSponsors(tenantId),
    enabled: enabled && Boolean(tenantId),
  })
}

export function usePublicSponsor(tenantId: string, sponsorId: string | undefined) {
  return useQuery({
    queryKey: ['sponsors', 'public', tenantId, sponsorId],
    queryFn: () => getPublicSponsor(tenantId, sponsorId ?? ''),
    enabled: Boolean(tenantId && sponsorId),
  })
}

/** Admin CRUD (callable functions, permission-enforced server-side). */
export function useAdminSponsors(tenantId: string, enabled = true) {
  return useQuery({
    queryKey: adminSponsorsKey(tenantId),
    queryFn: () => adminSponsorsApi.list(tenantId),
    enabled: enabled && Boolean(tenantId),
    select: (data) => data.sponsors,
  })
}

export function useCreateSponsor(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: functionsApi.createSponsor,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: publicSponsorsKey(tenantId) })
      void queryClient.invalidateQueries({ queryKey: adminSponsorsKey(tenantId) })
    },
  })
}

export function useUpdateSponsor(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: functionsApi.updateSponsor,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: publicSponsorsKey(tenantId) })
      void queryClient.invalidateQueries({ queryKey: adminSponsorsKey(tenantId) })
    },
  })
}

export function useDeleteSponsor(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: functionsApi.deleteSponsor,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: publicSponsorsKey(tenantId) })
      void queryClient.invalidateQueries({ queryKey: adminSponsorsKey(tenantId) })
    },
  })
}

export function useCreateInquiry() {
  return useMutation({ mutationFn: functionsApi.createInquiry })
}

export type { PublicSponsor, SponsorAdminView }
