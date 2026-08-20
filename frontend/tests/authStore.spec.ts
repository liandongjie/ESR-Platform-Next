import { AxiosError } from 'axios'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  login as loginRequest,
  logout as logoutRequest,
  refreshSession,
} from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

const userData = vi.hoisted(() => ({
  resetAnalysis: vi.fn(),
  resetTaskHistory: vi.fn(),
}))

vi.mock('@/api/auth', () => ({
  login: vi.fn(),
  logout: vi.fn(),
  refreshSession: vi.fn(),
  register: vi.fn(),
}))
vi.mock('@/stores/analysis', () => ({
  useAnalysisStore: () => ({ resetForUserBoundary: userData.resetAnalysis }),
}))
vi.mock('@/stores/taskHistory', () => ({
  useTaskHistoryStore: () => ({ resetForUserBoundary: userData.resetTaskHistory }),
}))

const mockedLogin = vi.mocked(loginRequest)
const mockedLogout = vi.mocked(logoutRequest)
const mockedRefresh = vi.mocked(refreshSession)
const session = {
  access_token: 'access-token',
  user: { id: 1, username: 'demo' },
}


function authError(status: number) {
  return new AxiosError('auth failed', 'ERR_BAD_REQUEST', undefined, undefined, {
    data: {},
    status,
    statusText: 'Error',
    headers: {},
    config: {} as never,
  })
}

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('attempts cookie refresh once during bootstrap and keeps the access token in memory', async () => {
    mockedRefresh.mockResolvedValueOnce(session)
    const store = useAuthStore()

    await store.bootstrap()
    await store.bootstrap()

    expect(mockedRefresh).toHaveBeenCalledOnce()
    expect(store.accessToken).toBe('access-token')
    expect(store.user?.username).toBe('demo')
    expect(store.authenticated).toBe(true)
    expect(store.initialized).toBe(true)
  })

  it('shares one in-flight refresh across concurrent bootstrap callers', async () => {
    let resolveRefresh!: (value: typeof session) => void
    mockedRefresh.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRefresh = resolve
      }),
    )
    const store = useAuthStore()

    const first = store.bootstrap()
    const second = store.bootstrap()
    expect(mockedRefresh).toHaveBeenCalledOnce()
    resolveRefresh(session)
    await Promise.all([first, second])

    expect(mockedRefresh).toHaveBeenCalledOnce()
    expect(store.authenticated).toBe(true)
  })

  it('does not expire a newer login when bootstrap receives a late 401', async () => {
    let rejectRefresh!: (reason: Error) => void
    const userB = { access_token: 'token-b', user: { id: 2, username: 'user-b' } }
    mockedRefresh.mockReturnValueOnce(
      new Promise((_resolve, reject) => {
        rejectRefresh = reject
      }),
    )
    mockedLogin.mockResolvedValueOnce(userB)
    const store = useAuthStore()

    const bootstrap = store.bootstrap()
    await store.login({ username: 'user-b', password: 'secret-b' })
    rejectRefresh(authError(401))
    await bootstrap

    expect(store.user).toEqual(userB.user)
    expect(store.accessToken).toBe('token-b')
    expect(userData.resetAnalysis).not.toHaveBeenCalled()
    expect(userData.resetTaskHistory).not.toHaveBeenCalled()
  })

  it('treats a missing refresh cookie as an anonymous initialized session', async () => {
    mockedRefresh.mockRejectedValueOnce(authError(401))
    const store = useAuthStore()

    await store.bootstrap()

    expect(store.authenticated).toBe(false)
    expect(store.notice).toBeNull()
    expect(store.initialized).toBe(true)
    expect(userData.resetAnalysis).toHaveBeenCalledOnce()
    expect(userData.resetTaskHistory).toHaveBeenCalledOnce()
  })

  it('preserves the local session when logout fails transiently', async () => {
    mockedLogin.mockResolvedValueOnce(session)
    mockedLogout.mockRejectedValueOnce(new Error('offline'))
    const store = useAuthStore()
    await store.login({ username: 'demo', password: 'secret' })

    await expect(store.logout()).rejects.toThrow('offline')

    expect(store.authenticated).toBe(true)
    expect(store.accessToken).toBe('access-token')
    expect(userData.resetAnalysis).not.toHaveBeenCalled()
  })

  it('clears user-bound task state across A logout and B login', async () => {
    const userB = { access_token: 'token-b', user: { id: 2, username: 'user-b' } }
    mockedLogin.mockResolvedValueOnce(session).mockResolvedValueOnce(userB)
    mockedLogout.mockResolvedValueOnce()
    const store = useAuthStore()

    await store.login({ username: 'demo', password: 'secret-a' })
    await store.logout()
    await store.login({ username: 'user-b', password: 'secret-b' })

    expect(userData.resetAnalysis).toHaveBeenCalledOnce()
    expect(userData.resetTaskHistory).toHaveBeenCalledOnce()
    expect(store.user).toEqual(userB.user)
    expect(store.accessToken).toBe('token-b')
  })

  it('resets user-bound state when refresh resolves to a different identity', () => {
    const store = useAuthStore()
    store.applySession(session)

    store.applySession({ access_token: 'token-b', user: { id: 2, username: 'user-b' } })

    expect(userData.resetAnalysis).toHaveBeenCalledOnce()
    expect(userData.resetTaskHistory).toHaveBeenCalledOnce()
    expect(store.user?.id).toBe(2)
  })

  it('reports transient bootstrap failures without treating them as logout', async () => {
    mockedRefresh.mockRejectedValueOnce(new Error('offline'))
    const store = useAuthStore()
    store.applySession(session)
    store.initialized = false

    await expect(store.bootstrap()).rejects.toThrow('offline')

    expect(store.authenticated).toBe(true)
    expect(store.bootstrapError).toBe('offline')
  })

  it('does not let an old refresh restore a session after logout', async () => {
    let resolveRefresh!: (value: typeof session) => void
    mockedRefresh.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRefresh = resolve
      }),
    )
    mockedLogout.mockResolvedValueOnce()
    const store = useAuthStore()
    store.applySession(session)

    const oldRefresh = store.refresh()
    await store.logout()
    resolveRefresh(session)

    await expect(oldRefresh).rejects.toThrow('认证会话已变化')
    expect(store.authenticated).toBe(false)
  })

  it('does not let an old refresh overwrite a newly logged-in identity', async () => {
    let resolveRefresh!: (value: typeof session) => void
    const userB = { access_token: 'token-b', user: { id: 2, username: 'user-b' } }
    mockedRefresh.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRefresh = resolve
      }),
    )
    mockedLogin.mockResolvedValueOnce(userB)
    const store = useAuthStore()
    store.applySession(session)

    const oldRefresh = store.refresh()
    await store.login({ username: 'user-b', password: 'secret-b' })
    resolveRefresh(session)

    await expect(oldRefresh).rejects.toThrow('认证会话已变化')
    expect(store.user).toEqual(userB.user)
    expect(store.accessToken).toBe('token-b')
  })

  it('does not let a late logout response clear a newer identity', async () => {
    let resolveLogout!: () => void
    const userB = { access_token: 'token-b', user: { id: 2, username: 'user-b' } }
    mockedLogout.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveLogout = resolve
      }),
    )
    mockedLogin.mockResolvedValueOnce(userB)
    const store = useAuthStore()
    store.applySession(session)

    const oldLogout = store.logout()
    await store.login({ username: 'user-b', password: 'secret-b' })
    resolveLogout()
    await oldLogout

    expect(store.user).toEqual(userB.user)
    expect(store.accessToken).toBe('token-b')
  })
})
