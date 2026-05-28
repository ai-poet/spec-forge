import { useEffect, useState } from 'react'
import type { Mode, ProjectSummary, UpdateProjectInput } from '../types'

interface Props {
  project: ProjectSummary | null
  busy: boolean
  onSave: (projectId: string, input: UpdateProjectInput) => Promise<void>
}

export function ProjectConfigPanel({ project, busy, onSave }: Props) {
  const [defaultMode, setDefaultMode] = useState<Mode>('dry-run')
  const [defaultTestCommand, setDefaultTestCommand] = useState('')
  const [plannerModel, setPlannerModel] = useState('')
  const [coderModel, setCoderModel] = useState('')
  const [testerModel, setTesterModel] = useState('')
  const [coderRetries, setCoderRetries] = useState(5)
  const [clarifications, setClarifications] = useState(3)
  const [verifyRejects, setVerifyRejects] = useState(2)

  useEffect(() => {
    if (!project) return
    setDefaultMode(project.default_mode)
    setDefaultTestCommand(project.default_test_command ?? '')
    setPlannerModel(project.planner_model ?? '')
    setCoderModel(project.coder_model ?? '')
    setTesterModel(project.tester_model ?? '')
    setCoderRetries(project.max_coder_tester_retries)
    setClarifications(project.max_clarifications)
    setVerifyRejects(project.max_verify_rejects)
  }, [project])

  async function handleSave() {
    if (!project) return
    await onSave(project.id, {
      default_mode: defaultMode,
      default_test_command: defaultTestCommand.trim() || null,
      planner_model: plannerModel.trim() || null,
      coder_model: coderModel.trim() || null,
      tester_model: testerModel.trim() || null,
      max_coder_tester_retries: coderRetries,
      max_clarifications: clarifications,
      max_verify_rejects: verifyRejects,
    })
  }

  return (
    <section className="panel stack">
      <div className="section-row">
        <h2 className="section-title">项目配置</h2>
        <button className="btn" onClick={handleSave} disabled={busy || !project}>
          Save config
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
          <span>Planner model</span>
          <input value={plannerModel} onChange={(event) => setPlannerModel(event.target.value)} placeholder="sonnet" disabled={!project} />
        </label>
        <label>
          <span>Coder model</span>
          <input value={coderModel} onChange={(event) => setCoderModel(event.target.value)} placeholder="sonnet" disabled={!project} />
        </label>
        <label>
          <span>Tester model</span>
          <input value={testerModel} onChange={(event) => setTesterModel(event.target.value)} placeholder="gpt-5.2" disabled={!project} />
        </label>
        <label>
          <span>Coder/Tester retries</span>
          <input type="number" min="0" max="20" value={coderRetries} onChange={(event) => setCoderRetries(Number(event.target.value))} disabled={!project} />
        </label>
        <label>
          <span>Clarifications</span>
          <input type="number" min="0" max="20" value={clarifications} onChange={(event) => setClarifications(Number(event.target.value))} disabled={!project} />
        </label>
        <label>
          <span>Verify rejects</span>
          <input type="number" min="0" max="20" value={verifyRejects} onChange={(event) => setVerifyRejects(Number(event.target.value))} disabled={!project} />
        </label>
      </div>
    </section>
  )
}
