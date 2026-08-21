import { useEffect, useMemo, useState } from 'react'
import { doc, onSnapshot } from 'firebase/firestore'
import { getFirebaseFirestore } from '../config/firebase'
import { PUBLIC_ROLE, rolesGrantPermission } from '../utils/permissions'
import { useAuth } from './useAuth'

export interface MemberRoles {
  roles: string[]
  loading: boolean
  hasPermission: (permission: string) => boolean
}

/**
 * Resolves the signed-in user's roles within a tenant by subscribing to
 * `tenants/{tenantId}/members/{uid}`. Unauthenticated callers get the `public`
 * role. Client-side only — the backend re-validates everything.
 */
export function usePermissions(tenantId: string): MemberRoles {
  const { user } = useAuth()
  const [roles, setRoles] = useState<string[]>(() => (user ? [] : [PUBLIC_ROLE]))
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!user) {
      setRoles([PUBLIC_ROLE])
      setLoading(false)
      return
    }
    const db = getFirebaseFirestore()
    const memberRef = doc(db, `tenants/${tenantId}/members/${user.uid}`)
    setLoading(true)
    const unsubscribe = onSnapshot(
      memberRef,
      (snapshot) => {
        const data = snapshot.exists() ? (snapshot.data() as { roles?: string[] }) : undefined
        setRoles(data?.roles?.length ? data.roles : [PUBLIC_ROLE])
        setLoading(false)
      },
      () => {
        setRoles([PUBLIC_ROLE])
        setLoading(false)
      },
    )
    return unsubscribe
  }, [user, tenantId])

  const hasPermission = useMemo(
    () => (permission: string) => rolesGrantPermission(roles, permission),
    [roles],
  )

  return { roles, loading, hasPermission }
}
