import ElementPlus, { ElButton } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAnalysisStore } from '@/stores/analysis'
import type { StudyPointCandidate } from '@/types/poi'
import WorkspaceView from '@/views/WorkspaceView.vue'

const mocks = vi.hoisted(() => ({
  searchAmapStudyPoints: vi.fn(),
}))

vi.mock('@/map/amapStudyPoint', () => ({
  searchAmapStudyPoints: mocks.searchAmapStudyPoints,
}))

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

function studyPointSearchButton(wrapper: ReturnType<typeof mountWorkspace>['wrapper']) {
  const button = wrapper.findAllComponents(ElButton).find((item) => item.text().trim() === '搜索')
  if (!button) throw new Error('missing study point search button')
  return button
}

function candidate(
  id: string,
  name: string,
  locationWgs84: [number, number],
): StudyPointCandidate {
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

describe('WorkspaceView address or POI study point search', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    mocks.searchAmapStudyPoints.mockReset()
  })

  it('searches only on button or Enter and renders candidates', async () => {
    mocks.searchAmapStudyPoints.mockResolvedValue([
      candidate('poi-1', '南京大学', [118.772, 32.061]),
    ])
    const { wrapper } = mountWorkspace()
    const input = wrapper.get('input[aria-label="地址或 POI 关键词"]')

    await input.setValue(' 南京大学 ')
    expect(mocks.searchAmapStudyPoints).not.toHaveBeenCalled()

    await studyPointSearchButton(wrapper).trigger('click')
    await flushPromises()
    expect(mocks.searchAmapStudyPoints).toHaveBeenLastCalledWith('南京大学')
    expect(wrapper.get('.study-point-result').text()).toContain('南京大学')
    expect(wrapper.get('.study-point-result').text()).toContain('江苏省南京市鼓楼区汉口路22号')

    await input.setValue('中关村')
    await input.trigger('keyup.enter')
    await flushPromises()
    expect(mocks.searchAmapStudyPoints).toHaveBeenLastCalledWith('中关村')
  })

  it('selects a WGS84 candidate through the existing store action', async () => {
    const selected = candidate('poi-1', '南京大学', [118.772, 32.061])
    mocks.searchAmapStudyPoints.mockResolvedValue([selected])
    const { wrapper, store } = mountWorkspace()
    const setSourcePoint = vi.spyOn(store, 'setSourcePoint')

    await wrapper.get('input[aria-label="地址或 POI 关键词"]').setValue('南京大学')
    await studyPointSearchButton(wrapper).trigger('click')
    await flushPromises()
    await wrapper.get('.study-point-result').trigger('click')

    expect(setSourcePoint).toHaveBeenCalledOnce()
    expect(setSourcePoint).toHaveBeenCalledWith(selected.locationWgs84)
    expect(wrapper.get('.study-point-selected').text()).toContain('已选择：南京大学')
  })

  it('shows empty and error states for the submitted keyword', async () => {
    mocks.searchAmapStudyPoints.mockResolvedValueOnce([])
    const { wrapper } = mountWorkspace()
    const input = wrapper.get('input[aria-label="地址或 POI 关键词"]')

    await input.setValue('不存在的地点')
    await studyPointSearchButton(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.get('.study-point-search-empty').text()).toContain('未找到')

    mocks.searchAmapStudyPoints.mockRejectedValueOnce(new Error('高德地点搜索失败'))
    await input.setValue('失败地点')
    await studyPointSearchButton(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.get('.study-point-search-error').text()).toContain('高德地点搜索失败')
  })

  it('rejects an empty keyword without calling the provider', async () => {
    const { wrapper } = mountWorkspace()

    await studyPointSearchButton(wrapper).trigger('click')

    expect(mocks.searchAmapStudyPoints).not.toHaveBeenCalled()
    expect(wrapper.get('.study-point-search-error').text()).toContain('请输入地址或 POI 关键词')
  })

  it('clears candidates but preserves the selected name when the keyword draft changes', async () => {
    mocks.searchAmapStudyPoints.mockResolvedValue([
      candidate('poi-1', '南京大学', [118.772, 32.061]),
    ])
    const { wrapper } = mountWorkspace()
    const input = wrapper.get('input[aria-label="地址或 POI 关键词"]')

    await input.setValue('南京大学')
    await studyPointSearchButton(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.find('.study-point-result').exists()).toBe(true)
    await wrapper.get('.study-point-result').trigger('click')
    expect(wrapper.get('.study-point-selected').text()).toContain('已选择：南京大学')

    await input.setValue('南京大学仙林校区')
    expect(wrapper.find('.study-point-result').exists()).toBe(false)
    expect(wrapper.get('.study-point-selected').text()).toContain('已选择：南京大学')

    await studyPointSearchButton(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.get('.study-point-selected').text()).toContain('已选择：南京大学')
  })

  it('clears the selected search name when coordinate input changes the study point', async () => {
    mocks.searchAmapStudyPoints.mockResolvedValue([
      candidate('poi-1', '南京大学', [118.772, 32.061]),
    ])
    const { wrapper, store } = mountWorkspace()

    await wrapper.get('input[aria-label="地址或 POI 关键词"]').setValue('南京大学')
    await studyPointSearchButton(wrapper).trigger('click')
    await flushPromises()
    await wrapper.get('.study-point-result').trigger('click')
    expect(wrapper.get('.study-point-selected').text()).toContain('已选择：南京大学')

    const inputs = coordinateInputs(wrapper)
    await inputs.longitude.setValue('118.9')
    await inputs.latitude.setValue('32.1')
    await applyButton(wrapper).trigger('click')

    expect(store.sourceGeometryWgs84?.coordinates).toEqual([118.9, 32.1])
    expect(wrapper.find('.study-point-selected').exists()).toBe(false)
  })

  it('ignores stale success, error, and empty responses after the keyword changes', async () => {
    const staleOutcomes = [
      { kind: 'success', value: [candidate('old', '旧地点', [118.7, 32])] },
      { kind: 'error', value: new Error('旧请求失败') },
      { kind: 'empty', value: [] },
    ] as const

    for (const outcome of staleOutcomes) {
      const request = deferred<StudyPointCandidate[]>()
      mocks.searchAmapStudyPoints.mockReturnValueOnce(request.promise)
      const { wrapper } = mountWorkspace()
      const input = wrapper.get('input[aria-label="地址或 POI 关键词"]')

      await input.setValue('旧关键词')
      await studyPointSearchButton(wrapper).trigger('click')
      await input.setValue('新关键词')

      if (outcome.kind === 'error') request.reject(outcome.value)
      else request.resolve([...outcome.value])
      await flushPromises()

      expect(wrapper.find('.study-point-result').exists()).toBe(false)
      expect(wrapper.find('.study-point-search-error').exists()).toBe(false)
      expect(wrapper.find('.study-point-search-empty').exists()).toBe(false)
      wrapper.unmount()
    }
  })

  it('does not let an earlier request overwrite a newer result', async () => {
    const oldRequest = deferred<StudyPointCandidate[]>()
    const newRequest = deferred<StudyPointCandidate[]>()
    mocks.searchAmapStudyPoints
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise)
    const { wrapper } = mountWorkspace()
    const input = wrapper.get('input[aria-label="地址或 POI 关键词"]')

    await input.setValue('旧关键词')
    await studyPointSearchButton(wrapper).trigger('click')
    await input.setValue('新关键词')
    await studyPointSearchButton(wrapper).trigger('click')

    newRequest.resolve([candidate('new', '新地点', [118.8, 32.1])])
    await flushPromises()
    oldRequest.resolve([candidate('old', '旧地点', [118.7, 32])])
    await flushPromises()

    expect(wrapper.findAll('.study-point-result')).toHaveLength(1)
    expect(wrapper.get('.study-point-result').text()).toContain('新地点')
    expect(wrapper.get('.study-point-result').text()).not.toContain('旧地点')
  })

  it('disables searching and candidate selection while analysis is locked', async () => {
    mocks.searchAmapStudyPoints.mockResolvedValue([
      candidate('poi-1', '南京大学', [118.772, 32.061]),
    ])
    const { wrapper, store } = mountWorkspace()
    const input = wrapper.get('input[aria-label="地址或 POI 关键词"]')
    await input.setValue('南京大学')
    await studyPointSearchButton(wrapper).trigger('click')
    await flushPromises()
    const setSourcePoint = vi.spyOn(store, 'setSourcePoint')

    store.polling = true
    await wrapper.vm.$nextTick()

    expect(input.attributes('disabled')).toBeDefined()
    expect(studyPointSearchButton(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.get('.study-point-result').attributes('disabled')).toBeDefined()
    await wrapper.get('.study-point-result').trigger('click')
    expect(setSourcePoint).not.toHaveBeenCalled()
  })
})
