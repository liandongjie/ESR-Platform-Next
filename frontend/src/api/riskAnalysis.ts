import axios from 'axios'

import { http } from '@/api/http'
import {
  parseRiskAnalysisResult,
  parseRiskAnalysisSpatialResult,
} from '@/validation/riskAnalysisResult'
import { parseRiskAnalysisSubmission } from '@/validation/riskAnalysisSubmission'
import { parseRiskIndicatorCatalog } from '@/validation/riskIndicatorCatalog'
import type {
  RiskAnalysisJobCreated,
  RiskAnalysisJobRequest,
  RiskAnalysisJobHistoryResponse,
  RiskAnalysisJobStatus,
  RiskIndicatorCatalog,
  RiskAnalysisResult,
  RiskAnalysisSpatialResult,
  RiskAnalysisSubmissionDetail,
} from '@/types/riskAnalysis'

const DEFAULT_RETRY_AFTER_MS = 2000

export type RiskAnalysisArtifactKind = 'raster' | 'manifest' | 'preview'

export interface DownloadedRiskAnalysisArtifact {
  blob: Blob
  filename: string
}

const ARTIFACT_FILENAME_SUFFIXES: Record<RiskAnalysisArtifactKind, string> = {
  raster: 'risk.tif',
  manifest: 'result.json',
  preview: 'preview.png',
}

export interface CreatedRiskAnalysisJob {
  job: RiskAnalysisJobCreated
  retryAfterMs: number
}

export async function getRiskIndicatorCatalog(): Promise<RiskIndicatorCatalog> {
  const response = await http.get<unknown>('/meta/risk-indicators')
  return parseRiskIndicatorCatalog(response.data)
}

function retryAfterMilliseconds(value: unknown): number {
  const seconds = Number(value)
  if (!Number.isFinite(seconds) || seconds <= 0) return DEFAULT_RETRY_AFTER_MS
  return seconds * 1000
}

function artifactFilename(
  contentDisposition: unknown,
  taskId: string,
  kind: RiskAnalysisArtifactKind,
) {
  if (typeof contentDisposition === 'string') {
    const match = /(?:^|;)\s*filename\s*=\s*(?:"([^"]+)"|([^;\s]+))/i.exec(contentDisposition)
    const filename = match?.[1] ?? match?.[2]
    if (filename) return filename
  }
  return `risk-analysis-${taskId}-${ARTIFACT_FILENAME_SUFFIXES[kind]}`
}

async function restoreBlobErrorPayload(error: unknown): Promise<void> {
  if (!axios.isAxiosError(error) || !(error.response?.data instanceof Blob)) return

  try {
    error.response.data = JSON.parse(await error.response.data.text())
  } catch {
    // Blob 不是 JSON 时保留原 AxiosError，继续复用既有 timeout/network/fallback 处理。
  }
}

export async function createRiskAnalysisJob(
  payload: RiskAnalysisJobRequest,
): Promise<CreatedRiskAnalysisJob> {
  // 幂等键在单次用户提交边界生成；Axios 的认证重放复用同一 request config，不会更换键。
  const response = await http.post<RiskAnalysisJobCreated>('/risk-analysis/jobs', payload, {
    headers: { 'Idempotency-Key': crypto.randomUUID() },
  })
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

export async function getRiskAnalysisSubmission(
  taskId: string,
): Promise<RiskAnalysisSubmissionDetail> {
  const response = await http.get<unknown>(
    `/risk-analysis/jobs/${encodeURIComponent(taskId)}/submission`,
  )
  return parseRiskAnalysisSubmission(response.data, taskId)
}

export async function getRiskAnalysisResult(taskId: string): Promise<RiskAnalysisResult> {
  const response = await http.get<unknown>(
    `/risk-analysis/jobs/${encodeURIComponent(taskId)}/result`,
  )
  if (response.status !== 200) {
    throw new Error('风险分析结果尚未就绪')
  }
  // TypeScript 泛型不会校验运行时 JSON；只有通过结构检查的数据才能进入 Pinia 和模板。
  return parseRiskAnalysisResult(response.data, taskId)
}

export async function getRiskAnalysisSpatialResult(
  taskId: string,
): Promise<RiskAnalysisSpatialResult> {
  const response = await http.get<unknown>(
    `/risk-analysis/jobs/${encodeURIComponent(taskId)}/result/spatial`,
  )
  if (response.status !== 200) {
    throw new Error('空间风险结果尚未就绪')
  }
  return parseRiskAnalysisSpatialResult(response.data, taskId)
}

export async function downloadRiskAnalysisArtifact(
  taskId: string,
  kind: RiskAnalysisArtifactKind,
): Promise<DownloadedRiskAnalysisArtifact> {
  try {
    const response = await http.get<Blob>(
      `/risk-analysis/jobs/${encodeURIComponent(taskId)}/result/artifacts/${kind}`,
      {
        responseType: 'blob',
        // 202 仍是未就绪错误，不得被 Axios 的默认 2xx 规则当作可下载文件。
        validateStatus: (status) => status === 200,
      },
    )
    return {
      blob: response.data,
      filename: artifactFilename(response.headers['content-disposition'], taskId, kind),
    }
  } catch (error: unknown) {
    await restoreBlobErrorPayload(error)
    throw error
  }
}

export async function downloadRiskAnalysisPreview(
  taskId: string,
): Promise<DownloadedRiskAnalysisArtifact> {
  const artifact = await downloadRiskAnalysisArtifact(taskId, 'preview')
  if (artifact.blob.size === 0 || artifact.blob.type.toLowerCase() !== 'image/png') {
    throw new Error('风险预览文件格式无效')
  }
  return artifact
}

export function isRiskAnalysisPreviewUnavailable(error: unknown): boolean {
  return (
    axios.isAxiosError(error) &&
    (error.response?.status === 404 || error.response?.status === 410)
  )
}
