import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getCurrentUser, login, parseAuthSession } from '@/api/auth'
import { http } from '@/api/http'

describe('auth API contract', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('accepts the concrete session envelope', () => {
    expect(
      parseAuthSession({
        access_token: 'access-token',
        user: { id: 1, username: 'demo' },
      }),
    ).toEqual({ access_token: 'access-token', user: { id: 1, username: 'demo' } })
  })

  it.each([
    {},
    { access_token: '', user: { id: 1, username: 'demo' } },
    { access_token: 'token', user: { id: 0, username: 'demo' } },
    { access_token: 'token', user: { id: 1, username: '' } },
  ])('rejects malformed session data %#', (value) => {
    expect(() => parseAuthSession(value)).toThrow('认证响应格式不完整')
  })

  it('validates login and current-user responses at the HTTP boundary', async () => {
    vi.spyOn(http, 'post').mockResolvedValueOnce({
      data: { access_token: 'token', user: { id: '1', username: 'demo' } },
    } as never)
    await expect(login({ username: 'demo', password: 'secret' })).rejects.toThrow(
      '认证响应格式不完整',
    )

    vi.spyOn(http, 'get').mockResolvedValueOnce({ data: { user: null } } as never)
    await expect(getCurrentUser()).rejects.toThrow('认证响应格式不完整')
  })
})
