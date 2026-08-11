import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAnalysisAreaBuffer } from '@/api/analysisAreas'
import {
  createRiskAnalysisJob,
  getRiskAnalysisJob,
  getRiskAnalysisResult,
  getRiskAnalysisSpatialResult,
  getRiskAnalysisSubmission,
} from '@/api/riskAnalysis'
import { searchAmapPois } from '@/map/amapPoi'
import { useAnalysisStore } from '@/stores/analysis'
import type { AnalysisAreaBufferResponse } from '@/types/analysisArea'
import type { PoiDto, PoiSearchResult } from '@/types/poi'
import type {
  RiskAnalysisJobStatus,
  RiskAnalysisResult,
  RiskAnalysisSpatialResult,
  RiskAnalysisSubmissionDetail,
} from '@/types/riskAnalysis'

vi.mock('@/api/analysisAreas', () => ({
  createAnalysisAreaBuffer: vi.fn(),
}))

vi.mock('@/api/riskAnalysis', () => ({
  createRiskAnalysisJob: vi.fn(),
  getRiskAnalysisJob: vi.fn(),
  getRiskAnalysisResult: vi.fn(),
  getRiskAnalysisSpatialResult: vi.fn(),
  getRiskAnalysisSubmission: vi.fn(),
}))

vi.mock('@/map/amapPoi', () => ({
  searchAmapPois: vi.fn(),
}))

const mockedCreateBuffer = vi.mocked(createAnalysisAreaBuffer)
const mockedCreateJob = vi.mocked(createRiskAnalysisJob)
const mockedGetJob = vi.mocked(getRiskAnalysisJob)
const mockedGetResult = vi.mocked(getRiskAnalysisResult)
const mockedGetSpatialResult = vi.mocked(getRiskAnalysisSpatialResult)
const mockedGetSubmission = vi.mocked(getRiskAnalysisSubmission)
const mockedSearchPois = vi.mocked(searchAmapPois)
const workspaceTaskStorageKey = 'esr:risk-analysis:workspace-task-id'
const workspaceDraftStorageKey = 'esr:risk-analysis:workspace-draft'

function makeDraft(bufferReady: boolean) {
  return {
    source_point_wgs84: [118.9, 32.1],
    buffer_distance_m: 3000,
    weights: [
      { code: 'PM25', weight_percent: 35 },
      { code: 'AQI', weight_percent: 35 },
      { code: 'NDVI', weight_percent: 30 },
    ],
    buffer_ready: bufferReady,
  }
}

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

function makeSpatialResult(taskId = 'task-1'): RiskAnalysisSpatialResult {
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
          properties: { value: 0 },
        },
      ],
    },
  }
}

function makeSubmission(): RiskAnalysisSubmissionDetail {
  return {
    task_id: 'task-1',
    submitted_at: '2026-08-07T12:00:00Z',
    request: {
      geometry: makeBufferResponse().buffer.geometry,
      weights: [
        { code: 'PM25', weight_percent: 30 },
        { code: 'AQI', weight_percent: 40 },
        { code: 'NDVI', weight_percent: 30 },
      ],
    },
  }
}

async function prepareBuffer(store: ReturnType<typeof useAnalysisStore>) {
  mockedCreateBuffer.mockResolvedValueOnce(makeBufferResponse())
  store.setSourcePoint([118.9, 32.1])
  await store.createBuffer()
}

function makePoi(id: string): PoiDto {
  return {
    id,
    name: `POI ${id}`,
    type: '科教文化服务',
    typeCode: '141200',
    address: '南京市',
    locationWgs84: [118.81, 32.02],
  }
}

function makePoiPage(
  page: number,
  total: number,
  count: number,
  prefix = `page-${page}`,
): PoiSearchResult {
  return {
    items: Array.from({ length: count }, (_, index) => makePoi(`${prefix}-${index}`)),
    total,
    page,
    pageSize: 50,
  }
}

async function preparePoiQuery(store: ReturnType<typeof useAnalysisStore>, total = 116) {
  await prepareBuffer(store)
  store.setPoiKeyword('学校')
  mockedSearchPois.mockResolvedValueOnce({
    items: [makePoi('visible-1')],
    total,
    page: 1,
    pageSize: 10,
  })
  await store.searchPois(1)
  mockedSearchPois.mockClear()
}

describe('analysis store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedCreateBuffer.mockReset()
    mockedCreateJob.mockReset()
    mockedGetJob.mockReset()
    mockedGetResult.mockReset()
    mockedGetSpatialResult.mockReset()
    mockedGetSpatialResult.mockResolvedValue(makeSpatialResult())
    mockedGetSubmission.mockReset()
    mockedGetSubmission.mockResolvedValue(makeSubmission())
    mockedSearchPois.mockReset()
    window.sessionStorage.clear()
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

  it('searches one real POI page from the current Polygon Buffer', async () => {
    const store = useAnalysisStore()
    await prepareBuffer(store)
    store.setPoiKeyword('学校')
    mockedSearchPois.mockResolvedValueOnce({
      items: [
        {
          id: 'poi-1',
          name: '学校一',
          type: '',
          typeCode: '',
          address: '',
          locationWgs84: [118.81, 32.02],
        },
      ],
      total: 44,
      page: 2,
      pageSize: 10,
    })

    await store.searchPois(2)

    expect(mockedSearchPois).toHaveBeenCalledOnce()
    expect(mockedSearchPois).toHaveBeenCalledWith({
      geometry: makeBufferResponse().buffer.geometry,
      keyword: '学校',
      page: 2,
      pageSize: 10,
    })
    expect(store.poiItems[0]?.id).toBe('poi-1')
    expect(store.poiTotal).toBe(44)
    expect(store.poiPage).toBe(2)
    expect(store.poiHasSearched).toBe(true)
  })

  it('ignores a late POI response after the keyword changes', async () => {
    const store = useAnalysisStore()
    await prepareBuffer(store)
    let resolveSearch:
      | ((value: Awaited<ReturnType<typeof searchAmapPois>>) => void)
      | undefined
    mockedSearchPois.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSearch = resolve
        }),
    )
    store.setPoiKeyword('学校')

    const pending = store.searchPois(1)
    store.setPoiKeyword('医院')
    resolveSearch?.({
      items: [
        {
          id: 'old',
          name: '旧结果',
          type: '',
          typeCode: '',
          address: '',
          locationWgs84: [118.81, 32.02],
        },
      ],
      total: 1,
      page: 1,
      pageSize: 10,
    })
    await pending

    expect(store.poiKeyword).toBe('医院')
    expect(store.poiItems).toEqual([])
    expect(store.poiTotal).toBe(0)
    expect(store.poiLoading).toBe(false)
  })

  it.each(['success', 'error'] as const)(
    'keeps page 2 when the late page 1 request ends with %s',
    async (outcome) => {
      const store = useAnalysisStore()
      await prepareBuffer(store)
      let resolveFirst:
        | ((value: Awaited<ReturnType<typeof searchAmapPois>>) => void)
        | undefined
      let rejectFirst: ((reason: Error) => void) | undefined
      let resolveSecond:
        | ((value: Awaited<ReturnType<typeof searchAmapPois>>) => void)
        | undefined
      mockedSearchPois
        .mockImplementationOnce(
          () =>
            new Promise((resolve, reject) => {
              resolveFirst = resolve
              rejectFirst = reject
            }),
        )
        .mockImplementationOnce(
          () =>
            new Promise((resolve) => {
              resolveSecond = resolve
            }),
        )
      store.setPoiKeyword('学校')

      const page1 = store.searchPois(1)
      const page2 = store.searchPois(2)
      resolveSecond?.({
        items: [
          {
            id: 'page-2',
            name: '第二页',
            type: '',
            typeCode: '',
            address: '',
            locationWgs84: [118.82, 32.03],
          },
        ],
        total: 44,
        page: 2,
        pageSize: 10,
      })
      await page2

      if (outcome === 'success') {
        resolveFirst?.({
          items: [
            {
              id: 'page-1',
              name: '第一页',
              type: '',
              typeCode: '',
              address: '',
              locationWgs84: [118.81, 32.02],
            },
          ],
          total: 44,
          page: 1,
          pageSize: 10,
        })
      } else {
        rejectFirst?.(new Error('late page 1 failure'))
      }
      await page1

      expect(mockedSearchPois).toHaveBeenNthCalledWith(1, expect.objectContaining({ page: 1 }))
      expect(mockedSearchPois).toHaveBeenNthCalledWith(2, expect.objectContaining({ page: 2 }))
      expect(store.poiPage).toBe(2)
      expect(store.poiItems.map((item) => item.id)).toEqual(['page-2'])
      expect(store.poiTotal).toBe(44)
      expect(store.poiError).toBeNull()
      expect(store.poiLoading).toBe(false)
    },
  )

  it('immediately invalidates POIs and ignores the late response when Buffer changes', async () => {
    const store = useAnalysisStore()
    await prepareBuffer(store)
    let resolveSearch:
      | ((value: Awaited<ReturnType<typeof searchAmapPois>>) => void)
      | undefined
    mockedSearchPois.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSearch = resolve
        }),
    )
    store.setPoiKeyword('学校')

    const pending = store.searchPois(1)
    store.setBufferDistance(5000)
    expect(store.poiItems).toEqual([])
    expect(store.poiLoading).toBe(false)

    resolveSearch?.({
      items: [
        {
          id: 'old',
          name: '旧结果',
          type: '',
          typeCode: '',
          address: '',
          locationWgs84: [118.81, 32.02],
        },
      ],
      total: 1,
      page: 1,
      pageSize: 10,
    })
    await pending
    expect(store.poiItems).toEqual([])
    expect(store.poiTotal).toBe(0)
  })

  it('rejects MultiPolygon Buffer without calling the POI provider', async () => {
    const store = useAnalysisStore()
    await prepareBuffer(store)
    const polygon = makeBufferResponse().buffer.geometry
    if (polygon.type !== 'Polygon') throw new Error('test fixture must be Polygon')
    store.bufferResult!.buffer.geometry = {
      type: 'MultiPolygon',
      coordinates: [polygon.coordinates],
    }
    store.setPoiKeyword('学校')

    await store.searchPois(1)

    expect(store.poiError).toBe('当前 POI 查询暂不支持 MultiPolygon 缓冲区')
    expect(mockedSearchPois).not.toHaveBeenCalled()
  })

  it('prepares only the current visible page without another provider request', async () => {
    const store = useAnalysisStore()
    await preparePoiQuery(store, 44)

    const data = store.prepareCurrentPagePoiExport()

    expect(mockedSearchPois).not.toHaveBeenCalled()
    expect(data).toMatchObject({
      mode: 'current-page',
      keyword: '学校',
      page: 1,
      totalReported: 44,
      retrievableLimit: 44,
      exportedCount: 1,
      items: [{ id: 'visible-1' }],
    })

    store.poiItems = []
    expect(store.prepareCurrentPagePoiExport()).toBeNull()
    expect(store.poiExportError).toBe('当前页没有可导出的 POI 数据')
    expect(mockedSearchPois).not.toHaveBeenCalled()
  })

  it('fixes the export plan from page 1 and caps an oversized final page', async () => {
    const store = useAnalysisStore()
    await preparePoiQuery(store)
    const pageBefore = store.poiPage
    const itemsBefore = store.poiItems
    const totalBefore = store.poiTotal
    mockedSearchPois
      .mockResolvedValueOnce(makePoiPage(1, 116, 50))
      .mockResolvedValueOnce(makePoiPage(2, 166, 50))
      .mockResolvedValueOnce(makePoiPage(3, 90, 30))

    const data = await store.collectRetrievablePoiExport()

    expect(mockedSearchPois).toHaveBeenCalledTimes(3)
    expect(mockedSearchPois.mock.calls.map(([request]) => request.page)).toEqual([1, 2, 3])
    expect(mockedSearchPois.mock.calls.every(([request]) => request.pageSize === 50)).toBe(true)
    expect(data).toMatchObject({
      totalReported: 116,
      retrievableLimit: 116,
      exportedCount: 116,
    })
    expect(data?.items.at(-1)?.id).toBe('page-3-15')
    expect(store.poiPage).toBe(pageBefore)
    expect(store.poiItems).toBe(itemsBefore)
    expect(store.poiTotal).toBe(totalBefore)
  })

  it('exports the actual first-page rows when count exceeds returned POIs', async () => {
    const store = useAnalysisStore()
    await preparePoiQuery(store, 15)
    mockedSearchPois.mockResolvedValueOnce(makePoiPage(1, 15, 14))

    const data = await store.collectRetrievablePoiExport()

    expect(mockedSearchPois).toHaveBeenCalledOnce()
    expect(data).toMatchObject({
      totalReported: 15,
      retrievableLimit: 15,
      exportedCount: 14,
    })
    expect(store.poiExportError).toBeNull()
  })

  it('stops after an empty first export page without retrying', async () => {
    const store = useAnalysisStore()
    await preparePoiQuery(store)
    mockedSearchPois.mockResolvedValueOnce({ items: [], total: 0, page: 1, pageSize: 50 })

    await expect(store.collectRetrievablePoiExport()).resolves.toBeNull()

    expect(mockedSearchPois).toHaveBeenCalledOnce()
    expect(mockedSearchPois).toHaveBeenCalledWith(expect.objectContaining({ page: 1, pageSize: 50 }))
    expect(store.poiExportLoading).toBe(false)
    expect(store.poiExportError).toBe('当前查询没有可导出的 POI 数据')
  })

  it('continues after short pages and consumes at most retrievableLimit raw rows', async () => {
    const store = useAnalysisStore()
    await preparePoiQuery(store)
    mockedSearchPois
      .mockResolvedValueOnce(makePoiPage(1, 116, 49))
      .mockResolvedValueOnce(makePoiPage(2, 166, 50))
      .mockResolvedValueOnce(makePoiPage(3, 90, 30))

    const data = await store.collectRetrievablePoiExport()

    expect(mockedSearchPois).toHaveBeenCalledTimes(3)
    expect(data).toMatchObject({
      totalReported: 116,
      retrievableLimit: 116,
      exportedCount: 116,
    })
    expect(data?.items.at(-1)?.id).toBe('page-3-16')
    expect(store.poiExportError).toBeNull()
  })

  it('stops successfully when a later planned page is empty', async () => {
    const store = useAnalysisStore()
    await preparePoiQuery(store)
    mockedSearchPois
      .mockResolvedValueOnce(makePoiPage(1, 116, 50))
      .mockResolvedValueOnce({ items: [], total: 0, page: 2, pageSize: 50 })

    const data = await store.collectRetrievablePoiExport()

    expect(mockedSearchPois).toHaveBeenCalledTimes(2)
    expect(data).toMatchObject({
      totalReported: 116,
      retrievableLimit: 116,
      exportedCount: 50,
    })
    expect(store.poiExportError).toBeNull()
  })

  it.each(['SDK error', 'malformed complete'])(
    'stops after a provider %s without retrying',
    async (message) => {
      const store = useAnalysisStore()
      await preparePoiQuery(store)
      mockedSearchPois
        .mockResolvedValueOnce(makePoiPage(1, 116, 50))
        .mockRejectedValueOnce(new Error(message))

      await expect(store.collectRetrievablePoiExport()).resolves.toBeNull()

      expect(mockedSearchPois).toHaveBeenCalledTimes(2)
      expect(store.poiExportError).toContain(message)
    },
  )

  it('requests at most 100 fixed-size pages when totalReported exceeds 5000', async () => {
    const store = useAnalysisStore()
    await preparePoiQuery(store, 5001)
    mockedSearchPois.mockImplementation((request) =>
      Promise.resolve(makePoiPage(request.page, 5001, 50)),
    )

    const data = await store.collectRetrievablePoiExport()

    expect(mockedSearchPois).toHaveBeenCalledTimes(100)
    expect(mockedSearchPois).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 100, pageSize: 50 }),
    )
    expect(data).toMatchObject({
      totalReported: 5001,
      retrievableLimit: 5000,
      exportedCount: 5000,
    })
  })

  it('deduplicates all-page results by strict POI ID in first-seen order', async () => {
    const store = useAnalysisStore()
    await preparePoiQuery(store, 100)
    const page1 = makePoiPage(1, 100, 50)
    const page2 = makePoiPage(2, 100, 50)
    page2.items[0] = page1.items[0]!
    mockedSearchPois.mockResolvedValueOnce(page1).mockResolvedValueOnce(page2)

    const data = await store.collectRetrievablePoiExport()

    expect(data?.exportedCount).toBe(99)
    expect(data?.items[0]?.id).toBe('page-1-0')
    expect(data?.items[50]?.id).toBe('page-2-1')
  })

  it('does not cancel an export when only the input draft changes', async () => {
    const store = useAnalysisStore()
    await preparePoiQuery(store, 1)
    let resolveExport: ((value: PoiSearchResult) => void) | undefined
    mockedSearchPois.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveExport = resolve
        }),
    )

    const pending = store.collectRetrievablePoiExport()
    store.setPoiKeyword('医院')
    resolveExport?.(makePoiPage(1, 1, 1))

    await expect(pending).resolves.toMatchObject({ keyword: '学校', exportedCount: 1 })
    expect(store.poiExportError).toBeNull()
  })

  it('keeps a newer export session immune to every late write from a canceled session', async () => {
    const store = useAnalysisStore()
    await preparePoiQuery(store, 116)
    let resolveOldExport: ((value: PoiSearchResult) => void) | undefined
    mockedSearchPois
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveOldExport = resolve
          }),
      )
      .mockResolvedValueOnce({ items: [makePoi('hospital')], total: 1, page: 1, pageSize: 10 })
      .mockResolvedValueOnce(makePoiPage(1, 1, 1, 'new'))

    const oldExport = store.collectRetrievablePoiExport()
    store.setPoiKeyword('医院')
    await store.searchPois(1)
    expect(store.poiExportError).toBe('查询条件已变化，导出已取消')

    const newExport = await store.collectRetrievablePoiExport()
    expect(newExport).toMatchObject({ keyword: '医院', exportedCount: 1 })
    expect(store.poiExportError).toBeNull()
    expect(store.poiExportLoading).toBe(false)

    resolveOldExport?.(makePoiPage(1, 116, 50, 'old'))
    await expect(oldExport).resolves.toBeNull()

    expect(mockedSearchPois).toHaveBeenCalledTimes(3)
    expect(store.poiExportError).toBeNull()
    expect(store.poiExportLoading).toBe(false)
    expect(store.poiExportProgress).toBeNull()
  })

  it('cancels an export after Buffer context changes and ignores its late page', async () => {
    const store = useAnalysisStore()
    await preparePoiQuery(store, 116)
    let resolveExport: ((value: PoiSearchResult) => void) | undefined
    mockedSearchPois.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveExport = resolve
        }),
    )

    const pending = store.collectRetrievablePoiExport()
    store.setBufferDistance(5000)
    expect(store.poiExportError).toBe('查询条件已变化，导出已取消')
    resolveExport?.(makePoiPage(1, 116, 50))

    await expect(pending).resolves.toBeNull()
    expect(mockedSearchPois).toHaveBeenCalledOnce()
    expect(store.poiExportLoading).toBe(false)
  })

  it('does not cancel an all-page export during ordinary result pagination', async () => {
    const store = useAnalysisStore()
    await preparePoiQuery(store, 1)
    let resolveExport: ((value: PoiSearchResult) => void) | undefined
    mockedSearchPois.mockImplementation((request) => {
      if (request.pageSize === 10) {
        return Promise.resolve({ items: [makePoi('visible-2')], total: 1, page: 2, pageSize: 10 })
      }
      return new Promise((resolve) => {
        resolveExport = resolve
      })
    })

    const pending = store.collectRetrievablePoiExport()
    await store.searchPois(2)
    resolveExport?.(makePoiPage(1, 1, 1))

    await expect(pending).resolves.toMatchObject({ exportedCount: 1 })
    expect(store.poiExportError).toBeNull()
  })

  it('rejects MultiPolygon export without calling the POI provider', async () => {
    const store = useAnalysisStore()
    await preparePoiQuery(store)
    const polygon = makeBufferResponse().buffer.geometry
    if (polygon.type !== 'Polygon') throw new Error('test fixture must be Polygon')
    store.bufferResult!.buffer.geometry = {
      type: 'MultiPolygon',
      coordinates: [polygon.coordinates],
    }

    await expect(store.collectRetrievablePoiExport()).resolves.toBeNull()

    expect(store.poiExportError).toContain('暂不支持 MultiPolygon')
    expect(mockedSearchPois).not.toHaveBeenCalled()
  })

  it('rejects a Polygon Buffer with an inner ring without calling the POI provider', async () => {
    const store = useAnalysisStore()
    await preparePoiQuery(store)
    const polygon = makeBufferResponse().buffer.geometry
    if (polygon.type !== 'Polygon') throw new Error('test fixture must be Polygon')
    store.bufferResult!.buffer.geometry = {
      type: 'Polygon',
      coordinates: [
        polygon.coordinates[0]!,
        [
          [118.88, 32.1],
          [118.9, 32.11],
          [118.91, 32.1],
          [118.88, 32.1],
        ],
      ],
    }

    await expect(store.collectRetrievablePoiExport()).resolves.toBeNull()

    expect(store.poiExportError).toContain('不含内部孔洞')
    expect(mockedSearchPois).not.toHaveBeenCalled()
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

  it('persists only draft inputs and marks the buffer ready after an accepted response', async () => {
    mockedCreateBuffer.mockResolvedValueOnce(makeBufferResponse())
    const store = useAnalysisStore()

    store.setSourcePoint([118.9, 32.1])
    store.setBufferDistance(4000)
    await store.createBuffer()
    store.setWeight('PM25', 35)

    const draft = JSON.parse(window.sessionStorage.getItem(workspaceDraftStorageKey) ?? '{}')
    expect(draft).toEqual({
      source_point_wgs84: [118.9, 32.1],
      buffer_distance_m: 4000,
      weights: [
        { code: 'PM25', weight_percent: 35 },
        { code: 'AQI', weight_percent: 40 },
        { code: 'NDVI', weight_percent: 30 },
      ],
      buffer_ready: true,
    })
    expect(JSON.stringify(draft)).not.toMatch(/geometry|area|working_crs|gcj|viewport/i)

    store.setBufferDistance(5000)
    expect(JSON.parse(window.sessionStorage.getItem(workspaceDraftStorageKey) ?? '{}')).toMatchObject(
      { buffer_distance_m: 5000, buffer_ready: false },
    )
  })

  it('restores draft inputs without creating a buffer when none had succeeded', async () => {
    window.sessionStorage.setItem(workspaceDraftStorageKey, JSON.stringify(makeDraft(false)))
    const store = useAnalysisStore()

    await store.restoreRiskAnalysis()

    expect(store.sourceGeometryWgs84?.coordinates).toEqual([118.9, 32.1])
    expect(store.bufferDistanceMeters).toBe(3000)
    expect(store.weights).toEqual(makeDraft(false).weights)
    expect(store.bufferResult).toBeNull()
    expect(mockedCreateBuffer).not.toHaveBeenCalled()
  })

  it('recreates a previously ready buffer through the existing Buffer API', async () => {
    window.sessionStorage.setItem(workspaceDraftStorageKey, JSON.stringify(makeDraft(true)))
    mockedCreateBuffer.mockResolvedValueOnce(makeBufferResponse())
    const store = useAnalysisStore()

    await store.restoreRiskAnalysis()

    expect(mockedCreateBuffer).toHaveBeenCalledWith({
      geometry: { type: 'Point', coordinates: [118.9, 32.1] },
      distance_m: 3000,
    })
    expect(store.bufferResult).toEqual(makeBufferResponse())
    expect(JSON.parse(window.sessionStorage.getItem(workspaceDraftStorageKey) ?? '{}')).toMatchObject(
      { buffer_ready: true },
    )
  })

  it('keeps a ready draft when automatic Buffer recovery fails', async () => {
    window.sessionStorage.setItem(workspaceDraftStorageKey, JSON.stringify(makeDraft(true)))
    mockedCreateBuffer.mockRejectedValueOnce(new Error('buffer unavailable'))
    const store = useAnalysisStore()

    await store.restoreRiskAnalysis()

    expect(store.sourceGeometryWgs84?.coordinates).toEqual([118.9, 32.1])
    expect(store.bufferResult).toBeNull()
    expect(store.bufferError).toBe('buffer unavailable')
    expect(JSON.parse(window.sessionStorage.getItem(workspaceDraftStorageKey) ?? '{}')).toMatchObject(
      { buffer_ready: true },
    )
  })

  it('does not let a late draft buffer response mark new inputs ready', async () => {
    window.sessionStorage.setItem(workspaceDraftStorageKey, JSON.stringify(makeDraft(true)))
    let resolveRequest: ((value: AnalysisAreaBufferResponse) => void) | undefined
    mockedCreateBuffer.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveRequest = resolve
        }),
    )
    const store = useAnalysisStore()

    const restoration = store.restoreRiskAnalysis()
    store.setSourcePoint([118.92, 32.12])
    resolveRequest?.(makeBufferResponse())
    await restoration

    expect(store.bufferResult).toBeNull()
    expect(JSON.parse(window.sessionStorage.getItem(workspaceDraftStorageKey) ?? '{}')).toMatchObject(
      { source_point_wgs84: [118.92, 32.12], buffer_ready: false },
    )
  })

  it('discards a malformed draft without calling the Buffer API', async () => {
    window.sessionStorage.setItem(
      workspaceDraftStorageKey,
      JSON.stringify({ ...makeDraft(true), source_point_wgs84: [999, 32.1] }),
    )
    const store = useAnalysisStore()

    await store.restoreRiskAnalysis()

    expect(store.sourceGeometryWgs84).toBeNull()
    expect(mockedCreateBuffer).not.toHaveBeenCalled()
    expect(window.sessionStorage.getItem(workspaceDraftStorageKey)).toBeNull()
  })

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
    expect(mockedGetSpatialResult).toHaveBeenCalledWith('task-1')
    expect(store.result?.statistics.valid_pixel_count).toBe(28)
    expect(store.spatialResult?.task_id).toBe('task-1')
    expect(store.jobStatus?.status).toBe('SUCCEEDED')
    expect(store.polling).toBe(false)
  })

  it('deduplicates spatial requests while the same task is loading and after it succeeds', async () => {
    const store = useAnalysisStore()
    store.job = { task_id: 'task-1' }
    store.result = makeRiskResult()
    let resolveSpatial: ((value: RiskAnalysisSpatialResult) => void) | undefined
    mockedGetSpatialResult.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSpatial = resolve
        }),
    )

    const first = store.loadRiskAnalysisSpatialResult('task-1', store.jobRevision)
    await store.loadRiskAnalysisSpatialResult('task-1', store.jobRevision)
    expect(mockedGetSpatialResult).toHaveBeenCalledTimes(1)

    resolveSpatial?.(makeSpatialResult())
    await first
    await store.loadRiskAnalysisSpatialResult('task-1', store.jobRevision)

    expect(mockedGetSpatialResult).toHaveBeenCalledTimes(1)
    expect(store.spatialResult?.task_id).toBe('task-1')
  })

  it('keeps a succeeded result when the independent spatial request fails', async () => {
    const store = useAnalysisStore()
    store.job = { task_id: 'task-1' }
    store.jobStatus = {
      task_id: 'task-1',
      status: 'SUCCEEDED',
      stage: 'COMPLETED',
      progress: 100,
      result_available: true,
      submitted_at: '2026-08-07T12:00:00Z',
    }
    store.result = makeRiskResult()
    mockedGetSpatialResult.mockRejectedValueOnce(new Error('spatial unavailable'))

    await store.loadRiskAnalysisSpatialResult('task-1', store.jobRevision)

    expect(store.result?.task_id).toBe('task-1')
    expect(store.jobStatus.status).toBe('SUCCEEDED')
    expect(store.taskError).toBeNull()
    expect(store.spatialWarning).toBe('spatial unavailable')
  })

  it.each(['success', 'error'] as const)(
    'ignores a late spatial %s after reset',
    async (outcome) => {
      const store = useAnalysisStore()
      store.job = { task_id: 'task-1' }
      store.result = makeRiskResult()
      let resolveSpatial: ((value: RiskAnalysisSpatialResult) => void) | undefined
      let rejectSpatial: ((reason: Error) => void) | undefined
      mockedGetSpatialResult.mockImplementationOnce(
        () =>
          new Promise((resolve, reject) => {
            resolveSpatial = resolve
            rejectSpatial = reject
          }),
      )

      const request = store.loadRiskAnalysisSpatialResult('task-1', store.jobRevision)
      store.resetRiskAnalysis()
      if (outcome === 'success') resolveSpatial?.(makeSpatialResult())
      else rejectSpatial?.(new Error('late failure'))
      await request

      expect(store.spatialResult).toBeNull()
      expect(store.spatialWarning).toBeNull()
      expect(store.spatialLoading).toBe(false)
    },
  )

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

  it('replaces the old workspace task pointer only after a new task is created', async () => {
    vi.useFakeTimers()
    const store = useAnalysisStore()
    await prepareBuffer(store)
    window.sessionStorage.setItem(workspaceTaskStorageKey, 'old-task')

    let resolveCreate:
      | ((value: Awaited<ReturnType<typeof createRiskAnalysisJob>>) => void)
      | undefined
    mockedCreateJob.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveCreate = resolve
        }),
    )

    const submission = store.submitRiskAnalysis()
    expect(window.sessionStorage.getItem(workspaceTaskStorageKey)).toBeNull()
    expect(window.sessionStorage.getItem(workspaceDraftStorageKey)).not.toBeNull()

    resolveCreate?.({
      job: {
        task_id: 'task-2',
        status: 'QUEUED',
        submitted_at: '2026-08-08T12:00:00Z',
        status_url: '/api/v1/risk-analysis/jobs/task-2',
        result_url: '/api/v1/risk-analysis/jobs/task-2/result',
      },
      retryAfterMs: 2000,
    })
    await submission

    expect(window.sessionStorage.getItem(workspaceTaskStorageKey)).toBe('task-2')
    expect(window.sessionStorage.getItem(workspaceDraftStorageKey)).toBeNull()
    store.resetRiskAnalysis()
    expect(window.sessionStorage.getItem(workspaceTaskStorageKey)).toBeNull()
  })

  it('keeps the draft when submission fails', async () => {
    const store = useAnalysisStore()
    await prepareBuffer(store)
    mockedCreateJob.mockRejectedValueOnce(new Error('submit unavailable'))

    await store.submitRiskAnalysis()

    expect(store.job).toBeNull()
    expect(store.taskError).toBe('submit unavailable')
    expect(window.sessionStorage.getItem(workspaceDraftStorageKey)).not.toBeNull()
  })

  it('keeps the draft when the created task pointer cannot be persisted', async () => {
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
    const originalSetItem = Storage.prototype.setItem
    const setItem = vi
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementation(function (this: Storage, key, value) {
        if (key === workspaceTaskStorageKey) throw new Error('storage unavailable')
        originalSetItem.call(this, key, value)
      })

    try {
      await store.submitRiskAnalysis()

      expect(store.job?.task_id).toBe('task-1')
      expect(window.sessionStorage.getItem(workspaceTaskStorageKey)).toBeNull()
      expect(window.sessionStorage.getItem(workspaceDraftStorageKey)).not.toBeNull()
    } finally {
      setItem.mockRestore()
    }
  })

  it('restores a running task once and reuses the existing polling loop', async () => {
    vi.useFakeTimers()
    window.sessionStorage.setItem(workspaceTaskStorageKey, 'task-1')
    window.sessionStorage.setItem(workspaceDraftStorageKey, JSON.stringify(makeDraft(true)))
    const store = useAnalysisStore()
    let resolveSubmission: ((value: RiskAnalysisSubmissionDetail) => void) | undefined
    mockedGetSubmission.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSubmission = resolve
        }),
    )

    mockedGetJob
      .mockResolvedValueOnce({
        task_id: 'task-1',
        status: 'RUNNING',
        stage: 'ANALYZING',
        progress: 35,
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

    await store.restoreRiskAnalysis()

    expect(store.sourceGeometryWgs84).toBeNull()
    expect(store.job?.task_id).toBe('task-1')
    expect(store.jobStatus?.status).toBe('RUNNING')
    expect(store.polling).toBe(true)
    expect(store.submissionLoading).toBe(true)
    expect(mockedGetJob).toHaveBeenCalledTimes(1)
    expect(mockedGetSubmission).toHaveBeenCalledTimes(1)
    expect(mockedCreateBuffer).not.toHaveBeenCalled()
    expect(window.sessionStorage.getItem(workspaceDraftStorageKey)).toBeNull()

    await store.restoreRiskAnalysis()
    expect(mockedGetJob).toHaveBeenCalledTimes(1)
    expect(mockedGetSubmission).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(2000)

    expect(mockedGetJob).toHaveBeenCalledTimes(2)
    expect(mockedGetResult).toHaveBeenCalledWith('task-1')
    expect(store.result?.task_id).toBe('task-1')
    expect(store.polling).toBe(false)
    expect(store.submissionContext).toBeNull()

    resolveSubmission?.(makeSubmission())
    await vi.advanceTimersByTimeAsync(0)

    expect(store.submissionContext?.request.geometry.type).toBe('Polygon')
    expect(store.weights).toEqual(makeSubmission().request.weights)
    expect(store.weights[0]).not.toBe(store.submissionContext?.request.weights[0])
    store.weights[0]!.weight_percent = 99
    expect(store.submissionContext?.request.weights[0]?.weight_percent).toBe(30)
  })

  it('restores an already completed task without starting polling', async () => {
    window.sessionStorage.setItem(workspaceTaskStorageKey, 'task-1')
    const store = useAnalysisStore()
    mockedGetJob.mockResolvedValueOnce({
      task_id: 'task-1',
      status: 'SUCCEEDED',
      stage: 'COMPLETED',
      progress: 100,
      result_available: true,
      submitted_at: '2026-08-07T12:00:00Z',
    })
    mockedGetResult.mockResolvedValueOnce(makeRiskResult())

    await store.restoreRiskAnalysis()

    expect(mockedGetResult).toHaveBeenCalledWith('task-1')
    expect(store.result?.task_id).toBe('task-1')
    expect(store.polling).toBe(false)
  })

  it('keeps result recovery independent when submission context fails', async () => {
    window.sessionStorage.setItem(workspaceTaskStorageKey, 'task-1')
    const store = useAnalysisStore()
    mockedGetSubmission.mockRejectedValueOnce(new Error('submission unavailable'))
    mockedGetJob.mockResolvedValueOnce({
      task_id: 'task-1',
      status: 'SUCCEEDED',
      stage: 'COMPLETED',
      progress: 100,
      result_available: true,
      submitted_at: '2026-08-07T12:00:00Z',
    })
    mockedGetResult.mockResolvedValueOnce(makeRiskResult())

    await store.restoreRiskAnalysis()

    expect(store.result?.task_id).toBe('task-1')
    expect(store.submissionContext).toBeNull()
    expect(store.submissionError).toBe('提交上下文恢复失败，但任务状态和分析结果不受影响')
    expect(store.taskError).toBeNull()
  })

  it('keeps a draft when a stale task pointer cannot be confirmed', async () => {
    window.sessionStorage.setItem(workspaceTaskStorageKey, 'stale-task')
    window.sessionStorage.setItem(workspaceDraftStorageKey, JSON.stringify(makeDraft(true)))
    mockedGetSubmission.mockRejectedValueOnce(new Error('submission unavailable'))
    mockedGetJob.mockRejectedValueOnce(new Error('task unavailable'))
    const store = useAnalysisStore()

    await store.restoreRiskAnalysis()

    expect(store.sourceGeometryWgs84).toBeNull()
    expect(mockedCreateBuffer).not.toHaveBeenCalled()
    expect(window.sessionStorage.getItem(workspaceDraftStorageKey)).not.toBeNull()
  })

  it.each([
    ['FAILED', '服务端分析失败'],
    ['CANCELED', '风险分析任务已取消'],
  ] as const)('restores the %s terminal state and error', async (status, expectedError) => {
    window.sessionStorage.setItem(workspaceTaskStorageKey, 'task-1')
    const store = useAnalysisStore()
    const jobStatus: RiskAnalysisJobStatus = {
      task_id: 'task-1',
      status,
      stage: status,
      progress: status === 'FAILED' ? 100 : null,
      result_available: false,
      submitted_at: '2026-08-07T12:00:00Z',
      ...(status === 'FAILED' ? { error: { message: expectedError } } : {}),
    }
    mockedGetJob.mockResolvedValueOnce(jobStatus)

    await store.restoreRiskAnalysis()

    expect(store.jobStatus?.status).toBe(status)
    expect(store.taskError).toBe(expectedError)
    expect(store.polling).toBe(false)
    expect(mockedGetResult).not.toHaveBeenCalled()
  })

  it('ignores a late restore response after the workflow is reset', async () => {
    window.sessionStorage.setItem(workspaceTaskStorageKey, 'task-1')
    const store = useAnalysisStore()
    let resolveStatus: ((value: RiskAnalysisJobStatus) => void) | undefined
    mockedGetJob.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveStatus = resolve
        }),
    )

    const restoration = store.restoreRiskAnalysis()
    expect(store.job?.task_id).toBe('task-1')

    store.resetRiskAnalysis()
    resolveStatus?.({
      task_id: 'task-1',
      status: 'RUNNING',
      stage: 'ANALYZING',
      progress: 40,
      result_available: false,
      submitted_at: '2026-08-07T12:00:00Z',
    })
    await restoration

    expect(store.job).toBeNull()
    expect(store.jobStatus).toBeNull()
    expect(store.polling).toBe(false)
    expect(window.sessionStorage.getItem(workspaceTaskStorageKey)).toBeNull()
  })

  it('ignores a late submission response after the workflow is reset', async () => {
    window.sessionStorage.setItem(workspaceTaskStorageKey, 'task-1')
    const store = useAnalysisStore()
    let resolveSubmission: ((value: RiskAnalysisSubmissionDetail) => void) | undefined
    mockedGetSubmission.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSubmission = resolve
        }),
    )
    mockedGetJob.mockResolvedValueOnce({
      task_id: 'task-1',
      status: 'RUNNING',
      stage: 'ANALYZING',
      progress: 40,
      result_available: false,
      submitted_at: '2026-08-07T12:00:00Z',
    })

    await store.restoreRiskAnalysis()
    store.resetRiskAnalysis()
    resolveSubmission?.(makeSubmission())
    await Promise.resolve()

    expect(store.submissionContext).toBeNull()
    expect(store.submissionLoading).toBe(false)
    expect(store.submissionError).toBeNull()
  })
})
