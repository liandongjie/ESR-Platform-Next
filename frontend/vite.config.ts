import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

const usePolling = process.env.VITE_USE_POLLING === 'true'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // Windows 宿主机通过 Docker bind mount 修改源码时，文件系统事件可能无法稳定传给容器内 Vite。
    // 仅在 Docker 开发环境显式开启 polling，避免普通本地开发和 CI 无谓增加文件扫描开销。
    watch: usePolling ? { usePolling: true } : undefined,
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_PROXY_TARGET || 'http://localhost:5000',
        changeOrigin: true,
      },
    },
  },
})
