import { useState } from 'react'

interface Props {
  disabled: boolean
  onCreate: (goal: string, mode: 'dry-run' | 'real-cli') => Promise<void>
}

export function CreateIterationPanel({ disabled, onCreate }: Props) {
  const [goal, setGoal] = useState('Build a spec-first pipeline dashboard')
  const [mode, setMode] = useState<'dry-run' | 'real-cli'>('dry-run')
  const [busy, setBusy] = useState(false)

  async function handleCreate() {
    if (!goal.trim()) return
    setBusy(true)
    try {
      await onCreate(goal.trim(), mode)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel stack">
      <h2 className="section-title">新建流水线</h2>
      <div className="form">
        <textarea value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="业务目标或系统改动" />
        <select value={mode} onChange={(event) => setMode(event.target.value as 'dry-run' | 'real-cli')}>
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
