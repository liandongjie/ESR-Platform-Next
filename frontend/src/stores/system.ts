import { defineStore } from 'pinia'

import { getCapabilities, getLiveHealth } from '@/api/system'
import type { Capabilities } from '@/types/system'

interface SystemState {
  backendOnline: boolean
  loading: boolean
  capabilities: Capabilities | null
  error: string | null
}

export const useSystemStore = defineStore('system', {
  state: (): SystemState => ({
    backendOnline: false,
    loading: false,
    capabilities: null,
    error: null,
  }),
  actions: {
    async load() {
      this.loading = true
      this.error = null
      try {
        const [health, capabilities] = await Promise.all([getLiveHealth(), getCapabilities()])
        this.backendOnline = health.status === 'ok'
        this.capabilities = capabilities
      } catch (error: unknown) {
        this.backendOnline = false
        this.error = error instanceof Error ? error.message : '后端连接失败'
      } finally {
        this.loading = false
      }
    },
  },
})
