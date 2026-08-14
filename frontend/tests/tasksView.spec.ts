import ElementPlus from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import TasksView from '@/views/TasksView.vue'

const mocks = vi.hoisted(() => ({
  store: {
    refreshing: false,
    total: 1,
    items: [
      {
        task_id: 'task-1',
        status: 'SUCCEEDED',
        stage: 'COMPLETED',
        progress: 100,
        result_available: true,
        submitted_at: '2026-08-08T02:00:00+00:00',
        request_summary: { geometry_type: 'Polygon', weights: [] },
      },
    ],
    polling: false,
    loading: false,
    error: null,
    limit: 20,
    page: 1,
    selectedTaskId: null,
    selectedTask: null,
    selectedResult: null,
    selectedSpatialResult: null,
    detailError: null,
    spatialError: null,
    detailLoading: false,
    spatialLoading: false,
    initialize: vi.fn(),
    stopAutoRefresh: vi.fn(),
    refreshNow: vi.fn(),
    changePage: vi.fn(),
    openTask: vi.fn(),
    closeDetail: vi.fn(),
  },
}))

vi.mock('@/stores/taskHistory', () => ({ useTaskHistoryStore: () => mocks.store }))

describe('TasksView shell', () => {
  beforeEach(() => {
    mocks.store.initialize.mockReset()
    mocks.store.stopAutoRefresh.mockReset()
  })

  it('uses concise Chinese labels and flat summary/table structures', async () => {
    const wrapper = mount(TasksView, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          MapCanvas: true,
          RiskAnalysisResultDownloads: true,
        },
      },
    })
    await flushPromises()

    expect(wrapper.get('h1').text()).toBe('历史任务')
    expect(wrapper.text()).not.toContain('TASK HISTORY')
    expect(wrapper.text()).not.toContain('风险分析历史任务')
    expect(wrapper.text()).toContain('阶段')
    expect(wrapper.text()).toContain('任务 ID')
    expect(wrapper.find('.history-summary-bar').exists()).toBe(true)
    expect(wrapper.find('.summary-card').exists()).toBe(false)
    expect(wrapper.get('.history-panel').classes()).not.toContain('panel-card')
    expect(mocks.store.initialize).toHaveBeenCalledOnce()

    wrapper.unmount()
    expect(mocks.store.stopAutoRefresh).toHaveBeenCalledOnce()
  })
})
