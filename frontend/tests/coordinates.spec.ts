import { describe, expect, it } from 'vitest'

import { gcj02ToWgs84, wgs84ToGcj02 } from '@/map/coordinates'

describe('coordinate adapter', () => {
  it('converts a known WGS84 control point to GCJ-02', () => {
    const converted = wgs84ToGcj02([116.404, 39.915])

    expect(converted[0]).toBeCloseTo(116.41024449916938, 6)
    expect(converted[1]).toBeCloseTo(39.91640428150164, 6)
  })

  it('keeps Nanjing round-trip error below one micro-degree', () => {
    const source: [number, number] = [118.9, 32.1]
    const gcj02 = wgs84ToGcj02(source)
    const restored = gcj02ToWgs84(gcj02)

    expect(Math.abs(restored[0] - source[0])).toBeLessThan(1e-6)
    expect(Math.abs(restored[1] - source[1])).toBeLessThan(1e-6)
  })

  it('does not offset coordinates outside China', () => {
    const sanFrancisco: [number, number] = [-122.4194, 37.7749]

    expect(wgs84ToGcj02(sanFrancisco)).toEqual(sanFrancisco)
    expect(gcj02ToWgs84(sanFrancisco)).toEqual(sanFrancisco)
  })
})
