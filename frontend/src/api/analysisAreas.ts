import { http } from '@/api/http'
import type {
  AdministrativeBoundariesNormalizeRequest,
  AdministrativeBoundariesNormalizeResponse,
  AnalysisAreaBufferRequest,
  AnalysisAreaBufferResponse,
  BufferGeometry,
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
