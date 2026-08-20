import axios from 'axios'
import { defineStore } from 'pinia'

import {
  login as loginRequest,
  logout as logoutRequest,
  refreshSession,
  register as registerRequest,
} from '@/api/auth'
import { getApiErrorMessage } from '@/api/errors'
import { useAnalysisStore } from '@/stores/analysis'
import { useTaskHistoryStore } from '@/stores/taskHistory'
import type { AuthCredentials, AuthSession, AuthUser } from '@/types/auth'

interface AuthState {
  accessToken: string | null
  user: AuthUser | null
  initialized: boolean
  loading: boolean
  notice: string | null
  bootstrapError: string | null
  sessionEpoch: number
}

let bootstrapRequest: Promise<void> | null = null

class SessionChangedError extends Error {
  constructor() {
    super('认证会话已变化')
  }
}

function isAuthenticationRejection(error: unknown): boolean {
  return (
    axios.isAxiosError(error) &&
    (error.response?.status === 401 || error.response?.status === 403)
  )
}

function resetUserData() {
  useAnalysisStore().resetForUserBoundary()
  useTaskHistoryStore().resetForUserBoundary()
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    accessToken: null,
    user: null,
    initialized: false,
    loading: false,
    notice: null,
    bootstrapError: null,
    sessionEpoch: 0,
  }),
  getters: {
    authenticated: (state) => Boolean(state.accessToken && state.user),
  },
  actions: {
    beginSessionChange() {
      this.sessionEpoch += 1
      return this.sessionEpoch
    },
    applySession(session: AuthSession, expectedEpoch?: number): boolean {
      const epoch = expectedEpoch ?? this.sessionEpoch
      if (epoch !== this.sessionEpoch) return false
      if (this.user && this.user.id !== session.user.id) {
        this.beginSessionChange()
        resetUserData()
      }
      this.accessToken = session.access_token
      this.user = session.user
      this.notice = null
      this.bootstrapError = null
      return true
    },
    clearSession(notice: string | null = null) {
      this.accessToken = null
      this.user = null
      this.notice = notice
    },
    async bootstrap() {
      if (this.initialized) return
      bootstrapRequest ??= this.bootstrapOnce().finally(() => {
        bootstrapRequest = null
      })
      return bootstrapRequest
    },
    async bootstrapOnce() {
      const epoch = this.sessionEpoch
      try {
        await this.refresh(epoch)
      } catch (error: unknown) {
        if (isAuthenticationRejection(error)) {
          this.expireSession(null, epoch)
          return
        }
        if (error instanceof SessionChangedError) {
          return
        }
        this.bootstrapError = getApiErrorMessage(error, '会话校验服务暂不可用，请稍后重试')
        throw error
      } finally {
        this.initialized = true
      }
    },
    async login(credentials: AuthCredentials) {
      const epoch = this.beginSessionChange()
      await this.runSessionRequest(() => loginRequest(credentials), epoch)
    },
    async register(credentials: AuthCredentials) {
      const epoch = this.beginSessionChange()
      await this.runSessionRequest(() => registerRequest(credentials), epoch)
    },
    async refresh(expectedEpoch?: number) {
      const epoch = expectedEpoch ?? this.sessionEpoch
      const session = await refreshSession()
      if (!this.applySession(session, epoch)) throw new SessionChangedError()
    },
    async logout() {
      const epoch = this.beginSessionChange()
      try {
        if (this.accessToken) await logoutRequest()
      } catch (error: unknown) {
        if (epoch !== this.sessionEpoch) return
        if (!isAuthenticationRejection(error)) throw error
      }
      if (epoch !== this.sessionEpoch) return
      resetUserData()
      this.clearSession()
    },
    expireSession(
      notice: string | null = '登录状态已过期，请重新登录',
      expectedEpoch?: number,
    ): boolean {
      const epoch = expectedEpoch ?? this.sessionEpoch
      if (epoch !== this.sessionEpoch) return false
      this.beginSessionChange()
      resetUserData()
      this.clearSession(notice)
      return true
    },
    async runSessionRequest(request: () => Promise<AuthSession>, expectedEpoch: number) {
      this.loading = true
      let ownedEpoch = expectedEpoch
      try {
        const session = await request()
        if (!this.applySession(session, expectedEpoch)) throw new SessionChangedError()
        ownedEpoch = this.sessionEpoch
        this.initialized = true
      } finally {
        if (ownedEpoch === this.sessionEpoch) this.loading = false
      }
    },
  },
})
