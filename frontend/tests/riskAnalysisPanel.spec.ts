import ElementPlus, { ElButton, ElInputNumber } from 'element-plus'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import RiskAnalysisPanel from '@/components/workspace/RiskAnalysisPanel.vue'
import type { RiskIndicatorWeightInput } from '@/types/riskAnalysis'

const committedWeights: RiskIndicatorWeightInput[] = [
  { code: 'PM25', weight_percent: 30 },
  { code: 'AQI', weight_percent: 40 },
  { code: 'NDVI', weight_percent: 30 },
]

function mountPanel(overrides: Record<string, unknown> = {}) {
  return mount(RiskAnalysisPanel, {
    props: {
      committedWeights: committedWeights.map((item) => ({ ...item })),
      disabled: false,
      submitting: false,
      polling: false,
      ...overrides,
    },
    global: {
      plugins: [ElementPlus],
      stubs: { ElInputNumber: true },
    },
  })
}

function weightInputs(wrapper: ReturnType<typeof mountPanel>) {
  return wrapper.findAllComponents(ElInputNumber)
}

function submitButton(wrapper: ReturnType<typeof mountPanel>) {
  const button = wrapper.findAllComponents(ElButton).at(-1)
  if (!button) throw new Error('missing risk submit button')
  return button
}

describe('RiskAnalysisPanel', () => {
  it('keeps weight edits local and emits a cloned draft only on submit', async () => {
    const source = committedWeights.map((item) => ({ ...item }))
    const wrapper = mountPanel({ committedWeights: source })

    weightInputs(wrapper)[0]!.vm.$emit('update:modelValue', 35)
    weightInputs(wrapper)[1]!.vm.$emit('update:modelValue', 35)
    await wrapper.vm.$nextTick()

    expect(source).toEqual(committedWeights)
    expect(wrapper.emitted('submit')).toBeUndefined()
    await submitButton(wrapper).trigger('click')
    expect(wrapper.emitted('submit')).toEqual([[
      [
        { code: 'PM25', weight_percent: 35 },
        { code: 'AQI', weight_percent: 35 },
        { code: 'NDVI', weight_percent: 30 },
      ],
    ]])
    expect(wrapper.emitted('submit')![0]![0]).not.toBe(source)
  })

  it.each([
    ['invalid total', [35, 40, 30]],
    ['negative', [-1, 71, 30]],
    ['above range', [101, 0, -1]],
    ['not finite', [Number.NaN, 70, 30]],
    ['no positive weight', [0, 0, 0]],
  ])('rejects %s weights', async (_label, values) => {
    const wrapper = mountPanel()
    values.forEach((value, index) => {
      weightInputs(wrapper)[index]!.vm.$emit('update:modelValue', value)
    })
    await wrapper.vm.$nextTick()

    expect(submitButton(wrapper).attributes('disabled')).toBeDefined()
    submitButton(wrapper).vm.$emit('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('submit')).toBeUndefined()
  })

  it('synchronizes external committed weights over an unsubmitted draft', async () => {
    const wrapper = mountPanel()
    weightInputs(wrapper)[0]!.vm.$emit('update:modelValue', 50)
    await wrapper.vm.$nextTick()

    await wrapper.setProps({
      committedWeights: [
        { code: 'PM25', weight_percent: 20 },
        { code: 'AQI', weight_percent: 50 },
        { code: 'NDVI', weight_percent: 30 },
      ],
    })

    expect(weightInputs(wrapper).map((input) => input.props('modelValue'))).toEqual([20, 50, 30])
  })

  it.each([
    ['locked', { disabled: true }],
    ['submitting', { submitting: true }],
  ])('guards submission while %s', async (_label, overrides) => {
    const wrapper = mountPanel(overrides)

    expect(submitButton(wrapper).attributes('disabled')).toBeDefined()
    submitButton(wrapper).vm.$emit('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('submit')).toBeUndefined()
    if ('disabled' in overrides) {
      expect(weightInputs(wrapper).every((input) => input.props('disabled'))).toBe(true)
    }
  })

  it('keeps the analysis-in-progress label while polling', () => {
    const wrapper = mountPanel({ disabled: true, polling: true })
    expect(submitButton(wrapper).text()).toContain('分析进行中')
  })
})
