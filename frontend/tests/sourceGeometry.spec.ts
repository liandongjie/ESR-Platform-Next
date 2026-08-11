import { describe, expect, it } from 'vitest'

import { parseSourceGeometry } from '@/validation/sourceGeometry'

describe('parseSourceGeometry', () => {
  it.each([
    { type: 'Point', coordinates: [118.9, 32.1] },
    {
      type: 'LineString',
      coordinates: [
        [118.9, 32.1],
        [118.91, 32.11],
      ],
    },
    {
      type: 'Polygon',
      coordinates: [
        [
          [118.9, 32.1],
          [118.91, 32.1],
          [118.91, 32.11],
          [118.9, 32.1],
        ],
      ],
    },
  ])('accepts and deep-clones $type', (geometry) => {
    const parsed = parseSourceGeometry(geometry)

    expect(parsed).toEqual(geometry)
    expect(parsed).not.toBe(geometry)
    expect(parsed.coordinates).not.toBe(geometry.coordinates)
  })

  it.each([
    [{ type: 'Point', coordinates: [181, 32.1] }, 'WGS84'],
    [{ type: 'Point', coordinates: [118.9, Number.NaN] }, 'WGS84'],
    [{ type: 'LineString', coordinates: [[118.9, 32.1]] }, '两个不同点'],
    [
      {
        type: 'LineString',
        coordinates: [
          [118.9, 32.1],
          [118.9, 32.1],
        ],
      },
      '两个不同点',
    ],
    [
      {
        type: 'Polygon',
        coordinates: [
          [
            [118.9, 32.1],
            [118.91, 32.1],
            [118.91, 32.11],
          ],
        ],
      },
      '闭合',
    ],
    [
      {
        type: 'Polygon',
        coordinates: [
          [
            [118.9, 32.1],
            [118.91, 32.1],
            [118.9, 32.1],
            [118.9, 32.1],
          ],
        ],
      },
      '三个不同顶点',
    ],
    [
      {
        type: 'Polygon',
        coordinates: [
          [
            [118.9, 32.1],
            [118.91, 32.1],
            [118.91, 32.11],
            [118.9, 32.1],
          ],
          [
            [118.901, 32.101],
            [118.902, 32.101],
            [118.902, 32.102],
            [118.901, 32.101],
          ],
        ],
      },
      '一个外环',
    ],
    [{ type: 'MultiPolygon', coordinates: [] }, '仅支持'],
    [{ type: 'Rectangle', coordinates: [] }, '仅支持'],
  ])('rejects an invalid frontend source contract', (geometry, message) => {
    expect(() => parseSourceGeometry(geometry)).toThrow(message)
  })
})
