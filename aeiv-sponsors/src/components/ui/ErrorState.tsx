interface ErrorStateProps {
  title?: string
  message: string
  onRetry?: () => void
}

export function ErrorState({ title = 'Something went wrong', message, onRetry }: ErrorStateProps) {
  return (
    <div role="alert" className="error-state">
      <h2>{title}</h2>
      <p>{message}</p>
      {onRetry ? (
        <button type="button" onClick={onRetry} className="button">
          Try again
        </button>
      ) : null}
    </div>
  )
}
