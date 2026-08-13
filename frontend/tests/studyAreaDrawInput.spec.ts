import ElementPlus, { ElButton } from 'element-plus'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import StudyAreaDrawInput from '@/components/workspace/StudyAreaDrawInput.vue'

function mountInput(overrides: Record<string, unknown> = {}) {
  return mount(StudyAreaDrawInput, {
    props: {
      disabled: false,
      activeDrawingMode: null,
      drawingError: null,
      ...overrides,
    },
    global: { plugins: [ElementPlus] },
  })
}

describe('StudyAreaDrawInput', () => {
  it.each([
    ['点', 'point'],
    ['线', 'polyline'],
    ['矩形', 'rectangle'],
    ['多边形', 'polygon'],
  ] as const)('requests %s drawing without touching a map instance', async (label, mode) => {
    const wrapper = mountInput()

    await wrapper.get(`button[aria-label="绘制${label}"]`).trigger('click')

    expect(wrapper.emitted('start-drawing')).toEqual([[mode]])
  })

  it('shows active drawing state, cancellation, and drawing errors', async () => {
    const wrapper = mountInput({
      activeDrawingMode: 'polygon',
      drawingError: 'MouseTool 加载失败',
    })
    const cancel = wrapper.findAllComponents(ElButton).find((item) => item.text() === '取消绘制')
    if (!cancel) throw new Error('missing cancel drawing button')

    expect(wrapper.text()).toContain('多边形绘制中')
    expect(wrapper.get('[role="alert"]').text()).toContain('MouseTool 加载失败')
    await cancel.trigger('click')
    expect(wrapper.emitted('cancel-drawing')).toHaveLength(1)
    expect(wrapper.text()).not.toContain('清除研究区')
  })

  it('disables every drawing action while locked', async () => {
    const wrapper = mountInput({ disabled: true, activeDrawingMode: 'point' })

    for (const label of ['点', '线', '矩形', '多边形']) {
      expect(wrapper.get(`button[aria-label="绘制${label}"]`).attributes('disabled')).toBeDefined()
    }
    const cancel = wrapper.findAllComponents(ElButton).find((item) => item.text() === '取消绘制')
    expect(cancel?.attributes('disabled')).toBeDefined()
  })
})
