import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Point at the Flask backend. Override when Flask runs on another
      // port, e.g. API_URL=http://127.0.0.1:5001 npm run dev
      '/api': process.env.API_URL || 'http://127.0.0.1:5000',
    },
  },
})
