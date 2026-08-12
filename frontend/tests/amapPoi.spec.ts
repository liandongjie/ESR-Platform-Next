import { beforeEach, describe, expect, it, vi } from 'vitest'

import { gcj02ToWgs84, wgs84ToGcj02 } from '@/map/coordinates'
import type { BufferGeometry, Coordinate, PolygonGeometry } from '@/types/analysisArea'

const mocks = vi.hoisted(() => ({
  loadAmap: vi.fn(),
  plugin: vi.fn(),
  options: [] as unknown[],
  paths: [] as Coordinate[][],
  callbackQueue: [] as Array<{ status: string; result: unknown }>,
  callbackStatus: 'complete',
  callbackResult: null as unknown,
}))

vi.mock('@/map/amap', () => ({ loadAmap: mocks.loadAmap }))

class FakePlaceSearch {
  constructor(options: unknown) {
    mocks.options.push(options)
  }

  searchInBounds(
    _keyword: string,
    path: Coordinate[],
    callback: (status: string, result: unknown) => void,
  ) {
    mocks.paths.push(path)
    const queued = mocks.callbackQueue.shift()
    callback(queued?.status ?? mocks.callbackStatus, queued?.result ?? mocks.callbackResult)
  }
}

const geometry: PolygonGeometry = {
  type: 'Polygon',
  coordinates: [
    [
      [118.8, 32.0],
      [118.83, 32.0],
      [118.83, 32.03],
      [118.8, 32.0],
    ],
  ],
}

function lngLat(lng: number, lat: number) {
  return { getLng: () => lng, getLat: () => lat }
}

function providerPoi(id: string, coordinateWgs84: Coordinate) {
  const [lng, lat] = wgs84ToGcj02(coordinateWgs84)
  return { id, name: id, location: lngLat(lng, lat) }
}

function providerPoiAtGcj02(id: string, coordinateGcj02: Coordinate) {
  return { id, name: id, location: lngLat(coordinateGcj02[0], coordinateGcj02[1]) }
}

function completePage(count: number, pois: unknown[]) {
  return { status: 'complete', result: { poiList: { count, pois } } }
}

function noDataPage() {
  return { status: 'no_data', result: null }
}

function square(west: number, south: number, east: number, north: number): Coordinate[] {
  return [
    [west, south],
    [east, south],
    [east, north],
    [west, north],
    [west, south],
  ]
}

const optionalFieldCases = [
  { source: 'type', target: 'type' },
  { source: 'typecode', target: 'typeCode' },
  { source: 'address', target: 'address' },
] as const

const invalidOptionalFieldCases = optionalFieldCases.flatMap(({ source, target }) =>
  [
    { source, target, label: 'missing', value: undefined },
    { source, target, label: 'null', value: null },
    { source, target, label: 'number', value: 42 },
    { source, target, label: 'object', value: {} },
  ] as const,
)

describe('AMap POI provider', () => {
  beforeEach(() => {
    vi.resetModules()
    mocks.loadAmap.mockReset()
    mocks.plugin.mockReset()
    mocks.options.length = 0
    mocks.paths.length = 0
    mocks.callbackQueue.length = 0
    mocks.callbackStatus = 'complete'
    mocks.callbackResult = {
      poiList: {
        count: 44,
        pois: [
          {
            id: 'poi-1',
            name: '学校',
            type: '科教文化服务;学校',
            typecode: '141200',
            address: '蓝旗街',
            location: lngLat(118.817936, 32.027436),
          },
        ],
      },
    }
    const namespace = {
      plugin: mocks.plugin,
      PlaceSearch: FakePlaceSearch,
    }
    mocks.plugin.mockImplementation((_name: string, callback: () => void) => callback())
    mocks.loadAmap.mockResolvedValue(namespace)
  })

  it('loads the plugin, pages once, and returns plain WGS84 DTOs', async () => {
    const { searchAmapPois } = await import('@/map/amapPoi')

    const result = await searchAmapPois({ geometry, keyword: ' 学校 ', page: 2, pageSize: 1 })

    expect(mocks.plugin).toHaveBeenCalledWith('AMap.PlaceSearch', expect.any(Function))
    expect(mocks.options).toEqual([{ pageIndex: 2, pageSize: 1, extensions: 'all' }])
    expect(mocks.paths[0]).toEqual(geometry.coordinates[0]!.map(wgs84ToGcj02))
    expect(result).toEqual({
      total: 44,
      page: 2,
      pageSize: 1,
      items: [
        {
          id: 'poi-1',
          name: '学校',
          type: '科教文化服务;学校',
          typeCode: '141200',
          address: '蓝旗街',
          locationWgs84: gcj02ToWgs84([118.817936, 32.027436]),
        },
      ],
    })
    expect(JSON.parse(JSON.stringify(result.items[0]))).toEqual(result.items[0])

    await searchAmapPois({ geometry, keyword: '医院', page: 1, pageSize: 10 })
    expect(mocks.plugin).toHaveBeenCalledOnce()
  })

  it.each(invalidOptionalFieldCases)(
    'normalizes $source when it is $label',
    async ({ source, target, value }) => {
      const poi: Record<string, unknown> = {
        id: 'poi-1',
        name: '学校',
        type: '科教文化服务;学校',
        typecode: '141200',
        address: '蓝旗街',
        location: lngLat(118.817936, 32.027436),
      }
      if (value === undefined) delete poi[source]
      else poi[source] = value
      mocks.callbackResult = { poiList: { count: 1, pois: [poi] } }
      const { searchAmapPois } = await import('@/map/amapPoi')

      const result = await searchAmapPois({ geometry, keyword: '学校', page: 1, pageSize: 10 })

      expect(result.items[0]![target]).toBe('')
    },
  )

  it('normalizes the real no_data shape to an empty successful page', async () => {
    mocks.callbackStatus = 'no_data'
    mocks.callbackResult = null
    const { searchAmapPois } = await import('@/map/amapPoi')

    await expect(
      searchAmapPois({ geometry, keyword: 'no-match', page: 1, pageSize: 10 }),
    ).resolves.toEqual({ items: [], total: 0, page: 1, pageSize: 10 })
  })

  it('preserves callback status and info on errors', async () => {
    mocks.callbackStatus = 'error'
    mocks.callbackResult = { info: 'CUQPS_HAS_EXCEEDED_THE_LIMIT' }
    const { AmapPoiSearchError, searchAmapPois } = await import('@/map/amapPoi')

    const request = searchAmapPois({ geometry, keyword: '学校', page: 1, pageSize: 10 })
    await expect(request).rejects.toBeInstanceOf(AmapPoiSearchError)
    await expect(request).rejects.toMatchObject({
      status: 'error',
      info: 'CUQPS_HAS_EXCEEDED_THE_LIMIT',
    })
  })

  it('rejects unsupported geometry and invalid paging before loading AMap', async () => {
    const { searchAmapPois } = await import('@/map/amapPoi')
    const multiPolygon = {
      type: 'MultiPolygon',
      coordinates: [[geometry.coordinates]],
    } as unknown as PolygonGeometry

    await expect(
      searchAmapPois({ geometry: multiPolygon, keyword: '学校', page: 1, pageSize: 10 }),
    ).rejects.toThrow('暂不支持 MultiPolygon 缓冲区')
    await expect(
      searchAmapPois({ geometry, keyword: '学校', page: 101, pageSize: 10 }),
    ).rejects.toThrow('页码')
    await expect(
      searchAmapPois({ geometry, keyword: ' ', page: 1, pageSize: 10 }),
    ).rejects.toThrow('关键词')
    expect(mocks.loadAmap).not.toHaveBeenCalled()
  })

  it('rejects malformed complete responses instead of dropping rows', async () => {
    mocks.callbackResult = { poiList: { count: 1, pois: [{ id: 'poi-1', name: '学校' }] } }
    const { searchAmapPois } = await import('@/map/amapPoi')

    await expect(
      searchAmapPois({ geometry, keyword: '学校', page: 1, pageSize: 10 }),
    ).rejects.toThrow('缺少 location')
  })

  it.each([
    ['id', '缺少 id 或 name'],
    ['name', '缺少 id 或 name'],
    ['location', '缺少 location'],
  ] as const)('rejects a POI missing required $0', async (field, message) => {
    const poi: Record<string, unknown> = {
      id: 'poi-1',
      name: '学校',
      location: lngLat(118.817936, 32.027436),
    }
    delete poi[field]
    mocks.callbackResult = { poiList: { count: 1, pois: [poi] } }
    const { searchAmapPois } = await import('@/map/amapPoi')

    await expect(
      searchAmapPois({ geometry, keyword: '学校', page: 1, pageSize: 10 }),
    ).rejects.toThrow(message)
  })

  it('queries only the outer ring and keeps outer and hole boundaries while filtering interiors', async () => {
    const outerBoundaryGcj02: Coordinate = [118.8, 32]
    const holeBoundaryGcj02: Coordinate = [118.82, 32]
    const outerBoundary = gcj02ToWgs84(outerBoundaryGcj02)
    const holeBoundary = gcj02ToWgs84(holeBoundaryGcj02)
    const polygonWithHole: PolygonGeometry = {
      type: 'Polygon',
      coordinates: [
        square(outerBoundary[0], outerBoundary[1] - 0.02, outerBoundary[0] + 0.06, outerBoundary[1] + 0.02),
        square(holeBoundary[0], holeBoundary[1] - 0.005, holeBoundary[0] + 0.01, holeBoundary[1] + 0.005),
      ],
    }
    mocks.callbackQueue.push(
      completePage(5, [
        providerPoi('outer-interior', [outerBoundary[0] + 0.01, outerBoundary[1] + 0.01]),
        providerPoiAtGcj02('outer-boundary', outerBoundaryGcj02),
        providerPoi('outer-exterior', [outerBoundary[0] - 0.01, outerBoundary[1]]),
        providerPoi('hole-interior', [holeBoundary[0] + 0.005, holeBoundary[1]]),
        providerPoiAtGcj02('hole-boundary', holeBoundaryGcj02),
      ]),
      completePage(5, []),
    )
    const { searchAmapPoisInGeometry } = await import('@/map/amapPoi')

    const result = await searchAmapPoisInGeometry({ geometry: polygonWithHole, keyword: '学校' })

    expect(mocks.paths).toEqual([
      polygonWithHole.coordinates[0]!.map(wgs84ToGcj02),
      polygonWithHole.coordinates[0]!.map(wgs84ToGcj02),
    ])
    expect(result).toMatchObject({
      reportedCandidateCount: 5,
      retrievedUniqueCount: 3,
      retrievalComplete: true,
      hasMore: false,
      truncatedReason: null,
    })
    expect(result.items.map((item) => item.id)).toEqual([
      'outer-interior',
      'outer-boundary',
      'hole-boundary',
    ])
  })

  it('filters every hole interior while retaining a hole boundary in a Polygon', async () => {
    const holeBoundaryGcj02: Coordinate = [118.84, 32]
    const holeBoundary = gcj02ToWgs84(holeBoundaryGcj02)
    const polygonWithMultipleHoles: PolygonGeometry = {
      type: 'Polygon',
      coordinates: [
        square(118.75, 31.95, 118.9, 32.05),
        square(118.78, 31.98, 118.8, 32.02),
        square(holeBoundary[0], 31.98, holeBoundary[0] + 0.02, 32.02),
      ],
    }
    mocks.callbackQueue.push(
      completePage(4, [
        providerPoi('outside-holes', [118.87, 32]),
        providerPoi('first-hole-interior', [118.79, 32]),
        providerPoi('second-hole-interior', [holeBoundary[0] + 0.01, 32]),
        providerPoiAtGcj02('second-hole-boundary', holeBoundaryGcj02),
      ]),
      completePage(4, []),
    )
    const { searchAmapPoisInGeometry } = await import('@/map/amapPoi')

    const result = await searchAmapPoisInGeometry({
      geometry: polygonWithMultipleHoles,
      keyword: '学校',
    })

    expect(mocks.paths).toEqual([
      polygonWithMultipleHoles.coordinates[0]!.map(wgs84ToGcj02),
      polygonWithMultipleHoles.coordinates[0]!.map(wgs84ToGcj02),
    ])
    expect(result.items.map((item) => item.id)).toEqual([
      'outside-holes',
      'second-hole-boundary',
    ])
  })

  it('queries MultiPolygon members in page-first order and deduplicates IDs first-seen', async () => {
    const memberOne: PolygonGeometry = {
      type: 'Polygon',
      coordinates: [square(118.7, 31.9, 118.75, 31.95)],
    }
    const memberTwo: PolygonGeometry = {
      type: 'Polygon',
      coordinates: [square(118.8, 32, 118.85, 32.05)],
    }
    const multiPolygon: BufferGeometry = {
      type: 'MultiPolygon',
      coordinates: [memberOne.coordinates, memberTwo.coordinates],
    }
    mocks.callbackQueue.push(
      completePage(2, [providerPoi('shared', [118.72, 31.92])]),
      completePage(2, [
        providerPoi('shared', [118.82, 32.02]),
        providerPoi('member-two', [118.83, 32.03]),
      ]),
      completePage(2, [
        providerPoi('shared', [118.72, 31.92]),
        providerPoi('member-one-page-two', [118.73, 31.93]),
      ]),
      completePage(2, []),
      completePage(2, []),
    )
    const { searchAmapPoisInGeometry } = await import('@/map/amapPoi')

    const result = await searchAmapPoisInGeometry({ geometry: multiPolygon, keyword: '学校' })

    expect(mocks.options).toEqual([
      { pageIndex: 1, pageSize: 50, extensions: 'all' },
      { pageIndex: 1, pageSize: 50, extensions: 'all' },
      { pageIndex: 2, pageSize: 50, extensions: 'all' },
      { pageIndex: 2, pageSize: 50, extensions: 'all' },
      { pageIndex: 3, pageSize: 50, extensions: 'all' },
    ])
    expect(mocks.paths).toEqual([
      memberOne.coordinates[0]!.map(wgs84ToGcj02),
      memberTwo.coordinates[0]!.map(wgs84ToGcj02),
      memberOne.coordinates[0]!.map(wgs84ToGcj02),
      memberTwo.coordinates[0]!.map(wgs84ToGcj02),
      memberOne.coordinates[0]!.map(wgs84ToGcj02),
    ])
    expect(result.items.map((item) => item.id)).toEqual([
      'shared',
      'member-two',
      'member-one-page-two',
    ])
    expect(result).toMatchObject({
      reportedCandidateCount: 4,
      retrievedUniqueCount: 3,
      retrievalComplete: true,
      hasMore: false,
      truncatedReason: null,
    })
  })

  it('filters a holed MultiPolygon member locally while aggregating another member', async () => {
    const memberWithHole: PolygonGeometry = {
      type: 'Polygon',
      coordinates: [
        square(118.7, 31.9, 118.75, 31.95),
        square(118.715, 31.915, 118.735, 31.935),
      ],
    }
    const otherMember: PolygonGeometry = {
      type: 'Polygon',
      coordinates: [square(118.8, 32, 118.85, 32.05)],
    }
    const multiPolygon: BufferGeometry = {
      type: 'MultiPolygon',
      coordinates: [memberWithHole.coordinates, otherMember.coordinates],
    }
    mocks.callbackQueue.push(
      completePage(2, [
        providerPoi('first-member-valid', [118.71, 31.91]),
        providerPoi('first-member-hole', [118.725, 31.925]),
      ]),
      completePage(1, [providerPoi('other-member-valid', [118.82, 32.02])]),
      completePage(2, []),
      completePage(1, []),
    )
    const { searchAmapPoisInGeometry } = await import('@/map/amapPoi')

    const result = await searchAmapPoisInGeometry({ geometry: multiPolygon, keyword: '学校' })

    expect(mocks.paths).toEqual([
      memberWithHole.coordinates[0]!.map(wgs84ToGcj02),
      otherMember.coordinates[0]!.map(wgs84ToGcj02),
      memberWithHole.coordinates[0]!.map(wgs84ToGcj02),
      otherMember.coordinates[0]!.map(wgs84ToGcj02),
    ])
    expect(result.items.map((item) => item.id)).toEqual([
      'first-member-valid',
      'other-member-valid',
    ])
    expect(result).toMatchObject({
      reportedCandidateCount: 3,
      retrievedUniqueCount: 2,
      retrievalComplete: true,
      hasMore: false,
      truncatedReason: null,
    })
  })

  it('rejects unsupported runtime geometry and excessive members before loading AMap', async () => {
    const { searchAmapPoisInGeometry } = await import('@/map/amapPoi')
    const point = { type: 'Point', coordinates: [118.8, 32] }
    const line = {
      type: 'LineString',
      coordinates: [
        [118.8, 32],
        [118.81, 32.01],
      ],
    }
    const tooManyMembers = {
      type: 'MultiPolygon',
      coordinates: Array.from({ length: 101 }, () => geometry.coordinates),
    }

    await expect(
      searchAmapPoisInGeometry({ geometry: point as never, keyword: '学校' }),
    ).rejects.toThrow('仅支持 Polygon 或 MultiPolygon')
    await expect(
      searchAmapPoisInGeometry({ geometry: line as never, keyword: '学校' }),
    ).rejects.toThrow('仅支持 Polygon 或 MultiPolygon')
    await expect(
      searchAmapPoisInGeometry({ geometry: tooManyMembers as never, keyword: '学校' }),
    ).rejects.toThrow('最多支持 100 个 Polygon member')
    expect(mocks.loadAmap).not.toHaveBeenCalled()
  })

  it('returns complete empty results only after every member reports no data', async () => {
    const multiPolygon: BufferGeometry = {
      type: 'MultiPolygon',
      coordinates: [geometry.coordinates, geometry.coordinates],
    }
    mocks.callbackQueue.push(noDataPage(), noDataPage())
    const { searchAmapPoisInGeometry } = await import('@/map/amapPoi')

    await expect(
      searchAmapPoisInGeometry({ geometry: multiPolygon, keyword: 'no-match' }),
    ).resolves.toEqual({
      items: [],
      reportedCandidateCount: 0,
      retrievedUniqueCount: 0,
      retrievalComplete: true,
      hasMore: false,
      truncatedReason: null,
    })
  })

  it('uses a global 5000-row budget before filtering and deduplication', async () => {
    const enclosingGeometry: PolygonGeometry = {
      type: 'Polygon',
      coordinates: [square(118.7, 31.9, 118.9, 32.1)],
    }
    for (let page = 1; page <= 100; page += 1) {
      mocks.callbackQueue.push(
        completePage(
          6000,
          Array.from({ length: 50 }, () => providerPoi('duplicate', [118.8, 32])),
        ),
      )
    }
    const { searchAmapPoisInGeometry } = await import('@/map/amapPoi')

    const result = await searchAmapPoisInGeometry({
      geometry: enclosingGeometry,
      keyword: '学校',
    })

    expect(mocks.options).toHaveLength(100)
    expect(result).toMatchObject({
      reportedCandidateCount: 6000,
      retrievedUniqueCount: 1,
      retrievalComplete: false,
      hasMore: true,
      truncatedReason: 'raw-row-limit',
    })
  })

  it('uses a global 100-call budget when non-empty pages stay short', async () => {
    const enclosingGeometry: PolygonGeometry = {
      type: 'Polygon',
      coordinates: [square(118.7, 31.9, 118.9, 32.1)],
    }
    for (let page = 1; page <= 100; page += 1) {
      mocks.callbackQueue.push(completePage(200, [providerPoi(`page-${page}`, [118.8, 32])]))
    }
    const { searchAmapPoisInGeometry } = await import('@/map/amapPoi')

    const result = await searchAmapPoisInGeometry({
      geometry: enclosingGeometry,
      keyword: '学校',
    })

    expect(mocks.options).toHaveLength(100)
    expect(result).toMatchObject({
      reportedCandidateCount: 200,
      retrievedUniqueCount: 100,
      retrievalComplete: false,
      hasMore: true,
      truncatedReason: 'provider-call-limit',
    })
  })

  it.each([
    ['provider error', { status: 'error', result: { info: 'LIMIT' } }, 'LIMIT'],
    [
      'malformed response',
      { status: 'complete', result: { poiList: { count: 1, pois: [{ id: 'bad' }] } } },
      '缺少 id 或 name',
    ],
  ] as const)('fails all-or-nothing after a later %s', async (_label, failure, message) => {
    const multiPolygon: BufferGeometry = {
      type: 'MultiPolygon',
      coordinates: [
        [square(118.7, 31.9, 118.75, 31.95)],
        [square(118.8, 32, 118.85, 32.05)],
      ],
    }
    mocks.callbackQueue.push(
      completePage(1, [providerPoi('first-member', [118.72, 31.92])]),
      failure,
    )
    const { searchAmapPoisInGeometry } = await import('@/map/amapPoi')

    await expect(
      searchAmapPoisInGeometry({ geometry: multiPolygon, keyword: '学校' }),
    ).rejects.toThrow(message)
    expect(mocks.options).toHaveLength(2)
  })
})
