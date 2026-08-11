import type { Coordinate, PolygonGeometry } from '@/types/analysisArea'

export interface PoiDto {
  id: string
  name: string
  type: string
  typeCode: string
  address: string
  locationWgs84: Coordinate
}

export interface PoiSearchRequest {
  geometry: PolygonGeometry
  keyword: string
  page: number
  pageSize: number
}

export interface PoiSearchResult {
  items: PoiDto[]
  total: number
  page: number
  pageSize: number
}
