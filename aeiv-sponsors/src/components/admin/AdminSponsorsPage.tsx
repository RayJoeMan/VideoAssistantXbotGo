import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAdminSponsors, useDeleteSponsor } from '../../hooks/useSponsors'
import { useTenantId } from '../../hooks/useTenant'
import { LoadingState } from '../ui/LoadingState'
import { EmptyState } from '../ui/EmptyState'
import { ErrorState } from '../ui/ErrorState'

/**
 * Admin sponsor list: search, sorting, delete-with-confirmation.
 * Permission-gated by the route (sponsors.view) and enforced server-side.
 */
export function AdminSponsorsPage() {
  const tenantId = useTenantId()
  const sponsorsQuery = useAdminSponsors(tenantId)
  const deleteMutation = useDeleteSponsor(tenantId)
  const [search, setSearch] = useState('')
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null)

  const sponsors = useMemo(() => {
    const list = sponsorsQuery.data ?? []
    const term = search.trim().toLowerCase()
    if (!term) return list
    return list.filter(
      (s) =>
        s.public.name.toLowerCase().includes(term) ||
        s.public.tier.toLowerCase().includes(term) ||
        s.admin.status.toLowerCase().includes(term),
    )
  }, [sponsorsQuery.data, search])

  const confirmDelete = async () => {
    if (!pendingDeleteId) return
    try {
      await deleteMutation.mutateAsync({ tenantId, sponsorId: pendingDeleteId })
    } finally {
      setPendingDeleteId(null)
    }
  }

  if (sponsorsQuery.isLoading) return <LoadingState label="Loading sponsors…" />
  if (sponsorsQuery.isError) {
    return (
      <ErrorState
        message="We couldn’t load the sponsor list."
        onRetry={() => void sponsorsQuery.refetch()}
      />
    )
  }

  return (
    <section className="admin-page" aria-labelledby="admin-sponsors-heading">
      <header className="admin-page__header">
        <h1 id="admin-sponsors-heading">Sponsors</h1>
        <Link className="button button--primary" to="/admin/sponsors/new">
          New sponsor
        </Link>
      </header>

      <div className="toolbar">
        <label className="sr-only" htmlFor="sponsor-search">
          Search sponsors
        </label>
        <input
          id="sponsor-search"
          type="search"
          placeholder="Search by name, tier, or status…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {(sponsors?.length ?? 0) === 0 ? (
        <EmptyState
          title="No sponsors found"
          description={
            search ? 'Try a different search.' : 'Create your first sponsor to get started.'
          }
        >
          {!search ? (
            <Link className="button" to="/admin/sponsors/new">
              Create sponsor
            </Link>
          ) : null}
        </EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Tier</th>
                <th scope="col">Status</th>
                <th scope="col">Published</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {sponsors?.map((sponsor) => (
                <tr key={sponsor.public.id}>
                  <td>{sponsor.public.name}</td>
                  <td>{sponsor.public.tier}</td>
                  <td>{sponsor.admin.status}</td>
                  <td>{sponsor.public.published ? 'Yes' : 'No'}</td>
                  <td className="table-actions">
                    <Link
                      className="button button--small"
                      to={`/admin/sponsors/${sponsor.public.id}`}
                    >
                      Edit
                    </Link>
                    <button
                      type="button"
                      className="button button--small button--danger"
                      onClick={() => setPendingDeleteId(sponsor.public.id)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deleteMutation.isError ? (
        <p className="form-error" role="alert">
          {deleteMutation.error instanceof Error
            ? deleteMutation.error.message
            : 'Failed to delete sponsor.'}
        </p>
      ) : null}

      {pendingDeleteId ? (
        <div className="dialog-backdrop" role="presentation">
          <div
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-delete-title"
          >
            <h2 id="confirm-delete-title">Delete sponsor?</h2>
            <p>This permanently removes the sponsor and its admin data. This cannot be undone.</p>
            <div className="dialog__actions">
              <button type="button" className="button" onClick={() => setPendingDeleteId(null)}>
                Cancel
              </button>
              <button
                type="button"
                className="button button--danger"
                onClick={() => void confirmDelete()}
                disabled={deleteMutation.isPending}
              >
                {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  )
}
