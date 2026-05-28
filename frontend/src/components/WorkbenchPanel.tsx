import { useMemo, useState } from 'react'
import type { IterationDetail, TimelineFilter } from '../types'
import { documentLabel } from '../labels'
import { DocumentPanel } from './DocumentPanel'
import { IterationSummaryPanel } from './IterationSummaryPanel'
import { RunLogPanel } from './RunLogPanel'
import { TimelinePanel } from './TimelinePanel'
import { UIVerificationPanel } from './UIVerificationPanel'

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
  const tabLabels: Record<WorkbenchTab, string> = {
    summary: '摘要',
    docs: '文档',
    tests: '测试',
    logs: '日志',
  }

  return (
    <section className="stack">
      <div className="tabbar">
        {(['summary', 'docs', 'tests', 'logs'] as WorkbenchTab[]).map((item) => (
          <button key={item} className={`tab ${tab === item ? 'active' : ''}`} onClick={() => setTab(item)}>
            {tabLabels[item]}
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
          <h2 className="section-title">测试与完整性</h2>
          <div className="actions">
            {testDocs.map((doc) => (
              <button key={doc.name} className="btn" onClick={() => onLoadDocument(doc.name)}>
                {documentLabel(doc.name)}
              </button>
            ))}
          </div>
          <UIVerificationPanel detail={detail} />
          <TimelinePanel detail={detail} filter="tests" />
        </section>
      ) : null}
      {tab === 'logs' ? <RunLogPanel detail={detail} /> : null}
    </section>
  )
}
