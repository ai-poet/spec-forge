import { useState } from 'react'
import { submitRuntimeNote } from '../../../shared/lib/api'
import type { IterationDetail } from '../../../shared/lib/types'
import styles from './RuntimeNotePanel.module.less'

const NOTE_STATUSES = new Set(['planning', 'coding', 'testing', 'retrying', 'queued', 'stopped'])

interface Props {
  detail: IterationDetail | null
  reviewMode?: boolean
  onSubmitted?: () => void
}

export function RuntimeNotePanel({ detail, reviewMode = false, onSubmitted }: Props) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canSubmit = Boolean(detail && NOTE_STATUSES.has(detail.status) && !reviewMode)
  const stopped = detail?.status === 'stopped'

  async function handleSubmit() {
    if (!detail || !note.trim() || !canSubmit) return
    setBusy(true)
    setError(null)
    try {
      await submitRuntimeNote(detail.id, note.trim())
      setNote('')
      onSubmitted?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  if (!detail || reviewMode) return null

  return (
    <section className={`panel ${styles.root}`}>
      <div className="section-row">
        <h2 className="section-title">{stopped ? '人工补充说明' : '运行中补充说明'}</h2>
      </div>
      <p className="muted">
        {stopped ? '停止后补充的说明会写入下一轮 Agent 提示。' : '在 Agent 仍在执行时插入简短说明，将在下一轮 CLI 提示中注入（类似 /btw）。'}
      </p>
      <textarea
        className={styles.input}
        rows={3}
        placeholder="例如：优先修复登录流程，UI 测试可跳过"
        value={note}
        disabled={!canSubmit || busy}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className={styles.actions}>
        <button type="button" className={`btn primary ${styles.submitButton}`} disabled={!canSubmit || busy || !note.trim()} onClick={() => void handleSubmit()}>
          {busy ? '提交中…' : '提交补充说明'}
        </button>
        {!canSubmit ? <span className="muted">当前状态不可提交</span> : null}
        {error ? <span className={styles.error}>{error}</span> : null}
      </div>
    </section>
  )
}
