import { loadAmap } from '@/map/amap'
import { gcj02ToWgs84 } from '@/map/coordinates'
import type { Coordinate } from '@/types/analysisArea'
import type { StudyPointCandidate } from '@/types/poi'

interface AMapLngLat {
  getLng: () => number
  getLat: () => number
}

interface PlaceSearchInstance {
  search: (keyword: string, callback: (status: string, result: unknown) => void) => void
}

interface AMapPlaceSearchNamespace {
  plugin: (name: string, callback: () => void) => void
  PlaceSearch?: new (options: {
    city: '全国'
    citylimit: false
    pageIndex: 1
    pageSize: 10
    extensions: 'all'
  }) => PlaceSearchInstance
}

export class AmapStudyPointSearchError extends Error {
  constructor(
    public readonly status: string,
    public readonly info: string | null,
  ) {
    super(info ? `高德地点搜索失败：${status} (${info})` : `高德地点搜索失败：${status}`)
    this.name = 'AmapStudyPointSearchError'
  }
}

let placeSearchNamespacePromise: Promise<AMapPlaceSearchNamespace> | null = null

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

async function loadPlaceSearchNamespace(): Promise<AMapPlaceSearchNamespace> {
  if (placeSearchNamespacePromise) return placeSearchNamespacePromise

  placeSearchNamespacePromise = loadAmap<AMapPlaceSearchNamespace>()
    .then(
      (amap) =>
        new Promise<AMapPlaceSearchNamespace>((resolve, reject) => {
          try {
            amap.plugin('AMap.PlaceSearch', () => {
              if (typeof amap.PlaceSearch === 'function') resolve(amap)
              else reject(new Error('AMap.PlaceSearch 插件加载失败'))
            })
          } catch (error: unknown) {
            reject(error)
          }
        }),
    )
    .catch((error: unknown) => {
      placeSearchNamespacePromise = null
      throw error
    })
  return placeSearchNamespacePromise
}

function optionalString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function normalizeCandidate(value: unknown): StudyPointCandidate {
  if (!isRecord(value) || typeof value.id !== 'string' || typeof value.name !== 'string') {
    throw new Error('高德地点响应缺少 id 或 name')
  }

  const location = value.location as AMapLngLat | undefined
  if (!location || typeof location.getLng !== 'function' || typeof location.getLat !== 'function') {
    throw new Error('高德地点响应缺少 location')
  }

  const gcj02: Coordinate = [location.getLng(), location.getLat()]
  if (!gcj02.every(Number.isFinite)) throw new Error('高德地点 location 无效')

  const id = value.id.trim()
  const name = value.name.trim()
  if (!id || !name) throw new Error('高德地点响应包含空 id 或 name')

  return {
    id,
    name,
    address: optionalString(value.address),
    district: [value.pname, value.cityname, value.adname].map(optionalString).filter(Boolean).join(''),
    locationWgs84: gcj02ToWgs84(gcj02),
  }
}

function callbackInfo(result: unknown): string | null {
  if (typeof result === 'string') return result
  if (isRecord(result) && typeof result.info === 'string') return result.info
  return null
}

function normalizeCompleteResult(result: unknown): StudyPointCandidate[] {
  if (!isRecord(result) || !isRecord(result.poiList) || !Array.isArray(result.poiList.pois)) {
    throw new Error('高德地点 complete 响应格式无效')
  }
  return result.poiList.pois.map(normalizeCandidate)
}

export async function searchAmapStudyPoints(keyword: string): Promise<StudyPointCandidate[]> {
  const submittedKeyword = keyword.trim()
  if (!submittedKeyword) throw new Error('请输入地址或 POI 关键词')

  const amap = await loadPlaceSearchNamespace()
  const PlaceSearch = amap.PlaceSearch
  if (!PlaceSearch) throw new Error('AMap.PlaceSearch 插件不可用')

  const placeSearch = new PlaceSearch({
    city: '全国',
    citylimit: false,
    pageIndex: 1,
    pageSize: 10,
    extensions: 'all',
  })

  return new Promise((resolve, reject) => {
    placeSearch.search(submittedKeyword, (status, result) => {
      try {
        if (status === 'no_data') {
          resolve([])
          return
        }
        if (status !== 'complete') {
          reject(new AmapStudyPointSearchError(status, callbackInfo(result)))
          return
        }
        resolve(normalizeCompleteResult(result))
      } catch (error: unknown) {
        reject(error)
      }
    })
  })
}
