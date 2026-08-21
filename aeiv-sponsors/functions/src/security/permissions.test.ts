import { describe, expect, it } from 'vitest'
import { ROLE_PERMISSIONS, rolesGrantPermission } from './permissions'

describe('backend rolesGrantPermission', () => {
  it('gives org.owner every module permission', () => {
    const all = Object.values(ROLE_PERMISSIONS).flat()
    for (const permission of all) {
      expect(rolesGrantPermission(['org.owner'], permission)).toBe(true)
    }
  })

  it('keeps sponsors.reporting out of reach of non-owners', () => {
    expect(rolesGrantPermission(['org.admin'], 'sponsors.reporting')).toBe(false)
    expect(rolesGrantPermission(['org.member'], 'sponsors.reporting')).toBe(false)
    expect(rolesGrantPermission(['public'], 'sponsors.reporting')).toBe(false)
  })

  it('denies unauthorized mutations to public users', () => {
    expect(rolesGrantPermission(['public'], 'sponsors.view')).toBe(false)
    expect(rolesGrantPermission(['public'], 'sponsors.create')).toBe(false)
    expect(rolesGrantPermission(['public'], 'sponsors.delete')).toBe(false)
  })

  it('denies unknown roles', () => {
    expect(rolesGrantPermission(['hacker'], 'sponsors.view')).toBe(false)
  })
})
