import { useEffect, useState } from 'react'
import { validateProjectPath } from '../../../shared/lib/api'
import type { ProjectSummary } from '../../../shared/lib/types'
import { FolderPicker } from '../FolderPicker'
import { formatProjectPath } from '../lib/formatPath'

interface Props {
  project: ProjectSummary | null
  busy: boolean
  onBind: (projectId: string, rootPath: string, createIfMissing: boolean) => Promise<void>
}

export function ProjectFolderPanel({ project, busy, onBind }: Props) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [createIfMissing, setCreateIfMissing] = useState(false)
  const [validationMessage, setValidationMessage] = useState<string | null>(null)
  const [validationOk, setValidationOk] = useState<boolean | null>(null)
  const [localBusy, setLocalBusy] = useState(false)

  useEffect(() => {
    setSelectedPath(project?.root_path ?? null)
    setValidationMessage(null)
    setValidationOk(null)
  }, [project?.id, project?.root_path])

  async function handleValidate() {
    if (!selectedPath) return
    setLocalBusy(true)
    try {
      const result = await validateProjectPath({
        root_path: selectedPath,
        create_if_missing: createIfMissing,
      })
      setValidationOk(result.ok)
      setValidationMessage(result.ok ? `可用：${result.resolved_path}` : result.message)
      if (result.ok) setSelectedPath(result.resolved_path)
    } catch (error) {
      setValidationOk(false)
      setValidationMessage(error instanceof Error ? error.message : '路径校验失败')
    } finally {
      setLocalBusy(false)
    }
  }

  async function handleBind() {
    if (!project || !selectedPath) return
    setLocalBusy(true)
    try {
      await onBind(project.id, selectedPath, createIfMissing)
      setValidationOk(true)
      setValidationMessage('目录已绑定')
    } finally {
      setLocalBusy(false)
    }
  }

  const isBusy = busy || localBusy
  const currentPath = project?.root_path ?? null

  return (
    <section className="surface stack project-folder-panel">
      <div>
        <h2 className="section-title">绑定目录</h2>
        <p className="muted">项目必须绑定本地文件夹，流水线产物写入 `.specforge/iterations/`。</p>
      </div>

      {currentPath ? (
        <div className="project-folder-current">
          <span className="eyebrow">当前目录</span>
          <code className="project-folder-path" title={currentPath}>
            {formatProjectPath(currentPath)}
          </code>
        </div>
      ) : (
        <p className="warning-text">尚未绑定目录，请选择文件夹后点击「绑定目录」。</p>
      )}

      <FolderPicker selectedPath={selectedPath} onSelectPath={setSelectedPath} />

      <label className="folder-mode-option">
        <input
          type="checkbox"
          checked={createIfMissing}
          onChange={(event) => {
            setCreateIfMissing(event.target.checked)
            setValidationOk(null)
            setValidationMessage(null)
          }}
          disabled={isBusy || !project}
        />
        若目录不存在则自动创建
      </label>

      {validationMessage ? (
        <p className={validationOk ? 'ok-text' : 'error-text'}>{validationMessage}</p>
      ) : null}

      <div className="compose-actions">
        <button type="button" className="btn btn-ghost btn-sm" onClick={handleValidate} disabled={isBusy || !selectedPath}>
          校验路径
        </button>
        <button
          type="button"
          className="btn btn-accent btn-sm"
          onClick={handleBind}
          disabled={isBusy || !project || !selectedPath}
        >
          {currentPath ? '更换绑定目录' : '绑定目录'}
        </button>
      </div>
    </section>
  )
}
