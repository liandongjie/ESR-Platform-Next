import type { PoiDto } from '@/types/poi'

export const POI_CSV_MIME_TYPE = 'text/csv;charset=utf-8'

export interface PoiExportData {
  mode: 'current-page' | 'retrievable'
  keyword: string
  page: number | null
  items: PoiDto[]
  totalReported: number
  retrievableLimit: number
  exportedCount: number
}

export interface PoiCsvArtifact {
  content: string
  filename: string
  mimeType: typeof POI_CSV_MIME_TYPE
}

const HEADERS = [
  'id',
  'name',
  'type',
  'type_code',
  'address',
  'longitude_wgs84',
  'latitude_wgs84',
  'coordinate_crs',
] as const
const WINDOWS_INVALID_FILENAME_CHARACTERS = '<>:"/\\|?*'

function quoteCsv(value: string): string {
  return `"${value.replaceAll('"', '""')}"`
}

function protectExternalString(value: string): string {
  return /^ *[=+\-@\t\r]/.test(value) ? `'${value}` : value
}

function sanitizeKeyword(keyword: string): string {
  const sanitized = Array.from(keyword, (character) => {
    const code = character.charCodeAt(0)
    return code <= 31 || code === 127 || WINDOWS_INVALID_FILENAME_CHARACTERS.includes(character)
      ? '_'
      : character
  })
    .join('')
    .trim()
  return Array.from(sanitized).slice(0, 32).join('')
}

function formatTimestamp(value: Date): string {
  if (Number.isNaN(value.getTime())) throw new Error('POI CSV 导出时间无效')
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${value.getFullYear()}${pad(value.getMonth() + 1)}${pad(value.getDate())}-${pad(value.getHours())}${pad(value.getMinutes())}${pad(value.getSeconds())}`
}

export function createPoiCsvArtifact(data: PoiExportData, exportedAt: Date): PoiCsvArtifact {
  const lines = [HEADERS.map(quoteCsv).join(',')]

  for (const poi of data.items) {
    const [longitude, latitude] = poi.locationWgs84
    if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) {
      throw new Error('POI CSV 包含无效 WGS84 坐标')
    }
    lines.push(
      [
        poi.id,
        poi.name,
        poi.type,
        poi.typeCode,
        poi.address,
      ]
        .map(protectExternalString)
        .concat(String(longitude), String(latitude), 'EPSG:4326')
        .map(quoteCsv)
        .join(','),
    )
  }

  const keyword = sanitizeKeyword(data.keyword)
  const timestamp = formatTimestamp(exportedAt)
  const suffix =
    data.mode === 'current-page' ? `当前页-${data.page}-${timestamp}` : `可获取结果-${timestamp}`

  return {
    content: `\ufeff${lines.join('\r\n')}\r\n`,
    filename: `POI数据-${keyword}-${suffix}.csv`,
    mimeType: POI_CSV_MIME_TYPE,
  }
}
