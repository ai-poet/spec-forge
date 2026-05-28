import { useState } from 'react'
import type { Mode } from '../../../shared/lib/types'

interface Props {
  disabled: boolean
  goalPlaceholder?: string
  onCreate: (goal: string, mode: Mode | null) => Promise<void>
}

export function CreateIterationPanel({ disabled, goalPlaceholder, onCreate }: Props) {
  const [goal, setGoal] = useState('')
  const [mode, setMode] = useState<Mode | 'project-default'>('project-default')
  const [busy, setBusy] = useState(false)

  async function handleCreate() {
    if (!goal.trim()) return
    setBusy(true)
    try {
      await onCreate(goal.trim(), mode === 'project-default' ? null : mode)
      setGoal('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel stack">
      <h2 className="section-title">新建流水线</h2>
      <div className="form">
        <textarea
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
          placeholder={goalPlaceholder || '描述本次迭代的业务目标或系统改动'}
          disabled={disabled}
        />
        <select value={mode} onChange={(event) => setMode(event.target.value as Mode | 'project-default')} disabled={disabled}>
          <option value="project-default">使用项目默认模式</option>
          <option value="dry-run">演示模式 dry-run</option>
          <option value="real-cli">真实 CLI 模式</option>
        </select>
        <button className="btn primary" onClick={handleCreate} disabled={busy || disabled || !goal.trim()}>
          创建迭代
        </button>
      </div>
    </section>
  )
}
