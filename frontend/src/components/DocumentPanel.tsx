import type { IterationDetail } from '../types'
import { documentLabel } from '../labels'

interface Props {
  detail: IterationDetail | null
  docText: string
  onLoadDocument: (name: string) => Promise<void>
}

export function DocumentPanel({ detail, docText, onLoadDocument }: Props) {
  return (
    <section className="panel stack">
      <h2 className="section-title">文档</h2>
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
