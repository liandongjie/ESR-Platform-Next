import { createPinia, setActivePinia } from 'pinia'
import {
  ElAlert,
  ElButton,
  ElEmpty,
  ElInput,
  ElPagination,
  ElTag,
} from 'element-plus'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import PoiSearchPanel from '@/components/poi/PoiSearchPanel.vue'
import { useAnalysisStore } from '@/stores/analysis'

function mountPanel() {
  return mount(PoiSearchPanel, {
    global: {
      plugins: [createPinia()],
      components: { ElAlert, ElButton, ElEmpty, ElInput, ElPagination, ElTag },
    },
  })
}

describe('PoiSearchPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
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

    expect(wrapper.text()).toContain('共 2,000 条')
    expect(wrapper.text()).toContain('学校')
    expect(wrapper.getComponent(ElPagination).props('pageCount')).toBe(100)
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
})
