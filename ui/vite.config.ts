import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API serves the built UI on one port, so the browser never needs CORS. In development and
// in `vite preview` the same relative path is forwarded to the API instead.
const api = { '/normalization': process.env.NORM_API_URL ?? 'http://localhost:8080' }

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: { proxy: api },
  preview: { proxy: api },
})
