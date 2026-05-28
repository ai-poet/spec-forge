import { useState } from 'react'
import type { Mode } from '../types'

interface Props {
  disabled: boolean
  onCreate: (goal: string, mode: Mode | null) => Promise<void>
}

export function CreateIterationPanel({ disabled, onCreate }: Props) {
  const [goal, setGoal] = useState('Build a spec-first pipeline dashboard')
  const [mode, setMode] = useState<Mode | 'project-default'>('project-default')
  const [busy, setBusy] = useState(false)

  async function handleCreate() {
    if (!goal.trim()) return
    setBusy(true)
    try {
      await onCreate(goal.trim(), mode === 'project-default' ? null : mode)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel stack">
      <h2 className="section-title">新建流水线</h2>
      <div className="form">
        <textarea value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="业务目标或系统改动" />
        <select value={mode} onChange={(event) => setMode(event.target.value as Mode | 'project-default')}>
          <option value="project-default">project default</option>
          <option value="dry-run">dry-run</option>
          <option value="real-cli">real-cli</option>
        </select>
        <button className="btn primary" onClick={handleCreate} disabled={busy || disabled || !goal.trim()}>
          Create iteration
        </button>
      </div>
    </section>
  )
}
