import { loadAmap } from '@/map/amap'
import { gcj02ToWgs84, wgs84ToGcj02 } from '@/map/coordinates'
import type { Coordinate, PolygonGeometry } from '@/types/analysisArea'
import type {
  PoiDto,
  PoiGeometrySearchRequest,
  PoiGeometrySearchResult,
  PoiGeometrySearchTruncatedReason,
  PoiSearchRequest,
  PoiSearchResult,
} from '@/types/poi'
import { parseSourceGeometry } from '@/validation/sourceGeometry'

const MAX_MEMBERS = 100
const MAX_PROVIDER_CALLS = 100
const MAX_RAW_ROWS = 5000
const PROVIDER_PAGE_SIZE = 50
const POINT_ON_SEGMENT_EPSILON = 1e-12

interface AMapLngLat {
  getLng: () => number
  getLat: () => number
}

interface PlaceSearchInstance {
  searchInBounds: (
    keyword: string,
    bounds: Coordinate[],
    callback: (status: string, result: unknown) => void,
  ) => void
}

interface AMapPlaceSearchNamespace {
  plugin: (name: string, callback: () => void) => void
  PlaceSearch?: new (options: {
    pageIndex: number
    pageSize: number
    extensions: 'all'
  }) => PlaceSearchInstance
}

export class AmapPoiSearchError extends Error {
  constructor(
    public readonly status: string,
    public readonly info: string | null,
  ) {
    super(info ? `高德 POI 查询失败：${status} (${info})` : `高德 POI 查询失败：${status}`)
    this.name = 'AmapPoiSearchError'
  }
}

let placeSearchNamespacePromise: Promise<AMapPlaceSearchNamespace> | null = null

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function validateRequest(request: PoiSearchRequest): { keyword: string; path: Coordinate[] } {
  const keyword = request.keyword.trim()
  if (!keyword) throw new Error('请输入 POI 关键词')
  if (!Number.isInteger(request.page) || request.page < 1 || request.page > 100) {
    throw new Error('POI 页码必须是 1 到 100 的整数')
  }
  if (!Number.isInteger(request.pageSize) || request.pageSize < 1 || request.pageSize > 50) {
    throw new Error('POI 每页数量必须是 1 到 50 的整数')
  }

  const geometry = request.geometry as { type?: unknown; coordinates?: unknown }
  if (geometry.type !== 'Polygon') {
    throw new Error('当前 POI 查询暂不支持 MultiPolygon 缓冲区')
  }
  if (!Array.isArray(geometry.coordinates) || geometry.coordinates.length !== 1) {
    throw new Error('当前 POI 查询仅支持不含内部孔洞的单 Polygon 缓冲区')
  }

  const ring = geometry.coordinates[0]
  if (!Array.isArray(ring) || ring.length < 4) throw new Error('POI 查询 Polygon 无效')

  const path = ring.map((value): Coordinate => {
    if (
      !Array.isArray(value) ||
      value.length !== 2 ||
      typeof value[0] !== 'number' ||
      typeof value[1] !== 'number' ||
      !Number.isFinite(value[0]) ||
      !Number.isFinite(value[1]) ||
      value[0] < -180 ||
      value[0] > 180 ||
      value[1] < -90 ||
      value[1] > 90
    ) {
      throw new Error('POI 查询 Polygon 包含无效 WGS84 坐标')
    }
    return [value[0], value[1]]
  })

  const first = path[0]!
  const last = path[path.length - 1]!
  if (first[0] !== last[0] || first[1] !== last[1]) {
    throw new Error('POI 查询 Polygon 必须闭合')
  }
  return { keyword, path: path.map(wgs84ToGcj02) }
}

function validateGeometrySearchRequest(request: PoiGeometrySearchRequest): {
  keyword: string
  members: PolygonGeometry[]
} {
  const keyword = request.keyword.trim()
  if (!keyword) throw new Error('请输入 POI 关键词')

  const geometry = parseSourceGeometry(request.geometry)
  if (geometry.type !== 'Polygon' && geometry.type !== 'MultiPolygon') {
    throw new Error('复杂 POI 查询仅支持 Polygon 或 MultiPolygon 缓冲区')
  }

  const members =
    geometry.type === 'Polygon'
      ? [geometry]
      : geometry.coordinates.map(
          (coordinates): PolygonGeometry => ({ type: 'Polygon', coordinates }),
        )
  if (members.length > MAX_MEMBERS) {
    throw new Error(`复杂 POI 查询最多支持 ${MAX_MEMBERS} 个 Polygon member`)
  }
  return { keyword, members }
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

function callbackInfo(result: unknown): string | null {
  if (typeof result === 'string') return result
  if (isRecord(result) && typeof result.info === 'string') return result.info
  return null
}

function normalizePoi(value: unknown): PoiDto {
  if (!isRecord(value) || typeof value.id !== 'string' || typeof value.name !== 'string') {
    throw new Error('高德 POI 响应缺少 id 或 name')
  }
  const location = value.location as AMapLngLat | undefined
  if (!location || typeof location.getLng !== 'function' || typeof location.getLat !== 'function') {
    throw new Error('高德 POI 响应缺少 location')
  }
  const gcj02: Coordinate = [location.getLng(), location.getLat()]
  if (!gcj02.every(Number.isFinite)) throw new Error('高德 POI location 无效')

  const id = value.id.trim()
  const name = value.name.trim()
  if (!id || !name) throw new Error('高德 POI 响应包含空 id 或 name')
  return {
    id,
    name,
    type: typeof value.type === 'string' ? value.type : '',
    typeCode: typeof value.typecode === 'string' ? value.typecode : '',
    address: typeof value.address === 'string' ? value.address : '',
    locationWgs84: gcj02ToWgs84(gcj02),
  }
}

function normalizeCompleteResult(
  result: unknown,
  page: number,
  pageSize: number,
): PoiSearchResult {
  if (!isRecord(result) || !isRecord(result.poiList)) {
    throw new Error('高德 POI complete 响应缺少 poiList')
  }
  const { count, pois } = result.poiList
  if (!Number.isInteger(count) || (count as number) < 0 || !Array.isArray(pois)) {
    throw new Error('高德 POI complete 响应格式无效')
  }
  return {
    items: pois.map(normalizePoi),
    total: count as number,
    page,
    pageSize,
  }
}

async function searchAmapPoiPage(
  keyword: string,
  path: Coordinate[],
  page: number,
  pageSize: number,
): Promise<PoiSearchResult> {
  const amap = await loadPlaceSearchNamespace()
  const PlaceSearch = amap.PlaceSearch
  if (!PlaceSearch) throw new Error('AMap.PlaceSearch 插件不可用')

  const placeSearch = new PlaceSearch({ pageIndex: page, pageSize, extensions: 'all' })
  return new Promise((resolve, reject) => {
    placeSearch.searchInBounds(keyword, path, (status, result) => {
      try {
        if (status === 'no_data') {
          resolve({ items: [], total: 0, page, pageSize })
          return
        }
        if (status !== 'complete') {
          reject(new AmapPoiSearchError(status, callbackInfo(result)))
          return
        }
        resolve(normalizeCompleteResult(result, page, pageSize))
      } catch (error: unknown) {
        reject(error)
      }
    })
  })
}

type RingRelation = 'outside' | 'inside' | 'boundary'

function pointOnSegment(point: Coordinate, start: Coordinate, end: Coordinate): boolean {
  const cross =
    (point[0] - start[0]) * (end[1] - start[1]) -
    (point[1] - start[1]) * (end[0] - start[0])
  if (Math.abs(cross) > POINT_ON_SEGMENT_EPSILON) return false

  return (
    point[0] >= Math.min(start[0], end[0]) - POINT_ON_SEGMENT_EPSILON &&
    point[0] <= Math.max(start[0], end[0]) + POINT_ON_SEGMENT_EPSILON &&
    point[1] >= Math.min(start[1], end[1]) - POINT_ON_SEGMENT_EPSILON &&
    point[1] <= Math.max(start[1], end[1]) + POINT_ON_SEGMENT_EPSILON
  )
}

function pointInRing(point: Coordinate, ring: Coordinate[]): RingRelation {
  let inside = false
  for (let index = 0; index < ring.length - 1; index += 1) {
    const start = ring[index]!
    const end = ring[index + 1]!
    if (pointOnSegment(point, start, end)) return 'boundary'

    const crossesLatitude = (start[1] > point[1]) !== (end[1] > point[1])
    if (
      crossesLatitude &&
      point[0] <
        ((end[0] - start[0]) * (point[1] - start[1])) / (end[1] - start[1]) + start[0]
    ) {
      inside = !inside
    }
  }
  return inside ? 'inside' : 'outside'
}

function pointInPolygon(point: Coordinate, polygon: PolygonGeometry): boolean {
  // Provider 只查询 outer ring；回到 WGS84 后再按完整 Polygon 过滤，孔洞边界仍属于 Polygon。
  if (pointInRing(point, polygon.coordinates[0]!) === 'outside') return false
  return polygon.coordinates.slice(1).every((hole) => pointInRing(point, hole) !== 'inside')
}

function aggregateResult(
  items: Map<string, PoiDto>,
  reportedCandidateCount: number,
  truncatedReason: PoiGeometrySearchTruncatedReason | null,
): PoiGeometrySearchResult {
  const aggregatedItems = Array.from(items.values())
  const retrievalComplete = truncatedReason === null
  return {
    items: aggregatedItems,
    reportedCandidateCount,
    retrievedUniqueCount: aggregatedItems.length,
    retrievalComplete,
    hasMore: !retrievalComplete,
    truncatedReason,
  }
}

export async function searchAmapPois(request: PoiSearchRequest): Promise<PoiSearchResult> {
  const { keyword, path } = validateRequest(request)
  return searchAmapPoiPage(keyword, path, request.page, request.pageSize)
}

export async function searchAmapPoisInGeometry(
  request: PoiGeometrySearchRequest,
): Promise<PoiGeometrySearchResult> {
  const { keyword, members } = validateGeometrySearchRequest(request)
  const activeMembers = members.map(() => true)
  const uniqueItems = new Map<string, PoiDto>()
  let reportedCandidateCount = 0
  let providerCalls = 0
  let rawRows = 0

  // 页优先轮询保证每个 member 先获得同一页机会，避免首个大 Polygon 独占全局预算。
  for (let page = 1; activeMembers.some(Boolean); page += 1) {
    for (let memberIndex = 0; memberIndex < members.length; memberIndex += 1) {
      if (!activeMembers[memberIndex]) continue
      if (providerCalls >= MAX_PROVIDER_CALLS) {
        return aggregateResult(uniqueItems, reportedCandidateCount, 'provider-call-limit')
      }

      const member = members[memberIndex]!
      const outerPath = member.coordinates[0]!.map(wgs84ToGcj02)
      const result = await searchAmapPoiPage(keyword, outerPath, page, PROVIDER_PAGE_SIZE)
      providerCalls += 1
      if (page === 1) reportedCandidateCount += result.total

      if (result.items.length === 0) {
        activeMembers[memberIndex] = false
        continue
      }

      const remainingRows = MAX_RAW_ROWS - rawRows
      const acceptedRows = result.items.slice(0, remainingRows)
      rawRows += acceptedRows.length
      for (const item of acceptedRows) {
        if (pointInPolygon(item.locationWgs84, member) && !uniqueItems.has(item.id)) {
          uniqueItems.set(item.id, item)
        }
      }

      if (result.items.length > remainingRows || rawRows >= MAX_RAW_ROWS) {
        return aggregateResult(uniqueItems, reportedCandidateCount, 'raw-row-limit')
      }
    }
  }

  return aggregateResult(uniqueItems, reportedCandidateCount, null)
}
