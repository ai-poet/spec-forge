export function formatProjectPath(path: string | null | undefined): string {
  if (!path) return '未绑定目录'
  const homeMatch = path.match(/^\/Users\/[^/]+/)
  if (homeMatch) return path.replace(homeMatch[0], '~')
  if (path.length > 48) return `…${path.slice(-45)}`
  return path
}
