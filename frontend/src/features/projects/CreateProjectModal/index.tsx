import { CreateProjectDialog } from '../CreateProjectDialog'
import type { CreateProjectInput } from '../../../shared/lib/types'
import styles from './CreateProjectModal.module.less'

interface Props {
  open: boolean
  onClose: () => void
  onCreate: (input: CreateProjectInput) => Promise<void>
}

export function CreateProjectModal({ open, onClose, onCreate }: Props) {
  if (!open) return null

  return (
    <div className={styles.overlay} onClick={onClose} role="presentation">
      <div className={`${styles.card} surface`} onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true">
        <div className={styles.header}>
          <h2 className="section-title">打开 / 新建项目</h2>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
            关闭
          </button>
        </div>
        <CreateProjectDialog
          embedded
          onCreate={async (input) => {
            await onCreate(input)
            onClose()
          }}
        />
      </div>
    </div>
  )
}
