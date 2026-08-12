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
export type SourceGeometry =
  | PointGeometry
  | LineStringGeometry
  | PolygonGeometry
  | MultiPolygonGeometry

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

export interface AdministrativeBoundariesNormalizeRequest {
  boundaries: Coordinate[][]
}

export interface AdministrativeBoundariesNormalizeResponse {
  crs: 'EPSG:4326'
  geometry: BufferGeometry
  input_boundary_count: number
  output_polygon_count: number
}

export interface ShapefileImportResponse {
  crs: 'EPSG:4326'
  source_crs: string
  feature_count: number
  coordinate_count: number
  geometry: SourceGeometry
}
