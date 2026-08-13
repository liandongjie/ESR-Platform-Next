import ElementPlus, { ElPagination } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import PoiResultPanel from '@/components/poi/PoiResultPanel.vue'
import PoiSearchPanel from '@/components/poi/PoiSearchPanel.vue'
import type { PoiExportData } from '@/export/poiCsv'
import { useAnalysisStore } from '@/stores/analysis'

const createObjectURL = vi.fn<(blob: Blob) => string>(() => 'blob:poi-csv')
const revokeObjectURL = vi.fn()
const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

function mountPanel() {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(PoiResultPanel, { global: { plugins: [pinia, ElementPlus] } })
}

function populateResult(store: ReturnType<typeof useAnalysisStore>) {
  store.poiKeyword = '学校'
  store.poiCommittedKeyword = '学校'
  store.poiItems = [{
    id: 'poi-1', name: '学校', type: '科教文化服务', typeCode: '141200', address: '南京市',
    locationWgs84: [118.81, 32.02],
  }]
  store.poiTotal = 6001
  store.poiHasSearched = true
}

function exportData(mode: PoiExportData['mode']): PoiExportData {
  return {
    mode,
    keyword: '学校',
    page: mode === 'current-page' ? 1 : null,
    items: [{
      id: 'poi-1', name: '学校', type: '科教文化服务', typeCode: '141200', address: '南京市',
      locationWgs84: [118.81, 32.02],
    }],
    totalReported: 6001,
    retrievableLimit: 5000,
    exportedCount: 1,
  }
}

function button(wrapper: ReturnType<typeof mountPanel>, label: string) {
  const target = wrapper.findAll('button').find((item) => item.text().includes(label))
  if (!target) throw new Error(`missing button: ${label}`)
  return target
}

describe('PoiResultPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    createObjectURL.mockReset().mockReturnValue('blob:poi-csv')
    revokeObjectURL.mockReset()
    anchorClick.mockReset().mockImplementation(() => {})
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
  })

  it('renders results and caps provider pagination at 100 pages', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    populateResult(store)
    store.poiTotal = 2000
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('高德报告 2,000 条')
    expect(wrapper.text()).toContain('学校')
    expect(wrapper.text()).not.toContain('POI 结果')
    expect(wrapper.getComponent(ElPagination).props('pageCount')).toBe(100)
  })

  it('renders complex retrieval semantics, local pages, and truncation', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    populateResult(store)
    store.poiAggregatedItems = [...store.poiItems]
    store.poiReportedCandidateCount = 99
    store.poiRetrievedUniqueCount = 12
    store.poiRetrievalComplete = false
    store.poiHasMore = true
    store.poiTruncatedReason = 'raw-row-limit'
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('已获取 12 条')
    expect(wrapper.text()).toContain('候选报告 99 条（非严格总数）')
    expect(wrapper.text()).toContain('达到 5,000 条 Provider 原始结果上限')
    expect(wrapper.getComponent(ElPagination).props('pageCount')).toBe(2)
  })

  it('renders an empty successful result', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    store.poiHasSearched = true
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('当前缓冲区内未找到匹配 POI')
  })

  it('delegates pagination without submitting a different keyword draft', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount({
      components: { PoiSearchPanel, PoiResultPanel },
      template: '<PoiSearchPanel :disabled="false" /><PoiResultPanel />',
    }, { global: { plugins: [pinia, ElementPlus] } })
    const store = useAnalysisStore()
    populateResult(store)
    store.poiTotal = 20
    await wrapper.vm.$nextTick()
    const setKeyword = vi.spyOn(store, 'setPoiKeyword')
    const changePage = vi.spyOn(store, 'changePoiPage').mockResolvedValue()
    vi.spyOn(store, 'prepareCurrentPagePoiExport').mockReturnValue(exportData('current-page'))

    await wrapper.get('input[aria-label="POI 关键词"]').setValue('医院')
    wrapper.getComponent(ElPagination).vm.$emit('current-change', 2)
    await wrapper.vm.$nextTick()
    await button(wrapper.findComponent(PoiResultPanel), '导出当前页').trigger('click')

    expect(store.poiKeyword).toBe('学校')
    expect(setKeyword).not.toHaveBeenCalled()
    expect(changePage).toHaveBeenCalledWith(2)
    expect(anchorClick).toHaveBeenCalledOnce()
  })

  it('keeps committed pagination and export available while analysis is locked', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    populateResult(store)
    store.poiTotal = 20
    store.polling = true
    const changePage = vi.spyOn(store, 'changePoiPage').mockResolvedValue()
    vi.spyOn(store, 'prepareCurrentPagePoiExport').mockReturnValue(exportData('current-page'))
    await wrapper.vm.$nextTick()

    wrapper.getComponent(ElPagination).vm.$emit('current-change', 2)
    await button(wrapper, '导出当前页').trigger('click')

    expect(changePage).toHaveBeenCalledWith(2)
    expect(anchorClick).toHaveBeenCalledOnce()
  })

  it('downloads the current page and cleans up browser resources', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    populateResult(store)
    await wrapper.vm.$nextTick()

    await button(wrapper, '导出当前页').trigger('click')

    expect(createObjectURL).toHaveBeenCalledOnce()
    expect(anchorClick).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:poi-csv')
    expect(document.body.querySelector('a[download]')).toBeNull()
    expect(wrapper.text()).toContain('已导出当前页 1 条 POI')
  })

  it('shows fixed-session export progress and labels truncated complex exports', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    populateResult(store)
    store.poiReportedCandidateCount = 99
    store.poiRetrievedUniqueCount = 1
    store.poiRetrievalComplete = false
    store.poiTruncatedReason = 'provider-call-limit'
    let resolveExport: ((value: PoiExportData) => void) | undefined
    vi.spyOn(store, 'collectRetrievablePoiExport').mockImplementation(() => {
      store.poiExportLoading = true
      store.poiExportProgress = { currentPage: 3, plannedPages: 100, totalReported: 6001, retrievableLimit: 5000 }
      return new Promise((resolve) => {
        resolveExport = resolve
      })
    })
    await wrapper.vm.$nextTick()

    const pendingClick = button(wrapper, '导出可获取结果').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('正在获取第 3 / 100 页')
    expect(wrapper.text()).toContain('本次最多尝试获取 5,000 条')
    expect(button(wrapper, '导出当前页').attributes('disabled')).toBeDefined()

    store.poiExportLoading = false
    store.poiExportProgress = null
    resolveExport?.(exportData('retrievable'))
    await pendingClick
    await flushPromises()

    expect(wrapper.text()).toContain('查询已截断；已导出已获取结果 1 条 POI')
  })

  it('does not create an artifact when Store returns no export data', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    populateResult(store)
    vi.spyOn(store, 'prepareCurrentPagePoiExport').mockReturnValue(null)
    await wrapper.vm.$nextTick()

    await button(wrapper, '导出当前页').trigger('click')

    expect(createObjectURL).not.toHaveBeenCalled()
  })

  it.each(['createObjectURL', 'createElement', 'appendChild', 'click'])(
    'cleans up POI CSV resources when %s fails',
    async (failurePoint) => {
      const wrapper = mountPanel()
      const store = useAnalysisStore()
      populateResult(store)
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

      await button(wrapper, '导出当前页').trigger('click')
      createElementSpy?.mockRestore()

      expect(store.poiExportError).toContain('failed')
      expect(document.body.querySelector('a[download]')).toBeNull()
      expect(revokeObjectURL).toHaveBeenCalledTimes(failurePoint === 'createObjectURL' ? 0 : 1)
    },
  )
})
