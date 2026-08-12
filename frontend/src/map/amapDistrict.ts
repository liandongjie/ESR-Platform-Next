import { loadAmap } from '@/map/amap'
import { gcj02ToWgs84 } from '@/map/coordinates'
import type { Coordinate } from '@/types/analysisArea'

export type AdministrativeRegionLevel = 'country' | 'province' | 'city' | 'district'

export interface AdministrativeRegion {
  adcode: string
  name: string
  level: Exclude<AdministrativeRegionLevel, 'country'>
}

interface AMapLngLat {
  getLng: () => number
  getLat: () => number
}

interface DistrictSearchInstance {
  search: (keyword: string, callback: (status: string, result: unknown) => void) => void
}

interface DistrictSearchOptions {
  level: AdministrativeRegionLevel
  subdistrict: 0 | 1
  extensions: 'base' | 'all'
  showbiz: false
}

interface AMapDistrictSearchNamespace {
  plugin: (name: string, callback: () => void) => void
  DistrictSearch?: new (options: DistrictSearchOptions) => DistrictSearchInstance
}

export class AmapDistrictSearchError extends Error {
  constructor(
    public readonly status: string,
    public readonly info: string | null,
  ) {
    super(info ? `高德行政区查询失败：${status} (${info})` : `高德行政区查询失败：${status}`)
    this.name = 'AmapDistrictSearchError'
  }
}

let districtSearchNamespacePromise: Promise<AMapDistrictSearchNamespace> | null = null

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isAdministrativeLevel(value: unknown): value is AdministrativeRegionLevel {
  return value === 'country' || value === 'province' || value === 'city' || value === 'district'
}

async function loadDistrictSearchNamespace(): Promise<AMapDistrictSearchNamespace> {
  if (districtSearchNamespacePromise) return districtSearchNamespacePromise

  districtSearchNamespacePromise = loadAmap<AMapDistrictSearchNamespace>()
    .then(
      (amap) =>
        new Promise<AMapDistrictSearchNamespace>((resolve, reject) => {
          try {
            amap.plugin('AMap.DistrictSearch', () => {
              if (typeof amap.DistrictSearch === 'function') resolve(amap)
              else reject(new Error('AMap.DistrictSearch 插件加载失败'))
            })
          } catch (error: unknown) {
            reject(error)
          }
        }),
    )
    .catch((error: unknown) => {
      districtSearchNamespacePromise = null
      throw error
    })
  return districtSearchNamespacePromise
}

function callbackInfo(result: unknown): string | null {
  if (typeof result === 'string') return result
  if (isRecord(result) && typeof result.info === 'string') return result.info
  return null
}

async function searchDistrict(
  keyword: string,
  options: DistrictSearchOptions,
): Promise<Record<string, unknown> | null> {
  const amap = await loadDistrictSearchNamespace()
  const DistrictSearch = amap.DistrictSearch
  if (!DistrictSearch) throw new Error('AMap.DistrictSearch 插件不可用')
  const search = new DistrictSearch(options)

  return new Promise((resolve, reject) => {
    search.search(keyword, (status, result) => {
      if (status === 'no_data') {
        resolve(null)
        return
      }
      if (status !== 'complete') {
        reject(new AmapDistrictSearchError(status, callbackInfo(result)))
        return
      }
      if (!isRecord(result) || !Array.isArray(result.districtList) || !isRecord(result.districtList[0])) {
        reject(new Error('高德行政区 complete 响应格式无效'))
        return
      }
      resolve(result.districtList[0])
    })
  })
}

function parseRegion(value: unknown): AdministrativeRegion | null {
  if (!isRecord(value)) throw new Error('高德行政区 child 格式无效')
  if (!isAdministrativeLevel(value.level) || value.level === 'country') return null
  if (typeof value.adcode !== 'string' || typeof value.name !== 'string') {
    throw new Error('高德行政区 child 缺少 adcode 或 name')
  }
  const adcode = value.adcode.trim()
  const name = value.name.trim()
  if (!adcode || !name) throw new Error('高德行政区 child 包含空 adcode 或 name')
  return { adcode, name, level: value.level }
}

export async function listAmapAdministrativeRegions(
  parent: AdministrativeRegion | null = null,
): Promise<AdministrativeRegion[]> {
  const district = await searchDistrict(parent?.adcode ?? '中国', {
    level: parent?.level ?? 'country',
    subdistrict: 1,
    extensions: 'base',
    showbiz: false,
  })
  if (!district) return []
  if (district.districtList === undefined) return []
  if (!Array.isArray(district.districtList)) {
    throw new Error('高德行政区响应缺少 districtList')
  }
  return district.districtList.map(parseRegion).filter((item) => item !== null)
}

function lngLatToWgs84(value: unknown): Coordinate {
  const lngLat = value as Partial<AMapLngLat> | null
  if (!lngLat || typeof lngLat.getLng !== 'function' || typeof lngLat.getLat !== 'function') {
    throw new Error('高德行政区 boundary 坐标格式无效')
  }
  const coordinate: Coordinate = [lngLat.getLng(), lngLat.getLat()]
  if (!coordinate.every(Number.isFinite)) throw new Error('高德行政区 boundary 坐标无效')
  return gcj02ToWgs84(coordinate)
}

export async function getAmapAdministrativeBoundaries(
  region: AdministrativeRegion,
): Promise<Coordinate[][]> {
  const district = await searchDistrict(region.adcode, {
    level: region.level,
    subdistrict: 0,
    extensions: 'all',
    showbiz: false,
  })
  if (!district || !Array.isArray(district.boundaries) || district.boundaries.length === 0) {
    throw new Error('高德行政区响应缺少 boundary')
  }
  return district.boundaries.map((boundary) => {
    if (!Array.isArray(boundary) || boundary.length === 0) {
      throw new Error('高德行政区 boundary 格式无效')
    }
    return boundary.map(lngLatToWgs84)
  })
}
