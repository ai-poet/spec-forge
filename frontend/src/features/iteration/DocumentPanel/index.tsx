import type { IterationDetail } from '../../../shared/lib/types'
import { documentLabel } from '../../../shared/lib/labels'
import { documentSummary } from '../../../shared/lib/presentation'

interface Props {
  detail: IterationDetail | null
  docText: string
  onLoadDocument: (name: string) => Promise<void>
}

export function DocumentPanel({ detail, docText, onLoadDocument }: Props) {
  const summaries = documentSummary(detail)
  return (
    <section className="panel stack">
      <h2 className="section-title">文档</h2>
      <div className="artifact-summary">
        {summaries.map((doc) => (
          <button
            key={doc.name}
            className={`artifact-chip ${doc.present ? 'present' : ''}`}
            onClick={() => doc.present && onLoadDocument(doc.name)}
            disabled={!doc.present}
          >
            {doc.present ? '✓' : '·'} {doc.label}
          </button>
        ))}
      </div>
      <div className="actions">
        {detail?.documents.map((doc) => (
          <button key={doc.name} className="btn" onClick={() => onLoadDocument(doc.name)}>
            {documentLabel(doc.name)}
          </button>
        ))}
      </div>
      <div className="docs code">{docText || '请选择一份文档'}</div>
    </section>
  )
}
