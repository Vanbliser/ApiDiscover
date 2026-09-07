import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend always binds to 127.0.0.1 (see run.sh) so it's never reachable
// from outside the server even when the frontend is exposed with --expose.
// The browser only ever talks to the frontend's own origin; Vite proxies
// /api (including its WebSocket upgrades) to the backend over localhost,
// which — unlike the browser's "localhost" — correctly means this same
// machine, since the proxying happens in Vite's own Node process here.
const backendPort = process.env.BACKEND_PORT || '8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: `http://localhost:${backendPort}`,
        ws: true,
      },
    },
  },
})
