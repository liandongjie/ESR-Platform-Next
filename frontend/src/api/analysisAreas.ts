import { http } from '@/api/http'
import type {
  AnalysisAreaBufferRequest,
  AnalysisAreaBufferResponse,
} from '@/types/analysisArea'

export async function createAnalysisAreaBuffer(
  payload: AnalysisAreaBufferRequest,
): Promise<AnalysisAreaBufferResponse> {
  const response = await http.post<AnalysisAreaBufferResponse>('/analysis-areas/buffer', payload)
  return response.data
}
