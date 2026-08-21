import { expect, test } from '@playwright/test'

/**
 * E2E smoke tests.
 *
 * These assert the app shell and critical navigation without requiring the
 * Firebase emulators (data-dependent queries degrade gracefully). Tests that
 * need seeded emulator data belong in tests/integration and require the
 * emulator suite to be running.
 */
test('home page renders the module shell and entry points', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'AEIV Sponsors module' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Public sponsor directory' })).toBeVisible()
  await expect(page.getByText('Module aeiv-sponsors')).toBeVisible()
})

test('navigation surfaces the Sponsors entry when the module is enabled', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('navigation', { name: 'Main' })).toContainText('Sponsors')
})

test('login page renders an accessible sign-in form', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: /Sign in/ })).toBeVisible()
  await expect(page.getByLabel('Email')).toBeVisible()
  await expect(page.getByLabel('Password')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
})

test('unknown routes resolve to the not-found page', async ({ page }) => {
  await page.goto('/does-not-exist')
  await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible()
})
