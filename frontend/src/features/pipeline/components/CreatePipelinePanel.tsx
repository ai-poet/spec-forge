import { useState } from 'react'
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
  onCreate: (input: { text: string }) => Promise<void>
}

export function CreatePipelinePanel({ mode, epicTitle, goalPlaceholder, disabled, onCreate }: Props) {
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  const canSubmit = mode === 'new' ? Boolean(parseEpicDraft(draft)) : Boolean(draft.trim())

  async function handleCreate() {
    if (!canSubmit) return
    setBusy(true)
    try {
      await onCreate({ text: draft })
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
          <p className="muted compose-card-subtitle">
            描述你的需求，系统将自动创建大需求并启动 real-cli 流水线（Planner / Coder / Tester）。
          </p>
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
      <div className="compose-footer">
        <button type="button" className="btn btn-accent btn-sm" onClick={handleCreate} disabled={busy || disabled || !canSubmit}>
          启动流水线
        </button>
      </div>
    </section>
  )
}
