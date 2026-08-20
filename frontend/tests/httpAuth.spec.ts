import { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { describe, expect, it, vi } from 'vitest'

import { configureHttpAuth, http } from '@/api/http'

function unauthorized(config: InternalAxiosRequestConfig) {
  const response: AxiosResponse = {
    data: { message: 'unauthorized' },
    status: 401,
    statusText: 'Unauthorized',
    headers: {},
    config,
  }
  return new AxiosError('unauthorized', 'ERR_BAD_REQUEST', config, undefined, response)
}

function refreshError(status: number) {
  return new AxiosError('refresh failed', 'ERR_BAD_REQUEST', undefined, undefined, {
    data: {},
    status,
    statusText: 'Error',
    headers: {},
    config: {} as InternalAxiosRequestConfig,
  })
}

describe('HTTP authentication', () => {
  it('uses the Flask-JWT refresh CSRF cookie for credentialed requests', () => {
    expect(http.defaults.withCredentials).toBe(true)
    expect(http.defaults.xsrfCookieName).toBe('csrf_refresh_token')
    expect(http.defaults.xsrfHeaderName).toBe('X-CSRF-TOKEN')
  })

  it('adds the bearer token and retries concurrent 401 responses after one refresh', async () => {
    let token = 'expired-token'
    let releaseRefresh!: () => void
    const refreshGate = new Promise<void>((resolve) => {
      releaseRefresh = () => {
        token = 'fresh-token'
        resolve()
      }
    })
    const refresh = vi.fn(() => refreshGate)
    const expired = vi.fn()
    const authorizationHeaders: string[] = []

    configureHttpAuth({
      getAccessToken: () => token,
      getSessionEpoch: () => 1,
      refresh,
      onSessionExpired: expired,
    })

    const adapter = async (config: InternalAxiosRequestConfig) => {
      const authorization = String(config.headers.get('Authorization'))
      authorizationHeaders.push(authorization)
      if (authorization !== 'Bearer fresh-token') throw unauthorized(config)
      return { data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config }
    }

    const requests = [http.get('/protected-a', { adapter }), http.get('/protected-b', { adapter })]
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledOnce())
    releaseRefresh()
    const responses = await Promise.all(requests)

    expect(responses.map((response) => response.data)).toEqual([{ ok: true }, { ok: true }])
    expect(refresh).toHaveBeenCalledOnce()
    expect(expired).not.toHaveBeenCalled()
    expect(authorizationHeaders).toEqual([
      'Bearer expired-token',
      'Bearer expired-token',
      'Bearer fresh-token',
      'Bearer fresh-token',
    ])
  })

  it('does not recursively refresh a rejected authentication endpoint', async () => {
    const refresh = vi.fn()
    configureHttpAuth({
      getAccessToken: () => null,
      getSessionEpoch: () => 1,
      refresh,
      onSessionExpired: vi.fn(),
    })
    const adapter = async (config: InternalAxiosRequestConfig) => {
      throw unauthorized(config)
    }

    await expect(http.post('/auth/refresh', undefined, { adapter })).rejects.toMatchObject({
      response: { status: 401 },
    })
    expect(refresh).not.toHaveBeenCalled()
  })

  it('keeps the idempotency key when authentication retries a submission', async () => {
    let token = 'expired-token'
    const seenKeys: string[] = []
    configureHttpAuth({
      getAccessToken: () => token,
      getSessionEpoch: () => 1,
      refresh: vi.fn(async () => {
        token = 'fresh-token'
      }),
      onSessionExpired: vi.fn(),
    })
    const adapter = async (config: InternalAxiosRequestConfig) => {
      seenKeys.push(String(config.headers.get('Idempotency-Key')))
      if (config.headers.get('Authorization') !== 'Bearer fresh-token') {
        throw unauthorized(config)
      }
      return { data: { ok: true }, status: 202, statusText: 'Accepted', headers: {}, config }
    }

    await http.post('/risk-analysis/jobs', {}, {
      adapter,
      headers: { 'Idempotency-Key': 'submission-key' },
    })

    expect(seenKeys).toEqual(['submission-key', 'submission-key'])
  })

  it('expires the local session when the refresh cookie is rejected', async () => {
    const expired = vi.fn()
    configureHttpAuth({
      getAccessToken: () => 'expired-token',
      getSessionEpoch: () => 1,
      refresh: vi.fn().mockRejectedValue(refreshError(401)),
      onSessionExpired: expired,
    })
    const adapter = async (config: InternalAxiosRequestConfig) => {
      throw unauthorized(config)
    }

    await expect(http.get('/protected', { adapter })).rejects.toMatchObject({
      response: { status: 401 },
    })
    expect(expired).toHaveBeenCalledOnce()
  })

  it('preserves the session and propagates a transient refresh failure', async () => {
    const expired = vi.fn()
    const serviceError = refreshError(503)
    configureHttpAuth({
      getAccessToken: () => 'current-token',
      getSessionEpoch: () => 1,
      refresh: vi.fn().mockRejectedValue(serviceError),
      onSessionExpired: expired,
    })
    const adapter = async (config: InternalAxiosRequestConfig) => {
      throw unauthorized(config)
    }

    await expect(http.get('/protected', { adapter })).rejects.toBe(serviceError)
    expect(expired).not.toHaveBeenCalled()
  })

  it('ignores a late 401 from an older session epoch', async () => {
    let epoch = 1
    let rejectRequest!: () => void
    const refresh = vi.fn()
    const expired = vi.fn()
    configureHttpAuth({
      getAccessToken: () => 'token',
      getSessionEpoch: () => epoch,
      refresh,
      onSessionExpired: expired,
    })
    const adapter = (config: InternalAxiosRequestConfig) =>
      new Promise<never>((_resolve, reject) => {
        rejectRequest = () => reject(unauthorized(config))
      })

    const request = http.get('/protected', { adapter })
    await vi.waitFor(() => expect(rejectRequest).toBeTypeOf('function'))
    epoch = 2
    rejectRequest()

    await expect(request).rejects.toMatchObject({ response: { status: 401 } })
    expect(refresh).not.toHaveBeenCalled()
    expect(expired).not.toHaveBeenCalled()
  })

  it('does not retry or expire a new session after an old refresh finishes', async () => {
    let epoch = 1
    let releaseRefresh!: () => void
    const refresh = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          releaseRefresh = resolve
        }),
    )
    const expired = vi.fn()
    const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => {
      throw unauthorized(config)
    })
    configureHttpAuth({
      getAccessToken: () => 'token',
      getSessionEpoch: () => epoch,
      refresh,
      onSessionExpired: expired,
    })

    const request = http.get('/protected', { adapter })
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledWith(1))
    epoch = 2
    releaseRefresh()

    await expect(request).rejects.toMatchObject({ response: { status: 401 } })
    expect(adapter).toHaveBeenCalledOnce()
    expect(expired).not.toHaveBeenCalled()
  })
})
