import { beforeEach, describe, expect, it, vi } from 'vitest'

import { gcj02ToWgs84, wgs84ToGcj02 } from '@/map/coordinates'
import type { Coordinate, PolygonGeometry } from '@/types/analysisArea'

const mocks = vi.hoisted(() => ({
  loadAmap: vi.fn(),
  plugin: vi.fn(),
  options: [] as unknown[],
  paths: [] as Coordinate[][],
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
    callback(mocks.callbackStatus, mocks.callbackResult)
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
})
