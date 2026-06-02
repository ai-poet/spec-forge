import { useEffect, useState } from 'react'
import { splitDiscoveryOptions } from '../../../shared/lib/discoveryOptions'
import type { IterationDetail } from '../../../shared/lib/types'
import styles from './RequirementsDiscoveryPanel.module.less'

interface Props {
  detail: IterationDetail
  busy: boolean
  onSubmitAnswer: (answer: string) => Promise<void>
  onSkip: () => Promise<void>
}

function discoveryDraftKey(iterationId: string, round: number, question: string) {
  return `specforge:discovery-draft:${iterationId}:${round}:${encodeURIComponent(question).slice(0, 120)}`
}

export function RequirementsDiscoveryPanel({ detail, busy, onSubmitAnswer, onSkip }: Props) {
  const pending = detail.pending_discovery
  const [customAnswer, setCustomAnswer] = useState('')
  const history = detail.discovery_history ?? []

  const { presets, customLabel } = splitDiscoveryOptions(pending?.options ?? [])
  const draftKey = pending ? discoveryDraftKey(detail.id, pending.round, pending.question) : null

  useEffect(() => {
    if (!draftKey) {
      setCustomAnswer('')
      return
    }
    setCustomAnswer(window.sessionStorage.getItem(draftKey) ?? '')
  }, [draftKey])

  useEffect(() => {
    if (!draftKey) return
    window.sessionStorage.setItem(draftKey, customAnswer)
  }, [customAnswer, draftKey])

  if (!pending) return null

  async function pickPreset(option: string) {
    if (busy) return
    await onSubmitAnswer(option)
  }

  async function submitCustomAnswer() {
    const text = customAnswer.trim()
    if (!text || busy) return
    await onSubmitAnswer(text)
    if (draftKey) window.sessionStorage.removeItem(draftKey)
    setCustomAnswer('')
  }

  function focusCustomInput() {
    if (busy) return
    document.getElementById('discovery-custom-answer')?.focus()
  }

  return (
    <div className={styles.panel}>
      <p className={styles.eyebrow}>Planner 需要你确认（第 {pending.round} 轮）</p>
      <p className={styles.question}>{pending.question}</p>
      {pending.assumptions.length ? (
        <div className={styles.assumptions}>
          <span className="muted">当前假设：</span>
          <ul>
            {pending.assumptions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className={styles.choiceBlock}>
        <p className={styles.choiceHint}>选择一项即可继续；最后一项可自定义输入</p>
        <ul className={styles.choiceList} role="listbox" aria-label="可选回答">
          {presets.map((option, index) => (
            <li key={option}>
              <button
                type="button"
                className={styles.choiceOption}
                disabled={busy}
                role="option"
                onClick={() => pickPreset(option)}
              >
                <span className={styles.choiceIndex}>{index + 1}</span>
                <span className={styles.choiceLabel}>{option}</span>
              </button>
            </li>
          ))}
          <li>
            <button
              type="button"
              className={styles.choiceOption}
              disabled={busy}
              role="option"
              onClick={focusCustomInput}
            >
              <span className={styles.choiceIndex}>{presets.length + 1}</span>
              <span className={styles.choiceLabel}>{customLabel}</span>
            </button>
          </li>
        </ul>
        <div className={styles.customBlock}>
          <label className={styles.freeformLabel} htmlFor="discovery-custom-answer">
            请说明你的选择
          </label>
          <textarea
            id="discovery-custom-answer"
            className={styles.input}
            rows={3}
            placeholder="输入自定义回答…"
            value={customAnswer}
            disabled={busy}
            onChange={(event) => setCustomAnswer(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                event.preventDefault()
                void submitCustomAnswer()
              }
            }}
          />
          <div className={styles.actions}>
            <button
              type="button"
              className="btn primary"
              disabled={busy || !customAnswer.trim()}
              onClick={submitCustomAnswer}
            >
              提交自定义回答
            </button>
          </div>
        </div>
      </div>

      <div className={styles.footerActions}>
        <button type="button" className="btn btn-ghost" disabled={busy} onClick={onSkip}>
          跳过澄清
        </button>
      </div>

      {history.length ? (
        <details className={styles.history}>
          <summary>已回答 {history.length} 轮</summary>
          <ol>
            {history.map((item) => (
              <li key={item.round}>
                <strong>Q{item.round}:</strong> {item.question}
                <br />
                <strong>A:</strong> {item.answer}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </div>
  )
}
