import { http } from '@/api/http'
import type {
  RiskAnalysisJobCreated,
  RiskAnalysisJobRequest,
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

export async function getRiskAnalysisJob(taskId: string): Promise<RiskAnalysisJobStatus> {
  const response = await http.get<RiskAnalysisJobStatus>(
    `/risk-analysis/jobs/${encodeURIComponent(taskId)}`,
  )
  return response.data
}

export async function getRiskAnalysisResult(taskId: string): Promise<RiskAnalysisResult> {
  const response = await http.get<RiskAnalysisResult>(
    `/risk-analysis/jobs/${encodeURIComponent(taskId)}/result`,
  )
  if (response.status !== 200) {
    throw new Error('风险分析结果尚未就绪')
  }
  return response.data
}
