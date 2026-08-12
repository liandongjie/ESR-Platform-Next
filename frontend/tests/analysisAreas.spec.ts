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
})
