import { expect, test } from '@playwright/test';

import {
  AUTH_E2E,
  adminApiJson,
  createInboxFixtureProject,
  seedBootstrapAdmin,
} from './auth.helpers';

test.describe('Admin Inbox lifecycle', () => {
  test('creates, claims, edits, approves, delivers, and closes a ticket', async ({ page }) => {
    test.slow();

    const seed = await seedBootstrapAdmin();
    const projectId = await createInboxFixtureProject(seed);
    await page.addInitScript(() => {
      window.localStorage.setItem('admin_onboarding_done', '1');
    });

    await page.goto(AUTH_E2E.adminUrl);
    await page.getByLabel('Email').fill(AUTH_E2E.bootstrapAdminEmail);
    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page.getByLabel('Password')).toBeVisible();
    await page.getByLabel('Password').fill(AUTH_E2E.bootstrapAdminPassword);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await page.goto(`${AUTH_E2E.adminUrl}/${seed.tenantId}/${projectId}/inbox?view=list`);

    await page.locator('[data-new-ticket-open]').first().click();
    await page.locator('[data-new-ticket-email]').fill('inbox-e2e-customer@example.com');
    await page.locator('[data-new-ticket-name]').fill('Inbox E2E Customer');
    await page.locator('[data-new-ticket-account]').fill('Inbox E2E Account');
    await page.locator('[data-new-ticket-subject]').fill('Deterministic delivery request');
    await page.locator('[data-new-ticket-body]').fill('Please confirm this ticket reaches deterministic delivery.');
    const createRequest = page.waitForResponse((response) => (
      response.url().includes(`/api/admin/projects/${projectId}/issues`)
      && response.request().method() === 'POST'
    ));
    await page.locator('[data-new-ticket-create]').click();
    const createResponse = await createRequest;
    expect(createResponse.status()).toBe(200);
    const createdIssue = await createResponse.json() as { id: string };
    expect(createdIssue.id).toBeTruthy();
    await expect(page.getByRole('heading', { name: 'Deterministic delivery request' })).toBeVisible();

    const unassignRequest = page.waitForResponse((response) => (
      response.url().endsWith(`/issues/${createdIssue.id}`)
      && response.request().method() === 'PATCH'
    ));
    await page.getByRole('button', { name: 'Unassign' }).last().click();
    expect((await unassignRequest).status()).toBe(200);
    await expect(page.locator('[data-ticket-assignee-current=""]').last()).toBeVisible();

    const claimRequest = page.waitForResponse((response) => (
      response.url().endsWith(`/issues/${createdIssue.id}`)
      && response.request().method() === 'PATCH'
    ));
    await page.getByRole('button', { name: 'Assign to me' }).last().click();
    expect((await claimRequest).status()).toBe(200);
    await expect(page.locator(`[data-ticket-assignee-current="${AUTH_E2E.bootstrapAdminEmail}"]`).last()).toBeVisible();

    const replyDraft = page.locator('[data-ticket-reply-draft]').last();
    await replyDraft.fill('Initial response awaiting human approval.');
    await page.getByText('Require approval', { exact: true }).last().click();
    const draftRequest = page.waitForResponse((response) => (
      response.url().endsWith(`/issues/${createdIssue.id}/replies`)
      && response.request().method() === 'POST'
    ));
    await page.getByRole('button', { name: 'Save draft' }).last().click();
    const draftResponse = await draftRequest;
    expect(draftResponse.status()).toBe(200);
    const draft = await draftResponse.json() as {
      id: string;
      metadata: { approvalRequired?: boolean };
    };
    expect(draft.metadata.approvalRequired).toBe(true);

    const replyCard = page.locator(`[data-outbound-reply="${draft.id}"]`).last();
    await replyCard.locator(`[data-outbound-reply-edit="${draft.id}"]`).click();
    await replyCard.locator(`[data-outbound-reply-edit-body="${draft.id}"]`).fill(
      'Edited and approved response delivered by the deterministic adapter.',
    );
    const editRequest = page.waitForResponse((response) => (
      response.url().endsWith(`/issues/${createdIssue.id}/replies/${draft.id}`)
      && response.request().method() === 'PATCH'
    ));
    await replyCard.locator(`[data-outbound-reply-edit-save="${draft.id}"]`).click();
    const editResponse = await editRequest;
    expect(editResponse.status()).toBe(200);
    expect((await editResponse.json() as { body: string }).body).toContain('Edited and approved');

    const approveRequest = page.waitForResponse((response) => (
      response.url().endsWith(`/issues/${createdIssue.id}/replies/${draft.id}/approve`)
      && response.request().method() === 'POST'
    ));
    await replyCard.locator(`[data-outbound-reply-approve="${draft.id}"]`).click();
    const approveResponse = await approveRequest;
    expect(approveResponse.status()).toBe(200);
    expect((await approveResponse.json() as { metadata: { approved?: boolean } }).metadata.approved).toBe(true);

    const sendRequest = page.waitForResponse((response) => (
      response.url().endsWith(`/issues/${createdIssue.id}/replies/${draft.id}/send`)
      && response.request().method() === 'POST'
    ));
    await replyCard.locator(`[data-outbound-reply-id="${draft.id}"]`).click();
    const sendResponse = await sendRequest;
    expect(sendResponse.status()).toBe(200);
    const sent = await sendResponse.json() as { status: string; provider: string };
    expect(sent.status).toBe('sent');
    expect(sent.provider).toBe('email_webhook');
    await expect(page.locator(`[data-outbound-reply="${draft.id}"][data-outbound-reply-status="sent"]`).last()).toBeVisible();

    const deliveryEvidence = await fetch(`${AUTH_E2E.deliveryStubUrl}/deliveries`).then(async (response) => {
      expect(response.ok).toBe(true);
      return response.json() as Promise<{ items: Array<{ messageId: string; body: { body?: string } }> }>;
    });
    expect(deliveryEvidence.items).toHaveLength(1);
    expect(deliveryEvidence.items[0].messageId).toBe(draft.id);
    expect(deliveryEvidence.items[0].body.body).toContain('Edited and approved');

    await page.reload();
    await expect(page.getByRole('heading', { name: 'Deterministic delivery request' })).toBeVisible();
    const closeRequest = page.waitForResponse((response) => (
      response.url().endsWith(`/issues/${createdIssue.id}`)
      && response.request().method() === 'PATCH'
    ));
    await page.locator('[data-ticket-status-select]').last().click();
    await page.getByRole('option', { name: 'Done' }).click();
    const closeResponse = await closeRequest;
    expect(closeResponse.status()).toBe(200);
    const closed = await closeResponse.json() as { status: string; workflowStatus?: string };
    expect(closed.workflowStatus || closed.status).toBe('done');

    const persisted = await adminApiJson(
      seed.apiToken,
      `/api/admin/projects/${encodeURIComponent(projectId)}/issues/${encodeURIComponent(createdIssue.id)}`,
    ) as {
      status: string;
      workflowStatus?: string;
      outboundMessages?: Array<{ id: string; status: string; provider: string }>;
    };
    expect(persisted.workflowStatus || persisted.status).toBe('done');
    expect(persisted.outboundMessages).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: draft.id, status: 'sent', provider: 'email_webhook' }),
    ]));
  });
});
