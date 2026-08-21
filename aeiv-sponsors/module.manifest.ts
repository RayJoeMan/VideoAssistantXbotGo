/**
 * AEIV Sponsors Module — Module Manifest
 *
 * This manifest is the contract between the AEIV platform host website and the
 * Sponsors module. Host websites discover, configure, and gate this module
 * through this file. No customer-specific information lives here — everything
 * tenant-specific is supplied via tenant configuration at runtime.
 *
 * The module is fully toggleable (module.enabled) and its individual
 * capabilities are gated by feature flags. Both are enforced in authorization
 * on the backend, not merely by hiding UI.
 */
import type { z } from 'zod'
import { moduleConfigurationSchema } from './src/schemas/moduleConfig'

/** Schema keys allowed in the tenant configuration object (from zod schema). */
export type ModuleConfiguration = z.infer<typeof moduleConfigurationSchema>

export interface ModuleRoute {
  /** Public URL path owned by the host website, e.g. /sponsors */
  path: string
  label: string
  /** Component name resolved by the host's router. */
  element: string
  /** Whether the route requires authentication. */
  requiresAuth: boolean
  /** Minimum permission required (undefined = public). */
  permission?: string
}

export interface ModuleAdminRoute {
  path: string
  label: string
  permission: string
}

export interface ModuleNavigationItem {
  label: string
  href: string
  /** When set, the item is only rendered for users holding this permission. */
  permission?: string
}

export interface ModuleFeatureFlag {
  description: string
  /** Default state when the tenant has not explicitly configured the flag. */
  defaultEnabled: boolean
}

export interface ModuleHealthCheck {
  /** HTTP endpoint (functions) that reports module health. */
  path: string
}

export interface ModuleManifest {
  id: string
  name: string
  description: string
  /** Semantic version — MAJOR.MINOR.PATCH */
  version: string
  /** Compatibility version of the AEIV Module SDK this module targets. */
  compatibilityVersion: number
  /** API version exposed by this module's backend. */
  apiVersion: string
  /** Whether the module is enabled by default for new tenants. */
  defaultEnabled: boolean
  routes: ModuleRoute[]
  adminRoutes: ModuleAdminRoute[]
  navigation: ModuleNavigationItem[]
  /** RBAC permissions in the form [module].[resource].[action]. */
  permissions: string[]
  /** Role → permissions mapping (org-level roles defined by the platform). */
  roles: Record<string, string[]>
  features: Record<string, ModuleFeatureFlag>
  /** Tenant configuration schema (Zod), shared with the backend for validation. */
  configuration: { properties: string[]; required: string[] }
  /** Other AEIV modules this module depends on. */
  dependencies: string[]
  healthCheck: ModuleHealthCheck
}

export const moduleManifest: ModuleManifest = {
  id: 'aeiv-sponsors',
  name: 'Sponsors',
  description:
    'Multi-tenant sponsor directory with public listings, an inquiry form, and a permission-gated admin interface.',
  version: '0.1.0',
  compatibilityVersion: 1,
  apiVersion: 'v1',
  defaultEnabled: true,
  routes: [
    { path: '/sponsors', label: 'Sponsors', element: 'SponsorsPage', requiresAuth: false },
    {
      path: '/sponsors/:sponsorId',
      label: 'Sponsor',
      element: 'SponsorDetailPage',
      requiresAuth: false,
    },
  ],
  adminRoutes: [
    { path: '/admin/sponsors', label: 'Sponsors', permission: 'sponsors.view' },
    { path: '/admin/sponsors/new', label: 'New Sponsor', permission: 'sponsors.create' },
    { path: '/admin/sponsors/:sponsorId', label: 'Edit Sponsor', permission: 'sponsors.edit' },
    { path: '/admin/sponsors/settings', label: 'Settings', permission: 'sponsors.settings' },
    { path: '/admin/sponsors/reporting', label: 'Reporting', permission: 'sponsors.reporting' },
  ],
  navigation: [{ label: 'Sponsors', href: '/sponsors' }],
  permissions: [
    'sponsors.view',
    'sponsors.create',
    'sponsors.edit',
    'sponsors.delete',
    'sponsors.settings',
    'sponsors.reporting',
  ],
  roles: {
    'org.owner': [
      'sponsors.view',
      'sponsors.create',
      'sponsors.edit',
      'sponsors.delete',
      'sponsors.settings',
      'sponsors.reporting',
    ],
    'org.admin': [
      'sponsors.view',
      'sponsors.create',
      'sponsors.edit',
      'sponsors.delete',
      'sponsors.settings',
    ],
    'org.member': ['sponsors.view'],
    /** Public access is handled by Firestore rules, not RBAC. */
    public: [],
  },
  features: {
    publicPage: {
      description: 'Public sponsor directory page.',
      defaultEnabled: true,
    },
    inquiryForm: {
      description: 'Public inquiry form routed to the tenant.',
      defaultEnabled: true,
    },
    homepage: {
      description: 'Homepage integration slot (sponsor carousel).',
      defaultEnabled: false,
    },
    footer: {
      description: 'Footer integration slot.',
      defaultEnabled: false,
    },
    analytics: {
      description: 'Track business events (impressions, clicks, inquiries).',
      defaultEnabled: false,
    },
    notifications: {
      description: 'Email notifications to tenant admins on new inquiries.',
      defaultEnabled: false,
    },
    payments: {
      description: 'Sponsorship payments (external processor).',
      defaultEnabled: false,
    },
  },
  configuration: {
    properties: Object.keys(moduleConfigurationSchema.shape),
    required: ['displayName'],
  },
  dependencies: ['aeiv-core', 'aeiv-auth'],
  healthCheck: { path: '/api/health' },
}

export default moduleManifest
