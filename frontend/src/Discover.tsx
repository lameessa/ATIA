import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, ChevronDown, Loader2, Search, ShieldCheck } from 'lucide-react'
import { human, Modal, Notice, SourceLink } from './components'
import { api } from './api'
import { Media, MediaCredit } from './Media'
import { formatCoordinates, type PlateProps } from './Plate'
import { OpportunityCard } from './Opportunities'
import type { Destination, MediaAsset, Opportunity } from './productTypes'
import type { Dossier, Entity } from './types'

const isArabic = (value: string) => /[؀-ۿ]/.test(value)
const cleanTitle = (value: string) => value.replace(/[-_]+/g, ' ')

export const placeTitle = (a: Destination) => {
  if (a.entities.length === 1) return a.entities[0].verified_name
  if (a.entities.length > 1) return 'Location under review'
  const locality = (a.localities[0] as { name?: string } | undefined)?.name
  if (!locality) return 'Unidentified area'
  return isArabic(locality) ? locality : `${locality} area`
}
const region = (a: Destination) =>
  Object.keys(a.regions)
    .filter((r) => r !== 'unknown')
    .join(' · ') || 'Saudi Arabia'
export const verified = (a: Destination) =>
  a.entities.filter(
    (e) =>
      e.verification_status === 'authoritative_source_name_confirmed' &&
      ['destination', 'attraction'].includes(e.entity_type),
  )
const summary = (a: Destination) => {
  const source =
    a.entities.length === 1
      ? a.entities[0].sources?.find((s) => s.content_excerpt || s.evidence)
      : undefined
  const value = (source?.content_excerpt || source?.evidence || '').replace(/\s+/g, ' ').trim()
  return value ? value.slice(0, 120) + (value.length > 120 ? '…' : '') : ''
}
/** An approved hero wins; otherwise the area's own archive photograph, labelled as a reference. */
const cardAsset = (a: Destination): MediaAsset | null => a.media || a.context_media[0] || null
const plateFor = (a: Destination): PlateProps => ({
  seed: a.cluster_id,
  region: Object.keys(a.regions).find((r) => r !== 'unknown'),
  latitude: a.centroid?.latitude,
  longitude: a.centroid?.longitude,
})

export function DestinationCard({
  area,
  onSelect,
  onCreate,
}: {
  area: Destination
  onSelect: (a: Destination) => void
  onCreate?: (e: Entity) => void
}) {
  const entities = verified(area)
  const asset = cardAsset(area)
  const description = summary(area)
  return (
    <article className="destination-card">
      <button className="destination-open" onClick={() => onSelect(area)}>
        <div className="destination-image">
          <Media asset={asset} plate={plateFor(area)} alt={asset?.title} />
          {area.entities.length > 0 && (
            <span className="identity-chip">
              <ShieldCheck size={12} /> Verified identity
            </span>
          )}
        </div>
        <div className="destination-copy">
          <span className="destination-region">{region(area)}</span>
          <h3 dir="auto">{placeTitle(area)}</h3>
          {area.entities.length > 1 && (
            <p>{area.entities.map((e) => e.verified_name).join(' · ')}</p>
          )}
          {description && <p dir="auto">{description}</p>}
          <span className="text-link">
            View research <ArrowRight size={13} />
          </span>
        </div>
      </button>
      {onCreate && entities.length === 1 && (
        <button className="button small card-action" onClick={() => onCreate(entities[0])}>
          Create Campaign <ArrowRight size={13} />
        </button>
      )}
    </article>
  )
}

export default function Discover({
  areas,
  archive = [],
  opportunities = [],
  onSelect,
  onCreate,
  onOpportunity,
  onOpportunityCreate,
}: {
  areas: Destination[]
  archive?: MediaAsset[]
  opportunities?: Opportunity[]
  onSelect: (a: Destination) => void
  onCreate: (e: Entity) => void
  onOpportunity?: (o: Opportunity) => void
  onOpportunityCreate?: (o: Opportunity) => void
}) {
  // Opportunities replace the older per-destination path, which cannot produce a draft.
  const createFromCard = opportunities.length ? undefined : onCreate
  const [limit, setLimit] = useState(12)
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [selectedRegion, setRegion] = useState('all')
  const regions = useMemo(
    () =>
      Array.from(new Set(areas.flatMap((a) => Object.keys(a.regions))))
        .filter((r) => r !== 'unknown')
        .sort(),
    [areas],
  )
  const query = search.trim().toLowerCase()
  const visible = areas.filter(
    (a) =>
      (filter === 'all' ||
        (filter === 'verified' && a.entities.length > 0) ||
        (filter === 'hidden' && a.hidden_gem_candidate)) &&
      (selectedRegion === 'all' || selectedRegion in a.regions) &&
      `${placeTitle(a)} ${region(a)} ${a.entities.map((e) => e.verified_name).join(' ')}`
        .toLowerCase()
        .includes(query),
  )
  const named = visible.filter((a) => a.entities.length > 0)
  const unnamed = visible.filter((a) => a.entities.length === 0)
  const namedTotal = areas.filter((a) => a.entities.length > 0).length

  return (
    <>
      {archive.length > 0 && (
        <section className="archive-band" aria-label="Reviewed photographs">
          <div className="archive-intro">
            <span className="hero-label">Reviewed photographs</span>
            <h2>Saudi Arabia, place by place</h2>
            {areas.length > 0 && (
              <p>
                {namedTotal} verified {namedTotal === 1 ? 'identity area' : 'identity areas'} ·{' '}
                {areas.length - namedTotal} geographic areas
              </p>
            )}
          </div>
          {archive.map((asset) => (
            <figure className="archive-tile" key={asset.media_id}>
              <Media asset={asset} alt={asset.title} eager />
              <figcaption dir="auto">{cleanTitle(asset.title)}</figcaption>
              <MediaCredit asset={asset} />
            </figure>
          ))}
        </section>
      )}
      {opportunities.length > 0 && onOpportunity && onOpportunityCreate && (
        <section className="page-section">
          <div className="section-heading">
            <div>
              <h2>Marketing opportunities</h2>
              <p>
                Flickr evidence that could become a campaign. Evidence strength is shown as it is.
              </p>
            </div>
          </div>
          <div className="destination-grid featured">
            {opportunities.map((o) => (
              <OpportunityCard
                key={o.id}
                opportunity={o}
                onOpen={onOpportunity}
                onCreate={onOpportunityCreate}
              />
            ))}
          </div>
        </section>
      )}
      <div className="explorer-toolbar">
        <div className="filter-tabs" aria-label="Destination filters">
          <button className={filter === 'all' ? 'selected' : ''} onClick={() => setFilter('all')}>
            All destinations
          </button>
          <button
            className={filter === 'verified' ? 'selected' : ''}
            onClick={() => setFilter('verified')}
          >
            Verified identities
          </button>
          {areas.some((a) => a.hidden_gem_candidate) && (
            <button
              className={filter === 'hidden' ? 'selected' : ''}
              onClick={() => setFilter('hidden')}
            >
              Hidden-gem candidates
            </button>
          )}
        </div>
        <div className="search-controls">
          <label className="search-box">
            <Search size={15} />
            <input
              aria-label="Search destinations"
              placeholder="Find a destination"
              dir="auto"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <select
            aria-label="Filter by region"
            value={selectedRegion}
            onChange={(e) => setRegion(e.target.value)}
          >
            <option value="all">All regions</option>
            {regions.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </div>
      </div>
      {areas.length > 0 && !visible.length && (
        <div className="inline-empty">
          <strong>No matching places</strong>
          <p>Try another name, region or filter.</p>
        </div>
      )}
      {named.length > 0 && (
        <section className="page-section">
          <div className="section-heading">
            <div>
              <h2>Verified destinations</h2>
              <p>
                {createFromCard
                  ? 'Identity confirmed by authoritative sources, ready for campaign research.'
                  : 'Identity confirmed by authoritative sources. Research only: campaigns start from the marketing opportunities above.'}
              </p>
            </div>
          </div>
          <div className="destination-grid featured">
            {named.map((a) => (
              <DestinationCard
                key={a.cluster_id}
                area={a}
                onSelect={onSelect}
                onCreate={createFromCard}
              />
            ))}
          </div>
        </section>
      )}
      {unnamed.length > 0 && (
        <section className="page-section">
          <div className="section-heading">
            <div>
              <h2>Geographic areas</h2>
              <p>
                {createFromCard
                  ? 'Identity verification needed before ATIA can prepare a campaign here.'
                  : 'Research only: campaigns start from the marketing opportunities above.'}
              </p>
            </div>
          </div>
          <div className="destination-grid compact">
            {unnamed.slice(0, limit).map((a) => (
              <DestinationCard
                key={a.cluster_id}
                area={a}
                onSelect={onSelect}
                onCreate={createFromCard}
              />
            ))}
          </div>
          {unnamed.length > limit && (
            <div className="show-more">
              <button className="button quiet" onClick={() => setLimit((n) => n + 12)}>
                More destinations <ArrowRight size={15} />
              </button>
            </div>
          )}
        </section>
      )}
    </>
  )
}

export function DestinationDetail({
  area,
  onClose,
  onCreate,
}: {
  area: Destination
  onClose: () => void
  onCreate?: (e: Entity) => void
}) {
  const entities = verified(area)
  const [entityId, setEntityId] = useState(entities[0]?.entity_id || '')
  const [dossier, setDossier] = useState<Dossier>()
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    api<Dossier>(`/destinations/${encodeURIComponent(area.cluster_id)}`)
      .then((d) => {
        if (active) setDossier(d)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
    return () => {
      active = false
    }
  }, [area.cluster_id])
  const sources = [
    ...area.entities.flatMap((e) => e.sources || []),
    ...(dossier?.research?.sources || []),
  ].filter((s, i, all) => all.findIndex((v) => v.url === s.url) === i)
  const visual = (dossier?.evidence.visual.possible_environment_counts || {}) as Record<
    string,
    number
  >
  const sentiment = dossier?.evidence.sentiment as
    | { distribution?: Record<string, number>; classified_comments?: number }
    | undefined
  const hero = cardAsset(area)
  const gallery = area.context_media.filter((m) => m.media_id !== hero?.media_id)
  const coverage = dossier?.research?.coverage_status || dossier?.research?.research_status

  return (
    <Modal wide title={<span dir="auto">{placeTitle(area)}</span>} onClose={onClose}>
      <div className="destination-profile-header">
        <div>
          <span>{region(area)}</span>
          <p>
            {area.entities.length
              ? 'Source-verified place · photo association provisional'
              : 'Unresolved geographic area'}
            {area.centroid &&
              ` · ${formatCoordinates(area.centroid.latitude, area.centroid.longitude)}`}
          </p>
        </div>
        {onCreate && entities.length > 0 && (
          <button
            className="button primary"
            onClick={() => onCreate(entities.find((e) => e.entity_id === entityId)!)}
          >
            Create Campaign <ArrowRight size={15} />
          </button>
        )}
      </div>
      <div className="detail-columns">
        <div className="detail-main">
          <div className="hero-frame">
            <Media
              asset={hero}
              className="destination-detail-hero"
              plate={plateFor(area)}
              alt={hero?.title}
            />
            {hero && <MediaCredit asset={hero} />}
          </div>
          {hero && !area.media && (
            <p className="muted small photo-note">
              Internal archive context, not verified campaign assets.
            </p>
          )}
          {!hero && (
            <p className="muted small photo-note">
              Illustrative plate. No approved photograph is attached to this place yet.
            </p>
          )}
          <section className="profile-overview">
            <h3>Destination research</h3>
            <p>
              {entities.length
                ? 'Authoritative sources confirm the place’s identity. Geographic photo associations remain provisional; ATIA must validate the opportunity and campaign imagery before creating a draft.'
                : 'These Flickr records form a geographic candidate, not a verified attraction. Establishing a reliable identity is the next step.'}
            </p>
            {entities.length > 1 && (
              <label className="field">
                Destination for campaign research
                <select value={entityId} onChange={(e) => setEntityId(e.target.value)}>
                  {entities.map((e) => (
                    <option key={e.entity_id} value={e.entity_id}>
                      {e.verified_name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {area.entities.map((e) => (
              <div className="entity-note" key={e.entity_id}>
                <ShieldCheck size={17} />
                <div>
                  <strong dir="auto">{e.verified_name}</strong>
                  <p>
                    {e.entity_type === 'attraction'
                      ? 'Attraction'
                      : e.entity_type === 'region'
                        ? 'Geographic region'
                        : 'Destination'}
                    {e.parent_name ? ` · ${e.parent_name}` : ''}
                  </p>
                </div>
              </div>
            ))}
          </section>
          {error && <Notice tone="error">Research could not be loaded: {error}</Notice>}
          {!dossier && !error && (
            <p className="inline-loading">
              <Loader2 size={16} className="spinner" /> Loading saved research…
            </p>
          )}
          {dossier && (
            <div className="insight-grid">
              <article>
                <h4>Promotional coverage</h4>
                <p>
                  {coverage ? human(coverage) : 'No coverage assessment is attached to this area.'}
                </p>
                <small>
                  Stored research, not a fresh search. Missing results do not establish
                  underpromotion.
                </small>
              </article>
              <article>
                <h4>Opportunity assessment</h4>
                <p>
                  {area.hidden_gem_candidate
                    ? 'Potential hidden gem, supported as a hypothesis in saved campaign evidence.'
                    : 'Further investigation required before claiming an overlooked destination or marketing opportunity.'}
                </p>
                <small>Photo counts and engagement do not establish tourism demand.</small>
              </article>
              <article>
                <h4>Visual characteristics</h4>
                <p>
                  {Object.keys(visual).length
                    ? Object.keys(visual).map(human).join(' · ')
                    : 'No accepted environment classifications are available for this area.'}
                </p>
                <small>Pretrained visual similarities are not calibrated probabilities.</small>
              </article>
              <article>
                <h4>Comment sentiment</h4>
                <p>
                  {sentiment?.classified_comments
                    ? Object.entries(sentiment.distribution || {})
                        .map(([k, v]) => `${human(k)}: ${v}`)
                        .join(' · ')
                    : 'No classified comment evidence is available.'}
                </p>
                <small>Comment sentiment is separate from demand and engagement metrics.</small>
              </article>
            </div>
          )}
          <details className="evidence-drawer">
            <summary>
              <ShieldCheck size={17} /> Uncertainties & required checks <ChevronDown size={16} />
            </summary>
            <div>
              <p>
                Verified entity existence does not establish that nearby photos depict that
                attraction. Image permissions, location associations and the marketing hypothesis
                require validation.
              </p>
              {dossier?.research?.limitations?.map((s, i) => (
                <p key={i} dir="auto">
                  {s}
                </p>
              ))}
            </div>
          </details>
        </div>
        <section className="research-findings">
          <h3>Sources & findings</h3>
          {sources.length ? (
            sources.slice(0, 5).map((s) => (
              <article key={s.url}>
                <SourceLink source={s} />
                {(s.content_excerpt || s.evidence) && (
                  <p dir="auto">{(s.content_excerpt || s.evidence || '').slice(0, 420)}</p>
                )}
              </article>
            ))
          ) : (
            <p className="muted">No authoritative sources are attached yet.</p>
          )}
        </section>
      </div>
      {gallery.length > 0 && (
        <section className="context-gallery">
          <h3>Geographic image references</h3>
          <p className="muted small">Internal archive context, not verified campaign assets.</p>
          <div className="context-grid">
            {gallery.map((m) => (
              <article key={m.media_id}>
                <Media asset={m} />
                <MediaCredit asset={m} />
              </article>
            ))}
          </div>
        </section>
      )}
    </Modal>
  )
}
