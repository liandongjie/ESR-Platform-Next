import axios from 'axios'

import type { ApiErrorPayload } from '@/types/api'

export function getApiErrorMessage(error: unknown, fallback = '请求失败'): string {
  if (axios.isAxiosError<ApiErrorPayload>(error)) {
    const payload = error.response?.data
    if (payload?.message) {
      const firstDetail = payload.details?.[0]
      if (firstDetail) {
        const fieldPrefix = firstDetail.field ? `${firstDetail.field}：` : ''
        return `${payload.message}（${fieldPrefix}${firstDetail.message}）`
      }
      return payload.message
    }

    if (error.code === 'ECONNABORTED') {
      return '请求超时，请稍后重试'
    }
    if (!error.response) {
      return '无法连接后端服务，请检查服务是否启动'
    }

    return fallback
  }

  return error instanceof Error ? error.message : fallback
}
