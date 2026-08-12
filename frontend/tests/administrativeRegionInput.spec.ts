import ElementPlus, { ElButton, ElSelect } from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AdministrativeRegionInput from '@/components/map/AdministrativeRegionInput.vue'

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  boundaries: vi.fn(),
  normalize: vi.fn(),
}))

vi.mock('@/map/amapDistrict', () => ({
  listAmapAdministrativeRegions: mocks.list,
  getAmapAdministrativeBoundaries: mocks.boundaries,
}))
vi.mock('@/api/analysisAreas', () => ({
  normalizeAdministrativeBoundaries: mocks.normalize,
}))

const jiangsu = { adcode: '320000', name: '江苏省', level: 'province' as const }
const beijing = { adcode: '110000', name: '北京市', level: 'province' as const }
const nanjing = { adcode: '320100', name: '南京市', level: 'city' as const }
const gulou = { adcode: '320106', name: '鼓楼区', level: 'district' as const }
const directCounty = { adcode: '469001', name: '五指山市', level: 'district' as const }
const boundary = [
  [118.8, 32],
  [118.9, 32],
  [118.9, 32.1],
  [118.8, 32],
] as Array<[number, number]>
const geometry = { type: 'Polygon' as const, coordinates: [boundary] }

function mountInput(disabled = false) {
  return mount(AdministrativeRegionInput, {
    props: { disabled },
    global: { plugins: [ElementPlus] },
  })
}

function confirmButton(wrapper: ReturnType<typeof mountInput>) {
  const button = wrapper
    .findAllComponents(ElButton)
    .find((item) => item.text().includes('确认行政区'))
  if (!button) throw new Error('missing administrative region confirm button')
  return button
}

async function selectAt(wrapper: ReturnType<typeof mountInput>, index: number, adcode: string) {
  wrapper.findAllComponents(ElSelect)[index]!.vm.$emit('update:modelValue', adcode)
  await flushPromises()
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

describe('AdministrativeRegionInput', () => {
  beforeEach(() => {
    mocks.list.mockReset()
    mocks.boundaries.mockReset()
    mocks.normalize.mockReset()
    mocks.list.mockImplementation((parent?: { adcode: string }) => {
      if (!parent) return Promise.resolve([jiangsu, beijing])
      if (parent.adcode === jiangsu.adcode) return Promise.resolve([nanjing])
      if (parent.adcode === nanjing.adcode) return Promise.resolve([gulou])
      return Promise.resolve([])
    })
    mocks.boundaries.mockResolvedValue([boundary])
    mocks.normalize.mockResolvedValue({
      crs: 'EPSG:4326',
      geometry,
      input_boundary_count: 1,
      output_polygon_count: 1,
    })
  })

  it('follows provider levels and allows city confirmation without forcing a district', async () => {
    const wrapper = mountInput()
    await flushPromises()

    await selectAt(wrapper, 0, jiangsu.adcode)
    expect(confirmButton(wrapper).props('disabled')).toBe(true)
    expect(wrapper.text()).toContain('仅支持浏览')
    expect(mocks.list).toHaveBeenLastCalledWith(jiangsu)

    await selectAt(wrapper, 1, nanjing.adcode)
    expect(wrapper.findAllComponents(ElSelect)).toHaveLength(3)
    expect(confirmButton(wrapper).props('disabled')).toBe(false)

    await confirmButton(wrapper).trigger('click')
    await flushPromises()

    expect(mocks.boundaries).toHaveBeenCalledWith(nanjing)
    expect(mocks.normalize).toHaveBeenCalledWith({ boundaries: [boundary] })
    expect(wrapper.emitted('confirm')).toEqual([[geometry]])
  })

  it('does not invent a city between a province and a provider district child', async () => {
    mocks.list.mockImplementation((parent?: { adcode: string }) => {
      if (!parent) return Promise.resolve([jiangsu])
      return Promise.resolve(parent.adcode === jiangsu.adcode ? [directCounty] : [])
    })
    const wrapper = mountInput()
    await flushPromises()

    await selectAt(wrapper, 0, jiangsu.adcode)
    await selectAt(wrapper, 1, directCounty.adcode)

    expect(wrapper.findAllComponents(ElSelect)).toHaveLength(2)
    expect(confirmButton(wrapper).props('disabled')).toBe(false)
    await confirmButton(wrapper).trigger('click')
    await flushPromises()
    expect(mocks.boundaries).toHaveBeenCalledWith(directCounty)
  })

  it('allows a municipality to be confirmed while exposing its real children', async () => {
    mocks.list.mockImplementation((parent?: { adcode: string }) =>
      Promise.resolve(parent ? [gulou] : [beijing]),
    )
    const wrapper = mountInput()
    await flushPromises()

    await selectAt(wrapper, 0, beijing.adcode)

    expect(wrapper.findAllComponents(ElSelect)).toHaveLength(2)
    expect(confirmButton(wrapper).props('disabled')).toBe(false)
    await confirmButton(wrapper).trigger('click')
    await flushPromises()
    expect(mocks.boundaries).toHaveBeenCalledWith(beijing)
  })

  it('ignores an in-flight boundary result after analysis becomes locked', async () => {
    const pending = deferred<Array<Array<[number, number]>>>()
    mocks.boundaries.mockReturnValueOnce(pending.promise)
    const wrapper = mountInput()
    await flushPromises()
    await selectAt(wrapper, 0, beijing.adcode)

    await confirmButton(wrapper).trigger('click')
    await wrapper.setProps({ disabled: true })
    pending.resolve([boundary])
    await flushPromises()

    expect(mocks.normalize).not.toHaveBeenCalled()
    expect(wrapper.emitted('confirm')).toBeUndefined()
    expect(confirmButton(wrapper).props('disabled')).toBe(true)
  })

  it('reloads the root after a locked in-flight list response is discarded', async () => {
    const pending = deferred<typeof jiangsu[]>()
    mocks.list.mockReturnValueOnce(pending.promise).mockResolvedValueOnce([jiangsu])
    const wrapper = mountInput()
    await wrapper.vm.$nextTick()

    await wrapper.setProps({ disabled: true })
    pending.resolve([beijing])
    await flushPromises()
    expect(wrapper.findAllComponents(ElSelect)).toHaveLength(0)

    await wrapper.setProps({ disabled: false })
    await flushPromises()
    expect(mocks.list).toHaveBeenCalledTimes(2)
    wrapper.findComponent(ElSelect).vm.$emit('update:modelValue', jiangsu.adcode)
    await flushPromises()
    expect(mocks.list).toHaveBeenLastCalledWith(jiangsu)
  })

  it('ignores stale child results and emits nothing when normalization fails', async () => {
    const oldChildren = deferred<typeof nanjing[]>()
    mocks.list.mockImplementation((parent?: { adcode: string }) => {
      if (!parent) return Promise.resolve([jiangsu, beijing])
      if (parent.adcode === jiangsu.adcode) return oldChildren.promise
      return Promise.resolve([])
    })
    const wrapper = mountInput()
    await flushPromises()

    wrapper.findComponent(ElSelect).vm.$emit('update:modelValue', jiangsu.adcode)
    await wrapper.vm.$nextTick()
    wrapper.findComponent(ElSelect).vm.$emit('update:modelValue', beijing.adcode)
    await flushPromises()
    oldChildren.resolve([nanjing])
    await flushPromises()
    expect(wrapper.text()).not.toContain('南京市')

    mocks.normalize.mockRejectedValueOnce(new Error('normalization failed'))
    await confirmButton(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('normalization failed')
    expect(wrapper.emitted('confirm')).toBeUndefined()
  })

  it('ignores a stale normalization response after the selected path changes', async () => {
    const pending = deferred<{
      crs: 'EPSG:4326'
      geometry: typeof geometry
      input_boundary_count: number
      output_polygon_count: number
    }>()
    mocks.normalize.mockReturnValueOnce(pending.promise)
    const wrapper = mountInput()
    await flushPromises()
    await selectAt(wrapper, 0, beijing.adcode)

    await confirmButton(wrapper).trigger('click')
    await flushPromises()
    await selectAt(wrapper, 0, jiangsu.adcode)
    pending.resolve({
      crs: 'EPSG:4326',
      geometry,
      input_boundary_count: 1,
      output_polygon_count: 1,
    })
    await flushPromises()

    expect(wrapper.emitted('confirm')).toBeUndefined()
  })
})
