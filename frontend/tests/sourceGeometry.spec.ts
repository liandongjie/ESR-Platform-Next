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
        [
          [118.902, 32.102],
          [118.904, 32.102],
          [118.904, 32.104],
          [118.902, 32.102],
        ],
      ],
    },
    {
      type: 'MultiPolygon',
      coordinates: [
        [
          [
            [118.9, 32.1],
            [118.91, 32.1],
            [118.91, 32.11],
            [118.9, 32.1],
          ],
        ],
        [
          [
            [118.92, 32.12],
            [118.93, 32.12],
            [118.93, 32.13],
            [118.92, 32.12],
          ],
          [
            [118.923, 32.123],
            [118.925, 32.123],
            [118.925, 32.125],
            [118.923, 32.123],
          ],
        ],
      ],
    },
  ])('accepts and deep-clones $type', (geometry) => {
    const parsed = parseSourceGeometry(geometry)

    expect(parsed).toEqual(geometry)
    expect(parsed).not.toBe(geometry)
    expect(parsed.coordinates).not.toBe(geometry.coordinates)
  })

  it('deep-clones every MultiPolygon member, ring, and coordinate', () => {
    const geometry = {
      type: 'MultiPolygon',
      coordinates: [
        [
          [
            [118.9, 32.1],
            [118.91, 32.1],
            [118.91, 32.11],
            [118.9, 32.1],
          ],
          [
            [118.902, 32.102],
            [118.904, 32.102],
            [118.904, 32.104],
            [118.902, 32.102],
          ],
        ],
      ],
    }

    const parsed = parseSourceGeometry(geometry)
    if (parsed.type !== 'MultiPolygon') throw new Error('expected MultiPolygon')

    expect(parsed).toEqual(geometry)
    expect(parsed.coordinates[0]).not.toBe(geometry.coordinates[0])
    expect(parsed.coordinates[0]?.[1]).not.toBe(geometry.coordinates[0]?.[1])
    expect(parsed.coordinates[0]?.[1]?.[0]).not.toBe(geometry.coordinates[0]?.[1]?.[0])
    geometry.coordinates[0]![1]![0]![0] = 120
    expect(parsed.coordinates[0]?.[1]?.[0]?.[0]).toBe(118.902)
    parsed.coordinates[0]![1]![0]![1] = 33
    expect(geometry.coordinates[0]?.[1]?.[0]?.[1]).toBe(32.102)
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
            [118.901, 32.102],
          ],
        ],
      },
      '必须闭合',
    ],
    [{ type: 'Polygon', coordinates: [] }, '至少需要一个 ring'],
    [{ type: 'MultiPolygon', coordinates: [] }, '至少需要一个 Polygon'],
    [{ type: 'MultiPolygon', coordinates: [[]] }, '至少需要一个 ring'],
    [
      {
        type: 'MultiPolygon',
        coordinates: [
          [
            [118.9, 32.1],
            [118.91, 32.1],
            [118.91, 32.11],
            [118.9, 32.1],
          ],
        ],
      },
      'WGS84',
    ],
    [
      {
        type: 'MultiPolygon',
        coordinates: [
          [
            [
              [118.9, 32.1],
              [118.91, 32.1],
              [181, 32.11],
              [118.9, 32.1],
            ],
          ],
        ],
      },
      'WGS84',
    ],
    [{ type: 'Rectangle', coordinates: [] }, '仅支持'],
  ])('rejects an invalid frontend source contract', (geometry, message) => {
    expect(() => parseSourceGeometry(geometry)).toThrow(message)
  })
})
