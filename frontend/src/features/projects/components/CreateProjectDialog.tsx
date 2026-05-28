import { useMemo, useState } from 'react'
import { validateProjectPath } from '../../../shared/lib/api'
import type { CreateProjectInput } from '../../../shared/lib/types'

type FolderMode = 'open' | 'create'

interface Props {
  onCreate: (input: CreateProjectInput) => Promise<void>
}

export function CreateProjectDialog({ onCreate }: Props) {
  const [mode, setMode] = useState<FolderMode>('open')
  const [rootPath, setRootPath] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [validationMessage, setValidationMessage] = useState<string | null>(null)
  const [validationOk, setValidationOk] = useState<boolean | null>(null)

  const suggestedName = useMemo(() => {
    const trimmed = rootPath.trim()
    if (!trimmed) return ''
    const parts = trimmed.split('/').filter(Boolean)
    return parts[parts.length - 1] ?? ''
  }, [rootPath])

  async function handleValidate() {
    if (!rootPath.trim()) return
    setBusy(true)
    try {
      const result = await validateProjectPath({
        root_path: rootPath.trim(),
        create_if_missing: mode === 'create',
      })
      setValidationOk(result.ok)
      setValidationMessage(result.ok ? `可用：${result.resolved_path}` : result.message)
      if (result.ok && !name.trim() && result.resolved_path) {
        const parts = result.resolved_path.split('/').filter(Boolean)
        setName(parts[parts.length - 1] ?? '')
      }
    } catch (error) {
      setValidationOk(false)
      setValidationMessage(error instanceof Error ? error.message : '路径校验失败')
    } finally {
      setBusy(false)
    }
  }

  async function handleCreate() {
    if (!rootPath.trim()) return
    setBusy(true)
    try {
      await onCreate({
        root_path: rootPath.trim(),
        create_if_missing: mode === 'create',
        name: name.trim() || suggestedName || undefined,
        description: description.trim() || undefined,
      })
      setRootPath('')
      setName('')
      setDescription('')
      setValidationMessage(null)
      setValidationOk(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel stack create-project-dialog">
      <h2 className="section-title">新建项目</h2>
      <div className="folder-mode-toggle">
        <label className="folder-mode-option">
          <input type="radio" name="folder-mode" checked={mode === 'open'} onChange={() => setMode('open')} />
          打开已有目录
        </label>
        <label className="folder-mode-option">
          <input type="radio" name="folder-mode" checked={mode === 'create'} onChange={() => setMode('create')} />
          创建新目录
        </label>
      </div>
      <div className="form compact">
        <input
          value={rootPath}
          onChange={(event) => {
            setRootPath(event.target.value)
            setValidationOk(null)
            setValidationMessage(null)
          }}
          placeholder="/Users/me/Projects/my-app"
        />
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder={`显示名称（默认 ${suggestedName || '目录名'}）`} />
        <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="描述（可选）" />
        {validationMessage ? (
          <p className={validationOk ? 'ok-text' : 'error-text'}>{validationMessage}</p>
        ) : (
          <p className="muted">项目会绑定到该文件夹，iteration 产物写入 `.specforge/iterations/`。</p>
        )}
        <div className="actions">
          <button className="btn" onClick={handleValidate} disabled={busy || !rootPath.trim()}>
            校验路径
          </button>
          <button className="btn primary" onClick={handleCreate} disabled={busy || !rootPath.trim()}>
            创建项目
          </button>
        </div>
      </div>
    </section>
  )
}
