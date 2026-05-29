interface Props {
  variant: 'no-project' | 'ready'
  projectName?: string
  epicTitle?: string
  onStartPipeline?: () => void
}

const copy: Record<Props['variant'], { title: string; body: string }> = {
  'no-project': {
    title: '选择一个项目开始',
    body: '从左侧选择已有项目，或点击「打开 / 新建项目」选择本地文件夹。',
  },
  ready: {
    title: '准备启动流水线',
    body: '描述你的需求，系统将自动创建大需求并启动 Planner → Coder → Tester 流程。',
  },
}

export function EmptyWorkspace({ variant, projectName, epicTitle, onStartPipeline }: Props) {
  const content = copy[variant]
  return (
    <div className="workspace-empty">
      <h2>{content.title}</h2>
      <p className="muted">{content.body}</p>
      {projectName ? <p className="workspace-empty-context">{projectName}</p> : null}
      {epicTitle ? <p className="workspace-empty-context">{epicTitle}</p> : null}
      {onStartPipeline ? (
        <button type="button" className="btn btn-ghost btn-sm pipeline-entry-btn" onClick={onStartPipeline}>
          新建流水线
        </button>
      ) : null}
    </div>
  )
}
