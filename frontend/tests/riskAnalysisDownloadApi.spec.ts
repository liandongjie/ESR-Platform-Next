import axios, { type AxiosError } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getApiErrorMessage } from '@/api/errors'
import { http } from '@/api/http'
import { downloadRiskAnalysisArtifact } from '@/api/riskAnalysis'

vi.mock('@/api/http', () => ({
  http: {
    get: vi.fn(),
  },
}))

const mockedGet = vi.mocked(http.get)

function jsonBlob(payload: unknown): Blob {
  const blob = new Blob([], { type: 'application/json' })
  Object.defineProperty(blob, 'text', {
    value: vi.fn().mockResolvedValue(JSON.stringify(payload)),
  })
  return blob
}

function blobAxiosError(data: Blob, status: number): AxiosError {
  return {
    isAxiosError: true,
    name: 'AxiosError',
    message: 'Request failed',
    toJSON: () => ({}),
    response: { data, status },
  } as AxiosError
}

describe('downloadRiskAnalysisArtifact', () => {
  beforeEach(() => {
    mockedGet.mockReset()
  })

  it.each([
    ['attachment; filename="backend-result.tif"', 'backend-result.tif'],
    ['attachment; filename=backend-result.tif', 'backend-result.tif'],
    [undefined, 'risk-analysis-task/with space-risk.tif'],
  ])('uses a simple Content-Disposition filename or fallback', async (header, filename) => {
    const blob = new Blob(['raster'])
    mockedGet.mockResolvedValue({
      data: blob,
      headers: { 'content-disposition': header },
    } as never)

    await expect(downloadRiskAnalysisArtifact('task/with space', 'raster')).resolves.toEqual({
      blob,
      filename,
    })

    const [url, config] = mockedGet.mock.calls[0]!
    expect(url).toBe('/risk-analysis/jobs/task%2Fwith%20space/result/artifacts/raster')
    expect(config?.responseType).toBe('blob')
    expect(config?.validateStatus?.(200)).toBe(true)
    expect(config?.validateStatus?.(202)).toBe(false)
    expect(config?.validateStatus?.(404)).toBe(false)
    expect(config?.validateStatus?.(409)).toBe(false)
  })

  it('uses the manifest fallback filename', async () => {
    const blob = new Blob(['manifest'])
    mockedGet.mockResolvedValue({ data: blob, headers: {} } as never)

    await expect(downloadRiskAnalysisArtifact('task-1', 'manifest')).resolves.toEqual({
      blob,
      filename: 'risk-analysis-task-1-result.json',
    })
  })

  it.each([202, 404, 409])(
    'restores a JSON Blob payload on the original AxiosError for status %s',
    async (status) => {
      const payload = { code: 'RESULT_ERROR', message: `后端错误 ${status}` }
      const error = blobAxiosError(jsonBlob(payload), status)
      mockedGet.mockRejectedValue(error)

      const caught = await downloadRiskAnalysisArtifact('task-1', 'raster').catch(
        (reason: unknown) => reason,
      )

      expect(caught).toBe(error)
      expect(error.response?.data).toEqual(payload)
      expect(getApiErrorMessage(error, '下载失败')).toBe(payload.message)
    },
  )

  it('preserves the original AxiosError when the Blob is not JSON', async () => {
    const blob = jsonBlob({ ignored: true })
    vi.mocked(blob.text).mockResolvedValue('not-json')
    const error = blobAxiosError(blob, 409)
    mockedGet.mockRejectedValue(error)

    const caught = await downloadRiskAnalysisArtifact('task-1', 'manifest').catch(
      (reason: unknown) => reason,
    )

    expect(caught).toBe(error)
    expect(error.response?.data).toBe(blob)
  })

  it.each([
    Object.assign(new Error('timeout'), { isAxiosError: true, code: 'ECONNABORTED' }),
    Object.assign(new Error('network'), { isAxiosError: true }),
  ])('preserves timeout and no-response Axios errors', async (error) => {
    mockedGet.mockRejectedValue(error)

    const caught = await downloadRiskAnalysisArtifact('task-1', 'raster').catch(
      (reason: unknown) => reason,
    )

    expect(axios.isAxiosError(caught)).toBe(true)
    expect(caught).toBe(error)
  })
})
