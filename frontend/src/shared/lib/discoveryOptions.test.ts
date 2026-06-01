import { describe, expect, it } from 'vitest'
import { DISCOVERY_CUSTOM_OPTION_LABEL, splitDiscoveryOptions } from './discoveryOptions'

describe('splitDiscoveryOptions', () => {
  it('splits presets and custom label', () => {
    const result = splitDiscoveryOptions(['A', 'B', DISCOVERY_CUSTOM_OPTION_LABEL])
    expect(result.presets).toEqual(['A', 'B'])
    expect(result.customLabel).toBe(DISCOVERY_CUSTOM_OPTION_LABEL)
  })
})
