import { describe, expect, it } from 'vitest'

import { createPoiCsvArtifact, type PoiExportData } from '@/export/poiCsv'
import type { PoiDto } from '@/types/poi'

function makePoi(overrides: Partial<PoiDto> = {}): PoiDto {
  return {
    id: 'poi-1',
    name: '学校',
    type: '科教文化服务',
    typeCode: '141200',
    address: '蓝旗街',
    locationWgs84: [-73.9857, 40.7484],
    ...overrides,
  }
}

function makeData(items: PoiDto[], overrides: Partial<PoiExportData> = {}): PoiExportData {
  return {
    mode: 'current-page',
    keyword: '学校',
    page: 2,
    items,
    totalReported: 44,
    retrievableLimit: 44,
    exportedCount: items.length,
    ...overrides,
  }
}

describe('POI CSV export', () => {
  it('writes BOM, CRLF, quoted WGS84 fields, and escaped external text', () => {
    const artifact = createPoiCsvArtifact(
      makeData([
        makePoi({
          name: '学校,"东区"\n新楼',
          address: '南京,秦淮',
        }),
      ]),
      new Date(2026, 7, 11, 12, 34, 56),
    )

    expect(artifact.mimeType).toBe('text/csv;charset=utf-8')
    expect(artifact.filename).toBe('POI数据-学校-当前页-2-20260811-123456.csv')
    expect(artifact.content.startsWith('\ufeff"id","name","type","type_code"')).toBe(true)
    expect(artifact.content).toContain('"学校,""东区""\n新楼"')
    expect(artifact.content).toContain('"南京,秦淮"')
    expect(artifact.content).toContain('"-73.9857","40.7484","EPSG:4326"')
    expect(artifact.content).not.toContain("\"'-73.9857\"")
    expect(artifact.content.endsWith('\r\n')).toBe(true)
    expect(artifact.content.replaceAll('\r\n', '').includes('\r')).toBe(false)
  })

  it.each(['=SUM(A1:A2)', '+1', '-1', '@cmd', '\tformula', '\rformula', '   =SUM(A1:A2)'])(
    'protects an external string starting with %j',
    (value) => {
      const artifact = createPoiCsvArtifact(
        makeData([makePoi({ id: value })]),
        new Date(2026, 7, 11, 12, 34, 56),
      )

      const firstValue = artifact.content.split('\r\n')[1]!.split(',')[0]
      expect(firstValue).toBe(`"'${value.replaceAll('"', '""')}"`)
    },
  )

  it('sanitizes and truncates the keyword in both filename modes', () => {
    const date = new Date(2026, 7, 11, 12, 34, 56)
    const current = createPoiCsvArtifact(
      makeData([], { keyword: ' 学校/\t医院:*? ' }),
      date,
    )
    const retrievable = createPoiCsvArtifact(
      makeData([], {
        mode: 'retrievable',
        keyword: '😀'.repeat(40),
        page: null,
      }),
      date,
    )

    expect(current.filename).toBe('POI数据-学校__医院___-当前页-2-20260811-123456.csv')
    expect(retrievable.filename).toBe(
      `POI数据-${'😀'.repeat(32)}-可获取结果-20260811-123456.csv`,
    )
  })

  it('rejects non-finite coordinates', () => {
    expect(() =>
      createPoiCsvArtifact(
        makeData([makePoi({ locationWgs84: [Number.NaN, 32] })]),
        new Date(),
      ),
    ).toThrow('无效 WGS84 坐标')
  })
})
