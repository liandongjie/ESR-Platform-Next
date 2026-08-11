import type { Coordinate, SourceGeometry } from '@/types/analysisArea'

function parseCoordinate(value: unknown): Coordinate {
  if (
    !Array.isArray(value) ||
    value.length !== 2 ||
    !value.every((item) => typeof item === 'number' && Number.isFinite(item)) ||
    value[0] < -180 ||
    value[0] > 180 ||
    value[1] < -90 ||
    value[1] > 90
  ) {
    throw new Error('source geometry 包含无效的 WGS84 坐标')
  }
  return [value[0], value[1]]
}

function coordinateKey(coordinate: Coordinate): string {
  return `${coordinate[0]},${coordinate[1]}`
}

function parseLinearRing(value: unknown): Coordinate[] {
  if (!Array.isArray(value)) throw new Error('Polygon ring 无效')

  const ring = value.map(parseCoordinate)
  if (ring.length < 4) throw new Error('Polygon ring 至少需要三个不同顶点并闭合')

  const first = ring[0]!
  const last = ring.at(-1)!
  if (first[0] !== last[0] || first[1] !== last[1]) {
    throw new Error('Polygon ring 必须闭合')
  }
  if (new Set(ring.slice(0, -1).map(coordinateKey)).size < 3) {
    throw new Error('Polygon ring 至少需要三个不同顶点')
  }
  return ring
}

function parsePolygonCoordinates(value: unknown): Coordinate[][] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error('Polygon 至少需要一个 ring')
  }
  return value.map(parseLinearRing)
}

export function parseSourceGeometry(value: unknown): SourceGeometry {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error('source geometry 必须是 GeoJSON geometry object')
  }

  const geometry = value as Record<string, unknown>
  if (geometry.type === 'Point') {
    return { type: 'Point', coordinates: parseCoordinate(geometry.coordinates) }
  }

  if (geometry.type === 'LineString') {
    if (!Array.isArray(geometry.coordinates)) {
      throw new Error('LineString coordinates 无效')
    }
    const coordinates = geometry.coordinates.map(parseCoordinate)
    if (new Set(coordinates.map(coordinateKey)).size < 2) {
      throw new Error('LineString 至少需要两个不同点')
    }
    return { type: 'LineString', coordinates }
  }

  if (geometry.type === 'Polygon') {
    return { type: 'Polygon', coordinates: parsePolygonCoordinates(geometry.coordinates) }
  }

  if (geometry.type === 'MultiPolygon') {
    if (!Array.isArray(geometry.coordinates) || geometry.coordinates.length === 0) {
      throw new Error('MultiPolygon 至少需要一个 Polygon')
    }
    return {
      type: 'MultiPolygon',
      coordinates: geometry.coordinates.map(parsePolygonCoordinates),
    }
  }

  throw new Error('source geometry 仅支持 Point、LineString、Polygon 或 MultiPolygon')
}
