import styles from './RunningIndicator.module.less'

interface Props {
  label?: string
  size?: 'sm' | 'md'
  mode?: 'dot' | 'spinner' | 'both'
  className?: string
}

export function RunningIndicator({ label, size = 'md', mode = 'both', className }: Props) {
  const showDot = mode === 'dot' || mode === 'both'
  const showSpinner = mode === 'spinner' || mode === 'both'

  return (
    <span className={[styles.root, styles[size], className].filter(Boolean).join(' ')} aria-live="polite">
      {showDot ? <span className={styles.dot} aria-hidden="true" /> : null}
      {showSpinner ? <span className={styles.spinner} aria-hidden="true" /> : null}
      {label ? <span className={styles.label}>{label}</span> : null}
    </span>
  )
}
