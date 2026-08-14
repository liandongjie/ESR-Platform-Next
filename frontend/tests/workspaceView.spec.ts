import ElementPlus, { ElButton, ElInputNumber, ElMessage, ElMessageBox } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AdministrativeRegionInput from '@/components/map/AdministrativeRegionInput.vue'
import ShapefileInput from '@/components/map/ShapefileInput.vue'
import AnalysisPanel from '@/components/workspace/AnalysisPanel.vue'
import BufferPanel from '@/components/workspace/BufferPanel.vue'
import RiskAnalysisPanel from '@/components/workspace/RiskAnalysisPanel.vue'
import StudyAreaCoordinateInput from '@/components/workspace/StudyAreaCoordinateInput.vue'
import StudyAreaPanel from '@/components/workspace/StudyAreaPanel.vue'
import StudyAreaSearchInput from '@/components/workspace/StudyAreaSearchInput.vue'
import RiskResultPanel from '@/components/risk-analysis/RiskResultPanel.vue'
import WorkspaceResultDrawer from '@/components/workspace/WorkspaceResultDrawer.vue'
import { getCapabilities, getLiveHealth } from '@/api/system'
import { useAnalysisStore } from '@/stores/analysis'
import { useSystemStore } from '@/stores/system'
import type { AnalysisAreaBufferResponse } from '@/types/analysisArea'
import type { StudyPointCandidate } from '@/types/poi'
import type { RiskJobStatus } from '@/types/riskAnalysis'
import WorkspaceView from '@/views/WorkspaceView.vue'
import { makeRiskIndicatorCatalog } from './fixtures/riskIndicatorCatalog'

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
    poiItems: { type: Array, default: () => [] },
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

function mountWorkspace(
  prepareStore?: (store: ReturnType<typeof useAnalysisStore>) => void,
  pinia = createPinia(),
) {
  setActivePinia(pinia)
  const store = useAnalysisStore()
  store.riskIndicatorCatalog = makeRiskIndicatorCatalog()
  store.initializeLegacyRiskWeights()
  if (prepareStore) prepareStore(store)
  else vi.spyOn(store, 'restoreRiskAnalysis').mockImplementation(() => new Promise(() => undefined))
  if (!vi.isMockFunction(store.loadRiskIndicatorCatalog)) {
    vi.spyOn(store, 'loadRiskIndicatorCatalog').mockResolvedValue()
  }
  const wrapper = mount(WorkspaceView, {
    global: {
      plugins: [pinia, ElementPlus],
      stubs: {
        AdministrativeRegionInput: true,
        ShapefileInput: true,
        MapCanvas: MapCanvasStub,
        RiskAnalysisResultDownloads: true,
        StatusCard: true,
      },
    },
  })
  return { wrapper, store, pinia }
}

async function selectStudyAreaTab(
  wrapper: ReturnType<typeof mountWorkspace>['wrapper'],
  label: string,
) {
  const tab = wrapper.findAll('button.study-area-tab').find((item) => item.text() === label)
  if (!tab) throw new Error(`missing ${label} study area tab`)
  await tab.trigger('click')
}

async function selectWorkflowStep(
  wrapper: ReturnType<typeof mountWorkspace>['wrapper'],
  label: string,
) {
  const step = wrapper.findAll('.workspace-workflow button').find((item) => item.text().includes(label))
  if (!step) throw new Error(`missing ${label} workflow step`)
  await step.trigger('click')
}

beforeEach(() => {
  drawingCanvasMocks.startDrawing.mockReset()
  drawingCanvasMocks.cancelDrawing.mockReset()
  vi.spyOn(ElMessageBox, 'confirm').mockReset().mockResolvedValue({} as never)
  vi.spyOn(ElMessage, 'success').mockReset().mockReturnValue({ close: vi.fn() } as never)
  vi.spyOn(ElMessage, 'error').mockReset().mockReturnValue({ close: vi.fn() } as never)
  vi.mocked(getLiveHealth).mockReset().mockResolvedValue({
    status: 'ok',
    service: 'esr-platform-api',
    environment: 'test',
  })
  vi.mocked(getCapabilities).mockReset().mockResolvedValue({
    project: 'ESR Platform',
    stage: 'test',
    coordinate_system: 'EPSG:4326',
    result_ttl_hours: 24,
    limits: { max_buffer_meters: 10_000, max_analysis_area_km2: 5_000 },
    implemented: [],
    planned: [],
  })
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

function bufferResult(distanceM = 3000): AnalysisAreaBufferResponse {
  return {
    source: {
      crs: 'EPSG:4326' as const,
      geometry_type: 'Point' as const,
      bounds: [118.9, 32.1, 118.9, 32.1] as [number, number, number, number],
    },
    buffer: {
      crs: 'EPSG:4326' as const,
      distance_m: distanceM,
      working_crs: 'EPSG:32650',
      area_m2: 28_228_936.4,
      area_km2: 28.2289364,
      bounds: [118.86, 32.07, 118.94, 32.13] as [number, number, number, number],
      geometry: {
        type: 'Polygon' as const,
        coordinates: [[
          [118.86, 32.1],
          [118.9, 32.13],
          [118.94, 32.1],
          [118.86, 32.1],
        ]],
      },
    },
  }
}

function setRiskJobStatus(
  store: ReturnType<typeof useAnalysisStore>,
  status: RiskJobStatus,
  taskId = 'task-1',
) {
  store.job = { task_id: taskId }
  store.jobStatus = {
    task_id: taskId,
    status,
    stage: status,
    progress: status === 'SUCCEEDED' ? 100 : 50,
    result_available: status === 'SUCCEEDED',
    submitted_at: null,
  }
}

function activeWorkflowLabel(wrapper: ReturnType<typeof mountWorkspace>['wrapper']) {
  return wrapper.get('.workspace-workflow li[data-state="active"] .step-label').text()
}

describe('WorkspaceView service status', () => {
  it('keeps successful service checks out of the workspace chrome', async () => {
    const { wrapper } = mountWorkspace((store) => {
      vi.spyOn(store, 'restoreRiskAnalysis').mockResolvedValue()
    })

    await flushPromises()

    expect(getLiveHealth).toHaveBeenCalledOnce()
    expect(wrapper.find('.workspace-service-error').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('服务在线')
    expect(wrapper.text()).not.toContain('检查服务')
  })

  it('shows a compact retry action after a failed service check', async () => {
    vi.mocked(getLiveHealth).mockRejectedValueOnce(new Error('offline'))
    const pinia = createPinia()
    setActivePinia(pinia)
    const systemStore = useSystemStore()
    const load = vi.spyOn(systemStore, 'load')
    const { wrapper } = mountWorkspace((store) => {
      vi.spyOn(store, 'restoreRiskAnalysis').mockResolvedValue()
    }, pinia)

    await flushPromises()

    expect(load).toHaveBeenCalledOnce()
    expect(wrapper.get('.workspace-service-error').text()).toContain('服务暂不可用')

    await wrapper.get('.workspace-service-error button').trigger('click')
    await flushPromises()

    expect(load).toHaveBeenCalledTimes(2)
  })
})

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
    await selectStudyAreaTab(wrapper, '坐标')
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
      const setSourceGeometry = vi.spyOn(store, 'setSourceGeometry')
      await selectStudyAreaTab(wrapper, '坐标')
      const inputs = coordinateInputs(wrapper)

      await inputs.longitude.setValue(longitude)
      await inputs.latitude.setValue(latitude)
      await applyButton(wrapper).trigger('click')

      expect(setSourceGeometry).not.toHaveBeenCalled()
      expect(store.sourceGeometryWgs84?.coordinates).toEqual([118.8, 32])
      expect(wrapper.get('[role="alert"]').text()).not.toBe('')
    },
  )

  it('clears the input error after a valid retry', async () => {
    const { wrapper, store } = mountWorkspace()
    await selectStudyAreaTab(wrapper, '坐标')
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
    await selectStudyAreaTab(wrapper, '坐标')
    const inputs = coordinateInputs(wrapper)
    await inputs.longitude.setValue('118.9')
    await inputs.latitude.setValue('32.1')
    const setSourceGeometry = vi.spyOn(store, 'setSourceGeometry')

    store.polling = true
    await wrapper.vm.$nextTick()

    expect(inputs.longitude.attributes('disabled')).toBeDefined()
    expect(inputs.latitude.attributes('disabled')).toBeDefined()
    expect(applyButton(wrapper).attributes('disabled')).toBeDefined()

    applyButton(wrapper).vm.$emit('click')
    await wrapper.vm.$nextTick()
    expect(setSourceGeometry).not.toHaveBeenCalled()
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
    await selectStudyAreaTab(wrapper, '搜索')
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
    await selectStudyAreaTab(wrapper, '搜索')
    const setSourceGeometry = vi.spyOn(store, 'setSourceGeometry')

    await wrapper.get('input[aria-label="地址或 POI 关键词"]').setValue('南京大学')
    await studyPointSearchButton(wrapper).trigger('click')
    await flushPromises()
    await wrapper.get('.study-point-result').trigger('click')

    expect(setSourceGeometry).toHaveBeenCalledOnce()
    expect(setSourceGeometry).toHaveBeenCalledWith({
      type: 'Point',
      coordinates: selected.locationWgs84,
    })
    expect(wrapper.findAll('.workspace-workflow li')[1]?.attributes('data-state')).toBe('active')
  })

  it('shows empty and error states for the submitted keyword', async () => {
    mocks.searchAmapStudyPoints.mockResolvedValueOnce([])
    const { wrapper } = mountWorkspace()
    await selectStudyAreaTab(wrapper, '搜索')
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
    await selectStudyAreaTab(wrapper, '搜索')

    await studyPointSearchButton(wrapper).trigger('click')

    expect(mocks.searchAmapStudyPoints).not.toHaveBeenCalled()
    expect(wrapper.get('.study-point-search-error').text()).toContain('请输入地址或 POI 关键词')
  })

  it('auto-forwards after selecting a search candidate', async () => {
    mocks.searchAmapStudyPoints.mockResolvedValue([
      candidate('poi-1', '南京大学', [118.772, 32.061]),
    ])
    const { wrapper } = mountWorkspace()
    await selectStudyAreaTab(wrapper, '搜索')
    const input = wrapper.get('input[aria-label="地址或 POI 关键词"]')

    await input.setValue('南京大学')
    await studyPointSearchButton(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.find('.study-point-result').exists()).toBe(true)
    await wrapper.get('.study-point-result').trigger('click')
    expect(wrapper.findAll('.workspace-workflow li')[1]?.attributes('data-state')).toBe('active')
  })

  it('can return and replace a selected search point from coordinate input', async () => {
    mocks.searchAmapStudyPoints.mockResolvedValue([
      candidate('poi-1', '南京大学', [118.772, 32.061]),
    ])
    const { wrapper, store } = mountWorkspace()
    await selectStudyAreaTab(wrapper, '搜索')

    await wrapper.get('input[aria-label="地址或 POI 关键词"]').setValue('南京大学')
    await studyPointSearchButton(wrapper).trigger('click')
    await flushPromises()
    await wrapper.get('.study-point-result').trigger('click')

    await selectWorkflowStep(wrapper, '研究区')
    await selectStudyAreaTab(wrapper, '坐标')
    const inputs = coordinateInputs(wrapper)
    await inputs.longitude.setValue('118.9')
    await inputs.latitude.setValue('32.1')
    await applyButton(wrapper).trigger('click')

    expect(store.sourceGeometryWgs84?.coordinates).toEqual([118.9, 32.1])
    expect(wrapper.findAll('.workspace-workflow li')[1]?.attributes('data-state')).toBe('active')
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
      await selectStudyAreaTab(wrapper, '搜索')
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
    await selectStudyAreaTab(wrapper, '搜索')
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
    await selectStudyAreaTab(wrapper, '搜索')
    const input = wrapper.get('input[aria-label="地址或 POI 关键词"]')
    await input.setValue('南京大学')
    await studyPointSearchButton(wrapper).trigger('click')
    await flushPromises()
    const setSourceGeometry = vi.spyOn(store, 'setSourceGeometry')

    store.polling = true
    await wrapper.vm.$nextTick()

    expect(input.attributes('disabled')).toBeDefined()
    expect(studyPointSearchButton(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.get('.study-point-result').attributes('disabled')).toBeDefined()
    await wrapper.get('.study-point-result').trigger('click')
    expect(setSourceGeometry).not.toHaveBeenCalled()
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
    expect(ElMessageBox.confirm).not.toHaveBeenCalled()
    expect(wrapper.findAll('.workspace-workflow li')[1]?.attributes('data-state')).toBe('active')
    wrapper.unmount()
  })

  it.each([
    ['map point', null, 'point'],
    ['map draw', null, 'draw'],
    ['coordinate', '坐标', StudyAreaCoordinateInput],
    ['search', '搜索', StudyAreaSearchInput],
    ['administrative', '行政区', AdministrativeRegionInput],
    ['file', '文件', ShapefileInput],
  ] as const)('protects the %s Source entry with the shared destructive gate', async (_name, tab, entry) => {
    const { wrapper, store } = mountWorkspace()
    store.setSourcePoint([118.9, 32.1])
    store.bufferResult = bufferResult()
    store.poiHasSearched = true
    store.taskError = '已有风险上下文'
    await wrapper.vm.$nextTick()
    const committed = {
      source: store.sourceGeometryWgs84,
      buffer: store.bufferResult,
      poiHasSearched: store.poiHasSearched,
      taskError: store.taskError,
      weights: store.weights,
    }
    const setSourcePoint = vi.spyOn(store, 'setSourcePoint')
    const setSourceGeometry = vi.spyOn(store, 'setSourceGeometry')
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')

    if (entry === 'point') {
      wrapper.findComponent(MapCanvasStub).vm.$emit('select-point', [120, 30])
    } else if (entry === 'draw') {
      wrapper.findComponent(MapCanvasStub).vm.$emit('select-geometry', {
        type: 'Point',
        coordinates: [120, 30],
      })
    } else {
      await selectStudyAreaTab(wrapper, tab as string)
      wrapper.findComponent(entry).vm.$emit('confirm', { type: 'Point', coordinates: [120, 30] })
    }
    await flushPromises()

    expect(ElMessageBox.confirm).toHaveBeenCalledOnce()
    expect(setSourcePoint).not.toHaveBeenCalled()
    expect(setSourceGeometry).not.toHaveBeenCalled()
    expect(store.sourceGeometryWgs84).toBe(committed.source)
    expect(store.bufferResult).toBe(committed.buffer)
    expect(store.poiHasSearched).toBe(committed.poiHasSearched)
    expect(store.taskError).toBe(committed.taskError)
    expect(store.weights).toBe(committed.weights)
    expect(wrapper.findAll('.workspace-workflow li')[0]?.attributes('data-state')).toBe('active')
    if (entry === 'point' || entry === 'draw') {
      expect(drawingCanvasMocks.cancelDrawing).toHaveBeenCalledOnce()
    }
  })

  it('commits a normalized administrative geometry through the existing store action', async () => {
    const { wrapper, store } = mountWorkspace()
    await selectStudyAreaTab(wrapper, '行政区')
    drawingCanvasMocks.cancelDrawing.mockClear()
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
    await flushPromises()

    expect(setSourceGeometry).toHaveBeenCalledWith(normalized)
    expect(store.sourceGeometryWgs84).toEqual(normalized)
    expect(store.bufferResult).toBeNull()
    expect(drawingCanvasMocks.cancelDrawing).toHaveBeenCalledOnce()
  })

  it('guards administrative geometry events while analysis is locked', async () => {
    const { wrapper, store } = mountWorkspace()
    await selectStudyAreaTab(wrapper, '行政区')
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

  it('commits imported Shapefile geometry through the existing store action', async () => {
    const { wrapper, store } = mountWorkspace()
    await selectStudyAreaTab(wrapper, '文件')
    drawingCanvasMocks.cancelDrawing.mockClear()
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
    const imported = {
      type: 'LineString' as const,
      coordinates: [
        [118.7, 31.9],
        [119.1, 32.3],
      ] as Array<[number, number]>,
    }

    wrapper.findComponent(ShapefileInput).vm.$emit('confirm', imported)
    await flushPromises()

    expect(setSourceGeometry).toHaveBeenCalledWith(imported)
    expect(store.sourceGeometryWgs84).toEqual(imported)
    expect(store.bufferResult).toBeNull()
    expect(drawingCanvasMocks.cancelDrawing).toHaveBeenCalledOnce()
  })

  it('guards Shapefile geometry events while analysis is locked', async () => {
    const { wrapper, store } = mountWorkspace()
    await selectStudyAreaTab(wrapper, '文件')
    store.setSourcePoint([118.9, 32.1])
    const setSourceGeometry = vi.spyOn(store, 'setSourceGeometry')
    store.polling = true
    await wrapper.vm.$nextTick()

    expect(wrapper.findComponent(ShapefileInput).props('disabled')).toBe(true)
    wrapper.findComponent(ShapefileInput).vm.$emit('confirm', {
      type: 'Polygon',
      coordinates: [[[118.8, 32], [119, 32], [119, 32.2], [118.8, 32]]],
    })
    await wrapper.vm.$nextTick()

    expect(setSourceGeometry).not.toHaveBeenCalled()
    expect(store.sourceGeometryWgs84).toEqual({ type: 'Point', coordinates: [118.9, 32.1] })
  })

  it('cancels drawing on tab switch without changing committed source state', async () => {
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

    await selectStudyAreaTab(wrapper, '坐标')

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
    expect(ElMessageBox.confirm).not.toHaveBeenCalled()
    expect(wrapper.findAll('.workspace-workflow li')[0]?.attributes('data-state')).toBe('active')
    wrapper.unmount()
  })

  it('keeps all committed state and local drafts when destructive Source clear is canceled', async () => {
    const { wrapper, store } = mountWorkspace()
    store.setSourcePoint([118.9, 32.1])
    store.bufferResult = bufferResult()
    store.poiHasSearched = true
    store.poiItems = [{
      id: 'poi-1', name: '学校', type: '', typeCode: '', address: '', locationWgs84: [118.81, 32.02],
    }]
    store.taskError = '已有风险上下文'
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '分析')
    const analysisPanel = wrapper.findComponent(AnalysisPanel)
    const poiDraft = analysisPanel.get('input[aria-label="POI 关键词"]')
    await poiDraft.setValue('医院')
    await analysisPanel.findAll('button.analysis-tab').find((item) => item.text() === '风险')!.trigger('click')
    const riskDraft = analysisPanel.findComponent(RiskAnalysisPanel).findAllComponents(ElInputNumber)[0]!
    riskDraft.vm.$emit('update:modelValue', 35)
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '研究区')
    const committed = {
      source: store.sourceGeometryWgs84,
      buffer: store.bufferResult,
      poiItems: store.poiItems,
      taskError: store.taskError,
      weights: store.weights,
    }
    const clearSelection = vi.spyOn(store, 'clearSelection')
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')
    const clearButton = wrapper.findAllComponents(ElButton).find(
      (button) => button.text().trim() === '清除研究区',
    )!

    await clearButton.trigger('click')
    await flushPromises()

    expect(clearSelection).not.toHaveBeenCalled()
    expect(store.sourceGeometryWgs84).toBe(committed.source)
    expect(store.bufferResult).toBe(committed.buffer)
    expect(store.poiItems).toBe(committed.poiItems)
    expect(store.taskError).toBe(committed.taskError)
    expect(store.weights).toBe(committed.weights)
    expect(wrapper.findAll('.workspace-workflow li')[0]?.attributes('data-state')).toBe('active')
    await selectWorkflowStep(wrapper, '分析')
    expect((poiDraft.element as HTMLInputElement).value).toBe('医院')
    expect(riskDraft.props('modelValue')).toBe(35)
  })

  it('continues through existing invalidation after destructive Source clear is confirmed', async () => {
    const { wrapper, store } = mountWorkspace()
    store.setSourcePoint([118.9, 32.1])
    store.bufferResult = bufferResult()
    store.poiHasSearched = true
    store.taskError = '已有风险上下文'
    await wrapper.vm.$nextTick()
    const clearSelection = vi.spyOn(store, 'clearSelection')
    const clearButton = wrapper.findAllComponents(ElButton).find(
      (button) => button.text().trim() === '清除研究区',
    )!

    await clearButton.trigger('click')
    await flushPromises()

    expect(ElMessageBox.confirm).toHaveBeenCalledWith(
      expect.stringContaining('清除研究区'),
      '确认清除研究区',
      expect.any(Object),
    )
    expect(clearSelection).toHaveBeenCalledOnce()
    expect(store.sourceGeometryWgs84).toBeNull()
    expect(store.bufferResult).toBeNull()
    expect(store.poiHasSearched).toBe(false)
    expect(store.taskError).toBeNull()
    expect(wrapper.findAll('.workspace-workflow li')[0]?.attributes('data-state')).toBe('active')
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

describe('WorkspaceView buffer panel wiring', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
  })

  function prepareBuffer(store: ReturnType<typeof useAnalysisStore>) {
    store.setSourcePoint([118.9, 32.1])
    store.bufferResult = bufferResult()
  }

  it('commits the generated distance before using the existing createBuffer action', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareBuffer(store)
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '缓冲区')
    const calls: string[] = []
    const setBufferDistance = vi.spyOn(store, 'setBufferDistance').mockImplementation((distance) => {
      calls.push(`set:${distance}`)
    })
    const createBuffer = vi.spyOn(store, 'createBuffer').mockImplementation(async () => {
      calls.push('create')
    })

    wrapper.findComponent(BufferPanel).vm.$emit('generate', 5000)
    await wrapper.vm.$nextTick()

    expect(setBufferDistance).toHaveBeenCalledWith(5000)
    expect(createBuffer).toHaveBeenCalledOnce()
    expect(calls).toEqual(['set:5000', 'create'])
  })

  it('does not confirm for an old Buffer alone and forwards only after the current request commits', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareBuffer(store)
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '缓冲区')
    const request = deferred<void>()
    vi.spyOn(store, 'createBuffer').mockImplementation(async () => {
      const revision = ++store.bufferRequestRevision
      store.bufferResult = null
      store.bufferError = null
      store.bufferLoading = true
      await request.promise
      if (revision !== store.bufferRequestRevision) return
      store.bufferResult = bufferResult(store.bufferDistanceMeters)
      store.bufferLoading = false
    })

    wrapper.findComponent(BufferPanel).vm.$emit('generate', 5000)
    await wrapper.vm.$nextTick()

    expect(ElMessageBox.confirm).not.toHaveBeenCalled()
    expect(wrapper.findAll('.workspace-workflow li')[1]?.attributes('data-state')).toBe('active')

    request.resolve()
    await flushPromises()

    expect(store.bufferResult?.buffer.distance_m).toBe(5000)
    expect(wrapper.findAll('.workspace-workflow li')[2]?.attributes('data-state')).toBe('active')
  })

  it('keeps the old step when a new Buffer request fails after an old Buffer existed', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareBuffer(store)
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '缓冲区')
    vi.spyOn(store, 'createBuffer').mockImplementation(async () => {
      store.bufferRequestRevision += 1
      store.bufferResult = null
      store.bufferLoading = true
      store.bufferError = null
      await Promise.resolve()
      store.bufferLoading = false
      store.bufferError = '生成缓冲区失败'
    })

    wrapper.findComponent(BufferPanel).vm.$emit('generate', 5000)
    await flushPromises()

    expect(store.bufferResult).toBeNull()
    expect(store.bufferError).toBe('生成缓冲区失败')
    expect(wrapper.findAll('.workspace-workflow li')[1]?.attributes('data-state')).toBe('active')
  })

  it('does not forward for a stale Buffer completion and forwards for the latest committed Buffer', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareBuffer(store)
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '缓冲区')
    const requests: Array<ReturnType<typeof deferred<void>>> = []
    vi.spyOn(store, 'createBuffer').mockImplementation(async () => {
      const revision = ++store.bufferRequestRevision
      const distance = store.bufferDistanceMeters
      const request = deferred<void>()
      requests.push(request)
      store.bufferResult = null
      store.bufferLoading = true
      store.bufferError = null
      await request.promise
      if (revision !== store.bufferRequestRevision) return
      store.bufferResult = bufferResult(distance)
      store.bufferLoading = false
    })

    wrapper.findComponent(BufferPanel).vm.$emit('generate', 4000)
    await wrapper.vm.$nextTick()
    wrapper.findComponent(BufferPanel).vm.$emit('generate', 5000)
    await wrapper.vm.$nextTick()

    requests[0]!.resolve()
    await flushPromises()
    expect(store.bufferResult).toBeNull()
    expect(wrapper.findAll('.workspace-workflow li')[1]?.attributes('data-state')).toBe('active')

    requests[1]!.resolve()
    await flushPromises()
    expect(store.bufferResult?.buffer.distance_m).toBe(5000)
    expect(wrapper.findAll('.workspace-workflow li')[2]?.attributes('data-state')).toBe('active')
  })

  it('cancels or confirms destructive Buffer regeneration before any Store mutation', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareBuffer(store)
    store.poiHasSearched = true
    store.taskError = '已有风险上下文'
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '缓冲区')
    const committed = {
      distance: store.bufferDistanceMeters,
      buffer: store.bufferResult,
      poiHasSearched: store.poiHasSearched,
      taskError: store.taskError,
    }
    const setBufferDistance = vi.spyOn(store, 'setBufferDistance')
    const createBuffer = vi.spyOn(store, 'createBuffer').mockImplementation(async () => {
      store.bufferRequestRevision += 1
      store.bufferResult = bufferResult(store.bufferDistanceMeters)
      store.bufferError = null
      store.bufferLoading = false
    })
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')

    wrapper.findComponent(BufferPanel).vm.$emit('generate', 5000)
    await flushPromises()

    expect(setBufferDistance).not.toHaveBeenCalled()
    expect(createBuffer).not.toHaveBeenCalled()
    expect(store.bufferDistanceMeters).toBe(committed.distance)
    expect(store.bufferResult).toBe(committed.buffer)
    expect(store.poiHasSearched).toBe(committed.poiHasSearched)
    expect(store.taskError).toBe(committed.taskError)
    expect(wrapper.findAll('.workspace-workflow li')[1]?.attributes('data-state')).toBe('active')

    wrapper.findComponent(BufferPanel).vm.$emit('generate', 5000)
    await flushPromises()

    expect(ElMessageBox.confirm).toHaveBeenCalledTimes(2)
    expect(setBufferDistance).toHaveBeenCalledWith(5000)
    expect(createBuffer).toHaveBeenCalledOnce()
    expect(wrapper.findAll('.workspace-workflow li')[2]?.attributes('data-state')).toBe('active')
  })

  it('preserves an unsubmitted Buffer draft across workflow navigation', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareBuffer(store)
    store.poiItems = [
      {
        id: 'poi-1',
        name: '学校一',
        type: '',
        typeCode: '',
        address: '',
        locationWgs84: [118.81, 32.02],
      },
    ]
    store.result = {
      schema_version: 1,
      task_id: 'task-1',
      status: 'SUCCEEDED',
      algorithm_version: 'v1',
      geometry: { type: 'Polygon', bounds: [118.86, 32.07, 118.94, 32.13] },
      grid: { crs: 'EPSG:4326', shape: [6, 8], nodata: -9999 },
      statistics: { valid_pixel_count: 28, minimum: 0.36, maximum: 0.41, mean: 0.38 },
      indicators: [],
      artifacts: {
        raster: 'risk-analysis/task-1/risk.tif',
        manifest: 'risk-analysis/task-1/result.json',
      },
    }
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '缓冲区')
    const committedDistance = store.bufferDistanceMeters
    const committedBuffer = store.bufferResult
    const committedPoiItems = store.poiItems
    const committedRisk = store.result
    const setBufferDistance = vi.spyOn(store, 'setBufferDistance')
    const createBuffer = vi.spyOn(store, 'createBuffer')
    const bufferPanel = wrapper.findComponent(BufferPanel)

    bufferPanel.findComponent({ name: 'ElInputNumber' }).vm.$emit('update:modelValue', 5000)
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '研究区')
    await selectWorkflowStep(wrapper, '缓冲区')

    expect(setBufferDistance).not.toHaveBeenCalled()
    expect(createBuffer).not.toHaveBeenCalled()
    expect(bufferPanel.findComponent({ name: 'ElInputNumber' }).props('modelValue')).toBe(5000)
    expect(store.bufferDistanceMeters).toBe(committedDistance)
    expect(store.bufferResult).toBe(committedBuffer)
    expect(store.poiItems).toBe(committedPoiItems)
    expect(store.result).toBe(committedRisk)
  })
})

describe('WorkspaceView analysis panel wiring', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
  })

  function prepareAnalysis(store: ReturnType<typeof useAnalysisStore>) {
    store.setSourcePoint([118.9, 32.1])
    store.bufferResult = {
      source: {
        crs: 'EPSG:4326',
        geometry_type: 'Point',
        bounds: [118.9, 32.1, 118.9, 32.1],
      },
      buffer: {
        crs: 'EPSG:4326',
        distance_m: 3000,
        working_crs: 'EPSG:32650',
        area_m2: 28_228_936.4,
        area_km2: 28.2289364,
        bounds: [118.86, 32.07, 118.94, 32.13],
        geometry: {
          type: 'Polygon',
          coordinates: [[[118.86, 32.1], [118.9, 32.13], [118.94, 32.1], [118.86, 32.1]]],
        },
      },
    }
  }

  function setRiskResult(store: ReturnType<typeof useAnalysisStore>) {
    store.result = {
      schema_version: 1,
      task_id: 'task-1',
      status: 'SUCCEEDED',
      algorithm_version: 'v1',
      geometry: { type: 'Polygon', bounds: [118.86, 32.07, 118.94, 32.13] },
      grid: { crs: 'EPSG:4326', shape: [6, 8], nodata: -9999 },
      statistics: { valid_pixel_count: 28, minimum: 0.36, maximum: 0.41, mean: 0.38 },
      indicators: [],
      artifacts: {
        raster: 'risk-analysis/task-1/risk.tif',
        manifest: 'risk-analysis/task-1/result.json',
      },
    }
  }

  it('applies legacy defaults when catalog retry succeeds in a new Workspace', async () => {
    let attempt = 0
    const { wrapper, store } = mountWorkspace((candidate) => {
      prepareAnalysis(candidate)
      window.sessionStorage.clear()
      candidate.weights = []
      candidate.riskIndicatorCatalog = null
      candidate.riskIndicatorCatalogError = null
      vi.spyOn(candidate, 'restoreRiskAnalysis').mockResolvedValue()
      vi.spyOn(candidate, 'loadRiskIndicatorCatalog').mockImplementation(async () => {
        attempt += 1
        if (attempt === 1) {
          candidate.riskIndicatorCatalog = null
          candidate.riskIndicatorCatalogError = '目录请求失败'
          return
        }
        candidate.riskIndicatorCatalog = makeRiskIndicatorCatalog()
        candidate.riskIndicatorCatalogError = null
        candidate.initializeLegacyRiskWeights()
      })
    })
    await flushPromises()
    await selectWorkflowStep(wrapper, '分析')
    const panel = wrapper.findComponent(AnalysisPanel)
    await panel.findAll('button.analysis-tab').find((item) => item.text() === '风险')!.trigger('click')
    const retry = panel
      .findComponent(RiskAnalysisPanel)
      .findAllComponents(ElButton)
      .find((item) => item.text().includes('重试加载'))
    if (!retry) throw new Error('missing catalog retry button')

    await retry.trigger('click')
    await flushPromises()

    expect(attempt).toBe(2)
    expect(store.weights).toEqual([
      { code: 'PM25', weight_percent: 30 },
      { code: 'AQI', weight_percent: 40 },
      { code: 'NDVI', weight_percent: 30 },
    ])
  })

  it('commits all Risk weights before using the existing submit action', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareAnalysis(store)
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '分析')
    const calls: string[] = []
    const setWeights = vi.spyOn(store, 'setRiskWeights').mockImplementation(() => {
      calls.push('set-all')
      return true
    })
    const submit = vi.spyOn(store, 'submitRiskAnalysis').mockImplementation(async () => {
      calls.push('submit')
    })
    const weights = [
      { code: 'PM25', weight_percent: 35 },
      { code: 'AQI', weight_percent: 35 },
      { code: 'NDVI', weight_percent: 30 },
    ]

    wrapper.findComponent(AnalysisPanel).vm.$emit('submit-risk', weights)
    await wrapper.vm.$nextTick()

    expect(setWeights).toHaveBeenCalledOnce()
    expect(setWeights).toHaveBeenCalledWith(weights)
    expect(submit).toHaveBeenCalledOnce()
    expect(calls).toEqual(['set-all', 'submit'])
    expect(wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(true)
    expect(wrapper.findComponent(WorkspaceResultDrawer).props('title')).toBe('风险任务 / 结果')
    expect(wrapper.findComponent(RiskResultPanel).exists()).toBe(true)
  })

  it('does not change committed weights or Risk result while only editing the Risk draft', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareAnalysis(store)
    setRiskResult(store)
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '分析')
    const committedWeights = store.weights.map((item) => ({ ...item }))
    const committedResult = store.result
    const setWeight = vi.spyOn(store, 'setRiskWeights')
    const submit = vi.spyOn(store, 'submitRiskAnalysis')
    const analysisPanel = wrapper.findComponent(AnalysisPanel)
    const riskTab = analysisPanel.findAll('button.analysis-tab').find((item) => item.text() === '风险')
    if (!riskTab) throw new Error('missing Risk tab')
    await riskTab.trigger('click')

    analysisPanel
      .findComponent(RiskAnalysisPanel)
      .findAllComponents(ElInputNumber)[0]!
      .vm.$emit('update:modelValue', 35)
    await wrapper.vm.$nextTick()

    expect(setWeight).not.toHaveBeenCalled()
    expect(submit).not.toHaveBeenCalled()
    expect(store.weights).toEqual(committedWeights)
    expect(store.result).toBe(committedResult)
  })

  it('reopens an existing Risk result without implicitly committing the local draft', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareAnalysis(store)
    setRiskResult(store)
    store.job = { task_id: 'task-1' }
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '分析')
    const committedWeights = store.weights.map((item) => ({ ...item }))
    const committedResult = store.result
    const setWeight = vi.spyOn(store, 'setRiskWeights')
    const submit = vi.spyOn(store, 'submitRiskAnalysis')
    const panel = wrapper.findComponent(AnalysisPanel)
    await panel.findAll('button.analysis-tab').find((item) => item.text() === '风险')!.trigger('click')
    const riskPanel = panel.findComponent(RiskAnalysisPanel)
    riskPanel.findAllComponents(ElInputNumber)[0]!.vm.$emit('update:modelValue', 35)
    await wrapper.vm.$nextTick()
    const draftValue = riskPanel.findAllComponents(ElInputNumber)[0]!.props('modelValue')
    const view = riskPanel.findAllComponents(ElButton).find((item) => item.text().includes('查看任务/结果'))
    if (!view) throw new Error('missing view task/result button')

    await view.trigger('click')

    expect(wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(true)
    expect(wrapper.findComponent(WorkspaceResultDrawer).props('title')).toBe('风险任务 / 结果')
    expect(setWeight).not.toHaveBeenCalled()
    expect(submit).not.toHaveBeenCalled()
    expect(store.weights).toEqual(committedWeights)
    expect(store.result).toBe(committedResult)
    expect(riskPanel.findAllComponents(ElInputNumber)[0]!.props('modelValue')).toBe(draftValue)
  })

  it('keeps a closed running Risk drawer closed when the task reaches success', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareAnalysis(store)
    store.job = { task_id: 'task-1' }
    store.jobStatus = {
      task_id: 'task-1', status: 'RUNNING', stage: 'RUNNING', progress: 50,
      result_available: false, submitted_at: null,
    }
    store.polling = true
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '分析')
    const job = store.job
    wrapper.findComponent(AnalysisPanel).vm.$emit('risk-open-result')
    await wrapper.vm.$nextTick()
    await wrapper.get('button[aria-label="关闭结果抽屉"]').trigger('click')

    expect(wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(false)
    expect(store.job).toBe(job)
    expect(store.polling).toBe(true)

    store.polling = false
    store.jobStatus.status = 'SUCCEEDED'
    store.jobStatus.progress = 100
    store.jobStatus.result_available = true
    setRiskResult(store)
    await wrapper.vm.$nextTick()

    expect(wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(false)
    expect(store.job).toBe(job)
    expect(store.result?.task_id).toBe('task-1')
  })

  it('keeps a restored Risk task closed and reopens it from the recovery entry without submit', async () => {
    const { wrapper, store } = mountWorkspace()
    store.job = { task_id: 'restored-task' }
    store.jobStatus = {
      task_id: 'restored-task', status: 'FAILED', stage: 'FAILED', progress: 60,
      result_available: false, submitted_at: null,
    }
    store.taskError = '恢复的任务失败'
    await wrapper.vm.$nextTick()
    const submit = vi.spyOn(store, 'submitRiskAnalysis')

    expect(wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(false)
    const view = wrapper.findAllComponents(ElButton).find((item) => item.text().includes('查看任务/结果'))
    if (!view) throw new Error('missing restored task entry')
    await view.trigger('click')

    expect(wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(true)
    expect(wrapper.findComponent(WorkspaceResultDrawer).props('title')).toBe('风险任务 / 结果')
    expect(submit).not.toHaveBeenCalled()
  })

  it('switches the existing drawer between POI and Risk content', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareAnalysis(store)
    store.poiHasSearched = true
    store.job = { task_id: 'task-1' }
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '分析')
    const panel = wrapper.findComponent(AnalysisPanel)

    panel.vm.$emit('poi-open-result')
    await wrapper.vm.$nextTick()
    expect(wrapper.findComponent(WorkspaceResultDrawer).props('title')).toBe('POI 结果')
    panel.vm.$emit('risk-open-result')
    await wrapper.vm.$nextTick()
    expect(wrapper.findComponent(WorkspaceResultDrawer).props('title')).toBe('风险任务 / 结果')
    expect(wrapper.findComponent(RiskResultPanel).exists()).toBe(true)
  })

  it('does not open the Risk drawer for guarded submit callbacks', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareAnalysis(store)
    store.polling = true
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '分析')

    wrapper.findComponent(AnalysisPanel).vm.$emit('submit-risk', store.weights)
    await wrapper.vm.$nextTick()

    expect(wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(false)
  })

  it('renders Risk task and result only inside the drawer, not in the context panel', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareAnalysis(store)
    store.job = { task_id: 'task-1' }
    setRiskResult(store)
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '分析')
    wrapper.findComponent(AnalysisPanel).vm.$emit('risk-open-result')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.workspace-context-panel').text()).not.toContain('异步任务')
    expect(wrapper.find('.workspace-context-panel').text()).not.toContain('分析结果')
    expect(wrapper.findComponent(WorkspaceResultDrawer).text()).toContain('异步任务')
    expect(wrapper.findComponent(WorkspaceResultDrawer).text()).toContain('分析结果')
  })

  it('keeps Analysis tabs viewable while locked and guards Risk submission', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareAnalysis(store)
    store.polling = true
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '分析')
    const setWeight = vi.spyOn(store, 'setRiskWeights')
    const submit = vi.spyOn(store, 'submitRiskAnalysis')
    const panel = wrapper.findComponent(AnalysisPanel)
    const riskTab = panel.findAll('button.analysis-tab').find((item) => item.text() === '风险')
    if (!riskTab) throw new Error('missing Risk tab')

    await riskTab.trigger('click')
    panel.vm.$emit('submit-risk', [
      { code: 'PM25', weight_percent: 30 },
      { code: 'AQI', weight_percent: 40 },
      { code: 'NDVI', weight_percent: 30 },
    ])
    await wrapper.vm.$nextTick()

    expect(panel.props('activeTab')).toBe('risk')
    expect(setWeight).not.toHaveBeenCalled()
    expect(submit).not.toHaveBeenCalled()
  })

  it('opens the POI result drawer only from a successful query event', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareAnalysis(store)
    store.poiCommittedKeyword = '学校'
    store.poiHasSearched = true
    store.poiItems = []
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '分析')
    const drawer = wrapper.findComponent(WorkspaceResultDrawer)

    expect(drawer.props('open')).toBe(false)
    wrapper.findComponent(AnalysisPanel).vm.$emit('poi-query-success')
    await wrapper.vm.$nextTick()

    expect(drawer.props('open')).toBe(true)
    expect(wrapper.text()).toContain('当前缓冲区内未找到匹配 POI')
  })

  it('keeps the drawer closed for restored results until a new query succeeds', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareAnalysis(store)
    store.poiCommittedKeyword = '学校'
    store.poiHasSearched = true
    store.poiItems = [{
      id: 'poi-1', name: '学校', type: '', typeCode: '', address: '', locationWgs84: [118.81, 32.02],
    }]
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '分析')

    expect(wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(false)
  })

  it('closes only the POI drawer without clearing committed results or map markers', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareAnalysis(store)
    store.poiKeyword = '学校'
    store.poiCommittedKeyword = '学校'
    store.poiHasSearched = true
    store.poiItems = [{
      id: 'poi-1', name: '学校', type: '', typeCode: '', address: '', locationWgs84: [118.81, 32.02],
    }]
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '分析')
    const items = store.poiItems
    const setKeyword = vi.spyOn(store, 'setPoiKeyword')
    const search = vi.spyOn(store, 'searchPois').mockResolvedValue()
    wrapper.findComponent(AnalysisPanel).vm.$emit('poi-query-success')
    await wrapper.vm.$nextTick()

    await wrapper.get('button[aria-label="关闭结果抽屉"]').trigger('click')

    expect(wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(false)
    expect(store.poiCommittedKeyword).toBe('学校')
    expect(store.poiItems).toBe(items)
    expect(wrapper.findComponent(MapCanvasStub).props('poiItems')).toBe(items)

    const viewResult = wrapper.findAll('button').find((item) => item.text() === '查看结果')
    if (!viewResult) throw new Error('missing view result button')
    await viewResult.trigger('click')

    expect(wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(true)
    expect(setKeyword).not.toHaveBeenCalled()
    expect(search).not.toHaveBeenCalled()
    expect(store.poiCommittedKeyword).toBe('学校')
    expect(store.poiItems).toBe(items)
    expect(wrapper.findComponent(MapCanvasStub).props('poiItems')).toBe(items)
  })

  it('allows opening and closing existing POI results while analysis is locked', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareAnalysis(store)
    store.polling = true
    store.poiHasSearched = true
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '分析')

    wrapper.findComponent(AnalysisPanel).vm.$emit('poi-query-success')
    await wrapper.vm.$nextTick()
    expect(wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(true)
    await wrapper.get('button[aria-label="关闭结果抽屉"]').trigger('click')
    expect(wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(false)
  })

  it('derives availability and completion from committed Store state', async () => {
    const { wrapper, store } = mountWorkspace()
    const states = () =>
      wrapper.findAll('.workspace-workflow li').map((step) => step.attributes('data-state'))
    const buttons = () => wrapper.findAll('.workspace-workflow button')

    expect(states()).toEqual(['active', 'unavailable', 'unavailable', 'unavailable'])
    store.setSourcePoint([118.9, 32.1])
    await wrapper.vm.$nextTick()
    expect(buttons()[1]?.attributes('disabled')).toBeUndefined()

    prepareAnalysis(store)
    await selectWorkflowStep(wrapper, '缓冲区')
    expect(states()).toEqual(['complete', 'active', 'pending', 'unavailable'])

    store.job = { task_id: 'task-1' }
    await wrapper.vm.$nextTick()
    expect(states()).toEqual(['complete', 'active', 'complete', 'pending'])

    setRiskResult(store)
    await wrapper.vm.$nextTick()
    expect(states()).toEqual(['complete', 'active', 'complete', 'complete'])
  })

  it('renders only the active context and uses map plus drawer for Result', async () => {
    const { wrapper, store } = mountWorkspace()

    expect(wrapper.get('.study-area-context').attributes('style') ?? '').not.toContain('display: none')
    expect(wrapper.get('.buffer-context').attributes('style')).toContain('display: none')
    expect(wrapper.get('.analysis-context').attributes('style')).toContain('display: none')

    store.setSourcePoint([118.9, 32.1])
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '缓冲区')
    expect(wrapper.find('.study-area-context').exists()).toBe(false)
    expect(wrapper.get('.buffer-context').attributes('style') ?? '').not.toContain('display: none')
    expect(wrapper.get('.analysis-context').attributes('style')).toContain('display: none')

    prepareAnalysis(store)
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '分析')
    expect(wrapper.find('.study-area-context').exists()).toBe(false)
    expect(wrapper.get('.buffer-context').attributes('style')).toContain('display: none')
    expect(wrapper.get('.analysis-context').attributes('style') ?? '').not.toContain('display: none')

    store.poiHasSearched = true
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '结果')
    expect(wrapper.find('.workspace-context-panel').exists()).toBe(true)
    expect(wrapper.find('.workspace-context-panel').attributes('style')).toContain('display: none')
    expect(wrapper.findComponent(StudyAreaPanel).exists()).toBe(false)
    expect(wrapper.findComponent(BufferPanel).exists()).toBe(true)
    expect(wrapper.findComponent(AnalysisPanel).exists()).toBe(true)
    expect(wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(true)
    expect(wrapper.findComponent(WorkspaceResultDrawer).props('title')).toBe('POI 结果')
  })

  it('ignores a late async Study Area confirmation after workflow navigation unmounts it', async () => {
    const { wrapper, store } = mountWorkspace()
    store.setSourcePoint([118.9, 32.1])
    store.bufferResult = {
      source: { crs: 'EPSG:4326', geometry_type: 'Point', bounds: [118.9, 32.1, 118.9, 32.1] },
      buffer: {
        crs: 'EPSG:4326', distance_m: 3000, working_crs: 'EPSG:32650', area_m2: 1,
        area_km2: 0.000001, bounds: [118.8, 32, 119, 32.2],
        geometry: { type: 'Polygon', coordinates: [[[118.8, 32], [119, 32], [119, 32.2], [118.8, 32]]] },
      },
    }
    store.poiHasSearched = true
    store.poiItems = [{
      id: 'poi-1', name: '学校', type: '', typeCode: '', address: '', locationWgs84: [118.81, 32.02],
    }]
    store.job = { task_id: 'task-1' }
    setRiskResult(store)
    await wrapper.vm.$nextTick()
    await selectStudyAreaTab(wrapper, '行政区')
    const pendingInput = wrapper.findComponent(AdministrativeRegionInput)
    const state = {
      source: store.sourceGeometryWgs84,
      buffer: store.bufferResult,
      poiItems: store.poiItems,
      job: store.job,
      result: store.result,
    }
    const setSourceGeometry = vi.spyOn(store, 'setSourceGeometry')

    await selectWorkflowStep(wrapper, '缓冲区')
    expect(wrapper.findComponent(StudyAreaPanel).exists()).toBe(false)
    pendingInput.vm.$emit('confirm', { type: 'Point', coordinates: [120, 30] })
    await wrapper.vm.$nextTick()

    expect(setSourceGeometry).not.toHaveBeenCalled()
    expect(store.sourceGeometryWgs84).toBe(state.source)
    expect(store.bufferResult).toBe(state.buffer)
    expect(store.poiItems).toBe(state.poiItems)
    expect(store.job).toBe(state.job)
    expect(store.result).toBe(state.result)
  })

  it('preserves unsubmitted POI and Risk drafts across Analysis and Result navigation', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareAnalysis(store)
    store.poiHasSearched = true
    store.job = { task_id: 'task-1' }
    setRiskResult(store)
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '分析')
    const analysisPanel = wrapper.findComponent(AnalysisPanel)
    const poiInput = analysisPanel.get('input[aria-label="POI 关键词"]')
    const actions = [
      vi.spyOn(store, 'createBuffer'),
      vi.spyOn(store, 'searchPois'),
      vi.spyOn(store, 'submitRiskAnalysis'),
      vi.spyOn(store, 'setPoiKeyword'),
      vi.spyOn(store, 'setSourceGeometry'),
      vi.spyOn(store, 'setSourcePoint'),
      vi.spyOn(store, 'setBufferDistance'),
      vi.spyOn(store, 'setRiskWeights'),
      vi.spyOn(store, 'clearSelection'),
    ]
    const committedWeights = store.weights.map((item) => ({ ...item }))

    await poiInput.setValue('医院')
    await analysisPanel
      .findAll('button.analysis-tab')
      .find((item) => item.text() === '风险')!
      .trigger('click')
    const riskInput = analysisPanel
      .findComponent(RiskAnalysisPanel)
      .findAllComponents(ElInputNumber)[0]!
    riskInput.vm.$emit('update:modelValue', 35)
    await wrapper.vm.$nextTick()

    await selectWorkflowStep(wrapper, '结果')
    await selectWorkflowStep(wrapper, '分析')

    expect((poiInput.element as HTMLInputElement).value).toBe('医院')
    expect(riskInput.props('modelValue')).toBe(35)
    expect(store.poiKeyword).toBe('')
    expect(store.weights).toEqual(committedWeights)
    actions.forEach((action) => expect(action).not.toHaveBeenCalled())
  })

  it('allows map editing only in unlocked Study Area Draw and preserves committed Source', async () => {
    const { wrapper, store } = mountWorkspace()
    const map = wrapper.findComponent(MapCanvasStub)

    expect(map.props('selectionDisabled')).toBe(false)
    await selectStudyAreaTab(wrapper, '坐标')
    expect(map.props('selectionDisabled')).toBe(true)
    expect(drawingCanvasMocks.cancelDrawing).toHaveBeenCalledOnce()

    await selectStudyAreaTab(wrapper, '绘制')
    expect(map.props('selectionDisabled')).toBe(false)
    store.setSourcePoint([118.9, 32.1])
    const committedSource = store.sourceGeometryWgs84
    map.vm.$emit('drawing-mode-change', 'polygon')
    await wrapper.vm.$nextTick()
    drawingCanvasMocks.cancelDrawing.mockClear()

    await selectWorkflowStep(wrapper, '缓冲区')

    expect(map.props('selectionDisabled')).toBe(true)
    expect(drawingCanvasMocks.cancelDrawing).toHaveBeenCalledOnce()
    expect(store.sourceGeometryWgs84).toBe(committedSource)

    await selectWorkflowStep(wrapper, '研究区')
    store.polling = true
    await wrapper.vm.$nextTick()
    expect(map.props('selectionDisabled')).toBe(true)
  })

  it('revalidates the recent drawer type before applying Risk then POI fallback', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareAnalysis(store)
    store.poiHasSearched = true
    store.job = { task_id: 'task-1' }
    setRiskResult(store)
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '分析')
    const analysisPanel = wrapper.findComponent(AnalysisPanel)

    analysisPanel.vm.$emit('poi-open-result')
    await wrapper.vm.$nextTick()
    await wrapper.get('button[aria-label="关闭结果抽屉"]').trigger('click')
    store.poiHasSearched = false
    store.poiItems = []
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '结果')
    expect(wrapper.findComponent(WorkspaceResultDrawer).props('title')).toBe('风险任务 / 结果')
    expect(wrapper.findComponent(RiskResultPanel).exists()).toBe(true)

    await selectWorkflowStep(wrapper, '分析')
    store.poiHasSearched = true
    store.job = null
    store.jobStatus = null
    store.result = null
    store.taskError = null
    await wrapper.vm.$nextTick()
    await selectWorkflowStep(wrapper, '结果')
    expect(wrapper.findComponent(WorkspaceResultDrawer).props('title')).toBe('POI 结果')
    expect(wrapper.findComponent(RiskResultPanel).exists()).toBe(false)
  })

  it('switches every workflow context without invoking or changing Store business state', async () => {
    const { wrapper, store } = mountWorkspace()
    prepareAnalysis(store)
    store.poiHasSearched = true
    store.poiItems = [{
      id: 'poi-1', name: '学校', type: '', typeCode: '', address: '', locationWgs84: [118.81, 32.02],
    }]
    store.job = { task_id: 'task-1' }
    setRiskResult(store)
    await flushPromises()
    const state = {
      source: store.sourceGeometryWgs84,
      buffer: store.bufferResult,
      poiItems: store.poiItems,
      job: store.job,
      result: store.result,
      weights: store.weights,
    }
    const actions = [
      vi.spyOn(store, 'createBuffer'),
      vi.spyOn(store, 'searchPois'),
      vi.spyOn(store, 'submitRiskAnalysis'),
      vi.spyOn(store, 'setPoiKeyword'),
      vi.spyOn(store, 'setSourceGeometry'),
      vi.spyOn(store, 'setSourcePoint'),
      vi.spyOn(store, 'setBufferDistance'),
      vi.spyOn(store, 'setRiskWeights'),
      vi.spyOn(store, 'clearSelection'),
    ]

    for (const step of ['研究区', '缓冲区', '分析', '结果']) {
      await selectWorkflowStep(wrapper, step)
    }

    actions.forEach((action) => expect(action).not.toHaveBeenCalled())
    expect(store.sourceGeometryWgs84).toBe(state.source)
    expect(store.bufferResult).toBe(state.buffer)
    expect(store.poiItems).toBe(state.poiItems)
    expect(store.job).toBe(state.job)
    expect(store.result).toBe(state.result)
    expect(store.weights).toBe(state.weights)
  })
})

describe('WorkspaceView recovery and background Risk completion', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
  })

  it('derives the initial step once from restored Source and Buffer prerequisites', async () => {
    const scenarios: Array<{
      name: string
      expected: string
      prepare: (store: ReturnType<typeof useAnalysisStore>) => void
    }> = [
      { name: 'empty', expected: '研究区', prepare: () => undefined },
      {
        name: 'Source',
        expected: '缓冲区',
        prepare: (store) => store.setSourcePoint([118.9, 32.1]),
      },
      {
        name: 'Buffer',
        expected: '分析',
        prepare: (store) => {
          store.setSourcePoint([118.9, 32.1])
          store.bufferResult = bufferResult()
        },
      },
    ]

    for (const scenario of scenarios) {
      const { wrapper, store } = mountWorkspace((candidate) => {
        scenario.prepare(candidate)
        vi.spyOn(candidate, 'restoreRiskAnalysis').mockResolvedValue(undefined)
      })
      await flushPromises()

      expect(activeWorkflowLabel(wrapper), scenario.name).toBe(scenario.expected)
      store.bufferResult = bufferResult()
      await wrapper.vm.$nextTick()
      expect(activeWorkflowLabel(wrapper), `${scenario.name} once-only`).toBe(scenario.expected)
      wrapper.unmount()
    }
  })

  it('does not skip prerequisites for restored Risk tasks and keeps their viewing entries available', async () => {
    const withSource = mountWorkspace((store) => {
      store.setSourcePoint([118.9, 32.1])
      setRiskJobStatus(store, 'FAILED', 'risk-with-source')
      vi.spyOn(store, 'restoreRiskAnalysis').mockResolvedValue(undefined)
    })
    await flushPromises()

    expect(activeWorkflowLabel(withSource.wrapper)).toBe('缓冲区')
    await selectWorkflowStep(withSource.wrapper, '结果')
    expect(withSource.wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(true)
    expect(withSource.wrapper.findComponent(WorkspaceResultDrawer).props('title')).toBe('风险任务 / 结果')
    withSource.wrapper.unmount()

    const withoutSource = mountWorkspace((store) => {
      setRiskJobStatus(store, 'FAILED', 'risk-without-source')
      vi.spyOn(store, 'restoreRiskAnalysis').mockResolvedValue(undefined)
    })
    await flushPromises()

    expect(activeWorkflowLabel(withoutSource.wrapper)).toBe('研究区')
    const recoveryEntry = withoutSource.wrapper
      .findAllComponents(ElButton)
      .find((button) => button.text().includes('查看任务/结果'))
    if (!recoveryEntry) throw new Error('missing restored Risk recovery entry')
    await recoveryEntry.trigger('click')
    expect(withoutSource.wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(true)
    withoutSource.wrapper.unmount()
  })

  it('does not let late recovery override manual or Source-driven workflow navigation', async () => {
    const manualRecovery = deferred<void>()
    const manual = mountWorkspace((store) => {
      store.setSourcePoint([118.9, 32.1])
      vi.spyOn(store, 'restoreRiskAnalysis').mockImplementation(() => manualRecovery.promise)
    })
    await selectWorkflowStep(manual.wrapper, '缓冲区')
    manual.store.bufferResult = bufferResult()
    manualRecovery.resolve()
    await flushPromises()
    expect(activeWorkflowLabel(manual.wrapper)).toBe('缓冲区')
    manual.wrapper.unmount()

    const sourceRecovery = deferred<void>()
    const sourceDriven = mountWorkspace((store) => {
      vi.spyOn(store, 'restoreRiskAnalysis').mockImplementation(() => sourceRecovery.promise)
    })
    sourceDriven.wrapper.findComponent(MapCanvasStub).vm.$emit('select-point', [118.9, 32.1])
    await flushPromises()
    expect(activeWorkflowLabel(sourceDriven.wrapper)).toBe('缓冲区')
    sourceDriven.store.bufferResult = bufferResult()
    sourceRecovery.resolve()
    await flushPromises()
    expect(activeWorkflowLabel(sourceDriven.wrapper)).toBe('缓冲区')
    sourceDriven.wrapper.unmount()
  })

  it('keeps the active Study method when recovery finishes after foreground interaction', async () => {
    const restoration = deferred<void>()
    const { wrapper, store } = mountWorkspace((candidate) => {
      vi.spyOn(candidate, 'restoreRiskAnalysis').mockImplementation(() => restoration.promise)
    })

    await selectStudyAreaTab(wrapper, '坐标')
    store.setSourcePoint([118.9, 32.1])
    store.bufferResult = bufferResult()
    restoration.resolve()
    await flushPromises()

    expect(activeWorkflowLabel(wrapper)).toBe('研究区')
    expect(wrapper.get('button.study-area-tab.active').text()).toBe('坐标')
    expect(wrapper.find('input[aria-label="研究点经度"]').exists()).toBe(true)
  })

  it('keeps the result drawer collapsed after remount with restored state', async () => {
    const first = mountWorkspace((store) => {
      store.setSourcePoint([118.9, 32.1])
      store.bufferResult = bufferResult()
      setRiskJobStatus(store, 'RUNNING')
      vi.spyOn(store, 'restoreRiskAnalysis').mockResolvedValue(undefined)
    })
    await flushPromises()
    first.wrapper.findComponent(AnalysisPanel).vm.$emit('risk-open-result')
    await first.wrapper.vm.$nextTick()
    expect(first.wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(true)
    first.wrapper.unmount()

    const remounted = mountWorkspace((store) => {
      vi.spyOn(store, 'restoreRiskAnalysis').mockResolvedValue(undefined)
    }, first.pinia)
    await flushPromises()
    expect(activeWorkflowLabel(remounted.wrapper)).toBe('分析')
    expect(remounted.wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(false)
    remounted.wrapper.unmount()
  })

  it.each([
    ['SUCCEEDED', 'success'],
    ['FAILED', 'error'],
  ] as const)('notifies for a background active-to-%s transition without changing the UI', async (status, method) => {
    const { wrapper, store } = mountWorkspace((candidate) => {
      candidate.setSourcePoint([118.9, 32.1])
      candidate.bufferResult = bufferResult()
      vi.spyOn(candidate, 'restoreRiskAnalysis').mockResolvedValue(undefined)
    })
    await flushPromises()
    const panel = wrapper.findComponent(AnalysisPanel)

    setRiskJobStatus(store, 'RUNNING')
    await wrapper.vm.$nextTick()
    setRiskJobStatus(store, status)
    await wrapper.vm.$nextTick()

    expect(ElMessage[method]).toHaveBeenCalledOnce()
    expect(activeWorkflowLabel(wrapper)).toBe('分析')
    expect(panel.props('activeTab')).toBe('poi')
    expect(wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(false)
    expect(wrapper.findComponent(WorkspaceResultDrawer).props('title')).toBe('POI 结果')
  })

  it('updates a foreground Risk drawer without a duplicate terminal message', async () => {
    const { wrapper, store } = mountWorkspace((candidate) => {
      candidate.setSourcePoint([118.9, 32.1])
      candidate.bufferResult = bufferResult()
      vi.spyOn(candidate, 'restoreRiskAnalysis').mockResolvedValue(undefined)
    })
    await flushPromises()
    setRiskJobStatus(store, 'RUNNING')
    await wrapper.vm.$nextTick()
    const panel = wrapper.findComponent(AnalysisPanel)
    const riskTab = panel.findAll('button.analysis-tab').find((button) => button.text() === '风险')
    if (!riskTab) throw new Error('missing Risk tab')
    await riskTab.trigger('click')
    panel.vm.$emit('risk-open-result')
    await wrapper.vm.$nextTick()

    setRiskJobStatus(store, 'FAILED')
    await wrapper.vm.$nextTick()

    expect(ElMessage.success).not.toHaveBeenCalled()
    expect(ElMessage.error).not.toHaveBeenCalled()
    expect(activeWorkflowLabel(wrapper)).toBe('分析')
    expect(panel.props('activeTab')).toBe('risk')
    expect(wrapper.findComponent(WorkspaceResultDrawer).props('open')).toBe(true)
    expect(wrapper.findComponent(WorkspaceResultDrawer).props('title')).toBe('风险任务 / 结果')
  })

  it('does not notify for an initially restored terminal task', async () => {
    const { wrapper } = mountWorkspace((store) => {
      setRiskJobStatus(store, 'FAILED', 'restored-terminal')
      vi.spyOn(store, 'restoreRiskAnalysis').mockResolvedValue(undefined)
    })
    await flushPromises()

    expect(ElMessage.success).not.toHaveBeenCalled()
    expect(ElMessage.error).not.toHaveBeenCalled()
    expect(activeWorkflowLabel(wrapper)).toBe('研究区')
  })
})
