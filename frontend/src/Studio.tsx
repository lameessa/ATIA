import { useState } from 'react'
import { ArrowRight, ChevronDown, Compass, FileCheck2, Search, Sparkles } from 'lucide-react'
import type { Campaign, Destination, Discovery, Opportunity, Workspace } from './productTypes'
import {
  campaignTitle,
  CampaignStatus,
  ValidationBadge,
  destinationName,
  list,
  statusLabel,
  text,
} from './CampaignWorkspace'
import { DestinationCard, verified } from './Discover'
import { OpportunityCard } from './Opportunities'
import { Media, MediaCredit } from './Media'
import { SourceLink } from './components'

const filters: Record<string, (c: Campaign) => boolean> = {
  All: () => true,
  'Needs correction': (c) =>
    c.status === 'PENDING_APPROVAL' && c.validation?.state === 'NEEDS_CORRECTION',
  Warnings: (c) => c.status === 'PENDING_APPROVAL' && c.validation?.state === 'WARNINGS',
  Ready: (c) =>
    c.status === 'PENDING_APPROVAL' && (!c.validation || c.validation.state === 'READY'),
  Approved: (c) => c.status === 'APPROVED',
  Revision: (c) => c.status === 'REVISION_REQUESTED',
}

const steps = [
  {
    Icon: Compass,
    title: 'Discover',
    detail: 'Pick a verified destination, or let ATIA find one.',
  },
  {
    Icon: Sparkles,
    title: 'Prepare',
    detail: 'ATIA drafts a campaign only if the evidence holds.',
  },
  { Icon: FileCheck2, title: 'Review', detail: 'Edit it in English and Arabic, then approve it.' },
]

const shortDate = (value: string) =>
  new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })

export function ActivityNote({ item }: { item: Discovery }) {
  const labels: Record<string, string> = {
    INVESTIGATE: 'Needed more evidence',
    NO_ACTION: 'No campaign opportunity found',
    CREATE: 'Campaign prepared',
    UPDATE: 'Campaign updated',
  }
  return (
    <details className="activity-note">
      <summary>
        <strong>{labels[item.decision || ''] || 'Research in progress'}</strong>
        <small>
          {new Date(item.created_at).toLocaleString(undefined, {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
          })}
        </small>
        <ChevronDown size={14} />
      </summary>
      <div className="activity-detail">
        <p dir="auto">{item.summary}</p>
        {item.uncertainties.map((s, i) => (
          <p className="muted" key={i} dir="auto">
            {s}
          </p>
        ))}
        {item.sources.map((s) => (
          <SourceLink key={s.url} source={s} />
        ))}
      </div>
    </details>
  )
}

function CampaignCard({ campaign, onOpen }: { campaign: Campaign; onOpen: () => void }) {
  const c = campaign.content
  const channels = list(c.suggested_channels || c.recommended_channels)
    .map((v) => text(v))
    .filter((v) => v && v.length < 24)
    .slice(0, 3)
  const arabic = text(c.campaign_name, 'ar')
  return (
    <button className="campaign-card" onClick={onOpen}>
      <div className="campaign-image">
        <Media asset={campaign.media[0]} plate={{ seed: campaign.id }} />
        <CampaignStatus value={campaign.status} />
        <ValidationBadge campaign={campaign} />
      </div>
      <div className="card-copy">
        <h3 dir="auto">{campaignTitle(campaign)}</h3>
        {arabic && (
          <p className="card-arabic" dir="rtl" lang="ar">
            {arabic}
          </p>
        )}
        <p className="card-place" dir="auto">
          {destinationName(campaign) || 'Location under review'}
        </p>
        <p className="card-description" dir="auto">
          {text(c.central_concept || c.campaign_concept) ||
            'Open the saved brief and supporting evidence.'}
        </p>
        {!!channels.length && (
          <span className="chip-row">
            {channels.map((channel) => (
              <span className="chip" key={channel}>
                {channel}
              </span>
            ))}
          </span>
        )}
        <span className="card-bottom">
          {shortDate(campaign.created_at)}
          <span className="round-arrow">
            <ArrowRight size={15} />
          </span>
        </span>
      </div>
    </button>
  )
}

export default function Studio({
  data,
  onCampaign,
  onDiscover,
  onAutonomous,
  onPlace,
  onCreate,
  onOpportunity,
  onOpportunityCreate,
}: {
  data: Workspace
  onCampaign: (c: Campaign) => void
  onDiscover: () => void
  onAutonomous: () => void
  onPlace: (a: Destination) => void
  onCreate: Parameters<typeof DestinationCard>[0]['onCreate']
  onOpportunity: (o: Opportunity) => void
  onOpportunityCreate: (o: Opportunity) => void
}) {
  const [filter, setFilter] = useState('All')
  const featured = data.campaigns.find((c) => c.status !== 'REJECTED')
  const visible = data.campaigns.filter(filters[filter])
  const pending = data.campaigns.filter((c) => c.status === 'PENDING_APPROVAL')
  const scenery = data.archive[data.archive.length - 1]
  const ready = data.areas.filter((a) => verified(a).length > 0).slice(0, 4)
  const opportunities = (data.opportunities || []).filter((o) => !o.campaign_id).slice(0, 4)

  return (
    <>
      <div className="studio-lead">
        {featured ? (
          <section className="hero">
            <button className="hero-open" onClick={() => onCampaign(featured)}>
              <Media asset={featured.media[0]} plate={{ seed: featured.id }} eager />
              <span className="hero-copy">
                <span className="hero-label">Featured campaign</span>
                <span className="hero-title" dir="auto">
                  {campaignTitle(featured)}
                </span>
                <span className="hero-place" dir="auto">
                  {destinationName(featured)}
                </span>
                <span className="button light">
                  View campaign <ArrowRight size={15} />
                </span>
              </span>
            </button>
            {featured.media[0] && <MediaCredit asset={featured.media[0]} />}
          </section>
        ) : (
          <section className="hero">
            <Media asset={scenery} plate={{ seed: 'atia-studio', region: 'South' }} eager />
            <div className="hero-copy">
              <span className="hero-label">Your campaigns</span>
              <h2 className="hero-title">No campaign justified yet</h2>
              <p>
                ATIA prepares a campaign only when the research supports one. Start with a verified
                destination, or let ATIA look for an opportunity.
              </p>
              <div className="hero-actions">
                <button className="button light" onClick={onAutonomous}>
                  <Search size={15} /> Discover opportunities
                </button>
                <button className="button glass" onClick={onDiscover}>
                  Explore destinations <ArrowRight size={15} />
                </button>
              </div>
            </div>
            {scenery && <MediaCredit asset={scenery} />}
          </section>
        )}
        {featured ? (
          <aside className="side-panel">
            <h2>Awaiting your review</h2>
            {pending.length ? (
              <div className="review-queue">
                {pending.slice(0, 4).map((c) => (
                  <button key={c.id} onClick={() => onCampaign(c)}>
                    <strong dir="auto">{campaignTitle(c)}</strong>
                    <small>
                      {statusLabel(c.status)} · {shortDate(c.created_at)}
                    </small>
                    <ArrowRight size={14} />
                  </button>
                ))}
              </div>
            ) : (
              <p className="muted">Nothing is waiting for a decision right now.</p>
            )}
          </aside>
        ) : (
          <aside className="side-panel">
            <h2>How a campaign comes together</h2>
            <ol className="steps">
              {steps.map(({ Icon, title, detail }) => (
                <li key={title}>
                  <span className="step-icon">
                    <Icon size={17} strokeWidth={1.6} />
                  </span>
                  <span>
                    <strong>{title}</strong>
                    <small>{detail}</small>
                  </span>
                </li>
              ))}
            </ol>
          </aside>
        )}
      </div>

      {data.campaigns.length > 0 ? (
        <section className="page-section">
          <div className="section-heading">
            <div>
              <h2>Campaigns</h2>
              <p>Prepared for your review, editing and approval.</p>
            </div>
            <div className="section-tools">
              <div className="filter-tabs" aria-label="Campaign filters">
                {Object.keys(filters).map((name) => (
                  <button
                    key={name}
                    className={name === filter ? 'selected' : ''}
                    onClick={() => setFilter(name)}
                  >
                    {name}
                    <span>{data.campaigns.filter(filters[name]).length}</span>
                  </button>
                ))}
              </div>
              <button className="button quiet small" onClick={onAutonomous}>
                <Search size={14} /> Discover opportunities
              </button>
            </div>
          </div>
          {visible.length ? (
            <div className="campaign-grid">
              {visible.map((c) => (
                <CampaignCard key={c.id} campaign={c} onOpen={() => onCampaign(c)} />
              ))}
            </div>
          ) : (
            <p className="inline-empty">No campaigns in this view. Choose another filter.</p>
          )}
        </section>
      ) : opportunities.length ? (
        <section className="page-section">
          <div className="section-heading">
            <div>
              <h2>Marketing opportunities</h2>
              <p>Flickr evidence ATIA can turn into a campaign draft for your review.</p>
            </div>
            <button className="text-link" onClick={onDiscover}>
              Browse all <ArrowRight size={14} />
            </button>
          </div>
          <div className="destination-grid">
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
      ) : (
        !!ready.length && (
          <section className="page-section">
            <div className="section-heading">
              <div>
                <h2>Ready to explore</h2>
                <p>Destinations whose identity is confirmed by authoritative sources.</p>
              </div>
              <button className="text-link" onClick={onDiscover}>
                Browse all <ArrowRight size={14} />
              </button>
            </div>
            <div className="destination-grid">
              {ready.map((area) => (
                <DestinationCard
                  key={area.cluster_id}
                  area={area}
                  onSelect={onPlace}
                  onCreate={onCreate}
                />
              ))}
            </div>
          </section>
        )
      )}

      {data.activity.length > 0 && (
        <details className="research-history">
          <summary>
            Research history <span>{data.activity.length}</span>
            <ChevronDown size={15} />
          </summary>
          <div>
            {data.activity.map((item) => (
              <ActivityNote key={item.id} item={item} />
            ))}
          </div>
        </details>
      )}
    </>
  )
}
