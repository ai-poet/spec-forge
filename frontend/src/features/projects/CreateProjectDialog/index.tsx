import { useEffect, useMemo, useState } from 'react'
import { validateProjectPath } from '../../../shared/lib/api'
import type { CreateProjectInput } from '../../../shared/lib/types'
import { FolderPicker } from '../FolderPicker'
import styles from './CreateProjectDialog.module.less'

type FolderMode = 'open' | 'create'

interface Props {
  embedded?: boolean
  onCreate: (input: CreateProjectInput) => Promise<void>
}

function folderBaseName(path: string): string {
  const parts = path.split('/').filter(Boolean)
  return parts[parts.length - 1] ?? ''
}

export function CreateProjectDialog({ embedded = false, onCreate }: Props) {
  const [mode, setMode] = useState<FolderMode>('open')
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [folderName, setFolderName] = useState('')
  const [name, setName] = useState('')
  const [nameEdited, setNameEdited] = useState(false)
  const [busy, setBusy] = useState(false)
  const [validationMessage, setValidationMessage] = useState<string | null>(null)
  const [validationOk, setValidationOk] = useState<boolean | null>(null)

  const targetPath = useMemo(() => {
    if (!selectedPath) return ''
    if (mode === 'open') return selectedPath
    const trimmed = folderName.trim()
    if (!trimmed) return selectedPath
    return `${selectedPath.replace(/\/+$/, '')}/${trimmed}`
  }, [selectedPath, folderName, mode])

  const suggestedName = useMemo(() => {
    if (mode === 'create' && folderName.trim()) return folderName.trim()
    if (!targetPath) return ''
    return folderBaseName(targetPath)
  }, [targetPath, folderName, mode])

  useEffect(() => {
    if (!nameEdited) {
      setName(suggestedName)
    }
  }, [nameEdited, suggestedName])

  async function handleValidate() {
    if (!targetPath) return
    setBusy(true)
    try {
      const result = await validateProjectPath({
        root_path: targetPath,
        create_if_missing: mode === 'create',
      })
      setValidationOk(result.ok)
      setValidationMessage(result.ok ? `可用：${result.resolved_path}` : result.message)
      if (result.ok && !nameEdited && result.resolved_path) {
        setName(folderBaseName(result.resolved_path))
      }
    } catch (error) {
      setValidationOk(false)
      setValidationMessage(error instanceof Error ? error.message : '路径校验失败')
    } finally {
      setBusy(false)
    }
  }

  async function handleCreate() {
    if (!targetPath) return
    setBusy(true)
    try {
      await onCreate({
        root_path: targetPath,
        create_if_missing: mode === 'create',
        name: name.trim() || suggestedName || undefined,
      })
      setSelectedPath(null)
      setFolderName('')
      setName('')
      setNameEdited(false)
      setValidationMessage(null)
      setValidationOk(null)
    } finally {
      setBusy(false)
    }
  }

  function handleModeChange(next: FolderMode) {
    setMode(next)
    setValidationOk(null)
    setValidationMessage(null)
    if (next === 'open') {
      setFolderName('')
    }
  }

  function handleSelectPath(path: string) {
    setSelectedPath(path)
    setValidationOk(null)
    setValidationMessage(null)
  }

  return (
    <section className={`${styles.root} stack ${embedded ? styles.embedded : 'surface'}`}>
      {!embedded ? <h2 className="section-title">打开 / 新建项目</h2> : null}

      <div className={styles.modeToggle}>
        <label className={styles.modeOption}>
          <input type="radio" name="folder-mode" checked={mode === 'open'} onChange={() => handleModeChange('open')} />
          打开已有文件夹
        </label>
        <label className={styles.modeOption}>
          <input type="radio" name="folder-mode" checked={mode === 'create'} onChange={() => handleModeChange('create')} />
          在此目录下新建项目文件夹
        </label>
      </div>

      <FolderPicker selectedPath={selectedPath} onSelectPath={handleSelectPath} />

      {mode === 'create' ? (
        <label className={styles.nameField}>
          <span>新建文件夹名称</span>
          <input
            className={styles.textInput}
            value={folderName}
            onChange={(event) => {
              setFolderName(event.target.value)
              setValidationOk(null)
              setValidationMessage(null)
            }}
            placeholder="my-app"
          />
        </label>
      ) : null}

      <label className={styles.nameField}>
        <span>项目显示名称（可选）</span>
        <input
          className={styles.textInput}
          value={name}
          onChange={(event) => {
            setName(event.target.value)
            setNameEdited(true)
          }}
          placeholder={suggestedName || '默认使用文件夹名'}
        />
      </label>

      {validationMessage ? (
        <p className={validationOk ? 'ok-text' : 'error-text'}>{validationMessage}</p>
      ) : (
        <p className="muted">
          {mode === 'open'
            ? '点击「选择文件夹」打开系统窗口，或在下方列表中浏览。'
            : '先选择父目录（推荐用系统选择窗口），再输入要创建的项目文件夹名称。'}
        </p>
      )}

      <div className={`actions ${styles.actions}`}>
        <button type="button" className="btn btn-ghost" onClick={handleValidate} disabled={busy || !targetPath}>
          校验路径
        </button>
        <button type="button" className="btn primary" onClick={handleCreate} disabled={busy || !targetPath || (mode === 'create' && !folderName.trim())}>
          {mode === 'open' ? '打开项目' : '创建项目'}
        </button>
      </div>
    </section>
  )
}
