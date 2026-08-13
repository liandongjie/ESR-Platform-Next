import ElementPlus, { ElButton, ElSelect } from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, onUnmounted } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AdministrativeRegionInput from '@/components/map/AdministrativeRegionInput.vue'
import ShapefileInput from '@/components/map/ShapefileInput.vue'
import StudyAreaCoordinateInput from '@/components/workspace/StudyAreaCoordinateInput.vue'
import StudyAreaDrawInput from '@/components/workspace/StudyAreaDrawInput.vue'
import StudyAreaPanel from '@/components/workspace/StudyAreaPanel.vue'
import StudyAreaSearchInput from '@/components/workspace/StudyAreaSearchInput.vue'
import type { SourceGeometry } from '@/types/analysisArea'

const apiMocks = vi.hoisted(() => ({
  list: vi.fn(),
  boundaries: vi.fn(),
  normalize: vi.fn(),
  importShapefile: vi.fn(),
}))

vi.mock('@/map/amapDistrict', () => ({
  listAmapAdministrativeRegions: apiMocks.list,
  getAmapAdministrativeBoundaries: apiMocks.boundaries,
}))
vi.mock('@/api/analysisAreas', () => ({
  normalizeAdministrativeBoundaries: apiMocks.normalize,
  importShapefile: apiMocks.importShapefile,
}))

const administrativeUnmounted = vi.fn()
const shapefileUnmounted = vi.fn()

function inputStub(name: string, unmounted?: () => void) {
  return defineComponent({
    name,
    props: { disabled: Boolean },
    emits: ['confirm', 'start-drawing', 'cancel-drawing'],
    setup() {
      if (unmounted) onUnmounted(unmounted)
      return () => h('div', { class: `${name}-stub` })
    },
  })
}

const DrawStub = inputStub('StudyAreaDrawInput')
const CoordinateStub = inputStub('StudyAreaCoordinateInput')
const SearchStub = inputStub('StudyAreaSearchInput')
const AdministrativeStub = inputStub('AdministrativeRegionInput', administrativeUnmounted)
const ShapefileStub = inputStub('ShapefileInput', shapefileUnmounted)

function mountPanel(sourceGeometry: SourceGeometry | null = null, disabled = false) {
  return mount(StudyAreaPanel, {
    props: {
      disabled,
      sourceGeometry,
      activeDrawingMode: null,
      drawingError: null,
    },
    global: {
      plugins: [ElementPlus],
      stubs: {
        StudyAreaDrawInput: DrawStub,
        StudyAreaCoordinateInput: CoordinateStub,
        StudyAreaSearchInput: SearchStub,
        AdministrativeRegionInput: AdministrativeStub,
        ShapefileInput: ShapefileStub,
      },
    },
  })
}

function mountPanelWithRealAsyncInputs() {
  return mount(StudyAreaPanel, {
    props: {
      disabled: false,
      sourceGeometry: null,
      activeDrawingMode: null,
      drawingError: null,
    },
    global: {
      plugins: [ElementPlus],
      stubs: {
        StudyAreaDrawInput: DrawStub,
        StudyAreaCoordinateInput: CoordinateStub,
        StudyAreaSearchInput: SearchStub,
      },
    },
  })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

function tabButton(wrapper: ReturnType<typeof mountPanel>, label: string) {
  const button = wrapper.findAll('button.study-area-tab').find((item) => item.text() === label)
  if (!button) throw new Error(`missing ${label} tab`)
  return button
}

function clearButton(wrapper: ReturnType<typeof mountPanel>) {
  const button = wrapper.findAllComponents(ElButton).find((item) => item.text() === '清除研究区')
  if (!button) throw new Error('missing clear study area button')
  return button
}

beforeEach(() => {
  administrativeUnmounted.mockReset()
  shapefileUnmounted.mockReset()
  apiMocks.list.mockReset()
  apiMocks.boundaries.mockReset()
  apiMocks.normalize.mockReset()
  apiMocks.importShapefile.mockReset()
})

describe('StudyAreaPanel input modes', () => {
  it('renders five ordered tabs and mounts only the default drawing input', () => {
    const wrapper = mountPanel()

    expect(wrapper.findAll('button.study-area-tab').map((item) => item.text())).toEqual([
      '绘制',
      '坐标',
      '搜索',
      '行政区',
      '文件',
    ])
    expect(wrapper.findComponent(StudyAreaDrawInput).exists()).toBe(true)
    expect(wrapper.findComponent(StudyAreaCoordinateInput).exists()).toBe(false)
    expect(wrapper.findComponent(StudyAreaSearchInput).exists()).toBe(false)
    expect(wrapper.findComponent(AdministrativeRegionInput).exists()).toBe(false)
    expect(wrapper.findComponent(ShapefileInput).exists()).toBe(false)
  })

  it('cancels drawing when leaving its tab without emitting geometry', async () => {
    const geometry: SourceGeometry = { type: 'Point', coordinates: [118.9, 32.1] }
    const wrapper = mountPanel(geometry)

    await tabButton(wrapper, '坐标').trigger('click')

    expect(wrapper.emitted('cancel-drawing')).toHaveLength(1)
    expect(wrapper.emitted('confirm')).toBeUndefined()
    expect(wrapper.props('sourceGeometry')).toEqual(geometry)
    expect(wrapper.findComponent(StudyAreaDrawInput).exists()).toBe(false)
    expect(wrapper.findComponent(StudyAreaCoordinateInput).exists()).toBe(true)
  })

  it('mounts administrative and file inputs on demand and unmounts each on exit', async () => {
    const wrapper = mountPanel()

    await tabButton(wrapper, '行政区').trigger('click')
    expect(wrapper.findComponent(AdministrativeRegionInput).exists()).toBe(true)
    expect(wrapper.findComponent(ShapefileInput).exists()).toBe(false)

    await tabButton(wrapper, '文件').trigger('click')
    expect(administrativeUnmounted).toHaveBeenCalledOnce()
    expect(wrapper.findComponent(AdministrativeRegionInput).exists()).toBe(false)
    expect(wrapper.findComponent(ShapefileInput).exists()).toBe(true)

    await tabButton(wrapper, '搜索').trigger('click')
    expect(shapefileUnmounted).toHaveBeenCalledOnce()
    expect(wrapper.findComponent(StudyAreaSearchInput).exists()).toBe(true)
  })

  it('lets administrative unmount invalidate an in-flight boundary response', async () => {
    const beijing = { adcode: '110000', name: '北京市', level: 'province' as const }
    const boundaryRequest = deferred<Array<Array<[number, number]>>>()
    apiMocks.list.mockImplementation((parent?: { adcode: string }) =>
      Promise.resolve(parent ? [] : [beijing]),
    )
    apiMocks.boundaries.mockReturnValue(boundaryRequest.promise)
    const wrapper = mountPanelWithRealAsyncInputs()

    await tabButton(wrapper, '行政区').trigger('click')
    await flushPromises()
    wrapper.findComponent(ElSelect).vm.$emit('update:modelValue', beijing.adcode)
    await flushPromises()
    const confirm = wrapper
      .findAllComponents(ElButton)
      .find((item) => item.text().includes('确认行政区'))
    if (!confirm) throw new Error('missing administrative confirm button')
    await confirm.trigger('click')
    await tabButton(wrapper, '搜索').trigger('click')
    boundaryRequest.resolve([[[118.8, 32], [118.9, 32], [118.8, 32]]])
    await flushPromises()

    expect(apiMocks.normalize).not.toHaveBeenCalled()
    expect(wrapper.emitted('confirm')).toBeUndefined()
  })

  it('lets Shapefile unmount invalidate an in-flight import response', async () => {
    const importRequest = deferred<{
      crs: 'EPSG:4326'
      source_crs: string
      feature_count: number
      coordinate_count: number
      geometry: SourceGeometry
    }>()
    apiMocks.importShapefile.mockReturnValue(importRequest.promise)
    const wrapper = mountPanelWithRealAsyncInputs()

    await tabButton(wrapper, '文件').trigger('click')
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [new File(['zip'], 'study.zip', { type: 'application/zip' })],
    })
    await input.trigger('change')
    await tabButton(wrapper, '搜索').trigger('click')
    importRequest.resolve({
      crs: 'EPSG:4326',
      source_crs: 'EPSG:4326',
      feature_count: 1,
      coordinate_count: 1,
      geometry: { type: 'Point', coordinates: [118.9, 32.1] },
    })
    await flushPromises()

    expect(wrapper.emitted('confirm')).toBeUndefined()
  })

  it.each([
    ['坐标', StudyAreaCoordinateInput],
    ['搜索', StudyAreaSearchInput],
    ['行政区', AdministrativeRegionInput],
    ['文件', ShapefileInput],
  ] as const)('forwards confirmed WGS84 geometry from %s', async (label, component) => {
    const wrapper = mountPanel()
    const geometry: SourceGeometry = { type: 'Point', coordinates: [118.9, 32.1] }

    await tabButton(wrapper, label).trigger('click')
    wrapper.findComponent(component).vm.$emit('confirm', geometry)
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('confirm')).toEqual([[geometry]])
  })
})

describe('StudyAreaPanel committed geometry summary', () => {
  it('always shows the summary and disables clear without committed geometry', () => {
    const wrapper = mountPanel()

    expect(wrapper.get('.study-area-summary').text()).toContain('当前研究区')
    expect(wrapper.get('.study-area-summary').text()).toContain('尚未确认研究区')
    expect(clearButton(wrapper).attributes('disabled')).toBeDefined()
  })

  it.each([
    [{ type: 'Point', coordinates: [118.9, 32.1] }, '118.900000, 32.100000'],
    [
      { type: 'LineString', coordinates: [[118.8, 32], [118.9, 32.1]] },
      'LineString · 2 个顶点',
    ],
    [
      {
        type: 'Polygon',
        coordinates: [
          [[118.8, 32], [118.9, 32], [118.9, 32.1], [118.8, 32]],
          [[118.83, 32.03], [118.85, 32.03], [118.85, 32.05], [118.83, 32.03]],
        ],
      },
      'Polygon · 3 个外环顶点 · 1 个孔洞',
    ],
    [
      {
        type: 'MultiPolygon',
        coordinates: [
          [[[118.8, 32], [118.9, 32], [118.9, 32.1], [118.8, 32]]],
          [[[119, 32.2], [119.1, 32.2], [119.1, 32.3], [119, 32.2]]],
        ],
      },
      'MultiPolygon · 2 个面 · 0 个孔洞',
    ],
  ] as const)('renders the existing geometry summary rules', (geometry, expected) => {
    const wrapper = mountPanel(geometry as SourceGeometry)
    expect(wrapper.get('.study-area-summary').text()).toContain(expected)
  })

  it('emits only clear and disables it while locked', async () => {
    const geometry: SourceGeometry = { type: 'Point', coordinates: [118.9, 32.1] }
    const wrapper = mountPanel(geometry)

    await clearButton(wrapper).trigger('click')
    expect(wrapper.emitted('clear')).toHaveLength(1)
    expect(wrapper.emitted('cancel-drawing')).toBeUndefined()
    await wrapper.setProps({ disabled: true })
    expect(clearButton(wrapper).attributes('disabled')).toBeDefined()
  })

  it('describes the committed geometry coordinate boundary', () => {
    const wrapper = mountPanel({ type: 'Point', coordinates: [118.9, 32.1] })

    expect(wrapper.get('.study-area-summary').text()).toContain(
      '业务坐标系：WGS84 / EPSG:4326；地图显示坐标转换由适配层处理。',
    )
  })
})
