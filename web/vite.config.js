import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'

// Dev server proxies API/auth to the FastAPI backend (default :8080, matching the README).
// Override with VITE_API_TARGET if you run the backend on a different port.
// Production build emits to dist/, which FastAPI serves.
const API_TARGET = process.env.VITE_API_TARGET || 'http://127.0.0.1:8080'

// Every build gets a unique ID. It's baked into the bundle (__BUILD_ID__) AND written to
// dist/version.json, so a running tab can poll version.json, notice its baked ID no longer matches,
// and prompt the user to reload instead of silently running the old JS after a deploy.
const BUILD_ID = process.env.BUILD_ID || String(Date.now())

function versionManifest() {
  return {
    name: 'version-manifest',
    apply: 'build',
    writeBundle(options) {
      fs.writeFileSync(path.join(options.dir, 'version.json'), JSON.stringify({ build: BUILD_ID }))
    },
  }
}

export default defineConfig({
  plugins: [react(), versionManifest()],
  define: { __BUILD_ID__: JSON.stringify(BUILD_ID) },
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
