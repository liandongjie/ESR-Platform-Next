import ElementPlus, { ElButton } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AdministrativeRegionInput from '@/components/map/AdministrativeRegionInput.vue'
import { useAnalysisStore } from '@/stores/analysis'
import type { StudyPointCandidate } from '@/types/poi'
import WorkspaceView from '@/views/WorkspaceView.vue'

const mocks = vi.hoisted(() => ({
  searchAmapStudyPoints: vi.fn(),
}))
const drawingCanvasMocks = {
  startDrawing: vi.fn(),
  cancelDrawing: vi.fn(),
}

const MapCanvasStub = defineComponent({
  name: 'MapCanvas',
  props: {
    sourceGeometry: { type: Object, default: null },
    selectionDisabled: Boolean,
  },
  emits: ['select-point', 'select-geometry', 'drawing-mode-change', 'drawing-error'],
  setup(_props, { expose }) {
    expose(drawingCanvasMocks)
    return () => h('div', { class: 'map-canvas-stub' })
  },
})

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
        AdministrativeRegionInput: true,
        MapCanvas: MapCanvasStub,
        PoiSearchPanel: true,
        RiskAnalysisResultDownloads: true,
        StatusCard: true,
      },
    },
  })
  return { wrapper, store: useAnalysisStore() }
}

beforeEach(() => {
  drawingCanvasMocks.startDrawing.mockReset()
  drawingCanvasMocks.cancelDrawing.mockReset()
})

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

describe('WorkspaceView online drawing', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
  })

  it.each([
    ['点', 'point'],
    ['线', 'polyline'],
    ['矩形', 'rectangle'],
    ['多边形', 'polygon'],
  ] as const)('starts %s drawing from the Workspace control', async (label, mode) => {
    const { wrapper } = mountWorkspace()

    await wrapper.get(`button[aria-label="绘制${label}"]`).trigger('click')

    expect(drawingCanvasMocks.startDrawing).toHaveBeenCalledWith(mode)
    wrapper.unmount()
  })

  it('commits selected geometry through setSourceGeometry', async () => {
    const { wrapper, store } = mountWorkspace()
    const setSourceGeometry = vi.spyOn(store, 'setSourceGeometry')
    const geometry = {
      type: 'LineString' as const,
      coordinates: [
        [118.8, 32],
        [118.9, 32.1],
      ] as Array<[number, number]>,
    }

    wrapper.findComponent(MapCanvasStub).vm.$emit('select-geometry', geometry)
    await wrapper.vm.$nextTick()

    expect(setSourceGeometry).toHaveBeenCalledWith(geometry)
    expect(store.sourceGeometryWgs84).toEqual(geometry)
    wrapper.unmount()
  })

  it('commits a normalized administrative geometry through the existing store action', async () => {
    const { wrapper, store } = mountWorkspace()
    store.setSourcePoint([118.9, 32.1])
    store.bufferResult = {
      source: { crs: 'EPSG:4326', geometry_type: 'Point', bounds: [118.9, 32.1, 118.9, 32.1] },
      buffer: {
        crs: 'EPSG:4326',
        distance_m: 3000,
        working_crs: 'EPSG:32650',
        area_m2: 1,
        area_km2: 0.000001,
        bounds: [118.8, 32, 119, 32.2],
        geometry: {
          type: 'Polygon',
          coordinates: [[[118.8, 32], [119, 32], [119, 32.2], [118.8, 32]]],
        },
      },
    }
    const setSourceGeometry = vi.spyOn(store, 'setSourceGeometry')
    const normalized = {
      type: 'Polygon' as const,
      coordinates: [[[118.7, 31.9], [119.1, 31.9], [119.1, 32.3], [118.7, 31.9]]],
    }

    wrapper.findComponent(AdministrativeRegionInput).vm.$emit('confirm', normalized)
    await wrapper.vm.$nextTick()

    expect(setSourceGeometry).toHaveBeenCalledWith(normalized)
    expect(store.sourceGeometryWgs84).toEqual(normalized)
    expect(store.bufferResult).toBeNull()
    expect(drawingCanvasMocks.cancelDrawing).toHaveBeenCalledOnce()
  })

  it('guards administrative geometry events while analysis is locked', async () => {
    const { wrapper, store } = mountWorkspace()
    store.setSourcePoint([118.9, 32.1])
    const setSourceGeometry = vi.spyOn(store, 'setSourceGeometry')
    store.polling = true
    await wrapper.vm.$nextTick()

    expect(wrapper.findComponent(AdministrativeRegionInput).props('disabled')).toBe(true)
    wrapper.findComponent(AdministrativeRegionInput).vm.$emit('confirm', {
      type: 'Polygon',
      coordinates: [[[118.8, 32], [119, 32], [119, 32.2], [118.8, 32]]],
    })
    await wrapper.vm.$nextTick()

    expect(setSourceGeometry).not.toHaveBeenCalled()
    expect(store.sourceGeometryWgs84).toEqual({ type: 'Point', coordinates: [118.9, 32.1] })
  })

  it('shows the active mode and cancels without changing committed source state', async () => {
    const { wrapper, store } = mountWorkspace()
    store.setSourceGeometry({
      type: 'LineString',
      coordinates: [
        [118.8, 32],
        [118.9, 32.1],
      ],
    })
    const committed = {
      type: 'LineString',
      coordinates: [
        [118.8, 32],
        [118.9, 32.1],
      ],
    }

    wrapper.findComponent(MapCanvasStub).vm.$emit('drawing-mode-change', 'polygon')
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('多边形绘制中')

    const cancelButton = wrapper
      .findAllComponents(ElButton)
      .find((button) => button.text().trim() === '取消绘制')
    if (!cancelButton) throw new Error('missing cancel drawing button')
    await cancelButton.trigger('click')

    expect(drawingCanvasMocks.cancelDrawing).toHaveBeenCalledOnce()
    expect(store.sourceGeometryWgs84).toEqual(committed)
    wrapper.unmount()
  })

  it('clears the study area only through the existing clearSelection action', async () => {
    const { wrapper, store } = mountWorkspace()
    store.setSourcePoint([118.9, 32.1])
    await wrapper.vm.$nextTick()
    const clearSelection = vi.spyOn(store, 'clearSelection')
    const clearButton = wrapper
      .findAllComponents(ElButton)
      .find((button) => button.text().trim() === '清除研究区')
    if (!clearButton) throw new Error('missing clear study area button')

    await clearButton.trigger('click')

    expect(drawingCanvasMocks.cancelDrawing).toHaveBeenCalledOnce()
    expect(clearSelection).toHaveBeenCalledOnce()
    expect(store.sourceGeometryWgs84).toBeNull()
    wrapper.unmount()
  })

  it('renders LineString, Polygon hole, and MultiPolygon source summaries', async () => {
    const { wrapper, store } = mountWorkspace()
    store.setSourceGeometry({
      type: 'LineString',
      coordinates: [
        [118.8, 32],
        [118.9, 32.1],
      ],
    })
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('LineString · 2 个顶点')

    store.setSourceGeometry({
      type: 'Polygon',
      coordinates: [
        [
          [118.8, 32],
          [118.9, 32],
          [118.9, 32.1],
          [118.8, 32],
        ],
      ],
    })
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Polygon · 3 个顶点')

    store.setSourceGeometry({
      type: 'Polygon',
      coordinates: [
        [
          [118.8, 32],
          [118.9, 32],
          [118.9, 32.1],
          [118.8, 32],
        ],
        [
          [118.83, 32.03],
          [118.85, 32.03],
          [118.85, 32.05],
          [118.83, 32.03],
        ],
      ],
    })
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Polygon · 3 个外环顶点 · 1 个孔洞')

    store.setSourceGeometry({
      type: 'MultiPolygon',
      coordinates: [
        [
          [
            [118.8, 32],
            [118.9, 32],
            [118.9, 32.1],
            [118.8, 32],
          ],
          [
            [118.83, 32.03],
            [118.85, 32.03],
            [118.85, 32.05],
            [118.83, 32.03],
          ],
        ],
        [
          [
            [119, 32.2],
            [119.1, 32.2],
            [119.1, 32.3],
            [119, 32.2],
          ],
        ],
      ],
    })
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('MultiPolygon · 2 个面 · 1 个孔洞')
    wrapper.unmount()
  })

  it('shows drawing errors without replacing the current source', async () => {
    const { wrapper, store } = mountWorkspace()
    store.setSourcePoint([118.9, 32.1])

    wrapper.findComponent(MapCanvasStub).vm.$emit('drawing-error', 'MouseTool 加载失败，请重试')
    await wrapper.vm.$nextTick()

    expect(wrapper.get('[role="alert"]').text()).toContain('MouseTool 加载失败，请重试')
    expect(store.sourceGeometryWgs84).toEqual({ type: 'Point', coordinates: [118.9, 32.1] })
    wrapper.unmount()
  })

  it('clears a drawing error after a Point path successfully selects a study point', async () => {
    const { wrapper, store } = mountWorkspace()
    const mapCanvas = wrapper.findComponent(MapCanvasStub)
    mapCanvas.vm.$emit('drawing-error', '上一次绘制失败')
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[role="alert"]').text()).toContain('上一次绘制失败')

    mapCanvas.vm.$emit('select-point', [118.9, 32.1])
    await wrapper.vm.$nextTick()

    expect(store.sourceGeometryWgs84).toEqual({ type: 'Point', coordinates: [118.9, 32.1] })
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('disables drawing controls and guards callbacks while analysis is locked', async () => {
    const { wrapper, store } = mountWorkspace()
    store.setSourcePoint([118.9, 32.1])
    const setSourceGeometry = vi.spyOn(store, 'setSourceGeometry')
    store.polling = true
    await wrapper.vm.$nextTick()

    for (const label of ['点', '线', '矩形', '多边形']) {
      expect(wrapper.get(`button[aria-label="绘制${label}"]`).attributes('disabled')).toBeDefined()
    }

    wrapper.findComponent(MapCanvasStub).vm.$emit('select-geometry', {
      type: 'Point',
      coordinates: [120, 30],
    })
    await wrapper.vm.$nextTick()

    expect(setSourceGeometry).not.toHaveBeenCalled()
    expect(store.sourceGeometryWgs84).toEqual({ type: 'Point', coordinates: [118.9, 32.1] })
    wrapper.unmount()
  })
})
