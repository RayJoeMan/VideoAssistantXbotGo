interface LoadingStateProps {
  label?: string
}

export function LoadingState({ label = 'Loading…' }: LoadingStateProps) {
  return (
    <div role="status" aria-live="polite" className="loading-state">
      <span className="spinner" aria-hidden="true" />
      <p>{label}</p>
    </div>
  )
}
