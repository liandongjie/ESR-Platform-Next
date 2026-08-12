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

class FakeDistrictSearch {
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

describe('AMap administrative district provider', () => {
  beforeEach(() => {
    vi.resetModules()
    mocks.loadAmap.mockReset()
    mocks.plugin.mockReset()
    mocks.options.length = 0
    mocks.keywords.length = 0
    mocks.callbackStatus = 'complete'
    mocks.callbackResult = null
    mocks.plugin.mockImplementation((_name: string, callback: () => void) => callback())
    mocks.loadAmap.mockResolvedValue({
      plugin: mocks.plugin,
      DistrictSearch: FakeDistrictSearch,
    })
  })

  it('loads root and children with base data using the real provider hierarchy', async () => {
    mocks.callbackResult = {
      districtList: [
        {
          districtList: [
            { adcode: '320000', name: '江苏省', level: 'province' },
            { adcode: '110000', name: '北京市', level: 'province' },
          ],
        },
      ],
    }
    const { listAmapAdministrativeRegions } = await import('@/map/amapDistrict')

    await expect(listAmapAdministrativeRegions()).resolves.toEqual([
      { adcode: '320000', name: '江苏省', level: 'province' },
      { adcode: '110000', name: '北京市', level: 'province' },
    ])

    mocks.callbackResult = {
      districtList: [
        { districtList: [{ adcode: '320100', name: '南京市', level: 'city' }] },
      ],
    }
    await expect(
      listAmapAdministrativeRegions({ adcode: '320000', name: '江苏省', level: 'province' }),
    ).resolves.toEqual([{ adcode: '320100', name: '南京市', level: 'city' }])

    expect(mocks.options).toEqual([
      { level: 'country', subdistrict: 1, extensions: 'base', showbiz: false },
      { level: 'province', subdistrict: 1, extensions: 'base', showbiz: false },
    ])
    expect(mocks.keywords).toEqual(['中国', '320000'])
    expect(mocks.plugin).toHaveBeenCalledOnce()
  })

  it('returns all final boundaries as plain WGS84 arrays', async () => {
    const first = [
      lngLat(118.8, 32),
      lngLat(118.9, 32),
      lngLat(118.8, 32),
    ]
    const second = [
      lngLat(119, 32.1),
      lngLat(119.1, 32.1),
      lngLat(119, 32.1),
    ]
    mocks.callbackResult = { districtList: [{ boundaries: [first, second] }] }
    const { getAmapAdministrativeBoundaries } = await import('@/map/amapDistrict')

    const result = await getAmapAdministrativeBoundaries({
      adcode: '320100',
      name: '南京市',
      level: 'city',
    })

    expect(mocks.options).toEqual([
      { level: 'city', subdistrict: 0, extensions: 'all', showbiz: false },
    ])
    expect(mocks.keywords).toEqual(['320100'])
    expect(result).toEqual([
      first.map((item) => gcj02ToWgs84([item.getLng(), item.getLat()])),
      second.map((item) => gcj02ToWgs84([item.getLng(), item.getLat()])),
    ])
    expect(JSON.parse(JSON.stringify(result))).toEqual(result)
  })

  it('normalizes no_data and ignores non-administrative child levels', async () => {
    const { listAmapAdministrativeRegions } = await import('@/map/amapDistrict')
    mocks.callbackStatus = 'no_data'
    await expect(listAmapAdministrativeRegions()).resolves.toEqual([])

    mocks.callbackStatus = 'complete'
    mocks.callbackResult = {
      districtList: [
        { districtList: [{ adcode: 'x', name: '商圈', level: 'biz_area' }] },
      ],
    }
    await expect(listAmapAdministrativeRegions()).resolves.toEqual([])
  })

  it('preserves provider status and rejects malformed responses', async () => {
    const { getAmapAdministrativeBoundaries, listAmapAdministrativeRegions } = await import(
      '@/map/amapDistrict'
    )
    mocks.callbackStatus = 'error'
    mocks.callbackResult = { info: 'CUQPS_HAS_EXCEEDED_THE_LIMIT' }
    await expect(listAmapAdministrativeRegions()).rejects.toMatchObject({
      name: 'AmapDistrictSearchError',
      info: 'CUQPS_HAS_EXCEEDED_THE_LIMIT',
    })

    mocks.callbackStatus = 'complete'
    mocks.callbackResult = { districtList: [{ districtList: 'invalid' }] }
    await expect(listAmapAdministrativeRegions()).rejects.toThrow('districtList')

    mocks.callbackResult = { districtList: [{ boundaries: [[{ lng: 118.8, lat: 32 }]] }] }
    await expect(
      getAmapAdministrativeBoundaries({ adcode: '320100', name: '南京市', level: 'city' }),
    ).rejects.toThrow('坐标格式无效')
  })
})
