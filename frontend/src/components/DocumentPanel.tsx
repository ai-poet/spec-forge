import type { IterationDetail } from '../types'

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
            {doc.name}
          </button>
        ))}
      </div>
      <div className="docs code">{docText || 'No document selected'}</div>
    </section>
  )
}
