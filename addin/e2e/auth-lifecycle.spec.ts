import { expect, test } from '@playwright/test';

import { AUTH_E2E, seedBootstrapAdmin } from './auth.helpers';

test.describe('Auth lifecycle', () => {
  test('admin provisions a user who is forced to change password on first login', async ({ browser }) => {
    test.slow();

    await seedBootstrapAdmin();

    const customerEmail = `customer.auth-e2e+${Date.now()}@example.com`;
    const initialPassword = 'InitialUser123!';
    const newPassword = 'CustomerNew123!';

    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await adminPage.addInitScript(() => {
      window.localStorage.setItem('admin_onboarding_done', '1');
    });

    await adminPage.goto(AUTH_E2E.adminUrl);
    await adminPage.getByLabel('Email').fill(AUTH_E2E.bootstrapAdminEmail);
    const adminResetRequest = adminPage.waitForResponse((response) => {
      return response.url().includes('/api/collections/users/request-password-reset')
        && response.request().method() === 'POST';
    });
    await adminPage.getByRole('button', { name: 'Forgot password?' }).click();
    expect((await adminResetRequest).status()).toBe(204);
    await adminPage.getByLabel('Password').fill(AUTH_E2E.bootstrapAdminPassword);
    await adminPage.getByRole('button', { name: 'Sign in' }).click();

    await adminPage.getByRole('button', { name: 'Users' }).click();
    await expect(adminPage.getByRole('heading', { name: 'Users', exact: true })).toBeVisible();

    await adminPage.locator('#new-user-email').fill(customerEmail);
    await adminPage.locator('#new-user-password').fill(initialPassword);
    const createUserRequest = adminPage.waitForResponse((response) => {
      return response.url().includes('/api/admin/users')
        && response.request().method() === 'POST';
    });
    const reloadUsersRequest = adminPage.waitForResponse((response) => {
      return response.url().includes('/api/admin/users')
        && response.request().method() === 'GET';
    });
    await adminPage.getByRole('button', { name: 'Create user' }).click();
    expect((await createUserRequest).status()).toBe(200);
    expect((await reloadUsersRequest).status()).toBe(200);

    const customerRow = adminPage.locator('div.grid').filter({ hasText: customerEmail }).first();
    await expect(customerRow.getByText(customerEmail)).toBeVisible();
    await expect(customerRow.getByText('Password change required')).toBeVisible();

    const customerFirstLoginContext = await browser.newContext();
    const customerFirstLoginPage = await customerFirstLoginContext.newPage();

    await customerFirstLoginPage.goto(AUTH_E2E.addinUrl);
    await customerFirstLoginPage.getByLabel('E-Mail').fill(customerEmail);
    const customerResetRequest = customerFirstLoginPage.waitForResponse((response) => {
      return response.url().includes('/api/collections/users/request-password-reset')
        && response.request().method() === 'POST';
    });
    await customerFirstLoginPage.getByRole('button', { name: 'Passwort vergessen?' }).click();
    expect((await customerResetRequest).status()).toBe(204);

    await customerFirstLoginPage.getByLabel('Passwort').fill(initialPassword);
    await customerFirstLoginPage.getByRole('button', { name: 'Anmelden' }).click();

    await expect(customerFirstLoginPage.getByRole('heading', { name: 'Passwort ändern' })).toBeVisible();
    await customerFirstLoginPage.locator('#current-password').fill(initialPassword);
    await customerFirstLoginPage.locator('#new-password').fill(newPassword);
    await customerFirstLoginPage.locator('#confirm-password').fill(newPassword);
    await customerFirstLoginPage.getByRole('button', { name: 'Passwort aktualisieren' }).click();

    await expect(customerFirstLoginPage.getByText('Willkommen bei Mantly')).toBeVisible();

    const customerReloginContext = await browser.newContext();
    const customerReloginPage = await customerReloginContext.newPage();
    await customerReloginPage.goto(AUTH_E2E.addinUrl);
    await customerReloginPage.getByLabel('E-Mail').fill(customerEmail);
    await customerReloginPage.getByLabel('Passwort').fill(newPassword);
    const reloginPocketBaseAuth = customerReloginPage.waitForResponse((response) => {
      return response.url().includes('/api/collections/users/auth-with-password')
        && response.request().method() === 'POST';
    });
    const reloginExchange = customerReloginPage.waitForResponse((response) => {
      return response.url().includes('/api/auth/exchange')
        && response.request().method() === 'POST';
    });
    await customerReloginPage.getByRole('button', { name: 'Anmelden' }).click();
    expect((await reloginPocketBaseAuth).status()).toBe(200);
    expect((await reloginExchange).status()).toBe(200);
    await expect(customerReloginPage.getByText('Willkommen bei Mantly')).toBeVisible();
    await expect(customerReloginPage.getByRole('heading', { name: 'Passwort ändern' })).toHaveCount(0);

    const deleteUserRequest = adminPage.waitForResponse((response) => {
      return response.url().includes('/api/admin/users/')
        && response.request().method() === 'DELETE';
    });
    const customerDeleteButton = adminPage
      .getByText(customerEmail)
      .locator('xpath=ancestor::div[contains(@class,"grid")][1]')
      .getByRole('button', { name: 'Delete' });
    adminPage.once('dialog', (dialog) => dialog.accept());
    await customerDeleteButton.click();
    expect((await deleteUserRequest).status()).toBe(200);

    const deletedUserLoginContext = await browser.newContext();
    const deletedUserLoginPage = await deletedUserLoginContext.newPage();
    await deletedUserLoginPage.goto(AUTH_E2E.addinUrl);
    await deletedUserLoginPage.getByLabel('E-Mail').fill(customerEmail);
    await deletedUserLoginPage.getByLabel('Passwort').fill(newPassword);
    const deletedUserLoginRequest = deletedUserLoginPage.waitForResponse((response) => {
      return response.url().includes('/api/collections/users/auth-with-password')
        && response.request().method() === 'POST';
    });
    await deletedUserLoginPage.getByRole('button', { name: 'Anmelden' }).click();
    expect((await deletedUserLoginRequest).status()).not.toBe(200);

    await deletedUserLoginContext.close();
    await customerReloginContext.close();
    await customerFirstLoginContext.close();
    await adminContext.close();
  });
});
