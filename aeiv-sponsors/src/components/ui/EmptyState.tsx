interface EmptyStateProps {
  title: string
  description?: string
  children?: React.ReactNode
}

export function EmptyState({ title, description, children }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <h2>{title}</h2>
      {description ? <p>{description}</p> : null}
      {children}
    </div>
  )
}
