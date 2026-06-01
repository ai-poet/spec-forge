import { API_BASE } from './api'

export function iterationWebSocketUrl(iterationId: string): string {
  const url = new URL(API_BASE)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.pathname = `/ws/iterations/${iterationId}`
  url.search = ''
  url.hash = ''
  return url.toString()
}
