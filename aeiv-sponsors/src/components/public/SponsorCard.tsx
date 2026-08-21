import { Link } from 'react-router-dom'
import type { PublicSponsor } from '../../schemas/sponsor'
import { trackEvent } from '../../analytics/events'

interface SponsorCardProps {
  tenantId: string
  sponsor: PublicSponsor
}

/** Public sponsor card — semantic HTML, inherits the host site's theme. */
export function SponsorCard({ tenantId, sponsor }: SponsorCardProps) {
  const handleVisit = () => {
    trackEvent(tenantId, 'sponsor_link_click', { sponsorId: sponsor.id })
  }

  return (
    <article className="sponsor-card">
      {sponsor.logoUrl ? (
        <img
          src={sponsor.logoUrl}
          alt={`${sponsor.name} logo`}
          className="sponsor-card__logo"
          loading="lazy"
        />
      ) : null}
      <h3 className="sponsor-card__name">{sponsor.name}</h3>
      <p className="sponsor-card__tier">Tier: {sponsor.tier}</p>
      {sponsor.tagline ? <p className="sponsor-card__tagline">{sponsor.tagline}</p> : null}
      {sponsor.description ? (
        <p className="sponsor-card__description">{sponsor.description}</p>
      ) : null}
      <div className="sponsor-card__actions">
        <Link className="button button--link" to={`/sponsors/${sponsor.id}`}>
          Learn more
        </Link>
        {sponsor.websiteUrl ? (
          <a
            className="button button--link"
            href={sponsor.websiteUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={handleVisit}
          >
            Visit website
          </a>
        ) : null}
      </div>
    </article>
  )
}
