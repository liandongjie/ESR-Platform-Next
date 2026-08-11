import { beforeEach, describe, expect, it, vi } from 'vitest'

import { gcj02ToWgs84 } from '@/map/coordinates'

const mocks = vi.hoisted(() => ({
  loadAmap: vi.fn(),
  plugin: vi.fn(),
  options: [] as unknown[],
  keywords: [] as string[],
  callbackStatus: 'complete',
  callbackResult: null as unknown,
}))

vi.mock('@/map/amap', () => ({ loadAmap: mocks.loadAmap }))

class FakePlaceSearch {
  constructor(options: unknown) {
    mocks.options.push(options)
  }

  search(keyword: string, callback: (status: string, result: unknown) => void) {
    mocks.keywords.push(keyword)
    callback(mocks.callbackStatus, mocks.callbackResult)
  }
}

function lngLat(lng: number, lat: number) {
  return { getLng: () => lng, getLat: () => lat }
}

describe('AMap study point provider', () => {
  beforeEach(() => {
    vi.resetModules()
    mocks.loadAmap.mockReset()
    mocks.plugin.mockReset()
    mocks.options.length = 0
    mocks.keywords.length = 0
    mocks.callbackStatus = 'complete'
    mocks.callbackResult = {
      poiList: {
        pois: [
          {
            id: 'poi-1',
            name: ' 南京大学 ',
            address: '汉口路22号',
            pname: '江苏省',
            cityname: '南京市',
            adname: '鼓楼区',
            location: lngLat(118.778074, 32.057235),
          },
        ],
      },
    }
    const namespace = { plugin: mocks.plugin, PlaceSearch: FakePlaceSearch }
    mocks.plugin.mockImplementation((_name: string, callback: () => void) => callback())
    mocks.loadAmap.mockResolvedValue(namespace)
  })

  it('searches the first nationwide page and returns plain WGS84 candidates', async () => {
    const { searchAmapStudyPoints } = await import('@/map/amapStudyPoint')

    const result = await searchAmapStudyPoints(' 南京大学 ')

    expect(mocks.plugin).toHaveBeenCalledWith('AMap.PlaceSearch', expect.any(Function))
    expect(mocks.options).toEqual([
      {
        city: '全国',
        citylimit: false,
        pageIndex: 1,
        pageSize: 10,
        extensions: 'all',
      },
    ])
    expect(mocks.keywords).toEqual(['南京大学'])
    expect(result).toEqual([
      {
        id: 'poi-1',
        name: '南京大学',
        address: '汉口路22号',
        district: '江苏省南京市鼓楼区',
        locationWgs84: gcj02ToWgs84([118.778074, 32.057235]),
      },
    ])
    expect(JSON.parse(JSON.stringify(result))).toEqual(result)

    await searchAmapStudyPoints('中关村')
    expect(mocks.plugin).toHaveBeenCalledOnce()
  })

  it('normalizes missing optional address fields', async () => {
    mocks.callbackResult = {
      poiList: { pois: [{ id: 'poi-1', name: '地点', location: lngLat(118.8, 32) }] },
    }
    const { searchAmapStudyPoints } = await import('@/map/amapStudyPoint')

    await expect(searchAmapStudyPoints('地点')).resolves.toMatchObject([
      { address: '', district: '' },
    ])
  })

  it('normalizes no_data to an empty result', async () => {
    mocks.callbackStatus = 'no_data'
    mocks.callbackResult = null
    const { searchAmapStudyPoints } = await import('@/map/amapStudyPoint')

    await expect(searchAmapStudyPoints('no-match')).resolves.toEqual([])
  })

  it('preserves callback status and info on errors', async () => {
    mocks.callbackStatus = 'error'
    mocks.callbackResult = { info: 'CUQPS_HAS_EXCEEDED_THE_LIMIT' }
    const { searchAmapStudyPoints } = await import('@/map/amapStudyPoint')

    await expect(searchAmapStudyPoints('南京大学')).rejects.toMatchObject({
      name: 'AmapStudyPointSearchError',
      status: 'error',
      info: 'CUQPS_HAS_EXCEEDED_THE_LIMIT',
    })
  })

  it('rejects an empty keyword before loading AMap', async () => {
    const { searchAmapStudyPoints } = await import('@/map/amapStudyPoint')

    await expect(searchAmapStudyPoints('   ')).rejects.toThrow('关键词')
    expect(mocks.loadAmap).not.toHaveBeenCalled()
  })

  it.each([
    [{ poiList: {} }, 'complete 响应格式无效'],
    [{ poiList: { pois: [{ id: 'poi-1', name: '地点' }] } }, '缺少 location'],
    [
      { poiList: { pois: [{ id: 'poi-1', name: '地点', location: lngLat(Number.NaN, 32) }] } },
      'location 无效',
    ],
  ])('rejects malformed complete responses', async (result, message) => {
    mocks.callbackResult = result
    const { searchAmapStudyPoints } = await import('@/map/amapStudyPoint')

    await expect(searchAmapStudyPoints('地点')).rejects.toThrow(message)
  })
})
