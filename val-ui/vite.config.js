import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const VAL_API = 'http://127.0.0.1:8765'

// Proxy config: all API paths forwarded to the backend
// This completely eliminates CORS issues
const PROXY_PATHS = [
  '/chat', '/query', '/stream',
  '/status', '/health',
  '/models', '/memory', '/reset',
  '/soc', '/osint', '/voice',
  '/terminal', '/logs', '/settings',
  '/agents', '/tools',
]

const proxy = Object.fromEntries(
  PROXY_PATHS.map(path => [
    path,
    {
      target: VAL_API,
      changeOrigin: true,
      // Keep SSE connections alive
      configure: (proxy) => {
        proxy.on('error', () => {});
      },
    }
  ])
)

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy,
  },
})

