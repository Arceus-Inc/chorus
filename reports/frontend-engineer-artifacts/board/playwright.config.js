import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  use: {
    baseURL: 'http://127.0.0.1:4173',
  },
  // Force all e2e tests to share the same storage state (same origin)
  // so localStorage persists across page reloads within a test.
  contextOptions: {
    storageState: undefined,
  },
  webServer: {
    command: 'python -m http.server 4173',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: true,
  },
});
