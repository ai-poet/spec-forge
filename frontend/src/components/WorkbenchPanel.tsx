import { useMemo, useState } from 'react'
import type { IterationDetail, TimelineFilter } from '../types'
import { DocumentPanel } from './DocumentPanel'
import { IterationSummaryPanel } from './IterationSummaryPanel'
import { RunLogPanel } from './RunLogPanel'
import { TimelinePanel } from './TimelinePanel'

interface Props {
  detail: IterationDetail | null
  docText: string
  onLoadDocument: (name: string) => Promise<void>
}

type WorkbenchTab = 'summary' | 'docs' | 'tests' | 'logs'

export function WorkbenchPanel({ detail, docText, onLoadDocument }: Props) {
  const [tab, setTab] = useState<WorkbenchTab>('summary')
  const [timelineFilter, setTimelineFilter] = useState<TimelineFilter>('all')
  const testDocs = useMemo(() => detail?.documents.filter((doc) => doc.name.includes('tests/')) ?? [], [detail])

  return (
    <section className="stack">
      <div className="tabbar">
        {(['summary', 'docs', 'tests', 'logs'] as WorkbenchTab[]).map((item) => (
          <button key={item} className={`tab ${tab === item ? 'active' : ''}`} onClick={() => setTab(item)}>
            {item === 'summary' ? 'Summary' : item === 'docs' ? 'Docs' : item === 'tests' ? 'Tests' : 'Logs'}
          </button>
        ))}
      </div>

      {tab === 'summary' ? (
        <div className="grid">
          <IterationSummaryPanel detail={detail} />
          <TimelinePanel detail={detail} filter={timelineFilter} onFilterChange={setTimelineFilter} />
        </div>
      ) : null}
      {tab === 'docs' ? <DocumentPanel detail={detail} docText={docText} onLoadDocument={onLoadDocument} /> : null}
      {tab === 'tests' ? (
        <section className="panel stack">
          <h2 className="section-title">Tests / Integrity</h2>
          <div className="actions">
            {testDocs.map((doc) => (
              <button key={doc.name} className="btn" onClick={() => onLoadDocument(doc.name)}>
                {doc.name}
              </button>
            ))}
          </div>
          <TimelinePanel detail={detail} filter="tests" />
        </section>
      ) : null}
      {tab === 'logs' ? <RunLogPanel detail={detail} /> : null}
    </section>
  )
}
