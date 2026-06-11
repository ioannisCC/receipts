import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/audit': 'http://localhost:8000',
      '/healthz': 'http://localhost:8000',
    },
  },
  preview: {
    host: '0.0.0.0',
    port: Number(process.env.PORT) || 3000,
    // Railway-generated domain + a catch-all so we don't have to redeploy
    // the frontend just to update an allowed-host whitelist.
    allowedHosts: [
      'receipts-frontend-production.up.railway.app',
      '.up.railway.app',
    ],
  },
})
