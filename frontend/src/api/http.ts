import axios, { AxiosHeaders, type InternalAxiosRequestConfig } from 'axios'

interface RetryableRequestConfig extends InternalAxiosRequestConfig {
  _authRetried?: boolean
  _authEpoch?: number
}

interface HttpAuthHandlers {
  getAccessToken: () => string | null
  getSessionEpoch: () => number
  refresh: (expectedEpoch: number) => Promise<void>
  onSessionExpired: (expectedEpoch: number) => void
}

let authHandlers: HttpAuthHandlers | null = null
let refreshRequest: { epoch: number; promise: Promise<void> } | null = null

export function configureHttpAuth(handlers: HttpAuthHandlers) {
  authHandlers = handlers
}

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 15_000,
  withCredentials: true,
  xsrfCookieName: 'csrf_refresh_token',
  xsrfHeaderName: 'X-CSRF-TOKEN',
  headers: {
    'Content-Type': 'application/json',
  },
})

http.interceptors.request.use((config) => {
  const retryableConfig = config as RetryableRequestConfig
  if (authHandlers) {
    const currentEpoch = authHandlers.getSessionEpoch()
    if (
      retryableConfig._authRetried &&
      retryableConfig._authEpoch !== undefined &&
      retryableConfig._authEpoch !== currentEpoch
    ) {
      return Promise.reject(new Error('认证会话已变化，请重新发起请求'))
    }
    retryableConfig._authEpoch = currentEpoch
  }
  const accessToken = authHandlers?.getAccessToken()
  if (!accessToken) return config

  config.headers = AxiosHeaders.from(config.headers)
  config.headers.set('Authorization', `Bearer ${accessToken}`)
  return config
})

http.interceptors.response.use(undefined, async (error: unknown) => {
  if (!axios.isAxiosError(error) || error.response?.status !== 401 || !authHandlers) {
    return Promise.reject(error)
  }

  const config = error.config as RetryableRequestConfig | undefined
  const isAuthRequest = config?.url?.startsWith('/auth/') ?? false
  if (!config || isAuthRequest) return Promise.reject(error)
  const requestEpoch = config._authEpoch
  if (requestEpoch === undefined || requestEpoch !== authHandlers.getSessionEpoch()) {
    return Promise.reject(error)
  }
  if (config._authRetried) {
    authHandlers.onSessionExpired(requestEpoch)
    return Promise.reject(error)
  }

  config._authRetried = true
  if (!refreshRequest || refreshRequest.epoch !== requestEpoch) {
    const promise = authHandlers.refresh(requestEpoch).finally(() => {
      if (refreshRequest?.promise === promise) refreshRequest = null
    })
    refreshRequest = { epoch: requestEpoch, promise }
  }

  try {
    await refreshRequest.promise
    if (requestEpoch !== authHandlers.getSessionEpoch()) return Promise.reject(error)
    return await http.request(config)
  } catch (refreshError: unknown) {
    if (
      axios.isAxiosError(refreshError) &&
      (refreshError.response?.status === 401 || refreshError.response?.status === 403)
    ) {
      if (requestEpoch === authHandlers.getSessionEpoch()) {
        authHandlers.onSessionExpired(requestEpoch)
      }
    }
    return Promise.reject(refreshError)
  }
})
