interface Props {
  variant: 'no-project' | 'no-epic' | 'no-iteration'
  projectName?: string
  epicTitle?: string
}

const copy: Record<Props['variant'], { title: string; body: string }> = {
  'no-project': {
    title: '选择一个项目开始',
    body: '从左侧选择已有项目，或点击「打开 / 新建项目」选择本地文件夹。',
  },
  'no-epic': {
    title: '选择或创建大需求',
    body: '大需求用于组织一次业务目标下的多条流水线迭代。',
  },
  'no-iteration': {
    title: '选择或创建流水线',
    body: '系统将按 Planner → Coder → Tester 自动推进。',
  },
}

export function EmptyWorkspace({ variant, projectName, epicTitle }: Props) {
  const content = copy[variant]
  return (
    <div className="workspace-empty">
      <h2>{content.title}</h2>
      <p className="muted">{content.body}</p>
      {projectName ? <p className="workspace-empty-context">{projectName}</p> : null}
      {epicTitle ? <p className="workspace-empty-context">{epicTitle}</p> : null}
    </div>
  )
}
