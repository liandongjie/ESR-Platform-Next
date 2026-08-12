import type { BufferGeometry, Coordinate, PolygonGeometry } from '@/types/analysisArea'

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

export interface PoiGeometrySearchRequest {
  geometry: BufferGeometry
  keyword: string
}

export type PoiGeometrySearchTruncatedReason = 'provider-call-limit' | 'raw-row-limit'

export interface PoiGeometrySearchResult {
  items: PoiDto[]
  reportedCandidateCount: number
  retrievedUniqueCount: number
  retrievalComplete: boolean
  hasMore: boolean
  truncatedReason: PoiGeometrySearchTruncatedReason | null
}

export interface StudyPointCandidate {
  id: string
  name: string
  address: string
  district: string
  locationWgs84: Coordinate
}
