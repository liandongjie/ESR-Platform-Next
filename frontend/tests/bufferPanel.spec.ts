import ElementPlus, { ElButton, ElInputNumber } from 'element-plus'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import BufferPanel from '@/components/workspace/BufferPanel.vue'
import type { AnalysisAreaBufferResponse } from '@/types/analysisArea'

const result: AnalysisAreaBufferResponse = {
  source: {
    crs: 'EPSG:4326',
    geometry_type: 'Point',
    bounds: [118.9, 32.1, 118.9, 32.1],
  },
  buffer: {
    crs: 'EPSG:4326',
    distance_m: 3000,
    working_crs: 'EPSG:32650',
    area_m2: 28_228_936.4,
    area_km2: 28.2289364,
    bounds: [118.86, 32.07, 118.94, 32.13],
    geometry: {
      type: 'Polygon',
      coordinates: [[[118.86, 32.1], [118.9, 32.13], [118.94, 32.1], [118.86, 32.1]]],
    },
  },
}

function mountPanel(overrides: Record<string, unknown> = {}) {
  return mount(BufferPanel, {
    props: {
      committedDistance: 3000,
      maxDistance: 10_000,
      disabled: false,
      loading: false,
      error: null,
      result: null,
      ...overrides,
    },
    global: {
      plugins: [ElementPlus],
      stubs: { ElInputNumber: true },
    },
  })
}

function distanceInput(wrapper: ReturnType<typeof mountPanel>) {
  return wrapper.getComponent(ElInputNumber)
}

function generateButton(wrapper: ReturnType<typeof mountPanel>) {
  const button = wrapper
    .findAllComponents(ElButton)
    .find((item) => item.text().includes('生成缓冲区'))
  if (!button) throw new Error('missing generate buffer button')
  return button
}

describe('BufferPanel', () => {
  it('keeps draft edits local while preserving an existing result summary', async () => {
    const wrapper = mountPanel({ result })

    distanceInput(wrapper).vm.$emit('update:modelValue', 5000)
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('generate')).toBeUndefined()
    expect(distanceInput(wrapper).props('modelValue')).toBe(5000)
    expect(wrapper.text()).toContain('重新生成缓冲区')
    expect(wrapper.text()).toContain('28.229 km²')
    expect(wrapper.text()).toContain('3,000 m')
    expect(wrapper.text()).toContain('EPSG:32650')
  })

  it('emits the valid draft only when generate is clicked', async () => {
    const wrapper = mountPanel()

    distanceInput(wrapper).vm.$emit('update:modelValue', 4500)
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('generate')).toBeUndefined()

    await generateButton(wrapper).trigger('click')
    expect(wrapper.emitted('generate')).toEqual([[4500]])
  })

  it.each([
    ['empty', undefined],
    ['not finite', Number.NaN],
    ['zero', 0],
    ['negative', -1],
    ['above max', 10_001],
  ])('rejects an invalid %s draft', async (_label, value) => {
    const wrapper = mountPanel({ committedDistance: value })

    expect(generateButton(wrapper).attributes('disabled')).toBeDefined()
    generateButton(wrapper).vm.$emit('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('generate')).toBeUndefined()
  })

  it('accepts the max boundary and validates positive values before max loads', async () => {
    const wrapper = mountPanel()
    distanceInput(wrapper).vm.$emit('update:modelValue', 10_000)
    await wrapper.vm.$nextTick()
    await generateButton(wrapper).trigger('click')
    expect(wrapper.emitted('generate')).toEqual([[10_000]])

    const withoutMax = mountPanel({ maxDistance: undefined })
    distanceInput(withoutMax).vm.$emit('update:modelValue', 20_000)
    await withoutMax.vm.$nextTick()
    await generateButton(withoutMax).trigger('click')
    expect(withoutMax.emitted('generate')).toEqual([[20_000]])
  })

  it('synchronizes external committed distance changes over an unsubmitted draft', async () => {
    const wrapper = mountPanel()
    distanceInput(wrapper).vm.$emit('update:modelValue', 5000)
    await wrapper.vm.$nextTick()

    await wrapper.setProps({ committedDistance: 4000 })

    expect(distanceInput(wrapper).props('modelValue')).toBe(4000)
    expect(wrapper.emitted('generate')).toBeUndefined()
  })

  it.each([
    ['locked', { disabled: true }],
    ['loading', { loading: true }],
  ])('guards generation while %s', async (_label, overrides) => {
    const wrapper = mountPanel(overrides)

    expect(generateButton(wrapper).attributes('disabled')).toBeDefined()
    generateButton(wrapper).vm.$emit('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('generate')).toBeUndefined()
    if ('disabled' in overrides && overrides.disabled) {
      expect(distanceInput(wrapper).props('disabled')).toBe(true)
    }
  })

  it('renders the current limit and error', () => {
    const wrapper = mountPanel({ error: '生成缓冲区失败' })

    expect(wrapper.text()).toContain('服务端当前上限 10,000 米')
    expect(wrapper.get('[role="alert"]').text()).toContain('生成缓冲区失败')
  })
})
