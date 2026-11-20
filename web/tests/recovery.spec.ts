import { expect, test, type Page } from '@playwright/test';

async function signIn(page: Page, user: string) {
  await page.getByLabel('Username').fill(user);
  await page.getByLabel('Password').fill('pipeline-demo');
  await page.getByRole('button', {name: 'Sign in'}).click();
  await expect(page.getByRole('heading', {name: 'Pipeline runs'})).toBeVisible();
  await expect(page.getByRole('status')).toHaveText('Live');
}

test('operator watches a failure and retries; viewer can inspect but cannot retry', async ({page, request}) => {
  let connections = 0;
  await page.route('**/api/workspaces/north/events', async route => {
    connections += 1;
    if (connections === 1) await route.abort();
    else await route.continue();
  });
  await page.goto('/');
  await signIn(page, 'operator');
  expect(connections).toBeGreaterThanOrEqual(2);
  await page.getByLabel('Source revision').selectOption('changed');
  const creation = page.waitForResponse(res => res.url().endsWith('/north/runs') && res.request().method() === 'POST');
  await page.getByRole('button', {name: 'Start run'}).click();
  const original = await (await creation).json();
  await expect(page.getByRole('heading', {name: 'Run detail'})).toBeVisible();
  await expect(page.locator('.heading .status')).toHaveText('failed', {timeout: 180_000});
  await expect(page.getByRole('cell', {name: 'D-0001', exact: true})).toBeVisible();
  await expect(page.getByText(original.correlation, {exact: true})).toBeVisible();
  const viewer = await page.context().newPage();
  await viewer.goto('/');
  await signIn(viewer, 'viewer');
  await viewer.getByRole('button', {name: original.id.slice(0, 8), exact: true}).click();
  await expect(viewer.getByRole('cell', {name: 'D-0001', exact: true})).toBeVisible();
  await expect(viewer.getByRole('button', {name: 'Retry run'})).toHaveCount(0);
  await viewer.close();
  await page.getByLabel('Use corrected demo fixture').check();
  await page.getByRole('button', {name: 'Retry run'}).click();
  await expect(page.locator('.heading .status')).toHaveText('succeeded', {timeout: 180_000});
  await expect(page.getByText('Original run', {exact: true})).toBeVisible();
  await page.getByRole('button', {name: 'Audit', exact: true}).click();
  await expect(page.getByRole('cell', {name: 'retry_corrected', exact: true}).first()).toBeVisible();
  await page.getByRole('button', {name: 'Sign out'}).click();
  await signIn(page, 'viewer');
  await page.getByLabel('Status').selectOption('failed');
  await page.getByRole('button', {name: original.id.slice(0, 8), exact: true}).click();
  await expect(page.getByRole('cell', {name: 'D-0001', exact: true})).toBeVisible();
  await expect(page.getByRole('button', {name: 'Retry run'})).toHaveCount(0);
  const login = await request.post('/api/sign-in', {data: {username: 'viewer', password: 'pipeline-demo'}});
  const {token} = await login.json();
  const denied = await request.post(`/api/workspaces/north/runs/${original.id}/retry`, {
    headers: {Authorization: `Bearer ${token}`}, data: {},
  });
  expect(denied.status()).toBe(403);
});
