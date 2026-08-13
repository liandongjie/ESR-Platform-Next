import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import WorkspaceWorkflowNavigator from '@/components/workspace/WorkspaceWorkflowNavigator.vue'

describe('WorkspaceWorkflowNavigator', () => {
  it('renders four controlled workflow buttons with independent states', () => {
    const wrapper = mount(WorkspaceWorkflowNavigator, {
      props: {
        activeStep: 2,
        availableSteps: [1, 2, 4],
        completedSteps: [1, 4],
      },
    })
    const steps = wrapper.findAll('li')

    expect(wrapper.findAll('button')).toHaveLength(4)
    expect(wrapper.findAll('.step-label').map((item) => item.text())).toEqual([
      '研究区',
      '缓冲区',
      '分析',
      '结果',
    ])
    expect(steps.map((step) => step.attributes('data-state'))).toEqual([
      'complete',
      'active',
      'unavailable',
      'complete',
    ])
    expect(steps[1]?.attributes('aria-current')).toBe('step')
    expect(steps[2]?.get('button').attributes('disabled')).toBeDefined()
  })

  it('emits only available step clicks', async () => {
    const wrapper = mount(WorkspaceWorkflowNavigator, {
      props: {
        activeStep: 1,
        availableSteps: [1, 2],
        completedSteps: [1],
      },
    })
    const buttons = wrapper.findAll('button')

    await buttons[1]?.trigger('click')
    await buttons[2]?.trigger('click')

    expect(wrapper.emitted('select-step')).toEqual([[2]])
  })

  it('updates visual state only from controlled props', async () => {
    const wrapper = mount(WorkspaceWorkflowNavigator, {
      props: {
        activeStep: 1,
        availableSteps: [1],
        completedSteps: [],
      },
    })

    await wrapper.setProps({
      activeStep: 4,
      availableSteps: [1, 2, 3, 4],
      completedSteps: [1, 2, 3, 4],
    })

    expect(wrapper.findAll('li').map((step) => step.attributes('data-state'))).toEqual([
      'complete',
      'complete',
      'complete',
      'active',
    ])
  })
})
