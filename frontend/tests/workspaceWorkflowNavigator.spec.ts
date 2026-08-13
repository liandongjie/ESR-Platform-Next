import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import WorkspaceWorkflowNavigator from '@/components/workspace/WorkspaceWorkflowNavigator.vue'

describe('WorkspaceWorkflowNavigator', () => {
  it('renders the four Workspace V2 stages', () => {
    const wrapper = mount(WorkspaceWorkflowNavigator, { props: { activeStep: 1 } })

    expect(wrapper.text()).toContain('研究区')
    expect(wrapper.text()).toContain('缓冲区')
    expect(wrapper.text()).toContain('分析')
    expect(wrapper.text()).toContain('结果')
    expect(wrapper.findAll('li')).toHaveLength(4)
  })

  it('marks the current stage without introducing click behavior', () => {
    const wrapper = mount(WorkspaceWorkflowNavigator, { props: { activeStep: 3 } })
    const steps = wrapper.findAll('li')

    expect(steps[0]?.attributes('data-state')).toBe('complete')
    expect(steps[1]?.attributes('data-state')).toBe('complete')
    expect(steps[2]?.attributes('data-state')).toBe('active')
    expect(steps[2]?.attributes('aria-current')).toBe('step')
    expect(steps[3]?.attributes('data-state')).toBe('pending')
    expect(wrapper.findAll('button')).toHaveLength(0)
  })

  it('updates the visual state when the active step changes', async () => {
    const wrapper = mount(WorkspaceWorkflowNavigator, { props: { activeStep: 2 } })

    await wrapper.setProps({ activeStep: 4 })

    const steps = wrapper.findAll('li')
    expect(steps[0]?.attributes('data-state')).toBe('complete')
    expect(steps[1]?.attributes('data-state')).toBe('complete')
    expect(steps[2]?.attributes('data-state')).toBe('complete')
    expect(steps[3]?.attributes('data-state')).toBe('active')
  })
})
