import type { BufferGeometry, Coordinate } from '@/types/analysisArea'
import type {
  RiskAnalysisSubmissionDetail,
  RiskIndicatorWeightInput,
} from '@/types/riskAnalysis'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isCoordinate(value: unknown): value is Coordinate {
  return (
    Array.isArray(value) &&
    value.length === 2 &&
    isFiniteNumber(value[0]) &&
    isFiniteNumber(value[1])
  )
}

function isPolygonCoordinates(value: unknown): value is Coordinate[][] {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every(
      (ring) => Array.isArray(ring) && ring.length >= 4 && ring.every(isCoordinate),
    )
  )
}

function isBufferGeometry(value: unknown): value is BufferGeometry {
  if (!isRecord(value)) return false
  if (value.type === 'Polygon') return isPolygonCoordinates(value.coordinates)
  return (
    value.type === 'MultiPolygon' &&
    Array.isArray(value.coordinates) &&
    value.coordinates.length > 0 &&
    value.coordinates.every(isPolygonCoordinates)
  )
}

function isWeight(value: unknown): value is RiskIndicatorWeightInput {
  if (!isRecord(value)) return false
  return (
    typeof value.code === 'string' &&
    value.code.length > 0 &&
    value.code.length <= 64 &&
    isFiniteNumber(value.weight_percent) &&
    value.weight_percent >= 0 &&
    value.weight_percent <= 100
  )
}

export function parseRiskAnalysisSubmission(
  value: unknown,
  expectedTaskId: string,
): RiskAnalysisSubmissionDetail {
  const invalid = new Error('任务提交上下文格式不完整或不受当前 Workspace 支持')
  if (!isRecord(value) || value.task_id !== expectedTaskId) throw invalid
  if (typeof value.submitted_at !== 'string' || value.submitted_at.length === 0) throw invalid
  if (!isRecord(value.request) || !isBufferGeometry(value.request.geometry)) throw invalid
  if (
    !Array.isArray(value.request.weights) ||
    value.request.weights.length === 0 ||
    value.request.weights.length > 12 ||
    !value.request.weights.every(isWeight)
  ) {
    throw invalid
  }

  // 只接受地图已支持的 WGS84 Polygon/MultiPolygon；不在客户端修复或推断持久化数据。
  return value as unknown as RiskAnalysisSubmissionDetail
}
