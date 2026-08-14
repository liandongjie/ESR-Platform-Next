import ElementPlus, { ElInputNumber } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import PoiSearchPanel from '@/components/poi/PoiSearchPanel.vue'
import AnalysisPanel from '@/components/workspace/AnalysisPanel.vue'
import RiskAnalysisPanel from '@/components/workspace/RiskAnalysisPanel.vue'
import { useAnalysisStore } from '@/stores/analysis'
import { makeRiskIndicatorCatalog } from './fixtures/riskIndicatorCatalog'

function mountPanel(activeTab: 'poi' | 'risk' = 'poi', disabled = false) {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(AnalysisPanel, {
    props: {
      activeTab,
      disabled,
      committedWeights: [
        { code: 'PM25', weight_percent: 30 },
        { code: 'AQI', weight_percent: 40 },
        { code: 'NDVI', weight_percent: 30 },
      ],
      riskSubmitting: false,
      riskPolling: false,
      riskHasTaskOrResult: false,
      riskIndicatorCatalog: makeRiskIndicatorCatalog(),
      riskIndicatorCatalogLoading: false,
      riskIndicatorCatalogError: null,
    },
    global: { plugins: [pinia, ElementPlus] },
  })
}

function tab(wrapper: ReturnType<typeof mountPanel>, label: string) {
  const button = wrapper.findAll('button.analysis-tab').find((item) => item.text() === label)
  if (!button) throw new Error(`missing ${label} tab`)
  return button
}

describe('AnalysisPanel', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('keeps both inputs mounted and controls tab changes through emit even while locked', async () => {
    const wrapper = mountPanel('poi', true)

    expect(wrapper.findComponent(PoiSearchPanel).exists()).toBe(true)
    expect(wrapper.findComponent(RiskAnalysisPanel).exists()).toBe(true)
    await tab(wrapper, '风险').trigger('click')
    expect(wrapper.emitted('update:activeTab')).toEqual([['risk']])
  })

  it('preserves POI and Risk drafts across controlled tab switches without mutations', async () => {
    const wrapper = mountPanel()
    const store = useAnalysisStore()
    const setKeyword = vi.spyOn(store, 'setPoiKeyword')
    const search = vi.spyOn(store, 'searchPois').mockResolvedValue()
    const poiInput = wrapper.get('input[aria-label="POI 关键词"]')

    await poiInput.setValue('学校')
    await wrapper.setProps({ activeTab: 'risk' })
    wrapper.findComponent(RiskAnalysisPanel).findAllComponents(ElInputNumber)[0]!.vm.$emit(
      'update:modelValue',
      35,
    )
    await wrapper.vm.$nextTick()
    await wrapper.setProps({ activeTab: 'poi' })

    expect(wrapper.get('input[aria-label="POI 关键词"]').element).toHaveProperty('value', '学校')
    expect(
      wrapper.findComponent(RiskAnalysisPanel).findAllComponents(ElInputNumber)[0]!.props(
        'modelValue',
      ),
    ).toBe(35)
    expect(setKeyword).not.toHaveBeenCalled()
    expect(search).not.toHaveBeenCalled()
    expect(wrapper.emitted('submit-risk')).toBeUndefined()
  })

  it('forwards Risk submission without changing the active tab', async () => {
    const wrapper = mountPanel('risk')
    const weights = [
      { code: 'PM25', weight_percent: 30 },
      { code: 'AQI', weight_percent: 40 },
      { code: 'NDVI', weight_percent: 30 },
    ]

    wrapper.findComponent(RiskAnalysisPanel).vm.$emit('submit', weights)
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('submit-risk')).toEqual([[weights]])
    expect(wrapper.emitted('update:activeTab')).toBeUndefined()
  })

  it('forwards POI query success without changing the active tab', async () => {
    const wrapper = mountPanel()

    wrapper.findComponent(PoiSearchPanel).vm.$emit('query-success')
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('poi-query-success')).toHaveLength(1)
    expect(wrapper.emitted('update:activeTab')).toBeUndefined()
  })

  it('forwards the committed POI result open request', async () => {
    const wrapper = mountPanel()

    wrapper.findComponent(PoiSearchPanel).vm.$emit('open-result')
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('poi-open-result')).toHaveLength(1)
  })

  it('forwards the committed Risk task or result open request', async () => {
    const wrapper = mountPanel('risk')

    wrapper.findComponent(RiskAnalysisPanel).vm.$emit('open-result')
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('risk-open-result')).toHaveLength(1)
    expect(wrapper.emitted('submit-risk')).toBeUndefined()
  })
})
