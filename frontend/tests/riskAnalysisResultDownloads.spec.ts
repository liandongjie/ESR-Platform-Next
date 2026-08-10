import { flushPromises, mount } from '@vue/test-utils'
import { ElAlert, ElButton } from 'element-plus'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { downloadRiskAnalysisArtifact } from '@/api/riskAnalysis'
import RiskAnalysisResultDownloads from '@/components/risk-analysis/RiskAnalysisResultDownloads.vue'

vi.mock('@/api/riskAnalysis', () => ({
  downloadRiskAnalysisArtifact: vi.fn(),
}))

const mockedDownload = vi.mocked(downloadRiskAnalysisArtifact)
const createObjectURL = vi.fn(() => 'blob:download')
const revokeObjectURL = vi.fn()
const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function mountDownloads() {
  return mount(RiskAnalysisResultDownloads, {
    props: { taskId: 'task-1' },
    global: {
      components: {
        ElButton,
        ElAlert,
      },
    },
  })
}

describe('RiskAnalysisResultDownloads', () => {
  beforeEach(() => {
    mockedDownload.mockReset()
    createObjectURL.mockClear()
    revokeObjectURL.mockClear()
    anchorClick.mockClear()
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
  })

  it('downloads both artifact kinds with independent loading and blocks duplicate clicks', async () => {
    const raster = deferred<{ blob: Blob; filename: string }>()
    mockedDownload.mockImplementation((_taskId, kind) => {
      if (kind === 'raster') return raster.promise
      return Promise.resolve({ blob: new Blob(['json']), filename: 'result.json' })
    })
    const wrapper = mountDownloads()
    const buttons = wrapper.findAll('button')

    await buttons[0]!.trigger('click')
    await nextTick()
    expect(buttons[0]!.attributes('disabled')).toBeDefined()
    expect(buttons[1]!.attributes('disabled')).toBeUndefined()
    await buttons[0]!.trigger('click')
    await buttons[1]!.trigger('click')
    await flushPromises()

    expect(mockedDownload).toHaveBeenCalledTimes(2)
    expect(mockedDownload).toHaveBeenCalledWith('task-1', 'raster')
    expect(mockedDownload).toHaveBeenCalledWith('task-1', 'manifest')

    raster.resolve({ blob: new Blob(['tif']), filename: 'risk.tif' })
    await flushPromises()
    expect(createObjectURL).toHaveBeenCalledTimes(2)
    expect(revokeObjectURL).toHaveBeenCalledTimes(2)
    expect(anchorClick).toHaveBeenCalledTimes(2)
    expect(document.body.querySelector('a[download]')).toBeNull()
  })

  it('keeps warnings independent and leaves the other artifact usable', async () => {
    mockedDownload.mockImplementation((_taskId, kind) => {
      if (kind === 'raster') return Promise.reject(new Error('栅格下载失败'))
      return Promise.resolve({ blob: new Blob(['json']), filename: 'result.json' })
    })
    const wrapper = mountDownloads()
    const buttons = wrapper.findAll('button')

    await buttons[0]!.trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toBe('栅格下载失败')

    await buttons[1]!.trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toBe('栅格下载失败')
    expect(buttons[1]!.attributes('disabled')).toBeUndefined()
  })

  it.each(['createObjectURL', 'createElement', 'appendChild', 'click'])(
    'cleans up resources when %s fails',
    async (failurePoint) => {
      mockedDownload.mockResolvedValue({ blob: new Blob(['tif']), filename: 'risk.tif' })
      const wrapper = mountDownloads()
      let createElementSpy: ReturnType<typeof vi.spyOn> | null = null
      if (failurePoint === 'createObjectURL') {
        createObjectURL.mockImplementationOnce(() => {
          throw new Error('create failed')
        })
      } else if (failurePoint === 'createElement') {
        const originalCreateElement = document.createElement.bind(document)
        createElementSpy = vi.spyOn(document, 'createElement').mockImplementation(((
          tagName: string,
          options?: ElementCreationOptions,
        ) => {
          if (tagName === 'a') throw new Error('element failed')
          return originalCreateElement(tagName, options)
        }) as typeof document.createElement)
      } else if (failurePoint === 'appendChild') {
        vi.spyOn(document.body, 'appendChild').mockImplementationOnce(() => {
          throw new Error('append failed')
        })
      } else {
        anchorClick.mockImplementationOnce(() => {
          throw new Error('click failed')
        })
      }

      await wrapper.get('button').trigger('click')
      await flushPromises()
      createElementSpy?.mockRestore()

      expect(wrapper.get('[role="alert"]').text()).toContain('failed')
      expect(document.body.querySelector('a[download]')).toBeNull()
      expect(revokeObjectURL).toHaveBeenCalledTimes(failurePoint === 'createObjectURL' ? 0 : 1)
      expect(wrapper.get('button').attributes('disabled')).toBeUndefined()
    },
  )
})
