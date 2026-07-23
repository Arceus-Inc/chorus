import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setupTests.js'],
    exclude: ['**/node_modules/**', '**/dist/**', '**/tests/**'],
  },
});
