import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

declare const process: { env: Record<string, string | undefined> }

// Set these to run a review copy beside a backend or dev server already using the defaults.
const api = process.env.ATIA_API_URL || 'http://127.0.0.1:8000'
const port = Number(process.env.ATIA_UI_PORT) || 5173

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port, strictPort: true, fs: {strict: true, allow: ['.'], deny: ['**/.env', '**/.env.*', '**/data/**', '**/Afaq_RawData.json']}, proxy: { '/api': api, '/health': api } },
  preview: { port, strictPort: true, proxy: { '/api': api } },
})
