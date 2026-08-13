import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import PoiSearchPanel from '@/components/poi/PoiSearchPanel.vue'
import { useAnalysisStore } from '@/stores/analysis'

function mountPanel(disabled = false) {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(PoiSearchPanel, {
    props: { disabled },
    global: { plugins: [pinia, ElementPlus] },
  })
}

describe('PoiSearchPanel', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('submits the first page from Enter in commit then query order', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    const calls: string[] = []
    vi.spyOn(store, 'setPoiKeyword').mockImplementation((keyword) => {
      calls.push(`set:${keyword}`)
      store.poiKeyword = keyword
    })
    vi.spyOn(store, 'searchPois').mockImplementation(async (page) => {
      calls.push(`search:${page}`)
    })

    await wrapper.get('input').setValue('学校')
    await wrapper.get('input').trigger('keyup.enter')

    expect(calls).toEqual(['set:学校', 'search:1'])
  })

  it('synchronizes an external committed keyword into the draft', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()

    store.setPoiKeyword('医院')
    await wrapper.vm.$nextTick()

    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('医院')
  })

  it('keeps keyword edits local without clearing committed results', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    store.poiKeyword = '学校'
    store.poiCommittedKeyword = '学校'
    store.poiHasSearched = true
    store.poiItems = [{
      id: 'poi-1', name: '学校', type: '', typeCode: '', address: '', locationWgs84: [118.81, 32.02],
    }]
    await wrapper.vm.$nextTick()
    const items = store.poiItems
    const setKeyword = vi.spyOn(store, 'setPoiKeyword')
    const search = vi.spyOn(store, 'searchPois').mockResolvedValue()

    await wrapper.get('input').setValue('医院')

    expect(setKeyword).not.toHaveBeenCalled()
    expect(search).not.toHaveBeenCalled()
    expect(store.poiKeyword).toBe('学校')
    expect(store.poiItems).toBe(items)
  })

  it('offers reopening committed results without querying or changing Store state', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    store.poiKeyword = '学校'
    store.poiCommittedKeyword = '学校'
    store.poiHasSearched = true
    store.poiItems = [{
      id: 'poi-1', name: '学校', type: '', typeCode: '', address: '', locationWgs84: [118.81, 32.02],
    }]
    await wrapper.vm.$nextTick()
    const items = store.poiItems
    const setKeyword = vi.spyOn(store, 'setPoiKeyword')
    const search = vi.spyOn(store, 'searchPois').mockResolvedValue()
    const viewResult = wrapper.findAll('button').find((item) => item.text() === '查看结果')
    if (!viewResult) throw new Error('missing view result button')

    await viewResult.trigger('click')

    expect(wrapper.emitted('open-result')).toHaveLength(1)
    expect(setKeyword).not.toHaveBeenCalled()
    expect(search).not.toHaveBeenCalled()
    expect(store.poiCommittedKeyword).toBe('学校')
    expect(store.poiItems).toBe(items)
  })

  it.each([1, 0])('emits query success when a valid response contains %i items', async (count) => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    vi.spyOn(store, 'searchPois').mockImplementation(async () => {
      store.poiCommittedKeyword = '学校'
      store.poiHasSearched = true
      store.poiItems = count
        ? [{ id: 'poi-1', name: '学校', type: '', typeCode: '', address: '', locationWgs84: [118.81, 32.02] }]
        : []
    })

    await wrapper.get('input').setValue('学校')
    await wrapper.get('button').trigger('click')

    expect(wrapper.emitted('query-success')).toHaveLength(1)
  })

  it('does not emit query success after an error or stale completion', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    const search = vi.spyOn(store, 'searchPois')
    search.mockImplementationOnce(async () => {
      store.poiError = '查询失败'
      store.poiHasSearched = false
    })
    await wrapper.get('input').setValue('失败')
    await wrapper.get('button').trigger('click')
    expect(wrapper.text()).toContain('查询失败')

    search.mockImplementationOnce(async () => {
      store.poiCommittedKeyword = '新查询'
      store.poiHasSearched = true
    })
    await wrapper.get('input').setValue('旧查询')
    await wrapper.get('button').trigger('click')

    expect(wrapper.emitted('query-success')).toBeUndefined()
  })

  it('locks new query mutation', async () => {
    const wrapper = mountPanel(true)
    const store = useAnalysisStore()
    const setKeyword = vi.spyOn(store, 'setPoiKeyword')
    const search = vi.spyOn(store, 'searchPois').mockResolvedValue()

    expect(wrapper.get('input').attributes('disabled')).toBeDefined()
    wrapper.getComponent({ name: 'ElButton' }).vm.$emit('click')
    await wrapper.vm.$nextTick()

    expect(setKeyword).not.toHaveBeenCalled()
    expect(search).not.toHaveBeenCalled()
  })
})
