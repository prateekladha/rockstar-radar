import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies API/auth to the FastAPI backend on :8090.
// Production build emits to dist/, which FastAPI serves.
export default defineConfig({
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8090',
      '/auth': 'http://127.0.0.1:8090',
    },
  },
})
