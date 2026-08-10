export interface RiskValueColorBin {
  minimum: number
  maximum: number
  color: string
  label: string
}

// 固定数值区间同时驱动 cell 样式和图例；这里只表达 [0,1] 数值，不推断业务风险等级。
export const RISK_VALUE_COLOR_BINS: readonly RiskValueColorBin[] = [
  { minimum: 0, maximum: 0.2, color: '#440154', label: '[0.0, 0.2)' },
  { minimum: 0.2, maximum: 0.4, color: '#3b528b', label: '[0.2, 0.4)' },
  { minimum: 0.4, maximum: 0.6, color: '#21918c', label: '[0.4, 0.6)' },
  { minimum: 0.6, maximum: 0.8, color: '#5ec962', label: '[0.6, 0.8)' },
  { minimum: 0.8, maximum: 1, color: '#fde725', label: '[0.8, 1.0]' },
]

export function riskColorForValue(value: number): string | null {
  const bin = RISK_VALUE_COLOR_BINS.find(
    (item, index) =>
      value >= item.minimum &&
      (index === RISK_VALUE_COLOR_BINS.length - 1
        ? value <= item.maximum
        : value < item.maximum),
  )
  return bin?.color ?? null
}
