import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3737,
    proxy: {
      '/api': {
        target: 'http://backend:8585',
        changeOrigin: true,
      },
    },
  },
})
