export type Coordinate = [number, number]

export interface PointGeometry {
  type: 'Point'
  coordinates: Coordinate
}

export interface LineStringGeometry {
  type: 'LineString'
  coordinates: Coordinate[]
}

export interface PolygonGeometry {
  type: 'Polygon'
  coordinates: Coordinate[][]
}

export interface MultiPolygonGeometry {
  type: 'MultiPolygon'
  coordinates: Coordinate[][][]
}

export type BufferGeometry = PolygonGeometry | MultiPolygonGeometry
export type SourceGeometry = PointGeometry | LineStringGeometry | PolygonGeometry

export interface AnalysisAreaBufferRequest {
  geometry: SourceGeometry
  distance_m: number
}

export interface AnalysisAreaBufferResponse {
  source: {
    crs: string
    geometry_type: string
    bounds: number[]
  }
  buffer: {
    crs: string
    distance_m: number
    working_crs: string
    area_m2: number
    area_km2: number
    bounds: number[]
    geometry: BufferGeometry
  }
}
