import ElementPlus from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ShapefileInput from '@/components/map/ShapefileInput.vue'

const mocks = vi.hoisted(() => ({ importShapefile: vi.fn() }))

vi.mock('@/api/analysisAreas', () => ({ importShapefile: mocks.importShapefile }))

const geometry = { type: 'Point' as const, coordinates: [118.9, 32.1] as [number, number] }

function mountInput(disabled = false) {
  return mount(ShapefileInput, {
    props: { disabled },
    global: { plugins: [ElementPlus] },
  })
}

async function selectFile(wrapper: ReturnType<typeof mountInput>, file: File) {
  const input = wrapper.get('input[type="file"]')
  Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
  await input.trigger('change')
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

describe('ShapefileInput', () => {
  beforeEach(() => mocks.importShapefile.mockReset())

  it('uploads the selected ZIP and emits only the validated geometry', async () => {
    mocks.importShapefile.mockResolvedValue({
      crs: 'EPSG:4326',
      source_crs: 'EPSG:3857',
      feature_count: 1,
      coordinate_count: 1,
      geometry,
    })
    const wrapper = mountInput()
    const file = new File(['zip'], 'study.zip', { type: 'application/zip' })

    await selectFile(wrapper, file)
    await flushPromises()

    expect(mocks.importShapefile).toHaveBeenCalledWith(file)
    expect(wrapper.emitted('confirm')).toEqual([[geometry]])
    expect(JSON.stringify(wrapper.emitted())).not.toContain('study.zip')
  })

  it('uses Element Plus Upload without submitting files itself', async () => {
    mocks.importShapefile.mockResolvedValue({
      crs: 'EPSG:4326',
      source_crs: 'EPSG:4326',
      feature_count: 1,
      coordinate_count: 1,
      geometry,
    })
    const wrapper = mountInput()
    const input = wrapper.get('input[type="file"]')

    expect(wrapper.find('.el-upload').exists()).toBe(true)
    expect(wrapper.get('.el-upload').attributes('action')).toBeUndefined()
    expect(input.attributes('accept')).toBe('.zip,application/zip')
    expect(wrapper.text()).toContain('选择 ZIP 文件')

    await selectFile(wrapper, new File(['zip'], 'study.zip', { type: 'application/zip' }))
    await flushPromises()

    expect(mocks.importShapefile).toHaveBeenCalledOnce()
    expect(wrapper.find('.el-upload-list__item').exists()).toBe(false)
  })

  it('allows selecting the same ZIP again after an import finishes', async () => {
    mocks.importShapefile.mockResolvedValue({
      crs: 'EPSG:4326',
      source_crs: 'EPSG:4326',
      feature_count: 1,
      coordinate_count: 1,
      geometry,
    })
    const wrapper = mountInput()
    const file = new File(['zip'], 'study.zip', { type: 'application/zip' })

    await selectFile(wrapper, file)
    await flushPromises()
    await selectFile(wrapper, file)
    await flushPromises()

    expect(mocks.importShapefile).toHaveBeenCalledTimes(2)
    expect(wrapper.emitted('confirm')).toEqual([[geometry], [geometry]])
  })

  it('shows API errors and emits nothing when import fails', async () => {
    mocks.importShapefile.mockRejectedValueOnce(new Error('invalid CRS'))
    const wrapper = mountInput()

    await selectFile(wrapper, new File(['zip'], 'study.zip'))
    await flushPromises()

    expect(wrapper.text()).toContain('invalid CRS')
    expect(wrapper.emitted('confirm')).toBeUndefined()
  })

  it('rejects non-ZIP files before calling the API', async () => {
    const wrapper = mountInput()

    await selectFile(wrapper, new File(['shape'], 'study.shp'))

    expect(mocks.importShapefile).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('ZIP')
  })

  it('blocks interaction while disabled', async () => {
    const wrapper = mountInput(true)

    expect(wrapper.get('input[type="file"]').attributes('disabled')).toBeDefined()
    await selectFile(wrapper, new File(['zip'], 'study.zip'))

    expect(mocks.importShapefile).not.toHaveBeenCalled()
  })

  it('ignores an in-flight response after analysis becomes locked', async () => {
    const pending = deferred<{
      crs: 'EPSG:4326'
      source_crs: string
      feature_count: number
      coordinate_count: number
      geometry: typeof geometry
    }>()
    mocks.importShapefile.mockReturnValue(pending.promise)
    const wrapper = mountInput()

    await selectFile(wrapper, new File(['zip'], 'study.zip'))
    await wrapper.setProps({ disabled: true })
    pending.resolve({
      crs: 'EPSG:4326',
      source_crs: 'EPSG:4326',
      feature_count: 1,
      coordinate_count: 1,
      geometry,
    })
    await flushPromises()

    expect(wrapper.emitted('confirm')).toBeUndefined()
    expect(wrapper.get('input[type="file"]').attributes('disabled')).toBeDefined()
  })
})
