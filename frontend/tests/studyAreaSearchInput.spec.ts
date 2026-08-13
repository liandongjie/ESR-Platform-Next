import ElementPlus, { ElButton } from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import StudyAreaSearchInput from '@/components/workspace/StudyAreaSearchInput.vue'
import type { StudyPointCandidate } from '@/types/poi'

const mocks = vi.hoisted(() => ({ searchAmapStudyPoints: vi.fn() }))

vi.mock('@/map/amapStudyPoint', () => ({
  searchAmapStudyPoints: mocks.searchAmapStudyPoints,
}))

function mountInput(disabled = false) {
  return mount(StudyAreaSearchInput, {
    props: { disabled, sourceGeometry: null },
    global: { plugins: [ElementPlus] },
  })
}

function searchButton(wrapper: ReturnType<typeof mountInput>) {
  const button = wrapper.findAllComponents(ElButton).find((item) => item.text().trim() === '搜索')
  if (!button) throw new Error('missing search button')
  return button
}

function candidate(id: string, name: string, locationWgs84: [number, number]): StudyPointCandidate {
  return {
    id,
    name,
    address: '汉口路22号',
    district: '江苏省南京市鼓楼区',
    locationWgs84,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

describe('StudyAreaSearchInput', () => {
  beforeEach(() => mocks.searchAmapStudyPoints.mockReset())

  it('searches only on button or Enter, renders candidates, and emits WGS84 geometry', async () => {
    const selected = candidate('poi-1', '南京大学', [118.772, 32.061])
    mocks.searchAmapStudyPoints.mockResolvedValue([selected])
    const wrapper = mountInput()
    const input = wrapper.get('input[aria-label="地址或 POI 关键词"]')

    await input.setValue(' 南京大学 ')
    expect(mocks.searchAmapStudyPoints).not.toHaveBeenCalled()
    await searchButton(wrapper).trigger('click')
    await flushPromises()
    expect(mocks.searchAmapStudyPoints).toHaveBeenCalledWith('南京大学')
    await wrapper.get('.study-point-result').trigger('click')
    expect(wrapper.emitted('confirm')).toEqual([[
      { type: 'Point', coordinates: selected.locationWgs84 },
    ]])
    await wrapper.setProps({
      sourceGeometry: { type: 'Point', coordinates: selected.locationWgs84 },
    })
    expect(wrapper.get('.study-point-selected').text()).toContain('已选择：南京大学')

    await input.setValue('中关村')
    await input.trigger('keyup.enter')
    await flushPromises()
    expect(mocks.searchAmapStudyPoints).toHaveBeenLastCalledWith('中关村')
  })

  it('shows a selected name only while committed geometry matches the candidate point', async () => {
    const selected = candidate('poi-1', '南京大学', [118.772, 32.061])
    mocks.searchAmapStudyPoints.mockResolvedValue([selected])
    const wrapper = mountInput()

    await wrapper.get('input[aria-label="地址或 POI 关键词"]').setValue('南京大学')
    await searchButton(wrapper).trigger('click')
    await flushPromises()
    await wrapper.get('.study-point-result').trigger('click')

    expect(wrapper.find('.study-point-selected').exists()).toBe(false)
    await wrapper.setProps({
      sourceGeometry: { type: 'Point', coordinates: selected.locationWgs84 },
    })
    expect(wrapper.get('.study-point-selected').text()).toContain('已选择：南京大学')

    await wrapper.setProps({ sourceGeometry: null })
    expect(wrapper.find('.study-point-selected').exists()).toBe(false)

    await wrapper.setProps({
      sourceGeometry: { type: 'Point', coordinates: [118.8, 32.1] },
    })
    expect(wrapper.find('.study-point-selected').exists()).toBe(false)
  })

  it('shows validation, empty, and provider error states', async () => {
    const wrapper = mountInput()
    const input = wrapper.get('input[aria-label="地址或 POI 关键词"]')

    await searchButton(wrapper).trigger('click')
    expect(mocks.searchAmapStudyPoints).not.toHaveBeenCalled()
    expect(wrapper.get('.study-point-search-error').text()).toContain('请输入')

    mocks.searchAmapStudyPoints.mockResolvedValueOnce([])
    await input.setValue('不存在的地点')
    await searchButton(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.get('.study-point-search-empty').text()).toContain('未找到')

    mocks.searchAmapStudyPoints.mockRejectedValueOnce(new Error('高德地点搜索失败'))
    await input.setValue('失败地点')
    await searchButton(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.get('.study-point-search-error').text()).toContain('高德地点搜索失败')
  })

  it('invalidates stale keyword results and prevents an older request overwriting a newer one', async () => {
    const oldRequest = deferred<StudyPointCandidate[]>()
    const newRequest = deferred<StudyPointCandidate[]>()
    mocks.searchAmapStudyPoints
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise)
    const wrapper = mountInput()
    const input = wrapper.get('input[aria-label="地址或 POI 关键词"]')

    await input.setValue('旧关键词')
    await searchButton(wrapper).trigger('click')
    await input.setValue('新关键词')
    await searchButton(wrapper).trigger('click')
    newRequest.resolve([candidate('new', '新地点', [118.8, 32.1])])
    await flushPromises()
    oldRequest.resolve([candidate('old', '旧地点', [118.7, 32])])
    await flushPromises()

    expect(wrapper.findAll('.study-point-result')).toHaveLength(1)
    expect(wrapper.get('.study-point-result').text()).toContain('新地点')
  })

  it('invalidates success and error responses after unmount', async () => {
    for (const outcome of ['success', 'error'] as const) {
      const request = deferred<StudyPointCandidate[]>()
      mocks.searchAmapStudyPoints.mockReturnValueOnce(request.promise)
      const wrapper = mountInput()
      await wrapper.get('input[aria-label="地址或 POI 关键词"]').setValue('旧关键词')
      await searchButton(wrapper).trigger('click')
      wrapper.unmount()

      if (outcome === 'success') request.resolve([candidate('old', '旧地点', [118.7, 32])])
      else request.reject(new Error('旧请求失败'))
      await flushPromises()

      expect(wrapper.emitted('confirm')).toBeUndefined()
    }
  })

  it('invalidates an in-flight request and guards selection while locked', async () => {
    const request = deferred<StudyPointCandidate[]>()
    mocks.searchAmapStudyPoints.mockReturnValueOnce(request.promise)
    const wrapper = mountInput()
    const input = wrapper.get('input[aria-label="地址或 POI 关键词"]')
    await input.setValue('南京大学')
    await searchButton(wrapper).trigger('click')
    await wrapper.setProps({ disabled: true })
    request.resolve([candidate('poi-1', '南京大学', [118.772, 32.061])])
    await flushPromises()

    expect(input.attributes('disabled')).toBeDefined()
    expect(searchButton(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.find('.study-point-result').exists()).toBe(false)
    expect(wrapper.emitted('confirm')).toBeUndefined()
  })
})
