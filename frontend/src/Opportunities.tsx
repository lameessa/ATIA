import { ArrowRight, ChevronDown, Layers, MapPin } from 'lucide-react'
import { Modal, Notice, SourceLink } from './components'
import { Media, MediaCredit } from './Media'
import { CampaignStatus } from './CampaignWorkspace'
import type { Opportunity } from './productTypes'

export const opportunityTitle = (o: Opportunity) => o.title.en || o.title.ar || 'Opportunity'
const kindLabel = (o: Opportunity) =>
  o.kind === 'named_destination' ? 'Destination' : 'Regional experience'
const place = (o: Opportunity) => o.regions.map((r) => r.en).join(' · ') || 'Saudi Arabia'
const evidenceLine = (o: Opportunity) => {
  const { photo_count: photos, distinct_photographers: people } = o.evidence
  return `${photos} ${photos === 1 ? 'photo' : 'photos'} · ${people} ${people === 1 ? 'photographer' : 'photographers'}`
}
const plate = (o: Opportunity) => ({ seed: o.id, region: undefined })

export function OpportunityCard({
  opportunity: o,
  onOpen,
  onCreate,
}: {
  opportunity: Opportunity
  onOpen: (o: Opportunity) => void
  onCreate: (o: Opportunity) => void
}) {
  return (
    <article className="destination-card">
      <button className="destination-open" onClick={() => onOpen(o)}>
        <div className="destination-image">
          <Media asset={o.media} plate={plate(o)} alt={o.media?.title} />
          <span className={`identity-chip evidence-${o.evidence_strength}`}>
            <Layers size={12} /> {o.evidence_label}
          </span>
        </div>
        <div className="destination-copy">
          <span className="destination-region">
            {kindLabel(o)} · {place(o)}
          </span>
          <h3 dir="auto">{opportunityTitle(o)}</h3>
          <p dir="auto">{o.angle.en}</p>
          <small className="muted">{evidenceLine(o)}</small>
          <span className="text-link">
            View opportunity <ArrowRight size={13} />
          </span>
        </div>
      </button>
      <button className="button small card-action" onClick={() => onCreate(o)}>
        {o.campaign_id ? 'Open campaign' : 'Create Campaign'} <ArrowRight size={13} />
      </button>
    </article>
  )
}

export function OpportunityDetail({
  opportunity: o,
  onClose,
  onCreate,
}: {
  opportunity: Opportunity
  onClose: () => void
  onCreate: (o: Opportunity) => void
}) {
  return (
    <Modal wide title={<span dir="auto">{opportunityTitle(o)}</span>} onClose={onClose}>
      <div className="destination-profile-header">
        <div>
          <span>
            {kindLabel(o)} · {place(o)}
          </span>
          <p>
            {o.evidence_label} · {evidenceLine(o)}
          </p>
        </div>
        <div className="section-tools">
          {o.campaign_status && <CampaignStatus value={o.campaign_status} />}
          <button className="button primary" onClick={() => onCreate(o)}>
            {o.campaign_id ? 'Open campaign' : 'Create Campaign'} <ArrowRight size={15} />
          </button>
        </div>
      </div>
      <div className="detail-columns">
        <div className="detail-main">
          <div className="hero-frame">
            <Media
              asset={o.media}
              className="destination-detail-hero"
              plate={plate(o)}
              alt={o.media?.title}
            />
            {o.media && <MediaCredit asset={o.media} />}
          </div>
          <p className="muted small photo-note">
            {o.licensed_images
              ? `${o.licensed_images} approved ${o.licensed_images === 1 ? 'image' : 'images'} available for a campaign.`
              : 'No image approved for display yet. A text-only draft is possible; the Flickr records below remain as evidence.'}
          </p>
          <section className="profile-overview">
            <h3>Marketing angle</h3>
            <p>{o.angle.en}</p>
            <p dir="rtl" lang="ar">
              {o.angle.ar}
            </p>
            {o.sensitive_note && <Notice>{o.sensitive_note}</Notice>}
          </section>
          <div className="insight-grid">
            <article>
              <h4>Flickr evidence</h4>
              <p>{evidenceLine(o)}</p>
              <small>
                {o.evidence.views.total.toLocaleString()} views ·{' '}
                {o.evidence.favorites.total.toLocaleString()} favourites ·{' '}
                {o.evidence.comments.total.toLocaleString()} comments
              </small>
            </article>
            <article>
              <h4>Identity</h4>
              <p>
                {o.identity_status === 'verified_entity_exists'
                  ? 'An authoritative source confirms this place exists.'
                  : o.kind === 'named_destination'
                    ? 'Name read from Flickr metadata; not yet confirmed.'
                    : 'A regional experience; no single named site is claimed.'}
              </p>
              <small>
                <MapPin size={11} className="inline-icon" />{' '}
                {o.localities.slice(0, 3).join(' · ') || place(o)}
              </small>
            </article>
          </div>
          <details className="evidence-drawer">
            <summary>
              <Layers size={17} /> What has not been assessed <ChevronDown size={16} />
            </summary>
            <div>
              <p>
                Promotional coverage, visitor demand and underrepresentation have not been
                researched. Engagement describes these photographs, not tourism demand, and low
                engagement is not evidence of underpromotion.
              </p>
            </div>
          </details>
        </div>
        <section className="research-findings">
          <h3>Supporting evidence</h3>
          {o.evidence_photos.map((p) => (
            <article key={p.evidence_ref}>
              <SourceLink
                source={{
                  title: p.title || 'Untitled Flickr photograph',
                  url: p.photo_url || '',
                  publisher: `Flickr · ${p.photographer || 'photographer not recorded'}`,
                }}
              />
              {p.description && <p dir="auto">{p.description.slice(0, 200)}</p>}
            </article>
          ))}
          {o.research.map((r) => (
            <article key={r.url}>
              <SourceLink source={{ title: r.title, url: r.url, publisher: r.publisher }} />
            </article>
          ))}
        </section>
      </div>
      {o.gallery.length > 1 && (
        <section className="context-gallery">
          <h3>Images</h3>
          <div className="context-grid">
            {o.gallery.map((m) => (
              <article key={m.media_id}>
                <Media asset={m} alt={m.title} />
                <MediaCredit asset={m} />
              </article>
            ))}
          </div>
        </section>
      )}
    </Modal>
  )
}
