export const AUTH_E2E = {
  pocketbaseUrl: process.env.E2E_PB_URL || 'http://127.0.0.1:8091',
  backendUrl: process.env.E2E_API_URL || 'http://127.0.0.1:8180',
  addinUrl: process.env.E2E_ADDIN_URL || 'http://127.0.0.1:4173',
  adminUrl: process.env.E2E_ADMIN_URL || 'http://127.0.0.1:4174',
  deliveryStubUrl: process.env.E2E_DELIVERY_STUB_URL || 'http://127.0.0.1:8190',
  superuserEmail: process.env.E2E_PB_ADMIN_EMAIL || 'admin@mantly.local',
  superuserPassword: process.env.E2E_PB_ADMIN_PASSWORD || 'adminpass123',
  bootstrapAdminEmail: 'owner.auth-e2e@example.com',
  bootstrapAdminPassword: 'TempAdmin123!',
};

export interface BootstrapAdminSeed {
  tenantId: string;
  apiToken: string;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function expectJson(response: Response): Promise<Record<string, unknown>> {
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${text}`);
  }
  return text ? JSON.parse(text) as Record<string, unknown> : {};
}

async function authenticateSuperuser(): Promise<string> {
  const response = await fetch(`${AUTH_E2E.pocketbaseUrl}/api/collections/_superusers/auth-with-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      identity: AUTH_E2E.superuserEmail,
      password: AUTH_E2E.superuserPassword,
    }),
  });
  const payload = await expectJson(response);
  return String(payload.token);
}

async function createTenant(token: string): Promise<string> {
  const response = await fetch(`${AUTH_E2E.pocketbaseUrl}/api/collections/tenants/records`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      name: 'Auth E2E Tenant',
    }),
  });
  const payload = await expectJson(response);
  return String(payload.id);
}

async function createUserRecord(
  token: string,
  tenantId: string,
  email: string,
  password: string,
  isRoot: boolean,
  mustChangePassword: boolean,
): Promise<void> {
  const response = await fetch(`${AUTH_E2E.pocketbaseUrl}/api/collections/users/records`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      email,
      password,
      passwordConfirm: password,
      tenant: tenantId,
      is_root: isRoot,
      must_change_password: mustChangePassword,
      verified: true,
    }),
  });
  await expectJson(response);
}

async function authenticateBootstrapAdmin(): Promise<{ token: string; tenantId: string }> {
  const response = await fetch(`${AUTH_E2E.pocketbaseUrl}/api/collections/users/auth-with-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      identity: AUTH_E2E.bootstrapAdminEmail,
      password: AUTH_E2E.bootstrapAdminPassword,
    }),
  });
  const payload = await expectJson(response);
  const record = payload.record as Record<string, unknown> | undefined;
  const tenant = record?.tenant;
  return {
    token: String(payload.token),
    tenantId: typeof tenant === 'string' ? tenant : '',
  };
}

async function exchangeBootstrapAdminToken(pbToken: string): Promise<string> {
  const response = await fetch(`${AUTH_E2E.backendUrl}/api/auth/exchange`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pb_token: pbToken }),
  });
  const payload = await expectJson(response);
  return String(payload.token);
}

async function waitForAdminUsersReady(apiToken: string): Promise<void> {
  let lastError = 'admin users endpoint did not become ready';

  for (let attempt = 1; attempt <= 15; attempt += 1) {
    const response = await fetch(`${AUTH_E2E.backendUrl}/api/admin/users`, {
      headers: {
        Authorization: `Bearer ${apiToken}`,
      },
    });

    if (response.ok) {
      return;
    }

    lastError = `HTTP ${response.status}: ${await response.text()}`;
    await sleep(500);
  }

  throw new Error(lastError);
}

export async function seedBootstrapAdmin(): Promise<BootstrapAdminSeed> {
  let bootstrapAdmin: { token: string; tenantId: string };
  try {
    bootstrapAdmin = await authenticateBootstrapAdmin();
  } catch {
    const token = await authenticateSuperuser();
    const tenantId = await createTenant(token);
    await createUserRecord(
      token,
      tenantId,
      AUTH_E2E.bootstrapAdminEmail,
      AUTH_E2E.bootstrapAdminPassword,
      true,
      false,
    );
    bootstrapAdmin = await authenticateBootstrapAdmin();
  }
  if (!bootstrapAdmin.tenantId) {
    throw new Error('Bootstrap admin authentication did not return a tenant');
  }
  const apiToken = await exchangeBootstrapAdminToken(bootstrapAdmin.token);
  await waitForAdminUsersReady(apiToken);
  return { tenantId: bootstrapAdmin.tenantId, apiToken };
}

export async function adminApiJson(
  apiToken: string,
  path: string,
  init: RequestInit = {},
): Promise<Record<string, unknown>> {
  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json');
  headers.set('Authorization', `Bearer ${apiToken}`);
  const response = await fetch(`${AUTH_E2E.backendUrl}${path}`, {
    ...init,
    headers,
  });
  return expectJson(response);
}

export async function createInboxFixtureProject(seed: BootstrapAdminSeed): Promise<string> {
  const project = await adminApiJson(seed.apiToken, '/api/admin/projects', {
    method: 'POST',
    body: JSON.stringify({
      name: `Inbox E2E ${Date.now()}`,
      description: 'Deterministic Admin Inbox lifecycle fixture',
    }),
  });
  const projectId = String(project.id);
  if (!projectId) {
    throw new Error('Project creation did not return an id');
  }
  await adminApiJson(seed.apiToken, `/api/admin/projects/${encodeURIComponent(projectId)}/channels`, {
    method: 'POST',
    body: JSON.stringify({
      channelKey: 'email:admin_inbox',
      type: 'email',
      name: 'Admin Inbox test email',
      status: 'active',
      config: {
        outboundTransport: 'webhook',
        outboundPayloadMode: 'generic',
        outboundWebhookUrl: `${AUTH_E2E.deliveryStubUrl}/deliver`,
      },
    }),
  });
  return projectId;
}
