import { describe, expect, it } from 'vitest'

import type { RiskAnalysisSubmissionDetail } from '@/types/riskAnalysis'
import { parseRiskAnalysisSubmission } from '@/validation/riskAnalysisSubmission'

function makeSubmission(): RiskAnalysisSubmissionDetail {
  return {
    task_id: 'task-1',
    submitted_at: '2026-08-08T12:00:00Z',
    request: {
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [118.86, 32.1],
            [118.9, 32.13],
            [118.94, 32.1],
            [118.86, 32.1],
          ],
        ],
      },
      weights: [
        { code: 'PM25', weight_percent: 30 },
        { code: 'AQI', weight_percent: 40 },
        { code: 'NDVI', weight_percent: 30 },
      ],
    },
  }
}

describe('risk analysis submission validator', () => {
  it('accepts the persisted Polygon submission contract', () => {
    const submission = makeSubmission()

    expect(parseRiskAnalysisSubmission(submission, 'task-1')).toBe(submission)
  })

  it('accepts MultiPolygon geometry supported by MapCanvas', () => {
    const submission = makeSubmission()
    const polygon = submission.request.geometry
    if (polygon.type !== 'Polygon') throw new Error('test fixture must be Polygon')
    submission.request.geometry = {
      type: 'MultiPolygon',
      coordinates: [polygon.coordinates],
    }

    expect(parseRiskAnalysisSubmission(submission, 'task-1').request.geometry.type).toBe(
      'MultiPolygon',
    )
  })

  it('rejects unsupported or malformed geometry instead of inferring a buffer', () => {
    const submission = makeSubmission()
    const request = submission.request as unknown as Record<string, unknown>
    request.geometry = {
      type: 'Point',
      coordinates: [118.9, 32.1],
    }

    expect(() => parseRiskAnalysisSubmission(submission, 'task-1')).toThrow(
      '不受当前 Workspace 支持',
    )
  })

  it('rejects task mismatches and non-finite weights', () => {
    const submission = makeSubmission()
    submission.request.weights[0]!.weight_percent = Number.NaN

    expect(() => parseRiskAnalysisSubmission(submission, 'other-task')).toThrow()
    expect(() => parseRiskAnalysisSubmission(submission, 'task-1')).toThrow()
  })
})
