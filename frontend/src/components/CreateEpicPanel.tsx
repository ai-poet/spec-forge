import { useState } from 'react'

interface Props {
  disabled: boolean
  onCreate: (input: { title: string; description: string; acceptance_criteria: string }) => Promise<void>
}

export function CreateEpicPanel({ disabled, onCreate }: Props) {
  const [title, setTitle] = useState('新需求')
  const [description, setDescription] = useState('描述这次要完成的业务目标')
  const [acceptanceCriteria, setAcceptanceCriteria] = useState('- 所有计划内测试通过\n- 验证报告通过并进入已交付状态')
  const [busy, setBusy] = useState(false)

  async function handleCreate() {
    if (!title.trim()) return
    setBusy(true)
    try {
      await onCreate({
        title: title.trim(),
        description: description.trim(),
        acceptance_criteria: acceptanceCriteria.trim(),
      })
      setTitle('')
      setDescription('')
      setAcceptanceCriteria('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel stack">
      <h2 className="section-title">新建大需求</h2>
      <div className="form">
        <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="需求标题" disabled={disabled} />
        <textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="需求描述" disabled={disabled} />
        <textarea value={acceptanceCriteria} onChange={(event) => setAcceptanceCriteria(event.target.value)} placeholder="验收标准" disabled={disabled} />
        <button className="btn primary" onClick={handleCreate} disabled={busy || disabled || !title.trim()}>
          创建大需求
        </button>
      </div>
    </section>
  )
}
