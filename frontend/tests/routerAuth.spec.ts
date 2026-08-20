import { beforeEach, describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({
  initialized: true,
  authenticated: false,
  bootstrap: vi.fn(),
}))

vi.mock('@/stores/auth', () => ({ useAuthStore: () => auth }))

import router from '@/router'

describe('authentication route guards', () => {
  beforeEach(() => {
    auth.initialized = true
    auth.authenticated = false
    auth.bootstrap.mockReset()
  })

  it('redirects anonymous users to login and preserves the requested URL', async () => {
    await router.push('/tasks?status=RUNNING')

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/tasks?status=RUNNING')
  })

  it(
    'keeps authenticated users out of login and registration pages',
    async () => {
      auth.authenticated = true

      await router.push('/register')

      expect(router.currentRoute.value.name).toBe('workspace')
    },
    15_000,
  )

  it('bootstraps authentication before deciding the initial route', async () => {
    auth.initialized = false
    auth.bootstrap.mockImplementationOnce(async () => {
      auth.initialized = true
      auth.authenticated = true
    })

    await router.push('/tasks')

    expect(auth.bootstrap).toHaveBeenCalledOnce()
    expect(router.currentRoute.value.name).toBe('tasks')
  })
})
