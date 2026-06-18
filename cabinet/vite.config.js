import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/auth': 'http://localhost:8766',
      '/portfolio': 'http://localhost:8766',
      '/yield': 'http://localhost:8766',
      '/health': 'http://localhost:8766',
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
