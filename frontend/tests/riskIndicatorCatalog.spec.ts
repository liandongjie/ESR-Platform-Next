import { describe, expect, it } from 'vitest'

import { parseRiskIndicatorCatalog } from '@/validation/riskIndicatorCatalog'
import { makeRiskIndicatorCatalog } from './fixtures/riskIndicatorCatalog'

describe('risk indicator catalog validation', () => {
  it('accepts the complete twelve-indicator increasing model contract', () => {
    const catalog = makeRiskIndicatorCatalog()

    expect(parseRiskIndicatorCatalog(catalog)).toEqual(catalog)
  })

  it('rejects duplicate indicators and unsupported risk directions', () => {
    const duplicate = makeRiskIndicatorCatalog()
    duplicate.indicators[1]!.code = duplicate.indicators[0]!.code
    expect(() => parseRiskIndicatorCatalog(duplicate)).toThrow()

    const decreasing = makeRiskIndicatorCatalog() as unknown as {
      indicators: Array<Record<string, unknown>>
    }
    decreasing.indicators[0]!.risk_direction = 'decreasing'
    expect(() => parseRiskIndicatorCatalog(decreasing)).toThrow()
  })

  it('rejects the historical misspelled model code', () => {
    const catalog = makeRiskIndicatorCatalog() as unknown as {
      model_contract: Record<string, unknown>
    }
    catalog.model_contract.code =
      'nimbly_facility_siting_environmental_social_risk_sensitivity'

    expect(() => parseRiskIndicatorCatalog(catalog)).toThrow()
  })
})
