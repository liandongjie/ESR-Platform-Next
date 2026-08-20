import ElementPlus from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import LoginView from '@/views/LoginView.vue'
import RegisterView from '@/views/RegisterView.vue'

const mocks = vi.hoisted(() => ({
  auth: {
    loading: false,
    notice: null as string | null,
    bootstrapError: null as string | null,
    login: vi.fn(),
    register: vi.fn(),
  },
  system: {
    capabilities: { registration_enabled: true } as { registration_enabled: boolean } | null,
    load: vi.fn(),
  },
}))

vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocks.auth }))
vi.mock('@/stores/system', () => ({ useSystemStore: () => mocks.system }))

function createTestRouter(path = '/login') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/tasks', component: { template: '<div />' } },
      { path: '/login', component: LoginView },
      { path: '/register', component: RegisterView },
    ],
  })
  return router.push(path).then(() => router)
}

describe('authentication views', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.auth.notice = null
    mocks.auth.bootstrapError = null
    mocks.system.capabilities = { registration_enabled: true }
  })

  it('submits credentials and honors a safe post-login redirect', async () => {
    const router = await createTestRouter('/login?redirect=/tasks')
    const wrapper = mount(LoginView, { global: { plugins: [ElementPlus, router] } })
    const inputs = wrapper.findAll('input')
    await inputs[0]!.setValue(' demo ')
    await inputs[1]!.setValue('secret')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(mocks.auth.login).toHaveBeenCalledWith({ username: 'demo', password: 'secret' })
    expect(router.currentRoute.value.path).toBe('/tasks')
  })

  it('shows session expiry and hides registration when production registration is disabled', async () => {
    mocks.auth.notice = '登录状态已过期，请重新登录'
    mocks.system.capabilities = { registration_enabled: false }
    const router = await createTestRouter()
    const wrapper = mount(LoginView, { global: { plugins: [ElementPlus, router] } })

    expect(wrapper.text()).toContain('登录状态已过期，请重新登录')
    expect(wrapper.text()).toContain('当前仅开放演示账号登录')
    expect(wrapper.find('a[href="/register"]').exists()).toBe(false)
  })

  it('disables account creation when the capability is off', async () => {
    mocks.system.capabilities = { registration_enabled: false }
    const router = await createTestRouter('/register')
    const wrapper = mount(RegisterView, { global: { plugins: [ElementPlus, router] } })

    expect(wrapper.text()).toContain('当前环境已关闭公开注册')
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
  })
})
