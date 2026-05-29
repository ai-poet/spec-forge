import { useState } from 'react'
import { parseEpicDraft } from '../lib/parseEpicDraft'

interface Props {
  disabled: boolean
  onCreate: (input: { title: string; description: string; acceptance_criteria: string }) => Promise<void>
}

const PLACEHOLDER = `第一行作为标题
详细描述业务目标与背景...

验收标准:
- ...`

export function CreateEpicPanel({ disabled, onCreate }: Props) {
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  const parsed = parseEpicDraft(draft)

  async function handleCreate() {
    if (!parsed) return
    setBusy(true)
    try {
      await onCreate(parsed)
      setDraft('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="workspace-stage-card compose-card stack">
      <h2 className="section-title">新建大需求</h2>
      <textarea
        className="compose-textarea"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder={PLACEHOLDER}
        disabled={disabled || busy}
      />
      <div className="compose-actions">
        <button className="btn primary" onClick={handleCreate} disabled={busy || disabled || !parsed}>
          创建大需求
        </button>
      </div>
    </section>
  )
}
