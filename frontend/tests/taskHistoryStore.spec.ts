import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  downloadRiskAnalysisPreview,
  getRiskAnalysisResult,
  getRiskAnalysisSpatialResult,
  isRiskAnalysisPreviewUnavailable,
  listRiskAnalysisJobs,
} from '@/api/riskAnalysis'
import { useTaskHistoryStore } from '@/stores/taskHistory'
import type {
  RiskAnalysisJobHistoryResponse,
  RiskAnalysisResult,
  RiskAnalysisSpatialResult,
} from '@/types/riskAnalysis'

vi.mock('@/api/riskAnalysis', () => ({
  downloadRiskAnalysisPreview: vi.fn(),
  getRiskAnalysisResult: vi.fn(),
  getRiskAnalysisSpatialResult: vi.fn(),
  isRiskAnalysisPreviewUnavailable: vi.fn(),
  listRiskAnalysisJobs: vi.fn(),
}))

const mockedListJobs = vi.mocked(listRiskAnalysisJobs)
const mockedDownloadPreview = vi.mocked(downloadRiskAnalysisPreview)
const mockedGetResult = vi.mocked(getRiskAnalysisResult)
const mockedGetSpatialResult = vi.mocked(getRiskAnalysisSpatialResult)
const mockedPreviewUnavailable = vi.mocked(isRiskAnalysisPreviewUnavailable)

function historyResponse(
  status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' = 'SUCCEEDED',
  resultAvailable = status === 'SUCCEEDED',
  taskId = 'task-1',
): RiskAnalysisJobHistoryResponse {
  return {
    items: [
      {
        task_id: taskId,
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

function riskResult(taskId = 'task-1'): RiskAnalysisResult {
  return {
    schema_version: 1,
    task_id: taskId,
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
      raster: `risk-analysis/${taskId}/risk.tif`,
      manifest: `risk-analysis/${taskId}/result.json`,
    },
  }
}

function previewRiskResult(taskId = 'task-1'): RiskAnalysisResult {
  const result = riskResult(taskId)
  result.grid.bounds = [118.86, 32.07, 118.94, 32.13]
  result.artifacts.preview = `risk-analysis/${taskId}/preview.png`
  return result
}

function spatialResult(taskId = 'task-1', value = 0.5): RiskAnalysisSpatialResult {
  return {
    schema_version: 1,
    task_id: taskId,
    crs: 'EPSG:4326',
    value_range: { minimum: 0, maximum: 1 },
    feature_collection: {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          geometry: {
            type: 'Polygon',
            coordinates: [
              [
                [118.86, 32.07],
                [118.87, 32.07],
                [118.87, 32.08],
                [118.86, 32.08],
                [118.86, 32.07],
              ],
            ],
          },
          properties: { value },
        },
      ],
    },
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

describe('task history store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedListJobs.mockReset()
    mockedDownloadPreview.mockReset()
    mockedGetResult.mockReset()
    mockedGetSpatialResult.mockReset()
    mockedPreviewUnavailable.mockReset()
    mockedPreviewUnavailable.mockReturnValue(false)
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:task-preview')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('loads server-side task history instead of relying on previous Pinia memory', async () => {
    mockedListJobs.mockResolvedValueOnce(historyResponse())

    const store = useTaskHistoryStore()
    await store.initialize()

    expect(mockedListJobs).toHaveBeenCalledWith(20, 0)
    expect(store.items[0]?.task_id).toBe('task-1')
    expect(store.total).toBe(1)
  })

  it('clears user-bound list and detail state while invalidating polling', () => {
    const store = useTaskHistoryStore()
    store.items = historyResponse().items
    store.total = 1
    store.polling = true
    store.selectedTaskId = 'task-1'
    store.selectedResult = riskResult()
    const refreshRevision = store.refreshRevision
    const detailRevision = store.detailRevision

    store.resetForUserBoundary()

    expect(store.items).toEqual([])
    expect(store.total).toBe(0)
    expect(store.polling).toBe(false)
    expect(store.selectedTaskId).toBeNull()
    expect(store.selectedResult).toBeNull()
    expect(store.refreshRevision).toBeGreaterThan(refreshRevision)
    expect(store.detailRevision).toBeGreaterThan(detailRevision)
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

  it('ignores an older page response without clearing the newer loading state', async () => {
    const firstPage = deferred<RiskAnalysisJobHistoryResponse>()
    const secondPage = deferred<RiskAnalysisJobHistoryResponse>()
    mockedListJobs.mockReturnValueOnce(firstPage.promise).mockReturnValueOnce(secondPage.promise)
    const store = useTaskHistoryStore()
    store.total = 40

    const firstLoad = store.loadJobs(true)
    store.page = 2
    const secondLoad = store.loadJobs(false)
    firstPage.resolve(historyResponse('SUCCEEDED', true, 'task-page-1'))
    await firstLoad

    expect(store.items).toEqual([])
    expect(store.refreshing).toBe(true)

    secondPage.resolve({
      ...historyResponse('SUCCEEDED', true, 'task-page-2'),
      offset: 20,
      total: 40,
    })
    await secondLoad

    expect(store.items[0]?.task_id).toBe('task-page-2')
    expect(store.refreshing).toBe(false)
  })

  it('ignores a previous user response after the user boundary resets', async () => {
    const userA = deferred<RiskAnalysisJobHistoryResponse>()
    const userB = deferred<RiskAnalysisJobHistoryResponse>()
    mockedListJobs.mockReturnValueOnce(userA.promise).mockReturnValueOnce(userB.promise)
    const store = useTaskHistoryStore()

    const loadA = store.loadJobs(true)
    store.resetForUserBoundary()
    const loadB = store.loadJobs(true)
    userB.resolve(historyResponse('SUCCEEDED', true, 'task-user-b'))
    await loadB
    userA.resolve(historyResponse('SUCCEEDED', true, 'task-user-a'))
    await loadA

    expect(store.items[0]?.task_id).toBe('task-user-b')
    expect(store.loading).toBe(false)
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

  it('loads final and spatial results only when the selected task is actually available', async () => {
    const store = useTaskHistoryStore()
    const running = historyResponse('RUNNING', false).items[0]
    const completed = historyResponse('SUCCEEDED', true).items[0]
    if (!running || !completed) throw new Error('test fixture missing task')

    await store.openTask(running)
    expect(mockedGetResult).not.toHaveBeenCalled()
    expect(mockedGetSpatialResult).not.toHaveBeenCalled()

    mockedGetResult.mockResolvedValueOnce(riskResult())
    mockedGetSpatialResult.mockResolvedValueOnce(spatialResult())
    await store.openTask(completed)

    expect(mockedGetResult).toHaveBeenCalledWith('task-1')
    expect(mockedGetSpatialResult).toHaveBeenCalledWith('task-1')
    expect(store.selectedResult?.statistics.valid_pixel_count).toBe(28)
    expect(store.selectedSpatialResult?.task_id).toBe('task-1')
  })

  it('prefers a preview Blob and revokes it when the detail closes', async () => {
    const store = useTaskHistoryStore()
    const task = historyResponse().items[0]!
    const blob = new Blob(['png'], { type: 'image/png' })
    mockedGetResult.mockResolvedValueOnce(previewRiskResult())
    mockedDownloadPreview.mockResolvedValueOnce({ blob, filename: 'preview.png' })

    await store.openTask(task)

    expect(mockedDownloadPreview).toHaveBeenCalledWith('task-1')
    expect(mockedGetSpatialResult).not.toHaveBeenCalled()
    expect(store.selectedRiskPreview?.url).toBe('blob:task-preview')

    store.closeDetail()

    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:task-preview')
    expect(store.selectedRiskPreview).toBeNull()
  })

  it('falls back to spatial data only when the preview is explicitly unavailable', async () => {
    const store = useTaskHistoryStore()
    const task = historyResponse().items[0]!
    mockedGetResult.mockResolvedValueOnce(previewRiskResult())
    mockedDownloadPreview.mockRejectedValueOnce(new Error('gone'))
    mockedPreviewUnavailable.mockReturnValueOnce(true)
    mockedGetSpatialResult.mockResolvedValueOnce(spatialResult())

    await store.openTask(task)

    expect(mockedGetSpatialResult).toHaveBeenCalledWith('task-1')
    expect(store.selectedSpatialResult?.task_id).toBe('task-1')
    expect(store.spatialError).toBe('轻量风险预览不可用，已回退到兼容图层')
  })

  it('does not hide a preview service failure behind the spatial fallback', async () => {
    const store = useTaskHistoryStore()
    const task = historyResponse().items[0]!
    mockedGetResult.mockResolvedValueOnce(previewRiskResult())
    mockedDownloadPreview.mockRejectedValueOnce(new Error('preview service failed'))

    await store.openTask(task)

    expect(mockedGetSpatialResult).not.toHaveBeenCalled()
    expect(store.selectedSpatialResult).toBeNull()
    expect(store.spatialError).toBe('preview service failed')
  })

  it('reuses in-flight and loaded requests in the same detail session', async () => {
    const store = useTaskHistoryStore()
    const task = historyResponse().items[0]!
    const resultRequest = deferred<RiskAnalysisResult>()
    const spatialRequest = deferred<RiskAnalysisSpatialResult>()
    mockedGetResult.mockReturnValueOnce(resultRequest.promise)
    mockedGetSpatialResult.mockReturnValueOnce(spatialRequest.promise)

    const opening = store.openTask(task)
    const revision = store.detailRevision
    await store.openTask(task)

    expect(store.detailRevision).toBe(revision)
    expect(mockedGetResult).toHaveBeenCalledTimes(1)
    expect(mockedGetSpatialResult).not.toHaveBeenCalled()

    resultRequest.resolve(riskResult())
    spatialRequest.resolve(spatialResult())
    await opening
    await Promise.resolve()
    expect(mockedGetSpatialResult).toHaveBeenCalledTimes(1)
    await store.openTask(task)

    expect(store.detailRevision).toBe(revision)
    expect(mockedGetResult).toHaveBeenCalledTimes(1)
    expect(mockedGetSpatialResult).toHaveBeenCalledTimes(1)
  })

  it('keeps the final result when the independent spatial request fails', async () => {
    const store = useTaskHistoryStore()
    const task = historyResponse().items[0]!
    mockedGetResult.mockResolvedValueOnce(riskResult())
    mockedGetSpatialResult.mockRejectedValueOnce(new Error('spatial unavailable'))

    await store.openTask(task)

    expect(store.selectedResult?.task_id).toBe('task-1')
    expect(store.detailError).toBeNull()
    expect(store.spatialError).toBe('spatial unavailable')
  })

  it.each(['success', 'error'] as const)(
    'ignores a late task A spatial %s after task B is selected',
    async (outcome) => {
      const store = useTaskHistoryStore()
      const taskA = historyResponse('SUCCEEDED', true, 'task-a').items[0]!
      const taskB = historyResponse('SUCCEEDED', true, 'task-b').items[0]!
      const spatialA = deferred<RiskAnalysisSpatialResult>()
      mockedGetResult.mockImplementation((taskId) => Promise.resolve(riskResult(taskId)))
      mockedGetSpatialResult
        .mockReturnValueOnce(spatialA.promise)
        .mockResolvedValueOnce(spatialResult('task-b'))

      await store.openTask(taskA)
      await store.openTask(taskB)
      if (outcome === 'success') spatialA.resolve(spatialResult('task-a'))
      else spatialA.reject(new Error('late task A failure'))
      await Promise.resolve()

      expect(store.selectedTaskId).toBe('task-b')
      expect(store.selectedSpatialResult?.task_id).toBe('task-b')
      expect(store.spatialError).toBeNull()
    },
  )

  it.each(['success', 'error'] as const)(
    'ignores a late spatial %s after closing the detail',
    async (outcome) => {
      const store = useTaskHistoryStore()
      const task = historyResponse().items[0]!
      const spatialRequest = deferred<RiskAnalysisSpatialResult>()
      mockedGetResult.mockResolvedValueOnce(riskResult())
      mockedGetSpatialResult.mockReturnValueOnce(spatialRequest.promise)

      await store.openTask(task)
      store.closeDetail()
      if (outcome === 'success') spatialRequest.resolve(spatialResult())
      else spatialRequest.reject(new Error('late closed detail failure'))
      await Promise.resolve()

      expect(store.selectedTaskId).toBeNull()
      expect(store.selectedSpatialResult).toBeNull()
      expect(store.spatialError).toBeNull()
    },
  )

  it('uses a new revision when a closed task is reopened and ignores its old response', async () => {
    const store = useTaskHistoryStore()
    const task = historyResponse().items[0]!
    const oldSpatial = deferred<RiskAnalysisSpatialResult>()
    mockedGetResult.mockResolvedValue(riskResult())
    mockedGetSpatialResult
      .mockReturnValueOnce(oldSpatial.promise)
      .mockResolvedValueOnce(spatialResult('task-1', 1))

    await store.openTask(task)
    const firstRevision = store.detailRevision
    store.closeDetail()
    await store.openTask(task)
    oldSpatial.resolve(spatialResult('task-1', 0))
    await Promise.resolve()

    expect(store.detailRevision).toBeGreaterThan(firstRevision)
    expect(store.selectedSpatialResult?.feature_collection.features[0]?.properties.value).toBe(1)
  })
})
