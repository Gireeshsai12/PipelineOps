import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  workers: 1,
  timeout: 420_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: process.env.PIPELINEOPS_WEB || 'http://127.0.0.1:5173',
    browserName: 'chromium',
    launchOptions: { executablePath: process.env.CHROMIUM_PATH },
  },
});
