import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    host: true, // bind 0.0.0.0 so docker port-mapping works
    proxy: {
      '/api': process.env.BACKEND_URL || 'http://localhost:8080',
    },
  },
  build: {
    outDir: 'dist',
  },
})
