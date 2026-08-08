import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getRiskAnalysisResult, listRiskAnalysisJobs } from '@/api/riskAnalysis'
import { useTaskHistoryStore } from '@/stores/taskHistory'
import type {
  RiskAnalysisJobHistoryResponse,
  RiskAnalysisResult,
} from '@/types/riskAnalysis'

vi.mock('@/api/riskAnalysis', () => ({
  getRiskAnalysisResult: vi.fn(),
  listRiskAnalysisJobs: vi.fn(),
}))

const mockedListJobs = vi.mocked(listRiskAnalysisJobs)
const mockedGetResult = vi.mocked(getRiskAnalysisResult)

function historyResponse(
  status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' = 'SUCCEEDED',
  resultAvailable = status === 'SUCCEEDED',
): RiskAnalysisJobHistoryResponse {
  return {
    items: [
      {
        task_id: 'task-1',
        status,
        stage: status === 'SUCCEEDED' ? 'COMPLETED' : status,
        progress: status === 'SUCCEEDED' ? 100 : 20,
        result_available: resultAvailable,
        submitted_at: '2026-08-08T02:00:00+00:00',
        request_summary: {
          geometry_type: 'Polygon',
          weights: [
            { code: 'PM25', weight_percent: 30 },
            { code: 'AQI', weight_percent: 40 },
            { code: 'NDVI', weight_percent: 30 },
          ],
        },
      },
    ],
    limit: 20,
    offset: 0,
    total: 1,
  }
}

function riskResult(): RiskAnalysisResult {
  return {
    schema_version: 1,
    task_id: 'task-1',
    status: 'SUCCEEDED',
    algorithm_version: 'v1',
    geometry: {
      type: 'Polygon',
      bounds: [118.86, 32.07, 118.94, 32.13],
    },
    grid: {
      crs: 'EPSG:4326',
      shape: [6, 8],
      nodata: -9999,
    },
    statistics: {
      valid_pixel_count: 28,
      minimum: 0.36,
      maximum: 0.41,
      mean: 0.38,
    },
    indicators: [],
    artifacts: {
      raster: 'risk-analysis/task-1/risk.tif',
      manifest: 'risk-analysis/task-1/result.json',
    },
  }
}

describe('task history store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedListJobs.mockReset()
    mockedGetResult.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads server-side task history instead of relying on previous Pinia memory', async () => {
    mockedListJobs.mockResolvedValueOnce(historyResponse())

    const store = useTaskHistoryStore()
    await store.initialize()

    expect(mockedListJobs).toHaveBeenCalledWith(20, 0)
    expect(store.items[0]?.task_id).toBe('task-1')
    expect(store.total).toBe(1)
  })

  it('loads the second page with an offset and reuses the same history API', async () => {
    const firstPage = {
      ...historyResponse(),
      total: 45,
    }
    const secondPage = {
      ...historyResponse(),
      items: [
        {
          ...historyResponse().items[0]!,
          task_id: 'task-page-2',
        },
      ],
      offset: 20,
      total: 45,
    }
    mockedListJobs
      .mockResolvedValueOnce(firstPage)
      .mockResolvedValueOnce(secondPage)

    const store = useTaskHistoryStore()
    await store.initialize()
    await store.changePage(2)

    expect(mockedListJobs).toHaveBeenNthCalledWith(2, 20, 20)
    expect(store.page).toBe(2)
    expect(store.offset).toBe(20)
    expect(store.items[0]?.task_id).toBe('task-page-2')
  })

  it('keeps refreshing while a task is active and stops after it reaches a terminal state', async () => {
    vi.useFakeTimers()
    mockedListJobs
      .mockResolvedValueOnce(historyResponse('RUNNING', false))
      .mockResolvedValueOnce(historyResponse('SUCCEEDED', true))

    const store = useTaskHistoryStore()
    await store.initialize()

    expect(store.polling).toBe(true)
    await vi.advanceTimersByTimeAsync(2000)

    expect(mockedListJobs).toHaveBeenCalledTimes(2)
    expect(store.items[0]?.status).toBe('SUCCEEDED')
    expect(store.polling).toBe(false)
  })

  it('a fresh store can rediscover a running task after a browser-style reload', async () => {
    vi.useFakeTimers()
    mockedListJobs.mockResolvedValue(historyResponse('RUNNING', false))

    const firstStore = useTaskHistoryStore()
    await firstStore.initialize()
    firstStore.stopAutoRefresh()

    setActivePinia(createPinia())
    const reloadedStore = useTaskHistoryStore()
    await reloadedStore.initialize()

    expect(reloadedStore.items[0]?.task_id).toBe('task-1')
    expect(reloadedStore.items[0]?.status).toBe('RUNNING')
    expect(reloadedStore.page).toBe(1)
    expect(reloadedStore.offset).toBe(0)
    expect(reloadedStore.polling).toBe(true)
  })

  it('loads final result only when the selected task is actually available', async () => {
    const store = useTaskHistoryStore()
    const running = historyResponse('RUNNING', false).items[0]
    const completed = historyResponse('SUCCEEDED', true).items[0]
    if (!running || !completed) throw new Error('test fixture missing task')

    await store.openTask(running)
    expect(mockedGetResult).not.toHaveBeenCalled()

    mockedGetResult.mockResolvedValueOnce(riskResult())
    await store.openTask(completed)

    expect(mockedGetResult).toHaveBeenCalledWith('task-1')
    expect(store.selectedResult?.statistics.valid_pixel_count).toBe(28)
  })
})
