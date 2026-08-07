import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import StatusCard from '@/components/common/StatusCard.vue'

describe('StatusCard', () => {
  it('renders the supplied baseline status', () => {
    const wrapper = mount(StatusCard, {
      props: {
        label: '后端服务',
        value: '在线',
        hint: 'Flask / API v1',
      },
    })

    expect(wrapper.text()).toContain('后端服务')
    expect(wrapper.text()).toContain('在线')
    expect(wrapper.text()).toContain('Flask / API v1')
  })
})
