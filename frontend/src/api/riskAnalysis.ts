import { http } from '@/api/http'
import { parseRiskAnalysisResult } from '@/validation/riskAnalysisResult'
import type {
  RiskAnalysisJobCreated,
  RiskAnalysisJobRequest,
  RiskAnalysisJobHistoryResponse,
  RiskAnalysisJobStatus,
  RiskAnalysisResult,
} from '@/types/riskAnalysis'

const DEFAULT_RETRY_AFTER_MS = 2000

export interface CreatedRiskAnalysisJob {
  job: RiskAnalysisJobCreated
  retryAfterMs: number
}

function retryAfterMilliseconds(value: unknown): number {
  const seconds = Number(value)
  if (!Number.isFinite(seconds) || seconds <= 0) return DEFAULT_RETRY_AFTER_MS
  return seconds * 1000
}

export async function createRiskAnalysisJob(
  payload: RiskAnalysisJobRequest,
): Promise<CreatedRiskAnalysisJob> {
  const response = await http.post<RiskAnalysisJobCreated>('/risk-analysis/jobs', payload)
  return {
    job: response.data,
    // 后端通过标准 Retry-After 告诉客户端建议轮询间隔；缺失时才使用前端保守默认值。
    retryAfterMs: retryAfterMilliseconds(response.headers['retry-after']),
  }
}

export async function listRiskAnalysisJobs(
  limit = 20,
  offset = 0,
): Promise<RiskAnalysisJobHistoryResponse> {
  const response = await http.get<RiskAnalysisJobHistoryResponse>('/risk-analysis/jobs', {
    params: { limit, offset },
  })
  return response.data
}

export async function getRiskAnalysisJob(taskId: string): Promise<RiskAnalysisJobStatus> {
  const response = await http.get<RiskAnalysisJobStatus>(
    `/risk-analysis/jobs/${encodeURIComponent(taskId)}`,
  )
  return response.data
}

export async function getRiskAnalysisResult(taskId: string): Promise<RiskAnalysisResult> {
  const response = await http.get<unknown>(
    `/risk-analysis/jobs/${encodeURIComponent(taskId)}/result`,
  )
  if (response.status !== 200) {
    throw new Error('风险分析结果尚未就绪')
  }
  // TypeScript 泛型不会校验运行时 JSON；只有通过结构检查的数据才能进入 Pinia 和模板。
  return parseRiskAnalysisResult(response.data)
}
