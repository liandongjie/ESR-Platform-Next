import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import WorkspaceResultDrawer from '@/components/workspace/WorkspaceResultDrawer.vue'

describe('WorkspaceResultDrawer', () => {
  it('is controlled, emits close, and keeps slot content mounted while hidden', async () => {
    const wrapper = mount(WorkspaceResultDrawer, {
      props: { open: true, title: 'POI 结果' },
      slots: { default: '<div class="drawer-result">result</div>' },
    })

    expect(wrapper.text()).toContain('POI 结果')
    await wrapper.get('button[aria-label="关闭结果抽屉"]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
    await wrapper.setProps({ open: false })
    expect(wrapper.attributes('style')).toContain('display: none')
    expect(wrapper.find('.drawer-result').exists()).toBe(true)
  })

  it('provides an independent scroll body without bubbling interaction to a sibling map', async () => {
    const mapClick = vi.fn()
    const mapWheel = vi.fn()
    const mapPointer = vi.fn()
    const wrapper = mount({
      components: { WorkspaceResultDrawer },
      template: `
        <div>
          <div class="map" @click="mapClick" @wheel="mapWheel" @pointerdown="mapPointer" />
          <WorkspaceResultDrawer :open="true" title="POI 结果"><button class="inside">内容</button></WorkspaceResultDrawer>
        </div>
      `,
      setup: () => ({ mapClick, mapWheel, mapPointer }),
    })

    const body = wrapper.get('.workspace-result-drawer-body')
    await wrapper.get('.inside').trigger('click')
    await body.trigger('wheel')
    await body.trigger('pointerdown')

    expect(mapClick).not.toHaveBeenCalled()
    expect(mapWheel).not.toHaveBeenCalled()
    expect(mapPointer).not.toHaveBeenCalled()
  })
})
