/// <reference types="vitest" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The browser only ever talks to /api (docs/architecture/data-and-contracts.md). The backend runs on :8000; point the proxy
// elsewhere with API_TARGET when a second server is running (verification, a second branch).
const target = process.env.API_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': target },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
  },
})
