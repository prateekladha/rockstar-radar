import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies API/auth to the FastAPI backend (default :8080, matching the README).
// Override with VITE_API_TARGET if you run the backend on a different port.
// Production build emits to dist/, which FastAPI serves.
const API_TARGET = process.env.VITE_API_TARGET || 'http://127.0.0.1:8080'
export default defineConfig({
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    port: 5173,
    proxy: {
      '/api': API_TARGET,
      '/auth': API_TARGET,
      '/ingest': API_TARGET,
    },
  },
})
