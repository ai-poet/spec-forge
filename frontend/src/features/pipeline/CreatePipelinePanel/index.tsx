import { useState } from 'react'
import { parseEpicDraft } from '../../epics/lib/parseEpicDraft'
import compose from '../../../shared/ui/compose.module.less'

const NEW_PLACEHOLDER = `第一行作为标题
详细描述业务目标与背景...

验收标准:
- ...`

interface Props {
  disabled: boolean
  onCreate: (input: { text: string }) => Promise<void>
}

export function CreatePipelinePanel({ disabled, onCreate }: Props) {
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  const canSubmit = Boolean(parseEpicDraft(draft))

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
    <section className={`workspace-stage-card ${compose.card} stack`}>
      <div>
        <h2 className="section-title">新建流水线</h2>
        <p className={`muted ${compose.subtitle}`}>
          描述你的大需求，系统将创建一条流水线并通过 real-cli 执行（Planner / Coder / Tester）。
        </p>
      </div>
      <textarea
        className={compose.textarea}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder={NEW_PLACEHOLDER}
        disabled={disabled || busy}
      />
      <div className={compose.footer}>
        <button type="button" className="btn btn-accent btn-sm" onClick={handleCreate} disabled={busy || disabled || !canSubmit}>
          启动流水线
        </button>
      </div>
    </section>
  )
}
