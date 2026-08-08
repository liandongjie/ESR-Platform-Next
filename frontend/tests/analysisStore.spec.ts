import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAnalysisAreaBuffer } from '@/api/analysisAreas'
import {
  createRiskAnalysisJob,
  getRiskAnalysisJob,
  getRiskAnalysisResult,
} from '@/api/riskAnalysis'
import { useAnalysisStore } from '@/stores/analysis'
import type { AnalysisAreaBufferResponse } from '@/types/analysisArea'
import type { RiskAnalysisResult } from '@/types/riskAnalysis'

vi.mock('@/api/analysisAreas', () => ({
  createAnalysisAreaBuffer: vi.fn(),
}))

vi.mock('@/api/riskAnalysis', () => ({
  createRiskAnalysisJob: vi.fn(),
  getRiskAnalysisJob: vi.fn(),
  getRiskAnalysisResult: vi.fn(),
}))

const mockedCreateBuffer = vi.mocked(createAnalysisAreaBuffer)
const mockedCreateJob = vi.mocked(createRiskAnalysisJob)
const mockedGetJob = vi.mocked(getRiskAnalysisJob)
const mockedGetResult = vi.mocked(getRiskAnalysisResult)

function makeBufferResponse(distanceM = 3000): AnalysisAreaBufferResponse {
  return {
    source: {
      crs: 'EPSG:4326',
      geometry_type: 'Point',
      bounds: [118.9, 32.1, 118.9, 32.1],
    },
    buffer: {
      crs: 'EPSG:4326',
      distance_m: distanceM,
      working_crs: 'EPSG:32650',
      area_m2: 28_228_936.4,
      area_km2: 28.2289364,
      bounds: [118.86, 32.07, 118.94, 32.13],
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [118.86, 32.1],
            [118.9, 32.13],
            [118.94, 32.1],
            [118.86, 32.1],
          ],
        ],
      },
    },
  }
}

function makeRiskResult(): RiskAnalysisResult {
  return {
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
      minimum: 0.36429525,
      maximum: 0.41313311,
      mean: 0.38284404,
    },
    indicators: [
      {
        code: 'PM25',
        name: 'PM2.5',
        weight_percent: 30,
        statistics: {
          valid_pixel_count: 28,
          minimum: 0.2,
          maximum: 0.6,
          mean: 0.4,
        },
      },
    ],
    artifacts: {
      raster: 'risk-analysis/task-1/risk.tif',
      manifest: 'risk-analysis/task-1/result.json',
    },
  }
}

async function prepareBuffer(store: ReturnType<typeof useAnalysisStore>) {
  mockedCreateBuffer.mockResolvedValueOnce(makeBufferResponse())
  store.setSourcePoint([118.9, 32.1])
  await store.createBuffer()
}

describe('analysis store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedCreateBuffer.mockReset()
    mockedCreateJob.mockReset()
    mockedGetJob.mockReset()
    mockedGetResult.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('stores WGS84 point and clears stale buffer when point changes', async () => {
    mockedCreateBuffer.mockResolvedValueOnce(makeBufferResponse())
    const store = useAnalysisStore()

    store.setSourcePoint([118.9, 32.1])
    await store.createBuffer()
    expect(store.bufferResult?.buffer.area_km2).toBeCloseTo(28.2289364)

    store.setSourcePoint([118.91, 32.11])
    expect(store.sourceGeometryWgs84?.coordinates).toEqual([118.91, 32.11])
    expect(store.bufferResult).toBeNull()
  })

  it('ignores a late buffer response after the user selects another point', async () => {
    let resolveRequest: ((value: AnalysisAreaBufferResponse) => void) | undefined
    mockedCreateBuffer.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveRequest = resolve
        }),
    )
    const store = useAnalysisStore()

    store.setSourcePoint([118.9, 32.1])
    const pending = store.createBuffer()
    store.setSourcePoint([118.92, 32.12])
    resolveRequest?.(makeBufferResponse())
    await pending

    expect(store.sourceGeometryWgs84?.coordinates).toEqual([118.92, 32.12])
    expect(store.bufferResult).toBeNull()
    expect(store.bufferLoading).toBe(false)
  })

  it('clears old buffer when distance changes', async () => {
    mockedCreateBuffer.mockResolvedValueOnce(makeBufferResponse())
    const store = useAnalysisStore()

    store.setSourcePoint([118.9, 32.1])
    await store.createBuffer()
    store.setBufferDistance(5000)

    expect(store.bufferDistanceMeters).toBe(5000)
    expect(store.bufferResult).toBeNull()
  })

  it(
    'uses the default 30/40/30 weights and invalidates old task results when weights change',
    async () => {
      const store = useAnalysisStore()
      expect(store.weights).toEqual([
        { code: 'PM25', weight_percent: 30 },
        { code: 'AQI', weight_percent: 40 },
        { code: 'NDVI', weight_percent: 30 },
      ])

      store.result = makeRiskResult()
      store.setWeight('PM25', 35)

      expect(store.weights[0]?.weight_percent).toBe(35)
      expect(store.result).toBeNull()
    },
  )

  it('polls until SUCCEEDED with result_available and then loads the real result', async () => {
    vi.useFakeTimers()
    const store = useAnalysisStore()
    await prepareBuffer(store)

    mockedCreateJob.mockResolvedValueOnce({
      job: {
        task_id: 'task-1',
        status: 'QUEUED',
        submitted_at: '2026-08-07T12:00:00Z',
        status_url: '/api/v1/risk-analysis/jobs/task-1',
        result_url: '/api/v1/risk-analysis/jobs/task-1/result',
      },
      retryAfterMs: 2000,
    })
    mockedGetJob.mockResolvedValueOnce({
      task_id: 'task-1',
      status: 'SUCCEEDED',
      stage: 'COMPLETED',
      progress: 100,
      result_available: true,
      submitted_at: '2026-08-07T12:00:00Z',
    })
    mockedGetResult.mockResolvedValueOnce(makeRiskResult())

    await store.submitRiskAnalysis()
    expect(store.polling).toBe(true)
    expect(store.jobStatus?.status).toBe('QUEUED')

    await vi.advanceTimersByTimeAsync(2000)

    expect(mockedGetJob).toHaveBeenCalledWith('task-1')
    expect(mockedGetResult).toHaveBeenCalledWith('task-1')
    expect(store.result?.statistics.valid_pixel_count).toBe(28)
    expect(store.jobStatus?.status).toBe('SUCCEEDED')
    expect(store.polling).toBe(false)
  })

  it(
    'does not fetch result while Celery is SUCCEEDED but result manifest is not visible yet',
    async () => {
      vi.useFakeTimers()
      const store = useAnalysisStore()
      await prepareBuffer(store)

      mockedCreateJob.mockResolvedValueOnce({
        job: {
          task_id: 'task-1',
          status: 'QUEUED',
          submitted_at: '2026-08-07T12:00:00Z',
          status_url: '/api/v1/risk-analysis/jobs/task-1',
          result_url: '/api/v1/risk-analysis/jobs/task-1/result',
        },
        retryAfterMs: 2000,
      })
      mockedGetJob
        .mockResolvedValueOnce({
          task_id: 'task-1',
          status: 'SUCCEEDED',
          stage: 'FINALIZING',
          progress: 100,
          result_available: false,
          submitted_at: '2026-08-07T12:00:00Z',
        })
        .mockResolvedValueOnce({
          task_id: 'task-1',
          status: 'SUCCEEDED',
          stage: 'COMPLETED',
          progress: 100,
          result_available: true,
          submitted_at: '2026-08-07T12:00:00Z',
        })
      mockedGetResult.mockResolvedValueOnce(makeRiskResult())

      await store.submitRiskAnalysis()
      await vi.advanceTimersByTimeAsync(2000)
      expect(mockedGetResult).not.toHaveBeenCalled()
      expect(store.polling).toBe(true)

      await vi.advanceTimersByTimeAsync(2000)
      expect(mockedGetResult).toHaveBeenCalledTimes(1)
      expect(store.polling).toBe(false)
    },
  )

  it('keeps the running task and locks analysis inputs until it reaches a terminal state', async () => {
    vi.useFakeTimers()
    const store = useAnalysisStore()
    await prepareBuffer(store)

    mockedCreateJob.mockResolvedValueOnce({
      job: {
        task_id: 'task-1',
        status: 'QUEUED',
        submitted_at: '2026-08-07T12:00:00Z',
        status_url: '/api/v1/risk-analysis/jobs/task-1',
        result_url: '/api/v1/risk-analysis/jobs/task-1/result',
      },
      retryAfterMs: 2000,
    })
    mockedGetJob.mockResolvedValueOnce({
      task_id: 'task-1',
      status: 'SUCCEEDED',
      stage: 'COMPLETED',
      progress: 100,
      result_available: true,
      submitted_at: '2026-08-07T12:00:00Z',
    })
    mockedGetResult.mockResolvedValueOnce(makeRiskResult())

    await store.submitRiskAnalysis()
    const originalPoint = store.sourceGeometryWgs84?.coordinates
    const originalWeight = store.weights[0]?.weight_percent

    store.setSourcePoint([118.91, 32.11])
    store.setBufferDistance(4000)
    store.setWeight('PM25', 35)

    expect(store.analysisLocked).toBe(true)
    expect(store.sourceGeometryWgs84?.coordinates).toEqual(originalPoint)
    expect(store.bufferDistanceMeters).toBe(3000)
    expect(store.weights[0]?.weight_percent).toBe(originalWeight)
    expect(store.job?.task_id).toBe('task-1')
    expect(store.polling).toBe(true)

    await vi.advanceTimersByTimeAsync(2000)
    expect(store.result?.task_id).toBe('task-1')
    expect(store.analysisLocked).toBe(false)
  })

  it('blocks duplicate submission after polling failures and can resume the same task', async () => {
    vi.useFakeTimers()
    const store = useAnalysisStore()
    await prepareBuffer(store)

    mockedCreateJob.mockResolvedValueOnce({
      job: {
        task_id: 'task-1',
        status: 'QUEUED',
        submitted_at: '2026-08-07T12:00:00Z',
        status_url: '/api/v1/risk-analysis/jobs/task-1',
        result_url: '/api/v1/risk-analysis/jobs/task-1/result',
      },
      retryAfterMs: 2000,
    })
    mockedGetJob
      .mockRejectedValueOnce(new Error('status unavailable'))
      .mockRejectedValueOnce(new Error('status unavailable'))
      .mockRejectedValueOnce(new Error('status unavailable'))

    await store.submitRiskAnalysis()
    await vi.advanceTimersByTimeAsync(6000)

    expect(store.polling).toBe(false)
    expect(store.analysisLocked).toBe(true)
    expect(store.canResumePolling).toBe(true)

    await store.submitRiskAnalysis()
    expect(mockedCreateJob).toHaveBeenCalledTimes(1)

    mockedGetJob.mockResolvedValueOnce({
      task_id: 'task-1',
      status: 'SUCCEEDED',
      stage: 'COMPLETED',
      progress: 100,
      result_available: true,
      submitted_at: '2026-08-07T12:00:00Z',
    })
    mockedGetResult.mockResolvedValueOnce(makeRiskResult())

    store.resumeRiskAnalysisPolling()
    await vi.advanceTimersByTimeAsync(2000)

    expect(mockedGetJob).toHaveBeenCalledTimes(4)
    expect(store.result?.task_id).toBe('task-1')
    expect(store.analysisLocked).toBe(false)
    expect(store.canResumePolling).toBe(false)
  })
})
