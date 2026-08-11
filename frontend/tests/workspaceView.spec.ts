import ElementPlus, { ElButton } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAnalysisStore } from '@/stores/analysis'
import WorkspaceView from '@/views/WorkspaceView.vue'

vi.mock('@/api/system', () => ({
  getLiveHealth: vi.fn().mockResolvedValue({ status: 'ok' }),
  getCapabilities: vi.fn().mockResolvedValue({
    result_ttl_hours: 24,
    limits: { max_buffer_meters: 10_000 },
  }),
}))

function mountWorkspace() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(WorkspaceView, {
    global: {
      plugins: [pinia, ElementPlus],
      stubs: {
        MapCanvas: true,
        PoiSearchPanel: true,
        RiskAnalysisResultDownloads: true,
        StatusCard: true,
      },
    },
  })
  return { wrapper, store: useAnalysisStore() }
}

function coordinateInputs(wrapper: ReturnType<typeof mountWorkspace>['wrapper']) {
  return {
    longitude: wrapper.get('input[aria-label="研究点经度"]'),
    latitude: wrapper.get('input[aria-label="研究点纬度"]'),
  }
}

function applyButton(wrapper: ReturnType<typeof mountWorkspace>['wrapper']) {
  const button = wrapper
    .findAllComponents(ElButton)
    .find((item) => item.text().includes('使用该坐标'))
  if (!button) throw new Error('missing coordinate apply button')
  return button
}

describe('WorkspaceView coordinate input', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
  })

  it.each([
    [' 118.9 ', '32.1', [118.9, 32.1]],
    ['-180', '90', [-180, 90]],
    ['+180.', '-.5', [180, -0.5]],
  ])('sets a WGS84 point from ordinary decimal text', async (longitude, latitude, expected) => {
    const { wrapper, store } = mountWorkspace()
    const inputs = coordinateInputs(wrapper)

    await inputs.longitude.setValue(longitude)
    await inputs.latitude.setValue(latitude)
    await applyButton(wrapper).trigger('click')

    expect(store.sourceGeometryWgs84?.coordinates).toEqual(expected)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it.each([
    ['', '32.1'],
    ['   ', '32.1'],
    ['text', '32.1'],
    ['NaN', '32.1'],
    ['Infinity', '32.1'],
    ['-Infinity', '32.1'],
    ['0x76', '32.1'],
    ['0b10', '32.1'],
    ['0o10', '32.1'],
    ['1e2', '32.1'],
    ['1,2', '32.1'],
    ['180.0001', '32.1'],
    ['118.9', '-90.0001'],
  ])(
    'rejects invalid coordinate text without changing the current point',
    async (longitude, latitude) => {
      const { wrapper, store } = mountWorkspace()
      store.setSourcePoint([118.8, 32])
      const setSourcePoint = vi.spyOn(store, 'setSourcePoint')
      const inputs = coordinateInputs(wrapper)

      await inputs.longitude.setValue(longitude)
      await inputs.latitude.setValue(latitude)
      await applyButton(wrapper).trigger('click')

      expect(setSourcePoint).not.toHaveBeenCalled()
      expect(store.sourceGeometryWgs84?.coordinates).toEqual([118.8, 32])
      expect(wrapper.get('[role="alert"]').text()).not.toBe('')
    },
  )

  it('clears the input error after a valid retry', async () => {
    const { wrapper, store } = mountWorkspace()
    const inputs = coordinateInputs(wrapper)

    await inputs.longitude.setValue('0x76')
    await inputs.latitude.setValue('32.1')
    await applyButton(wrapper).trigger('click')
    expect(wrapper.get('[role="alert"]').text()).toContain('普通十进制')

    await inputs.longitude.setValue('118.9')
    await applyButton(wrapper).trigger('click')

    expect(store.sourceGeometryWgs84?.coordinates).toEqual([118.9, 32.1])
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('disables coordinate changes and guards the handler while analysis is locked', async () => {
    const { wrapper, store } = mountWorkspace()
    const inputs = coordinateInputs(wrapper)
    await inputs.longitude.setValue('118.9')
    await inputs.latitude.setValue('32.1')
    const setSourcePoint = vi.spyOn(store, 'setSourcePoint')

    store.polling = true
    await wrapper.vm.$nextTick()

    expect(inputs.longitude.attributes('disabled')).toBeDefined()
    expect(inputs.latitude.attributes('disabled')).toBeDefined()
    expect(applyButton(wrapper).attributes('disabled')).toBeDefined()

    applyButton(wrapper).vm.$emit('click')
    await wrapper.vm.$nextTick()
    expect(setSourcePoint).not.toHaveBeenCalled()
  })
})
