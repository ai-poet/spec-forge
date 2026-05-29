import { useEffect, useState } from 'react'
import { browseProjectDirectory, pickProjectFolder } from '../../../shared/lib/api'
import type { BrowseDirectoryResult } from '../../../shared/lib/types'
import { formatProjectPath } from '../lib/formatPath'
import styles from './FolderPicker.module.less'

interface Props {
  selectedPath: string | null
  onSelectPath: (path: string) => void
}

export function FolderPicker({ selectedPath, onSelectPath }: Props) {
  const [browse, setBrowse] = useState<BrowseDirectoryResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function loadDirectory(path?: string | null, selectCurrent = true) {
    setLoading(true)
    setError(null)
    try {
      const result = await browseProjectDirectory(path)
      setBrowse(result)
      if (selectCurrent) {
        onSelectPath(result.path)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法读取目录')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadDirectory(selectedPath).catch(console.error)
  }, [])

  function handleEnter(path: string) {
    loadDirectory(path).catch(console.error)
  }

  function handleSelectCurrent() {
    if (browse) onSelectPath(browse.path)
  }

  async function handleNativePick() {
    setLoading(true)
    setError(null)
    try {
      const result = await pickProjectFolder()
      if (result.cancelled || !result.path) return
      await loadDirectory(result.path)
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法打开文件夹选择窗口')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles.root}>
      <div className={styles.nativeRow}>
        <button type="button" className="btn btn-accent btn-sm" onClick={handleNativePick} disabled={loading}>
          选择文件夹…
        </button>
        <span className={`muted ${styles.nativeHint}`}>打开系统文件夹选择窗口</span>
      </div>

      <div className={styles.toolbar}>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => browse?.parent && handleEnter(browse.parent)}
          disabled={loading || !browse?.parent}
        >
          上一级
        </button>
        <div className={styles.path} title={browse?.path ?? ''}>
          {browse ? formatProjectPath(browse.path) : '加载中…'}
        </div>
      </div>

      {browse?.quick_roots.length ? (
        <div className={styles.quick}>
          {browse.quick_roots.map((root) => (
            <button
              key={root.path}
              type="button"
              className={styles.quickBtn}
              onClick={() => handleEnter(root.path)}
              disabled={loading}
            >
              {root.label}
            </button>
          ))}
        </div>
      ) : null}

      <div className={styles.list}>
        {loading ? <div className={styles.empty}>正在读取目录…</div> : null}
        {error ? <div className={`${styles.empty} error-text`}>{error}</div> : null}
        {!loading && !error && browse ? (
          <button
            type="button"
            className={`${styles.row} ${styles.rowCurrent} ${selectedPath === browse.path ? styles.rowSelected : ''}`}
            onClick={handleSelectCurrent}
          >
            <span className={styles.icon}>📂</span>
            <span className={styles.name}>当前目录</span>
          </button>
        ) : null}
        {!loading && !error && browse?.entries.length === 0 ? (
          <div className={`${styles.empty} muted`}>此目录下没有子文件夹</div>
        ) : null}
        {!loading && !error
          ? browse?.entries.map((entry) => (
              <button
                key={entry.path}
                type="button"
                className={`${styles.row} ${selectedPath === entry.path ? styles.rowSelected : ''}`}
                onClick={() => onSelectPath(entry.path)}
                onDoubleClick={() => handleEnter(entry.path)}
              >
                <span className={styles.icon}>📁</span>
                <span className={styles.name}>{entry.name}</span>
              </button>
            ))
          : null}
      </div>

      {selectedPath ? (
        <p className={styles.selected}>
          已选择：<span title={selectedPath}>{formatProjectPath(selectedPath)}</span>
        </p>
      ) : null}
    </div>
  )
}
