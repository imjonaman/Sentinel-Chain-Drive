import { test, expect } from '@playwright/test';

test.describe('Sentinel Chain Drive Operator Experience E2E', () => {
  test('renders application shell, brand banner, and KPI stats', async ({ page }) => {
    await page.goto('/');

    // Check navbar brand
    await expect(page.locator('text=SENTINEL')).toBeVisible();
    await expect(page.locator('text=CHAIN DRIVE')).toBeVisible();

    // Check KPI cards
    await expect(page.locator('text=Monitored Transactions')).toBeVisible();
    await expect(page.locator('text=MuleChain Alerts')).toBeVisible();
    await expect(page.locator('text=DRUNIX Outbox State')).toBeVisible();
  });

  test('switches operator role view dynamically and adapts navigation links', async ({ page }) => {
    await page.goto('/');

    // Open Role Dropdown
    await page.locator('button:has-text("Bank Operator")').click();
    await page.locator('button:has-text("Fraud Analyst")').click();

    // Verify Fraud Analyst navigation links appear
    await expect(page.locator('text=Topology Explorer')).toBeVisible();
    await expect(page.locator('text=MuleChain Alerts')).toBeVisible();
    await expect(page.locator('text=Case Management')).toBeVisible();
  });

  test('navigates to Cytoscape transaction graph explorer', async ({ page }) => {
    await page.goto('/fraud/graph');

    await expect(page.locator('text=Interactive Cross-Account Transaction Graph Explorer')).toBeVisible();
    await expect(page.locator('text=Topology Legend')).toBeVisible();
    await expect(page.locator('text=Run MuleChain Detectors')).toBeVisible();
  });
});
