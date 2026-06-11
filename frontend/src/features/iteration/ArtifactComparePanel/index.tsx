import { useCallback, useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { generateArtifactComparison, getArtifactComparison, getIteration, getIterationDocument } from '../../../shared/lib/api'
import { documentLabel, iterationStatusLabel } from '../../../shared/lib/labels'
import type { ArtifactComparisonResponse, IterationDetail, IterationSummary } from '../../../shared/lib/types'
import { RunningIndicator } from '../../../shared/ui/RunningIndicator'
import {
  artifactOptions,
  comparisonCandidates,
  defaultArtifactName,
  diffLineStats,
  type ArtifactOption,
} from '../lib/artifactCompare'
import styles from './ArtifactComparePanel.module.less'

interface Props {
  currentDetail: IterationDetail | null
  iterations: IterationSummary[]
}

const ON_DEMAND_NODES = new Set(['log_summarizer', 'artifact_comparator'])

export function TaskArtifactComparePanel({ currentDetail, iterations }: Props) {
  const candidates = useMemo(
    () => comparisonCandidates(iterations, currentDetail?.id ?? null),
    [iterations, currentDetail?.id],
  )
  const candidateKey = candidates.map((item) => item.id).join('|')
  const [targetId, setTargetId] = useState<string | null>(null)
  const [targetDetail, setTargetDetail] = useState<IterationDetail | null>(null)
  const [targetLoading, setTargetLoading] = useState(false)
  const [targetError, setTargetError] = useState<string | null>(null)
  const [comparison, setComparison] = useState<ArtifactComparisonResponse | null>(null)
  const [comparisonLoading, setComparisonLoading] = useState(false)
  const [comparisonGenerating, setComparisonGenerating] = useState(false)
  const [comparisonError, setComparisonError] = useState<string | null>(null)
  const [selectedArtifact, setSelectedArtifact] = useState<string | null>(null)
  const [currentDocText, setCurrentDocText] = useState('')
  const [targetDocText, setTargetDocText] = useState('')
  const [docLoading, setDocLoading] = useState(false)
  const [docError, setDocError] = useState<string | null>(null)

  const comparisonEventKey = useMemo(
    () => (currentDetail?.events ?? [])
      .filter((event) => event.type.startsWith('artifact_comparison.'))
      .map((event) => event.id)
      .join('|'),
    [currentDetail?.events],
  )

  const options = useMemo(() => artifactOptions(currentDetail, targetDetail), [currentDetail, targetDetail])
  const selectedOption = options.find((item) => item.name === selectedArtifact) ?? null
  const diffStats = useMemo(() => diffLineStats(currentDocText, targetDocText), [currentDocText, targetDocText])

  useEffect(() => {
    if (!candidates.length) {
      setTargetId(null)
      return
    }
    if (!targetId || !candidates.some((item) => item.id === targetId)) {
      setTargetId(candidates[0].id)
    }
  }, [candidateKey, targetId])

  useEffect(() => {
    let cancelled = false
    if (!targetId) {
      setTargetDetail(null)
      setTargetError(null)
      return
    }
    setTargetLoading(true)
    setTargetError(null)
    getIteration(targetId)
      .then((detail) => {
        if (!cancelled) setTargetDetail(detail)
      })
      .catch((exc) => {
        if (!cancelled) {
          setTargetDetail(null)
          setTargetError(exc instanceof Error ? exc.message : '读取对比任务失败')
        }
      })
      .finally(() => {
        if (!cancelled) setTargetLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [targetId])

  useEffect(() => {
    const next = defaultArtifactName(currentDetail, targetDetail)
    if (!selectedArtifact || !options.some((item) => item.name === selectedArtifact)) {
      setSelectedArtifact(next)
    }
  }, [currentDetail?.id, targetDetail?.id, options.map((item) => item.name).join('|'), selectedArtifact])

  useEffect(() => {
    let cancelled = false
    if (!currentDetail || !targetId) {
      setComparison(null)
      setComparisonError(null)
      return
    }
    setComparisonLoading(true)
    setComparisonError(null)
    getArtifactComparison(currentDetail.id, targetId)
      .then((payload) => {
        if (!cancelled) setComparison(payload)
      })
      .catch((exc) => {
        if (!cancelled) {
          setComparison(null)
          setComparisonError(exc instanceof Error ? exc.message : '读取产物对比失败')
        }
      })
      .finally(() => {
        if (!cancelled) setComparisonLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [currentDetail?.id, targetId, comparisonEventKey])

  useEffect(() => {
    let cancelled = false
    async function loadDocs(option: ArtifactOption) {
      setDocLoading(true)
      setDocError(null)
      try {
        const [currentText, targetText] = await Promise.all([
          currentDetail && option.current ? getIterationDocument(currentDetail.id, option.name) : Promise.resolve(''),
          targetDetail && option.target ? getIterationDocument(targetDetail.id, option.name) : Promise.resolve(''),
        ])
        if (!cancelled) {
          setCurrentDocText(currentText)
          setTargetDocText(targetText)
        }
      } catch (exc) {
        if (!cancelled) {
          setCurrentDocText('')
          setTargetDocText('')
          setDocError(exc instanceof Error ? exc.message : '读取文档失败')
        }
      } finally {
        if (!cancelled) setDocLoading(false)
      }
    }
    if (!selectedOption) {
      setCurrentDocText('')
      setTargetDocText('')
      setDocError(null)
      return
    }
    loadDocs(selectedOption).catch(console.error)
    return () => {
      cancelled = true
    }
  }, [currentDetail?.id, targetDetail?.id, selectedArtifact, selectedOption?.presence])

  const handleGenerate = useCallback(async () => {
    if (!currentDetail || !targetId) return
    setComparisonGenerating(true)
    setComparisonError(null)
    try {
      const payload = await generateArtifactComparison(currentDetail.id, targetId)
      setComparison(payload)
    } catch (exc) {
      setComparisonError(exc instanceof Error ? exc.message : '生成产物对比失败')
    } finally {
      setComparisonGenerating(false)
    }
  }, [currentDetail, targetId])

  if (!currentDetail) return null

  return (
    <div className={styles.root}>
      <section className={styles.toolbar}>
        <label className={styles.selectorLabel}>
          <span>对比任务</span>
          <select value={targetId ?? ''} onChange={(event) => setTargetId(event.target.value || null)} disabled={!candidates.length || targetLoading}>
            {!candidates.length ? <option value="">暂无可对比任务</option> : null}
            {candidates.map((item) => (
              <option key={item.id} value={item.id}>
                {compactGoal(item.goal)} · {iterationStatusLabel[item.status]} · {shortId(item.id)}
              </option>
            ))}
          </select>
        </label>
        {targetLoading ? <RunningIndicator size="sm" mode="dot" label="读取任务" /> : null}
      </section>

      {targetError ? <div className="error-text">{targetError}</div> : null}
      {!candidates.length ? <div className="empty">同项目下还没有另一条任务可对比。</div> : null}

      {targetDetail ? (
        <>
          <section className={styles.summaryGrid}>
            <IterationStatCard title="当前任务" detail={currentDetail} />
            <IterationStatCard title="对比任务" detail={targetDetail} />
          </section>

          <section className={styles.artifactArea}>
            <div className={styles.artifactList} aria-label="产物列表">
              {options.map((option) => (
                <button
                  key={option.name}
                  type="button"
                  className={`${styles.artifactButton} ${selectedArtifact === option.name ? styles.artifactButtonActive : ''}`}
                  onClick={() => setSelectedArtifact(option.name)}
                >
                  <span>{documentLabel(option.name)}</span>
                  <small>{presenceLabel(option.presence)}</small>
                </button>
              ))}
            </div>
            <div className={styles.diffPanel}>
              <div className={styles.diffHeader}>
                <div>
                  <h3>{selectedArtifact ? documentLabel(selectedArtifact) : '产物差异'}</h3>
                  <p className="muted">
                    当前 {diffStats.current_lines} 行 · 对比 {diffStats.target_lines} 行 · 变更 {diffStats.changed} · 新增 {diffStats.added} · 删除 {diffStats.removed}
                  </p>
                </div>
                {docLoading ? <RunningIndicator size="sm" mode="dot" label="读取文档" /> : null}
              </div>
              {docError ? <div className="error-text">{docError}</div> : null}
              <div className={styles.diffColumns}>
                <DocumentPreview title="当前任务" text={currentDocText} missing={!selectedOption?.current} />
                <DocumentPreview title="对比任务" text={targetDocText} missing={!selectedOption?.target} />
              </div>
            </div>
          </section>

          <section className={styles.aiPanel}>
            <div className={styles.aiHeader}>
              <div>
                <h3>AI 对比分析</h3>
                {comparison?.generated_at ? <p className="muted">生成于 {new Date(comparison.generated_at).toLocaleString()}</p> : null}
              </div>
              <div className={styles.aiActions}>
                {comparisonLoading ? <RunningIndicator size="sm" mode="dot" label="读取分析" /> : null}
                {comparison?.generating || comparisonGenerating ? <RunningIndicator size="sm" mode="dot" label="分析中" /> : null}
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={handleGenerate}
                  disabled={!targetId || comparisonGenerating || comparison?.generating}
                >
                  {comparison?.generated ? '重新生成分析' : '生成 AI 对比分析'}
                </button>
              </div>
            </div>
            {comparisonError || comparison?.error ? <div className="error-text">{comparisonError ?? comparison?.error}</div> : null}
            {comparison ? <ComparisonResult comparison={comparison} /> : null}
          </section>
        </>
      ) : null}
    </div>
  )
}

function IterationStatCard({ title, detail }: { title: string; detail: IterationDetail }) {
  const metrics = iterationMetrics(detail)
  return (
    <article className={styles.statCard}>
      <div>
        <span className="eyebrow">{title}</span>
        <strong>{iterationStatusLabel[detail.status]}</strong>
      </div>
      <p>{compactGoal(detail.goal, 120)}</p>
      <div className={styles.statGrid}>
        <span>Run {metrics.mainRuns}</span>
        <span>失败 {metrics.failedRuns}</span>
        <span>产物 {detail.documents.length}</span>
        <span>UI {detail.ui_results.length}</span>
      </div>
      {detail.last_error ? <small className={styles.errorLine}>{detail.last_error}</small> : null}
    </article>
  )
}

function DocumentPreview({ title, text, missing }: { title: string; text: string; missing: boolean }) {
  return (
    <div className={styles.docPreview}>
      <strong>{title}</strong>
      {missing ? <div className={styles.missingDoc}>未生成该产物。</div> : <pre>{text || '空文档'}</pre>}
    </div>
  )
}

function ComparisonResult({ comparison }: { comparison: ArtifactComparisonResponse }) {
  return (
    <div className={styles.comparisonResult}>
      <div className={styles.verdictRow}>
        <span>{verdictLabel(comparison.verdict)}</span>
        <p>{comparison.overall_summary || '暂无总结。'}</p>
      </div>
      <div className={styles.resultBlock}>
        <strong>稳定性判断</strong>
        <p>{comparison.stability_assessment || '暂无稳定性判断。'}</p>
      </div>
      <ComparisonTable
        title="维度对比"
        columns={['维度', '当前', '对比', '判断']}
        rows={comparison.dimensions.map((item) => [item.dimension, item.current, item.target, joinText(item.assessment, item.evidence)])}
        empty="暂无维度对比。"
      />
      <ComparisonTable
        title="产物发现"
        columns={['产物', '状态', '说明']}
        rows={comparison.artifact_findings.map((item) => [documentLabel(item.artifact), findingStatusLabel(item.status), joinText(item.summary, item.evidence)])}
        empty="暂无产物发现。"
      />
      <ComparisonTable
        title="验收对比"
        columns={['验收点', '当前', '对比', '判断']}
        rows={comparison.acceptance_comparison.map((item) => [item.point, item.current_status, item.target_status, joinText(item.assessment, item.evidence)])}
        empty="暂无验收对比。"
      />
      {comparison.risks_or_followups.length ? (
        <div className={styles.resultBlock}>
          <strong>风险与后续</strong>
          <ul>
            {comparison.risks_or_followups.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

function ComparisonTable({ title, columns, rows, empty }: { title: string; columns: string[]; rows: string[][]; empty: string }) {
  return (
    <div className={styles.tableBlock}>
      <strong>{title}</strong>
      <div className={styles.table} style={{ '--columns': columns.length } as CSSProperties & Record<'--columns', number>}>
        <div className={styles.tableHead}>
          {columns.map((column) => <span key={column}>{column}</span>)}
        </div>
        {rows.length ? rows.map((row, index) => (
          <div key={`${title}-${index}`} className={styles.tableRow}>
            {row.map((cell, cellIndex) => <span key={`${title}-${index}-${cellIndex}`}>{cell || '暂无'}</span>)}
          </div>
        )) : <div className={styles.tableEmpty}>{empty}</div>}
      </div>
    </div>
  )
}

function iterationMetrics(detail: IterationDetail) {
  const mainRuns = detail.runs.filter((run) => !ON_DEMAND_NODES.has(run.node)).length
  const failedRuns = detail.runs.filter((run) => !ON_DEMAND_NODES.has(run.node) && run.status !== 'success').length
  return { mainRuns, failedRuns }
}

function compactGoal(value: string, limit = 72) {
  const text = value.replace(/\s+/g, ' ').trim()
  if (text.length <= limit) return text || '未命名任务'
  return `${text.slice(0, limit)}...`
}

function shortId(value: string) {
  return value.replace(/^iter_/, '').slice(0, 8)
}

function presenceLabel(value: string) {
  const labels: Record<string, string> = {
    same: '一致',
    different: '不同',
    current_only: '仅当前',
    target_only: '仅对比',
    missing: '缺失',
  }
  return labels[value] ?? value
}

function findingStatusLabel(value: string) {
  const labels: Record<string, string> = {
    same: '一致',
    different: '不同',
    current_only: '仅当前',
    target_only: '仅对比',
    missing_both: '均缺失',
  }
  return labels[value] ?? value
}

function verdictLabel(value: string) {
  const labels: Record<string, string> = {
    current_better: '当前更优',
    target_better: '对比任务更优',
    mixed: '各有优劣',
    equivalent: '基本相当',
    inconclusive: '证据不足',
  }
  return labels[value] ?? value
}

function joinText(primary: string, evidence: string) {
  return [primary, evidence].filter(Boolean).join(' · ')
}
