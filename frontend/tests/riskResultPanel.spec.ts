import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import RiskAnalysisResultDownloads from '@/components/risk-analysis/RiskAnalysisResultDownloads.vue'
import RiskResultPanel from '@/components/risk-analysis/RiskResultPanel.vue'
import { useAnalysisStore } from '@/stores/analysis'
import type { RiskJobStatus } from '@/types/riskAnalysis'

function mountPanel() {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(RiskResultPanel, {
    global: { plugins: [pinia, ElementPlus], stubs: { RiskAnalysisResultDownloads: true } },
  })
}

function setResult(store: ReturnType<typeof useAnalysisStore>) {
  store.result = {
    schema_version: 1,
    task_id: 'task-1',
    status: 'SUCCEEDED',
    algorithm_version: 'v1',
    geometry: { type: 'Polygon', bounds: [118.86, 32.07, 118.94, 32.13] },
    grid: { crs: 'EPSG:4326', shape: [6, 8], nodata: -9999 },
    statistics: { valid_pixel_count: 28, minimum: 0.36, maximum: 0.41, mean: 0.38 },
    indicators: [{
      code: 'PM25', name: 'PM2.5', weight_percent: 30,
      statistics: { valid_pixel_count: 28, minimum: 0.2, maximum: 0.5, mean: 0.35 },
    }],
    artifacts: { raster: 'risk.tif', manifest: 'result.json' },
  }
}

describe('RiskResultPanel', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('shows submitting before a task exists', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    store.jobSubmitting = true
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('提交中')
    expect(wrapper.text()).toContain('正在提交风险分析任务')
  })

  it.each([
    ['QUEUED', '排队中'], ['RUNNING', '分析中'], ['RETRYING', '重试中'],
    ['SUCCEEDED', '已完成'], ['FAILED', '失败'], ['CANCELED', '已取消'],
  ] as [RiskJobStatus, string][])('renders %s task status', async (status, label) => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    store.job = { task_id: 'task-1' }
    store.jobStatus = {
      task_id: 'task-1', status, stage: 'RASTER_OVERLAY', progress: 42,
      result_available: status === 'SUCCEEDED', submitted_at: null,
    }
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain(label)
    expect(wrapper.text()).toContain('task-1')
    expect(wrapper.text()).toContain('RASTER_OVERLAY')
    expect(wrapper.text()).toContain('42%')
  })

  it('renders task error and resumes polling through the existing Store action', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    store.job = { task_id: 'task-1' }
    store.taskError = '状态查询失败'
    const resume = vi.spyOn(store, 'resumeRiskAnalysisPolling').mockImplementation(() => {})
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('状态查询失败')
    await wrapper.get('button').trigger('click')
    expect(resume).toHaveBeenCalledOnce()
  })

  it('renders statistics, grid, indicators, downloads, and spatial state', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    setResult(store)
    store.spatialLoadingTaskId = 'task-1'
    store.spatialWarning = '空间结果暂不可用'
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('有效像元')
    expect(wrapper.text()).toContain('28')
    expect(wrapper.text()).toContain('0.380000')
    expect(wrapper.text()).toContain('6 × 8 · EPSG:4326')
    expect(wrapper.text()).toContain('PM25')
    expect(wrapper.text()).toContain('PM2.5 · 30%')
    expect(wrapper.text()).toContain('mean 0.350000')
    expect(wrapper.text()).toContain('正在加载空间风险分布')
    expect(wrapper.text()).toContain('空间结果暂不可用')
    expect(wrapper.findComponent(RiskAnalysisResultDownloads).props('taskId')).toBe('task-1')
  })
})
