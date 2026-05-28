import { useEffect, useState } from 'react'
import type { Mode, ProjectSummary, UpdateProjectInput } from '../../../shared/lib/types'

interface Props {
  project: ProjectSummary | null
  busy: boolean
  onSave: (projectId: string, input: UpdateProjectInput) => Promise<void>
}

export function ProjectConfigPanel({ project, busy, onSave }: Props) {
  const [defaultMode, setDefaultMode] = useState<Mode>('dry-run')
  const [defaultTestCommand, setDefaultTestCommand] = useState('')
  const [coderRetries, setCoderRetries] = useState(5)
  const [clarifications, setClarifications] = useState(3)
  const [verifyRejects, setVerifyRejects] = useState(2)

  useEffect(() => {
    if (!project) return
    setDefaultMode(project.default_mode)
    setDefaultTestCommand(project.default_test_command ?? '')
    setCoderRetries(project.max_coder_tester_retries)
    setClarifications(project.max_clarifications)
    setVerifyRejects(project.max_verify_rejects)
  }, [project])

  async function handleSave() {
    if (!project) return
    await onSave(project.id, {
      default_mode: defaultMode,
      default_test_command: defaultTestCommand.trim() || null,
      max_coder_tester_retries: coderRetries,
      max_clarifications: clarifications,
      max_verify_rejects: verifyRejects,
    })
  }

  return (
    <section className="surface stack">
      <div className="section-row">
        <div>
          <h2 className="section-title">项目配置</h2>
          <p className="muted">real-cli 模式下各 CLI 使用其默认模型，无需单独配置。</p>
        </div>
        <button type="button" className="btn primary" onClick={handleSave} disabled={busy || !project}>
          保存配置
        </button>
      </div>
      <div className="config-grid">
        <label>
          <span>默认模式</span>
          <select value={defaultMode} onChange={(event) => setDefaultMode(event.target.value as Mode)} disabled={!project}>
            <option value="dry-run">dry-run</option>
            <option value="real-cli">real-cli</option>
          </select>
        </label>
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
  )
}
