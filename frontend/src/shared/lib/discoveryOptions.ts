export const DISCOVERY_CUSTOM_OPTION_LABEL = '其他（请说明）'

export function splitDiscoveryOptions(options: string[]) {
  if (options.length === 0) {
    return { presets: [] as string[], customLabel: DISCOVERY_CUSTOM_OPTION_LABEL }
  }
  const last = options[options.length - 1]
  if (last === DISCOVERY_CUSTOM_OPTION_LABEL) {
    return { presets: options.slice(0, -1), customLabel: last }
  }
  return { presets: options, customLabel: DISCOVERY_CUSTOM_OPTION_LABEL }
}

export function isDiscoveryCustomOption(label: string) {
  return label.trim() === DISCOVERY_CUSTOM_OPTION_LABEL
}
