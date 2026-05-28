import { useEffect, useState } from 'react'
import type { ProjectSummary, UpdateProjectInput } from '../../../shared/lib/types'
import { ProjectFolderPanel } from './ProjectFolderPanel'

interface Props {
  project: ProjectSummary | null
  busy: boolean
  onSave: (projectId: string, input: UpdateProjectInput) => Promise<void>
  onBindFolder: (projectId: string, rootPath: string, createIfMissing: boolean) => Promise<void>
  onDelete: (projectId: string) => Promise<void>
}

export function ProjectConfigPanel({ project, busy, onSave, onBindFolder, onDelete }: Props) {
  const [defaultTestCommand, setDefaultTestCommand] = useState('')
  const [coderRetries, setCoderRetries] = useState(5)
  const [clarifications, setClarifications] = useState(3)
  const [verifyRejects, setVerifyRejects] = useState(2)

  useEffect(() => {
    if (!project) return
    setDefaultTestCommand(project.default_test_command ?? '')
    setCoderRetries(project.max_coder_tester_retries)
    setClarifications(project.max_clarifications)
    setVerifyRejects(project.max_verify_rejects)
  }, [project])

  async function handleSave() {
    if (!project) return
    await onSave(project.id, {
      default_test_command: defaultTestCommand.trim() || null,
      max_coder_tester_retries: coderRetries,
      max_clarifications: clarifications,
      max_verify_rejects: verifyRejects,
    })
  }

  async function handleDelete() {
    if (!project) return
    const confirmed = window.confirm(
      `确定从 SpecForge 移除「${project.name}」？\n\n本地文件夹不会被删除，只是不再出现在项目列表中。`,
    )
    if (!confirmed) return
    await onDelete(project.id)
  }

  return (
    <>
    <ProjectFolderPanel project={project} busy={busy} onBind={onBindFolder} />

    <section className="surface stack">
      <div className="section-row">
        <div>
          <h2 className="section-title">项目配置</h2>
          <p className="muted">流水线通过 Claude / Codex CLI 执行，各 CLI 使用其默认模型，无需单独配置。</p>
        </div>
        <button type="button" className="btn primary" onClick={handleSave} disabled={busy || !project}>
          保存配置
        </button>
      </div>
      <div className="config-grid">
        <label>
          <span>默认测试命令</span>
          <input value={defaultTestCommand} onChange={(event) => setDefaultTestCommand(event.target.value)} placeholder="pytest" disabled={!project} />
        </label>
        <label>
          <span>Coder/Tester 重试上限</span>
          <input type="number" min="0" max="20" value={coderRetries} onChange={(event) => setCoderRetries(Number(event.target.value))} disabled={!project} />
        </label>
        <label>
          <span>澄清上限</span>
          <input type="number" min="0" max="20" value={clarifications} onChange={(event) => setClarifications(Number(event.target.value))} disabled={!project} />
        </label>
        <label>
          <span>规格复核驳回上限</span>
          <input type="number" min="0" max="20" value={verifyRejects} onChange={(event) => setVerifyRejects(Number(event.target.value))} disabled={!project} />
        </label>
      </div>
    </section>

    <section className="surface stack danger-zone">
      <div className="section-row">
        <div>
          <h2 className="section-title">移除项目</h2>
          <p className="muted">从 SpecForge 项目列表中移除，不会删除本地文件夹或 `.specforge` 产物。</p>
        </div>
        <button type="button" className="btn danger btn-sm" onClick={handleDelete} disabled={busy || !project}>
          从 SpecForge 移除
        </button>
      </div>
    </section>
    </>
  )
}
