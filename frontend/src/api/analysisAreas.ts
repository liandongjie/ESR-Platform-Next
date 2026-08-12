import { http } from '@/api/http'
import type {
  AdministrativeBoundariesNormalizeRequest,
  AdministrativeBoundariesNormalizeResponse,
  AnalysisAreaBufferRequest,
  AnalysisAreaBufferResponse,
  BufferGeometry,
  ShapefileImportResponse,
} from '@/types/analysisArea'
import { parseSourceGeometry } from '@/validation/sourceGeometry'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseNormalizeResponse(value: unknown): AdministrativeBoundariesNormalizeResponse {
  if (!isRecord(value) || value.crs !== 'EPSG:4326') {
    throw new Error('行政区 normalization 响应缺少 EPSG:4326 CRS')
  }
  if (
    !Number.isInteger(value.input_boundary_count) ||
    (value.input_boundary_count as number) < 1 ||
    !Number.isInteger(value.output_polygon_count) ||
    (value.output_polygon_count as number) < 1
  ) {
    throw new Error('行政区 normalization 响应 metadata 无效')
  }

  const geometry = parseSourceGeometry(value.geometry)
  if (geometry.type !== 'Polygon' && geometry.type !== 'MultiPolygon') {
    throw new Error('行政区 normalization 响应必须是 Polygon 或 MultiPolygon')
  }

  return {
    crs: 'EPSG:4326',
    geometry: geometry as BufferGeometry,
    input_boundary_count: value.input_boundary_count as number,
    output_polygon_count: value.output_polygon_count as number,
  }
}

function parseShapefileImportResponse(value: unknown): ShapefileImportResponse {
  if (!isRecord(value) || value.crs !== 'EPSG:4326') {
    throw new Error('Shapefile 导入响应缺少 EPSG:4326 CRS')
  }
  if (
    typeof value.source_crs !== 'string' ||
    value.source_crs.length === 0 ||
    !Number.isInteger(value.feature_count) ||
    (value.feature_count as number) < 1 ||
    !Number.isInteger(value.coordinate_count) ||
    (value.coordinate_count as number) < 1
  ) {
    throw new Error('Shapefile 导入响应 metadata 无效')
  }

  return {
    crs: 'EPSG:4326',
    source_crs: value.source_crs,
    feature_count: value.feature_count as number,
    coordinate_count: value.coordinate_count as number,
    geometry: parseSourceGeometry(value.geometry),
  }
}

export async function createAnalysisAreaBuffer(
  payload: AnalysisAreaBufferRequest,
): Promise<AnalysisAreaBufferResponse> {
  const response = await http.post<AnalysisAreaBufferResponse>('/analysis-areas/buffer', payload)
  return response.data
}

export async function normalizeAdministrativeBoundaries(
  payload: AdministrativeBoundariesNormalizeRequest,
): Promise<AdministrativeBoundariesNormalizeResponse> {
  const response = await http.post<unknown>('/analysis-areas/normalize-boundaries', payload)
  return parseNormalizeResponse(response.data)
}

export async function importShapefile(file: File): Promise<ShapefileImportResponse> {
  const form = new FormData()
  form.append('file', file)
  // 清除共享 client 的 JSON 默认值，交给浏览器生成包含 boundary 的 multipart header。
  const response = await http.post<unknown>('/analysis-areas/import-shapefile', form, {
    headers: { 'Content-Type': undefined },
  })
  return parseShapefileImportResponse(response.data)
}
