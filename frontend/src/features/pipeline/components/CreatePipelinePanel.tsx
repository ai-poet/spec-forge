import { useState } from 'react'
import type { Mode } from '../../../shared/lib/types'
import { parseEpicDraft } from '../../epics/lib/parseEpicDraft'

const NEW_PLACEHOLDER = `第一行作为标题
详细描述业务目标与背景...

验收标准:
- ...`

interface Props {
  mode: 'new' | 'append'
  epicTitle?: string
  goalPlaceholder?: string
  disabled: boolean
  onCreate: (input: { text: string; runMode: Mode | null }) => Promise<void>
}

export function CreatePipelinePanel({ mode, epicTitle, goalPlaceholder, disabled, onCreate }: Props) {
  const [draft, setDraft] = useState('')
  const [runMode, setRunMode] = useState<Mode | 'project-default'>('project-default')
  const [busy, setBusy] = useState(false)

  const canSubmit = mode === 'new' ? Boolean(parseEpicDraft(draft)) : Boolean(draft.trim())

  async function handleCreate() {
    if (!canSubmit) return
    setBusy(true)
    try {
      await onCreate({
        text: draft,
        runMode: runMode === 'project-default' ? null : runMode,
      })
      setDraft('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="workspace-stage-card compose-card stack">
      <div>
        <h2 className="section-title">{mode === 'new' ? '新建流水线' : '再跑一条流水线'}</h2>
        {mode === 'new' ? (
          <p className="muted compose-card-subtitle">描述你的需求，系统将自动创建大需求并启动第一条流水线。</p>
        ) : (
          <p className="compose-epic-context">
            大需求：<strong>{epicTitle}</strong>
          </p>
        )}
      </div>
      <textarea
        className="compose-textarea"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder={mode === 'new' ? NEW_PLACEHOLDER : goalPlaceholder || '描述本次迭代的业务目标或系统改动'}
        disabled={disabled || busy}
      />
      <select
        className="compose-select"
        value={runMode}
        onChange={(event) => setRunMode(event.target.value as Mode | 'project-default')}
        disabled={disabled || busy}
      >
        <option value="project-default">使用项目默认模式</option>
        <option value="dry-run">演示模式 dry-run</option>
        <option value="real-cli">真实 CLI 模式</option>
      </select>
      <div className="compose-actions">
        <button type="button" className="btn btn-accent btn-sm" onClick={handleCreate} disabled={busy || disabled || !canSubmit}>
          启动流水线
        </button>
      </div>
    </section>
  )
}
