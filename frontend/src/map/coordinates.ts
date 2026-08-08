import type { Coordinate } from '@/types/analysisArea'

const PI = Math.PI
const KRASOVSKY_A = 6_378_245.0
const ECCENTRICITY_SQUARED = 0.006693421622965943
const REVERSE_TOLERANCE = 1e-7
const MAX_REVERSE_ITERATIONS = 10

function isOutsideChina([lng, lat]: Coordinate): boolean {
  return lng < 72.004 || lng > 137.8347 || lat < 0.8293 || lat > 55.8271
}

function transformLatitude(lng: number, lat: number): number {
  let value = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat
  value += 0.2 * Math.sqrt(Math.abs(lng))
  value += ((20.0 * Math.sin(6.0 * lng * PI) + 20.0 * Math.sin(2.0 * lng * PI)) * 2.0) / 3.0
  value += ((20.0 * Math.sin(lat * PI) + 40.0 * Math.sin((lat / 3.0) * PI)) * 2.0) / 3.0
  value += ((160.0 * Math.sin((lat / 12.0) * PI) + 320.0 * Math.sin((lat * PI) / 30.0)) * 2.0) / 3.0
  return value
}

function transformLongitude(lng: number, lat: number): number {
  let value = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat
  value += 0.1 * Math.sqrt(Math.abs(lng))
  value += ((20.0 * Math.sin(6.0 * lng * PI) + 20.0 * Math.sin(2.0 * lng * PI)) * 2.0) / 3.0
  value += ((20.0 * Math.sin(lng * PI) + 40.0 * Math.sin((lng / 3.0) * PI)) * 2.0) / 3.0
  value += ((150.0 * Math.sin((lng / 12.0) * PI) + 300.0 * Math.sin((lng / 30.0) * PI)) * 2.0) / 3.0
  return value
}

/**
 * 业务层统一保存 WGS84；只有进入高德地图展示边界时才转换为 GCJ-02。
 * 这样可以避免把高德坐标误当成 EPSG:4326 送给后端栅格和 Buffer 计算。
 */
export function wgs84ToGcj02(coordinate: Coordinate): Coordinate {
  if (isOutsideChina(coordinate)) return [...coordinate]

  const [lng, lat] = coordinate
  let deltaLat = transformLatitude(lng - 105.0, lat - 35.0)
  let deltaLng = transformLongitude(lng - 105.0, lat - 35.0)
  const radLat = (lat / 180.0) * PI
  const sinLat = Math.sin(radLat)
  const magic = 1 - ECCENTRICITY_SQUARED * sinLat * sinLat
  const sqrtMagic = Math.sqrt(magic)

  deltaLat =
    (deltaLat * 180.0) /
    (((KRASOVSKY_A * (1 - ECCENTRICITY_SQUARED)) / (magic * sqrtMagic)) * PI)
  deltaLng =
    (deltaLng * 180.0) / ((KRASOVSKY_A / sqrtMagic) * Math.cos(radLat) * PI)

  return [lng + deltaLng, lat + deltaLat]
}

/**
 * 高德点击事件给出 GCJ-02，但后端只接受 WGS84。
 * GCJ-02 没有公开的精确解析逆变换，因此用正向变换迭代逼近，避免简单一次反推留下可见偏移。
 */
export function gcj02ToWgs84(coordinate: Coordinate): Coordinate {
  if (isOutsideChina(coordinate)) return [...coordinate]

  const [targetLng, targetLat] = coordinate
  let estimateLng = targetLng
  let estimateLat = targetLat

  for (let index = 0; index < MAX_REVERSE_ITERATIONS; index += 1) {
    const [convertedLng, convertedLat] = wgs84ToGcj02([estimateLng, estimateLat])
    const deltaLng = convertedLng - targetLng
    const deltaLat = convertedLat - targetLat

    estimateLng -= deltaLng
    estimateLat -= deltaLat

    if (Math.abs(deltaLng) < REVERSE_TOLERANCE && Math.abs(deltaLat) < REVERSE_TOLERANCE) {
      break
    }
  }

  return [estimateLng, estimateLat]
}
