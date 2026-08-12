import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ post: vi.fn() }))

vi.mock('@/api/http', () => ({ http: { post: mocks.post } }))

const boundary = [
  [118.8, 32],
  [118.9, 32],
  [118.9, 32.1],
  [118.8, 32],
] as Array<[number, number]>

describe('analysis area normalization API', () => {
  beforeEach(() => mocks.post.mockReset())

  it('posts all boundaries and returns a structurally validated polygon', async () => {
    mocks.post.mockResolvedValue({
      data: {
        crs: 'EPSG:4326',
        geometry: { type: 'Polygon', coordinates: [boundary] },
        input_boundary_count: 2,
        output_polygon_count: 1,
      },
    })
    const { normalizeAdministrativeBoundaries } = await import('@/api/analysisAreas')
    const boundaries = [boundary, boundary]

    await expect(normalizeAdministrativeBoundaries({ boundaries })).resolves.toMatchObject({
      geometry: { type: 'Polygon' },
    })
    expect(mocks.post).toHaveBeenCalledWith('/analysis-areas/normalize-boundaries', {
      boundaries,
    })
  })

  it.each([
    [{ crs: 'GCJ-02' }, 'EPSG:4326'],
    [
      {
        crs: 'EPSG:4326',
        geometry: { type: 'Point', coordinates: [118.8, 32] },
        input_boundary_count: 1,
        output_polygon_count: 1,
      },
      'Polygon',
    ],
    [
      {
        crs: 'EPSG:4326',
        geometry: { type: 'Polygon', coordinates: [[[118.8, 32]]] },
        input_boundary_count: 1,
        output_polygon_count: 1,
      },
      'ring',
    ],
  ])('rejects malformed normalization responses', async (data, message) => {
    mocks.post.mockResolvedValue({ data })
    const { normalizeAdministrativeBoundaries } = await import('@/api/analysisAreas')

    await expect(normalizeAdministrativeBoundaries({ boundaries: [boundary] })).rejects.toThrow(
      message,
    )
  })

  it('uploads one ZIP and validates the imported SourceGeometry at runtime', async () => {
    const geometry = { type: 'Polygon', coordinates: [boundary] }
    mocks.post.mockResolvedValue({
      data: {
        crs: 'EPSG:4326',
        source_crs: 'EPSG:3857',
        feature_count: 2,
        coordinate_count: 4,
        geometry,
      },
    })
    const { importShapefile } = await import('@/api/analysisAreas')
    const file = new File(['zip'], 'study.zip', { type: 'application/zip' })

    await expect(importShapefile(file)).resolves.toMatchObject({ geometry })
    expect(mocks.post).toHaveBeenCalledWith(
      '/analysis-areas/import-shapefile',
      expect.any(FormData),
      { headers: { 'Content-Type': undefined } },
    )
    const form = mocks.post.mock.calls[0]?.[1] as FormData
    expect(form.get('file')).toBe(file)
  })

  it.each([
    [{ crs: 'GCJ-02' }, 'EPSG:4326'],
    [
      {
        crs: 'EPSG:4326',
        source_crs: 'EPSG:4326',
        feature_count: 1,
        coordinate_count: 1,
        geometry: { type: 'Point', coordinates: [999, 32] },
      },
      'WGS84',
    ],
    [
      {
        crs: 'EPSG:4326',
        source_crs: '',
        feature_count: 0,
        coordinate_count: 0,
        geometry: { type: 'Point', coordinates: [118.9, 32.1] },
      },
      'metadata',
    ],
  ])('rejects malformed Shapefile import responses', async (data, message) => {
    mocks.post.mockResolvedValue({ data })
    const { importShapefile } = await import('@/api/analysisAreas')

    await expect(importShapefile(new File(['zip'], 'study.zip'))).rejects.toThrow(message)
  })
})
