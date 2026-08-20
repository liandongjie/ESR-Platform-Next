import { beforeEach, describe, expect, it, vi } from 'vitest'

import { http } from '@/api/http'
import { createRiskAnalysisJob } from '@/api/riskAnalysis'
import type { RiskAnalysisJobRequest } from '@/types/riskAnalysis'

const payload: RiskAnalysisJobRequest = {
  geometry: {
    type: 'Polygon',
    coordinates: [
      [
        [118.89, 32.09],
        [118.9, 32.09],
        [118.9, 32.1],
        [118.89, 32.1],
        [118.89, 32.09],
      ],
    ],
  },
  weights: [
    { code: 'PM25', weight_percent: 30 },
    { code: 'AQI', weight_percent: 40 },
    { code: 'NDVI', weight_percent: 30 },
  ],
}

describe('create risk analysis API', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('generates one idempotency key for a submission request', async () => {
    const key = '11111111-1111-4111-8111-111111111111'
    const randomUUID = vi.spyOn(crypto, 'randomUUID').mockReturnValue(key)
    const post = vi.spyOn(http, 'post').mockResolvedValue({
      data: {
        task_id: 'task-1',
        status: 'QUEUED',
        submitted_at: '2026-08-20T00:00:00Z',
        status_url: '/api/v1/risk-analysis/jobs/task-1',
        result_url: '/api/v1/risk-analysis/jobs/task-1/result',
      },
      headers: { 'retry-after': '2' },
    } as never)

    await expect(createRiskAnalysisJob(payload)).resolves.toMatchObject({
      job: { task_id: 'task-1' },
      retryAfterMs: 2000,
    })

    expect(randomUUID).toHaveBeenCalledOnce()
    expect(post).toHaveBeenCalledWith('/risk-analysis/jobs', payload, {
      headers: { 'Idempotency-Key': key },
    })
  })
})
