import { useEffect, useMemo, useRef, useState } from 'react'
import { approveDesign, approveVerify, createIteration, getIteration, listIterations, stopIteration } from './api'
import type { IterationDetail, IterationSummary } from './types'

export default function App() {
  const [iterations, setIterations] = useState<IterationSummary[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<IterationDetail | null>(null)
  const [projectName, setProjectName] = useState('specforge-demo')
  const [goal, setGoal] = useState('Build a spec-first pipeline dashboard')
  const [mode, setMode] = useState<'dry-run' | 'real-cli'>('dry-run')
  const [busy, setBusy] = useState(false)
  const [docName, setDocName] = useState('system_design')
  const [docText, setDocText] = useState('')
  const [liveError, setLiveError] = useState<string | null>(null)
  const docNameRef = useRef(docName)

  async function refresh() {
    const items = await listIterations()
    setIterations(items)
    if (items.length && !selected) {
      setSelected(items[0].id)
    }
  }

  async function loadDetail(id: string) {
    const data = await getIteration(id)
    setDetail(data)
    const doc = data.documents.find((item) => item.name === docName) ?? data.documents[0]
    if (doc) {
      setDocName(doc.name)
      const response = await fetch(`http://127.0.0.1:8787/api/iterations/${id}/documents/${doc.name}`)
      const json = await response.json()
      setDocText(json.content)
    } else {
      setDocText('')
    }
  }

  useEffect(() => {
    refresh().catch(console.error)
  }, [])

  useEffect(() => {
    if (selected) {
      loadDetail(selected).catch(console.error)
    }
  }, [selected])

  useEffect(() => {
    docNameRef.current = docName
  }, [docName])

  useEffect(() => {
    if (!selected) {
      return
    }
    const socket = new WebSocket(`ws://127.0.0.1:8787/ws/iterations/${selected}`)
    socket.onmessage = async (event) => {
      try {
        const snapshot = JSON.parse(event.data) as IterationDetail
        setDetail(snapshot)
        setLiveError(null)
        const doc = snapshot.documents.find((item) => item.name === docNameRef.current) ?? snapshot.documents[0]
        if (doc) {
          const response = await fetch(`http://127.0.0.1:8787/api/iterations/${selected}/documents/${doc.name}`)
          const json = await response.json()
          setDocText(json.content)
          if (doc.name !== docNameRef.current) {
            setDocName(doc.name)
          }
        } else {
          setDocText('')
        }
      } catch (error) {
        setLiveError(error instanceof Error ? error.message : String(error))
      }
    }
    socket.onerror = () => {
      setLiveError('Live feed disconnected')
    }
    return () => socket.close()
  }, [selected])

  const activeIteration = detail ?? null

  const statusCards = useMemo(() => {
    const current = activeIteration?.current_node ?? null
    return [
      { key: 'planner', label: 'Planner' },
      { key: 'coder', label: 'Coder' },
      { key: 'tester', label: 'Tester' },
    ].map((node) => ({
      ...node,
      active: current === node.key,
    }))
  }, [activeIteration?.current_node])

  async function handleCreate() {
    setBusy(true)
    try {
      const item = await createIteration({
        project_name: projectName,
        goal,
        mode,
      })
      await refresh()
      setSelected(item.id)
    } finally {
      setBusy(false)
    }
  }

  async function handleApproveDesign() {
    if (!selected) return
    setBusy(true)
    try {
      await approveDesign(selected)
      await loadDetail(selected)
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  async function handleApproveVerify() {
    if (!selected) return
    setBusy(true)
    try {
      await approveVerify(selected)
      await loadDetail(selected)
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  async function handleStop() {
    if (!selected) return
    setBusy(true)
    try {
      await stopIteration(selected, 'user stop')
      await loadDetail(selected)
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  async function loadDocument(name: string) {
    if (!selected) return
    setDocName(name)
    const response = await fetch(`http://127.0.0.1:8787/api/iterations/${selected}/documents/${name}`)
    const json = await response.json()
    setDocText(json.content)
  }

  return (
    <div className="app">
      <aside className="sidebar stack">
        <div className="panel stack">
          <div>
            <h1 style={{ margin: 0, fontSize: 20 }}>SpecForge</h1>
            <p className="muted" style={{ margin: '6px 0 0' }}>
              Local spec-first agent pipeline
            </p>
          </div>
          <div className="form">
            <input value={projectName} onChange={(e) => setProjectName(e.target.value)} placeholder="Project name" />
            <textarea value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="Goal" />
            <select value={mode} onChange={(e) => setMode(e.target.value as 'dry-run' | 'real-cli')}>
              <option value="dry-run">dry-run</option>
              <option value="real-cli">real-cli</option>
            </select>
            <button className="btn primary" onClick={handleCreate} disabled={busy}>
              Create iteration
            </button>
          </div>
        </div>

        <div className="panel stack">
          <h2 className="section-title">Iterations</h2>
          <div className="list">
            {iterations.map((item) => (
              <button
                key={item.id}
                className={`item ${selected === item.id ? 'active' : ''}`}
                onClick={() => setSelected(item.id)}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <strong>{item.project_name}</strong>
                  <span className="muted">{item.status}</span>
                </div>
                <div className="muted" style={{ marginTop: 6, fontSize: 12 }}>
                  {item.goal}
                </div>
              </button>
            ))}
          </div>
        </div>
      </aside>

      <main className="main stack">
        <div className="panel stack">
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <h2 className="section-title">Pipeline</h2>
              <div className="muted">{activeIteration?.project_name ?? 'No iteration selected'}</div>
              {activeIteration ? (
                <div className="muted" style={{ marginTop: 4 }}>
                  Graph next: {activeIteration.graph_next.length ? activeIteration.graph_next.join(', ') : 'done'}
                </div>
              ) : null}
              {liveError ? <div className="muted" style={{ color: '#ffb4b4', marginTop: 4 }}>{liveError}</div> : null}
            </div>
            <div className="actions">
              <button className="btn" onClick={handleApproveDesign} disabled={busy || activeIteration?.status !== 'awaiting_design_approval'}>
                Approve design
              </button>
              <button className="btn" onClick={handleApproveVerify} disabled={busy || activeIteration?.status !== 'awaiting_verify_approval'}>
                Approve verify
              </button>
              <button className="btn" onClick={handleStop} disabled={busy || !activeIteration}>
                Stop
              </button>
            </div>
          </div>

          <div className="board">
            {statusCards.map((node) => (
              <div key={node.key} className={`node ${node.active ? 'active' : ''}`}>
                <strong>{node.label}</strong>
                <div className="muted" style={{ marginTop: 6 }}>
                  {node.active ? 'Active' : 'Idle'}
                </div>
              </div>
            ))}
            <div className={`node ${activeIteration?.status === 'awaiting_design_approval' ? 'active' : ''}`}>
              <strong>Design approval</strong>
              <div className="muted" style={{ marginTop: 6 }}>
                {activeIteration?.status === 'awaiting_design_approval' ? 'Waiting' : 'Done'}
              </div>
            </div>
            <div className={`node ${activeIteration?.status === 'awaiting_verify_approval' ? 'active' : ''}`}>
              <strong>Verify approval</strong>
              <div className="muted" style={{ marginTop: 6 }}>
                {activeIteration?.status === 'awaiting_verify_approval' ? 'Waiting' : 'Done'}
              </div>
            </div>
            <div className={`node ${activeIteration?.status === 'delivered' ? 'active' : ''}`}>
              <strong>Delivered</strong>
              <div className="muted" style={{ marginTop: 6 }}>
                {activeIteration?.status === 'delivered' ? 'Complete' : 'Pending'}
              </div>
            </div>
          </div>
        </div>

        <div className="grid">
          <div className="panel stack">
            <h2 className="section-title">Documents</h2>
            <div className="actions">
              {detail?.documents.map((doc) => (
                <button key={doc.name} className="btn" onClick={() => loadDocument(doc.name)}>
                  {doc.name}
                </button>
              ))}
            </div>
            <div className="docs code">{docText || 'No document selected'}</div>
          </div>

          <div className="panel stack">
            <h2 className="section-title">Timeline</h2>
            <div className="timeline">
              {detail?.events.map((event) => (
                <div key={event.id} className="item">
                  <strong>{event.type}</strong>
                  <div className="muted" style={{ marginTop: 4, fontSize: 12 }}>
                    {JSON.stringify(event.payload)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="panel stack">
          <h2 className="section-title">Run logs</h2>
          <div className="timeline">
            {detail?.runs.length ? (
              detail.runs.map((run) => (
                <div key={run.id} className="item">
                  <strong>{run.node}</strong>
                  <div className="muted" style={{ marginTop: 4 }}>
                    {run.status} {run.command}
                  </div>
                  <pre className="code" style={{ whiteSpace: 'pre-wrap' }}>
                    {run.stdout}
                  </pre>
                </div>
              ))
            ) : (
              <div className="muted">No runs yet.</div>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}
