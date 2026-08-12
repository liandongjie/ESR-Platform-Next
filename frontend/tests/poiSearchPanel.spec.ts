import { createPinia, setActivePinia } from 'pinia'
import {
  ElAlert,
  ElButton,
  ElEmpty,
  ElInput,
  ElPagination,
  ElTag,
} from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import PoiSearchPanel from '@/components/poi/PoiSearchPanel.vue'
import type { PoiExportData } from '@/export/poiCsv'
import { useAnalysisStore } from '@/stores/analysis'

const createObjectURL = vi.fn<(blob: Blob) => string>(() => 'blob:poi-csv')
const revokeObjectURL = vi.fn()
const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

function mountPanel() {
  return mount(PoiSearchPanel, {
    global: {
      plugins: [createPinia()],
      components: { ElAlert, ElButton, ElEmpty, ElInput, ElPagination, ElTag },
    },
  })
}

function populatePoiResult(store: ReturnType<typeof useAnalysisStore>) {
  store.poiKeyword = '学校'
  store.poiCommittedKeyword = '学校'
  store.poiItems = [
    {
      id: 'poi-1',
      name: '学校',
      type: '科教文化服务',
      typeCode: '141200',
      address: '南京市',
      locationWgs84: [118.81, 32.02],
    },
  ]
  store.poiTotal = 6001
  store.poiHasSearched = true
}

function populateTruncatedComplexResult(store: ReturnType<typeof useAnalysisStore>) {
  populatePoiResult(store)
  store.poiAggregatedItems = [...store.poiItems]
  store.poiReportedCandidateCount = 99
  store.poiRetrievedUniqueCount = 12
  store.poiRetrievalComplete = false
  store.poiHasMore = true
  store.poiTruncatedReason = 'raw-row-limit'
}

function exportButton(wrapper: ReturnType<typeof mountPanel>, label: string) {
  const button = wrapper.findAll('button').find((item) => item.text().includes(label))
  if (!button) throw new Error(`missing button: ${label}`)
  return button
}

function exportData(mode: PoiExportData['mode']): PoiExportData {
  return {
    mode,
    keyword: '学校',
    page: mode === 'current-page' ? 1 : null,
    items: [
      {
        id: 'poi-1',
        name: '学校',
        type: '科教文化服务',
        typeCode: '141200',
        address: '南京市',
        locationWgs84: [118.81, 32.02],
      },
    ],
    totalReported: 6001,
    retrievableLimit: 5000,
    exportedCount: 1,
  }
}

describe('PoiSearchPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    createObjectURL.mockReset().mockReturnValue('blob:poi-csv')
    revokeObjectURL.mockReset()
    anchorClick.mockReset().mockImplementation(() => {})
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
  })

  it('submits the first page from Enter', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    const search = vi.spyOn(store, 'searchPois').mockResolvedValue()

    await wrapper.get('input').setValue('学校')
    await wrapper.get('input').trigger('keyup.enter')

    expect(store.poiKeyword).toBe('学校')
    expect(search).toHaveBeenCalledWith(1)
  })

  it('renders total, current results, and a page-count capped at 100', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    store.poiItems = [
      {
        id: 'poi-1',
        name: '学校',
        type: '',
        typeCode: '',
        address: '',
        locationWgs84: [118.81, 32.02],
      },
    ]
    store.poiTotal = 2000
    store.poiHasSearched = true
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('高德报告 2,000 条')
    expect(wrapper.text()).toContain('学校')
    expect(wrapper.getComponent(ElPagination).props('pageCount')).toBe(100)
  })

  it('renders retrieved complex semantics, local pages, and the truncation warning', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    populateTruncatedComplexResult(store)
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('已获取 12 条')
    expect(wrapper.text()).toContain('候选报告 99 条（非严格总数）')
    expect(wrapper.text()).not.toContain('高德报告 99 条')
    expect(wrapper.text()).toContain('达到 5,000 条 Provider 原始结果上限')
    expect(wrapper.text()).toContain('仅展示和导出已获取结果')
    expect(wrapper.getComponent(ElPagination).props('pageCount')).toBe(2)
  })

  it('delegates page changes to Store local-or-provider pagination', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    populateTruncatedComplexResult(store)
    const changePage = vi.spyOn(store, 'changePoiPage').mockResolvedValue()
    await wrapper.vm.$nextTick()

    wrapper.getComponent(ElPagination).vm.$emit('current-change', 2)
    await wrapper.vm.$nextTick()

    expect(changePage).toHaveBeenCalledWith(2)
  })

  it('renders no_data as an empty success state', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    store.poiHasSearched = true
    store.poiTotal = 0
    store.poiItems = []
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('当前缓冲区内未找到匹配 POI')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('renders the POI query error', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    store.poiError = '高德 POI 查询失败：error'
    await wrapper.vm.$nextTick()

    expect(wrapper.get('[role="alert"]').text()).toContain('高德 POI 查询失败：error')
  })

  it('downloads the current page and always cleans up its browser resources', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    populatePoiResult(store)
    await wrapper.vm.$nextTick()

    await exportButton(wrapper, '导出当前页').trigger('click')

    expect(createObjectURL).toHaveBeenCalledOnce()
    expect((createObjectURL.mock.calls[0]![0] as Blob).type).toBe('text/csv;charset=utf-8')
    expect(anchorClick).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:poi-csv')
    expect(document.body.querySelector('a[download]')).toBeNull()
    expect(wrapper.text()).toContain('已导出当前页 1 条 POI')
  })

  it('shows fixed-session progress and the 5000-row cap while fetching', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    populatePoiResult(store)
    let resolveExport: ((value: PoiExportData) => void) | undefined
    vi.spyOn(store, 'collectRetrievablePoiExport').mockImplementation(() => {
      store.poiExportLoading = true
      store.poiExportProgress = {
        currentPage: 3,
        plannedPages: 100,
        totalReported: 6001,
        retrievableLimit: 5000,
      }
      return new Promise((resolve) => {
        resolveExport = resolve
      })
    })
    await wrapper.vm.$nextTick()

    const pendingClick = exportButton(wrapper, '导出可获取结果').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('正在获取第 3 / 100 页')
    expect(wrapper.text()).toContain('高德报告 6,001 条，本次最多尝试获取 5,000 条')
    expect(exportButton(wrapper, '导出当前页').attributes('disabled')).toBeDefined()
    expect(exportButton(wrapper, '导出可获取结果').attributes('disabled')).toBeDefined()

    store.poiExportLoading = false
    store.poiExportProgress = null
    resolveExport?.(exportData('retrievable'))
    await pendingClick
    await flushPromises()

    expect(wrapper.text()).toContain('高德报告 6,001 条')
    expect(wrapper.text()).toContain('本次最多尝试获取 5,000 条')
    expect(wrapper.text()).toContain('实际导出 1 条')
  })

  it('labels a truncated complex export as only the retrieved result', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    populateTruncatedComplexResult(store)
    vi.spyOn(store, 'collectRetrievablePoiExport').mockResolvedValue(exportData('retrievable'))
    await wrapper.vm.$nextTick()

    await exportButton(wrapper, '导出可获取结果').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('查询已截断；已导出已获取结果 1 条 POI')
  })

  it('does not create an artifact when the Store returns no export data', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    populatePoiResult(store)
    vi.spyOn(store, 'prepareCurrentPagePoiExport').mockReturnValue(null)
    await wrapper.vm.$nextTick()

    await exportButton(wrapper, '导出当前页').trigger('click')

    expect(createObjectURL).not.toHaveBeenCalled()
    expect(anchorClick).not.toHaveBeenCalled()
  })

  it.each(['createObjectURL', 'createElement', 'appendChild', 'click'])(
    'cleans up POI CSV resources when %s fails',
    async (failurePoint) => {
      const wrapper = mountPanel()
      const store = useAnalysisStore()
      populatePoiResult(store)
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
      await wrapper.vm.$nextTick()

      await exportButton(wrapper, '导出当前页').trigger('click')
      createElementSpy?.mockRestore()

      expect(store.poiExportError).toContain('failed')
      expect(document.body.querySelector('a[download]')).toBeNull()
      expect(revokeObjectURL).toHaveBeenCalledTimes(failurePoint === 'createObjectURL' ? 0 : 1)
    },
  )
})
