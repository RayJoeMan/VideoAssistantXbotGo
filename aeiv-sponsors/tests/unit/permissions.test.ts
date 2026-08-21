import { describe, expect, it } from 'vitest'
import { publicRoles, rolesGrantPermission } from '../../src/utils/permissions'

describe('rolesGrantPermission (client-side RBAC view)', () => {
  it('grants the public role no module permissions (public access is rule-based)', () => {
    expect(rolesGrantPermission(publicRoles(), 'sponsors.view')).toBe(false)
    expect(rolesGrantPermission(publicRoles(), 'sponsors.create')).toBe(false)
    expect(rolesGrantPermission(publicRoles(), 'sponsors.delete')).toBe(false)
  })

  it('grants org.member view but not mutations', () => {
    expect(rolesGrantPermission(['org.member'], 'sponsors.view')).toBe(true)
    expect(rolesGrantPermission(['org.member'], 'sponsors.edit')).toBe(false)
    expect(rolesGrantPermission(['org.member'], 'sponsors.settings')).toBe(false)
  })

  it('grants org.admin everything except reporting', () => {
    expect(rolesGrantPermission(['org.admin'], 'sponsors.create')).toBe(true)
    expect(rolesGrantPermission(['org.admin'], 'sponsors.delete')).toBe(true)
    expect(rolesGrantPermission(['org.admin'], 'sponsors.settings')).toBe(true)
    expect(rolesGrantPermission(['org.admin'], 'sponsors.reporting')).toBe(false)
  })

  it('grants org.owner every module permission', () => {
    const all = [
      'sponsors.view',
      'sponsors.create',
      'sponsors.edit',
      'sponsors.delete',
      'sponsors.settings',
      'sponsors.reporting',
    ]
    for (const permission of all) {
      expect(rolesGrantPermission(['org.owner'], permission)).toBe(true)
    }
  })

  it('denies unknown roles', () => {
    expect(rolesGrantPermission(['nope'], 'sponsors.view')).toBe(false)
    expect(rolesGrantPermission([], 'sponsors.view')).toBe(false)
  })
})
