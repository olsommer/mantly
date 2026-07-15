import { defineConfig, devices } from '@playwright/test';

const addinUrl = process.env.E2E_ADDIN_URL || 'http://127.0.0.1:4173';

export default defineConfig({
  testDir: './e2e',
  testMatch: 'auth-lifecycle.spec.ts',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: 'html',
  timeout: 180_000,

  expect: {
    timeout: 20_000,
  },

  use: {
    baseURL: addinUrl,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
