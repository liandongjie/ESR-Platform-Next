/*
 * @Author: liandongjie
 * @Date: 2026-08-14 13:04:45
 * @LastEditors: liandongjie
 * @LastEditTime: 2026-08-14 14:30:45
 * @Description:
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'

import AppShell from '@/layouts/AppShell.vue'

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/tasks', component: { template: '<div />' } },
    ],
  })
}

describe('AppShell', () => {
  it('renders the two-level professional shell without fake brand or user chrome', async () => {
    const router = createTestRouter()
    await router.push('/')
    await router.isReady()
    const wrapper = mount(AppShell, {
      global: { plugins: [router] },
      slots: { default: '<div>content</div>' },
    })

    expect(wrapper.get('.wordmark strong').text()).toBe(
      'Environmental and Social Risk Platform | 环境社会风险分析平台',
    )
    // expect(wrapper.get('.wordmark span').text()).toBe('环境社会风险分析平台')
    expect(wrapper.text()).not.toContain('ESR')
    expect(wrapper.find('.brand-mark').exists()).toBe(false)
    expect(wrapper.find('.sidebar').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('DJ')
    expect(wrapper.findAll('.global-nav-item').map((item) => item.text())).toEqual([
      '风险分析',
      '历史任务',
    ])

    await wrapper.findAll('.global-nav-item')[1]!.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/tasks')
  })
})
