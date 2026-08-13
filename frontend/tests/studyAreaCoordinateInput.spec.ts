import ElementPlus, { ElButton } from 'element-plus'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import StudyAreaCoordinateInput from '@/components/workspace/StudyAreaCoordinateInput.vue'

function mountInput(disabled = false) {
  return mount(StudyAreaCoordinateInput, {
    props: { disabled },
    global: { plugins: [ElementPlus] },
  })
}

function applyButton(wrapper: ReturnType<typeof mountInput>) {
  const button = wrapper.findAllComponents(ElButton).find((item) => item.text().includes('使用该坐标'))
  if (!button) throw new Error('missing coordinate apply button')
  return button
}

describe('StudyAreaCoordinateInput', () => {
  it.each([
    [' 118.9 ', '32.1', [118.9, 32.1]],
    ['-180', '90', [-180, 90]],
    ['+180.', '-.5', [180, -0.5]],
  ])('emits a WGS84 point from ordinary decimal text', async (longitude, latitude, expected) => {
    const wrapper = mountInput()

    await wrapper.get('input[aria-label="研究点经度"]').setValue(longitude)
    await wrapper.get('input[aria-label="研究点纬度"]').setValue(latitude)
    await applyButton(wrapper).trigger('click')

    expect(wrapper.emitted('confirm')).toEqual([[{ type: 'Point', coordinates: expected }]])
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it.each([
    ['', '32.1'],
    ['text', '32.1'],
    ['NaN', '32.1'],
    ['Infinity', '32.1'],
    ['0x76', '32.1'],
    ['1e2', '32.1'],
    ['180.0001', '32.1'],
    ['118.9', '-90.0001'],
  ])('rejects invalid coordinate text', async (longitude, latitude) => {
    const wrapper = mountInput()

    await wrapper.get('input[aria-label="研究点经度"]').setValue(longitude)
    await wrapper.get('input[aria-label="研究点纬度"]').setValue(latitude)
    await applyButton(wrapper).trigger('click')

    expect(wrapper.emitted('confirm')).toBeUndefined()
    expect(wrapper.get('[role="alert"]').text()).not.toBe('')
  })

  it('clears the validation error after a valid retry', async () => {
    const wrapper = mountInput()
    const longitude = wrapper.get('input[aria-label="研究点经度"]')
    const latitude = wrapper.get('input[aria-label="研究点纬度"]')

    await longitude.setValue('0x76')
    await latitude.setValue('32.1')
    await applyButton(wrapper).trigger('click')
    expect(wrapper.get('[role="alert"]').text()).toContain('普通十进制')

    await longitude.setValue('118.9')
    await applyButton(wrapper).trigger('click')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('disables controls and guards confirmation while locked', async () => {
    const wrapper = mountInput(true)

    expect(wrapper.get('input[aria-label="研究点经度"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('input[aria-label="研究点纬度"]').attributes('disabled')).toBeDefined()
    expect(applyButton(wrapper).attributes('disabled')).toBeDefined()
    applyButton(wrapper).vm.$emit('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('confirm')).toBeUndefined()
  })
})
