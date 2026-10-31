import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ArrowRight,
  CalendarDays,
  Check,
  Compass,
  LayoutGrid,
  Loader2,
  Menu,
  RefreshCw,
  ShieldCheck,
  X,
} from 'lucide-react'
import { api } from './api'
import { Modal, Notice } from './components'
import Studio from './Studio'
import Discover, { DestinationDetail } from './Discover'
import Calendar from './Calendar'
import CampaignWorkspace from './CampaignWorkspace'
import { OpportunityDetail, opportunityTitle } from './Opportunities'
import type {
  Campaign,
  Destination,
  Opportunity,
  Workspace,
  PreparationJob,
  CalendarEntry,
} from './productTypes'
import type { Entity, Policy } from './types'

const navigation = [
  {
    id: 'studio',
    name: 'Studio',
    Icon: LayoutGrid,
    subtitle: 'Create, review and approve Saudi tourism campaigns.',
  },
  {
    id: 'discover',
    name: 'Discover',
    Icon: Compass,
    subtitle: 'Explore destinations and the research behind them.',
  },
  {
    id: 'calendar',
    name: 'Calendar',
    Icon: CalendarDays,
    subtitle: 'Approved campaign plans. Nothing is published or scheduled externally.',
  },
]
const route = () =>
  navigation.some((n) => n.id === location.hash.slice(1)) ? location.hash.slice(1) : 'studio'
const isActive = (job?: PreparationJob) => !!job && ['queued', 'running'].includes(job.status)
type ReviewDecision = 'APPROVED' | 'REJECTED' | 'REVISION_REQUESTED'

function Logo() {
  return (
    <svg viewBox="0 0 48 48" width="38" height="38" aria-hidden="true">
      <g fill="none" stroke="#d9ad6c" strokeWidth="1.7" strokeLinecap="round">
        <circle cx="24" cy="24" r="8" />
        <path d="M24 6v6M24 36v6M6 24h6M36 24h6M11.300 11.300l4.200 4.200M32.500 32.500l4.200 4.200M36.700 11.300l-4.200 4.200M15.500 32.500l-4.200 4.200" />
      </g>
    </svg>
  )
}

function SidebarArt() {
  return (
    <svg
      className="sidebar-art"
      viewBox="0 0 240 300"
      preserveAspectRatio="xMidYMax slice"
      aria-hidden="true"
    >
      <circle
        cx="176"
        cy="96"
        r="17"
        fill="none"
        stroke="#d9ad6c"
        strokeWidth="1.2"
        opacity="0.55"
      />
      <path d="M0 160c28-20 44-8 68-24s34-36 62-22 40 30 62 20 34-14 48-6v172H0z" fill="#1d4a3f" />
      <path d="M0 208c34-14 56 2 86-14s48-22 78-8 52 12 76 2v112H0z" fill="#174036" />
      <path d="M0 252c44-12 74 6 116-6s80-14 124 0v54H0z" fill="#0f2f28" />
    </svg>
  )
}

export default function App() {
  const [tab, setTab] = useState(route)
  const [data, setData] = useState<Workspace>()
  const [entries, setEntries] = useState<CalendarEntry[]>([])
  const [policy, setPolicy] = useState<Policy>()
  const [job, setJob] = useState<PreparationJob>()
  const [startedJob, setStartedJob] = useState<string>()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [mobile, setMobile] = useState(false)
  const [campaignId, setCampaignId] = useState<string>()
  const [place, setPlace] = useState<Destination>()
  const [opportunity, setOpportunity] = useState<Opportunity>()
  const [notice, setNotice] = useState('')
  const [request, setRequest] = useState<{
    entity?: Entity
    opportunity?: Opportunity
    key: string
  }>()
  const [requestError, setRequestError] = useState('')
  const [requestBusy, setRequestBusy] = useState(false)
  const [review, setReview] = useState<{ campaign: Campaign; decision: ReviewDecision }>()
  const [reviewer, setReviewer] = useState('')
  const [launchDate, setLaunchDate] = useState('')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')

  const refresh = useCallback(async () => {
    setError('')
    try {
      const [snapshot, calendar, jobs, limits] = await Promise.all([
        api<Workspace>('/workspace'),
        api<{ entries: CalendarEntry[] }>('/calendar'),
        api<{ jobs: PreparationJob[] }>('/campaign-requests'),
        api<Policy>('/agent/policy'),
      ])
      setData(snapshot)
      setEntries(calendar.entries)
      setPolicy(limits)
      setJob(jobs.jobs.find(isActive) || jobs.jobs[0])
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    const update = () => setTab(route())
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])

  useEffect(() => {
    if (!job?.job_id || !isActive(job)) return
    let active = true
    const timer = setInterval(() => {
      api<PreparationJob>(`/campaign-requests/${encodeURIComponent(job.job_id!)}`)
        .then(async (latest) => {
          if (!active) return
          setJob(latest)
          if (isActive(latest)) return
          setNotice(latest.message || 'Investigation finished.')
          await refresh()
          if (latest.campaign_id) {
            setCampaignId(latest.campaign_id)
            setTab('studio')
            location.hash = 'studio'
          }
        })
        .catch(() => {
          if (active)
            setNotice(
              'Progress connection interrupted. Refresh to inspect the saved request; no paid retry was made.',
            )
        })
    }, 1500)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [job?.job_id, job?.status, refresh])

  // A fast job can finish before the first poll, so the requested result is opened from any update.
  const openedJob = useRef<string>(undefined)
  useEffect(() => {
    if (!job?.job_id || job.job_id !== startedJob || isActive(job) || !job.campaign_id) return
    if (openedJob.current === job.job_id) return
    openedJob.current = job.job_id
    setCampaignId(job.campaign_id)
    // The job can finish between the workspace and job reads of one refresh.
    if (!data?.campaigns.some((c) => c.id === job.campaign_id)) void refresh()
  }, [job, startedJob, data, refresh])

  function navigate(id: string) {
    setTab(id)
    location.hash = id
    setMobile(false)
    window.scrollTo?.({ top: 0, behavior: 'instant' })
  }

  function requestCampaign(entity?: Entity) {
    const existing =
      entity &&
      data?.campaigns.find(
        (c) =>
          c.kind === 'campaign' &&
          c.status !== 'REJECTED' &&
          (c.content.destination as { entity_id?: string })?.entity_id === entity.entity_id,
      )
    if (existing) {
      setPlace(undefined)
      navigate('studio')
      setCampaignId(existing.id)
      return
    }
    setRequest({ entity, key: crypto.randomUUID() })
    setRequestError('')
  }

  function requestOpportunity(target: Opportunity) {
    if (target.campaign_id) {
      setOpportunity(undefined)
      navigate('studio')
      setCampaignId(target.campaign_id)
      return
    }
    setRequest({ opportunity: target, key: crypto.randomUUID() })
    setRequestError('')
  }

  async function prepare() {
    if (!request || requestBusy) return
    setRequestBusy(true)
    setRequestError('')
    try {
      const started = await api<PreparationJob>('/campaign-requests', {
        entity_id: request.entity?.entity_id || null,
        opportunity_id: request.opportunity?.id || null,
        idempotency_key: request.key,
        confirmed: true,
      })
      setJob(started)
      setStartedJob(started.job_id)
      setRequest(undefined)
      setPlace(undefined)
      setOpportunity(undefined)
      navigate('studio')
      setNotice(started.message || 'Investigation requested.')
      if (started.campaign_id) setCampaignId(started.campaign_id)
      await refresh()
    } catch (e) {
      setRequestError((e as Error).message)
    } finally {
      setRequestBusy(false)
    }
  }

  function requestReview(campaign: Campaign, decision: ReviewDecision) {
    setReview({ campaign, decision })
    setActionError('')
    setReviewer('')
    setLaunchDate('')
    setNotes('')
  }

  async function saveReview() {
    if (!review || busy) return
    setBusy(true)
    setActionError('')
    try {
      const id = encodeURIComponent(review.campaign.id)
      const path =
        review.campaign.kind === 'campaign' ? `/campaigns/${id}/review` : `/proposals/${id}/review`
      await api(path, {
        decision: review.decision,
        reviewer: reviewer.trim() || 'Local reviewer',
        notes,
        revision: review.campaign.revision || 0,
        ...(launchDate ? { launch_date: launchDate } : {}),
        confirmed: true,
      })
      setReview(undefined)
      setNotice('Your review is saved. Nothing has been published.')
      await refresh()
    } catch (e) {
      setActionError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const selected = data?.campaigns.find((c) => c.id === campaignId)
  const active = isActive(job)
  // Past outcomes live in Studio's research history; only live or just-requested work is announced.
  const reviewedDraft = data?.campaigns.some(
    (c) => c.id === job?.campaign_id && c.status !== 'PENDING_APPROVAL',
  )
  const showJob =
    !!job && job.status !== 'existing' && !reviewedDraft && (active || job.job_id === startedJob)
  const status =
    active || data?.agent_status === 'investigating'
      ? 'ATIA is investigating'
      : data?.agent_status === 'awaiting_approval'
        ? 'Campaigns await your review'
        : 'ATIA is idle'
  const page = navigation.find((n) => n.id === tab)!
  const hasOpportunities = !!data?.opportunities?.length
  const oneRequest = !!request?.opportunity || (!request?.entity && hasOpportunities)

  return (
    <div className="product-shell">
      <aside className={`product-sidebar ${mobile ? 'mobile-open' : ''}`}>
        <a
          href="#studio"
          className="product-brand"
          aria-label="ATIA Studio"
          onClick={() => navigate('studio')}
        >
          <Logo />
          <span>
            ATIA
            <small>
              Autonomous Tourism
              <br />
              Intelligence & Marketing
            </small>
          </span>
        </a>
        <nav aria-label="Main navigation">
          {navigation.map(({ id, name, Icon }) => (
            <button
              key={id}
              className={tab === id ? 'active' : ''}
              aria-current={tab === id ? 'page' : undefined}
              onClick={() => navigate(id)}
            >
              <Icon size={18} strokeWidth={1.6} />
              <span>{name}</span>
            </button>
          ))}
        </nav>
        <SidebarArt />
        <p className="sidebar-tagline">
          Discover
          <br />
          Promote
          <br />
          Grow
          <strong>Saudi Arabia</strong>
          <small>HUMAIN Future AI Builders</small>
        </p>
      </aside>
      {mobile && (
        <button
          className="sidebar-backdrop"
          aria-label="Close navigation"
          onClick={() => setMobile(false)}
        />
      )}

      <div className="product-main">
        <header className="product-topbar">
          <button
            className="icon-btn mobile-menu"
            aria-label="Open navigation"
            onClick={() => setMobile(true)}
          >
            <Menu size={19} />
          </button>
          <div className="page-title">
            <h1>{page.name}</h1>
            <p>{page.subtitle}</p>
          </div>
          <div className="topbar-actions">
            <span className={`agent-pill ${active ? 'working' : ''}`}>
              <i />
              {loading ? 'Connecting' : error && !data ? 'Connection unavailable' : status}
            </span>
            <button
              className="icon-btn"
              aria-label="Refresh stored workspace"
              onClick={() => void refresh()}
            >
              <RefreshCw size={15} />
            </button>
          </div>
        </header>

        <main className="product-content" id="main-content">
          {notice && (
            <div className="toast" role="status">
              <Check size={16} />
              <span>{notice}</span>
              <button
                className="icon-btn"
                aria-label="Dismiss notification"
                onClick={() => setNotice('')}
              >
                <X size={14} />
              </button>
            </div>
          )}
          {showJob && (
            <div className={`job-banner ${active ? 'active' : ''}`} role="status">
              {active ? <Loader2 size={17} className="spinner" /> : <ShieldCheck size={17} />}
              <div>
                <strong>
                  {active
                    ? 'Campaign research in progress'
                    : job.status === 'needs_review'
                      ? 'Campaign not created'
                      : job.outcome === 'INVESTIGATE'
                        ? 'Additional evidence required'
                        : job.status === 'failed' || job.status === 'interrupted'
                          ? 'Investigation stopped'
                          : job.campaign_id
                            ? 'Campaign available for review'
                            : 'Investigation complete'}
                </strong>
                <p>{job.message}</p>
              </div>
              {job.campaign_id && (
                <button
                  className="button quiet small"
                  onClick={() => setCampaignId(job.campaign_id)}
                >
                  Open campaign <ArrowRight size={14} />
                </button>
              )}
            </div>
          )}
          {error && (
            <div className="connection-error" role="alert">
              <h2>{data ? 'Unable to refresh' : 'Workspace unavailable'}</h2>
              <p>{error}</p>
              <button className="button primary" onClick={() => void refresh()}>
                Retry stored-data request <ArrowRight size={15} />
              </button>
            </div>
          )}
          {loading && !data ? (
            <div className="loading-workspace" role="status">
              <Loader2 size={24} className="spinner" />
              <p>Loading your workspace…</p>
            </div>
          ) : data ? (
            <>
              {tab === 'studio' && (
                <Studio
                  data={data}
                  onCampaign={(c) => setCampaignId(c.id)}
                  onDiscover={() => navigate('discover')}
                  onAutonomous={() => requestCampaign()}
                  onPlace={setPlace}
                  onCreate={requestCampaign}
                  onOpportunity={setOpportunity}
                  onOpportunityCreate={requestOpportunity}
                />
              )}
              {tab === 'discover' && (
                <Discover
                  areas={data.areas}
                  archive={data.archive}
                  opportunities={data.opportunities}
                  onOpportunity={setOpportunity}
                  onOpportunityCreate={requestOpportunity}
                  onSelect={setPlace}
                  onCreate={requestCampaign}
                />
              )}
              {tab === 'calendar' && (
                <Calendar
                  campaigns={data.campaigns}
                  entries={entries}
                  onCampaign={(c) => setCampaignId(c.id)}
                />
              )}
            </>
          ) : null}
        </main>
      </div>

      {selected && !review && (
        <CampaignWorkspace
          campaign={selected}
          onClose={() => setCampaignId(undefined)}
          onReview={requestReview}
          onSaved={async () => {
            await refresh()
            setNotice('Edits saved as a new draft version. The original AI content is preserved.')
          }}
        />
      )}
      {place && !request && (
        <DestinationDetail
          area={place}
          onClose={() => setPlace(undefined)}
          onCreate={hasOpportunities ? undefined : requestCampaign}
        />
      )}
      {opportunity && !request && !selected && (
        <OpportunityDetail
          opportunity={opportunity}
          onClose={() => setOpportunity(undefined)}
          onCreate={requestOpportunity}
        />
      )}
      {request && (
        <Modal
          title={
            request.entity || request.opportunity
              ? 'Prepare a campaign?'
              : 'Discover an opportunity?'
          }
          onClose={() => {
            if (!requestBusy) setRequest(undefined)
          }}
        >
          <p className="dialog-description">
            {request.opportunity
              ? `ATIA will review the Flickr evidence for ${opportunityTitle(request.opportunity)} and draft a bilingual campaign only if the evidence supports it.`
              : oneRequest
                ? 'ATIA will choose the strongest opportunity without a draft and review its Flickr evidence.'
                : request.entity
                  ? `ATIA will investigate ${request.entity.verified_name}, reuse existing research, and prepare a campaign only if the evidence supports it.`
                  : 'ATIA will independently choose an eligible destination and investigate whether a campaign is justified.'}
          </p>
          {oneRequest ? (
            <Notice>
              This action may incur an OpenAI charge, capped at $
              {policy?.limits.run_budget_usd.toFixed(2)} for one request. No Tavily search,
              automatic retries or publishing.
            </Notice>
          ) : (
            <Notice>
              This action may incur OpenAI and Tavily charges. The OpenAI run is capped at $
              {policy?.limits.run_budget_usd.toFixed(2)} with at most {policy?.limits.max_steps}{' '}
              requests and {policy?.limits.max_tool_calls} tool calls. At most{' '}
              {policy?.limits.max_searches} additional Tavily search. No automatic retries or
              publishing.
            </Notice>
          )}
          <p className="dialog-description">
            An INVESTIGATE or NO_ACTION outcome is valid. Choosing a destination does not guarantee
            a campaign.
          </p>
          {policy?.openai_configured === false && (
            <Notice>
              Live AI generation requires configuration: set OPENAI_API_KEY in .env and restart the
              server. Nothing will be sent or charged. Saved campaigns stay available.
            </Notice>
          )}
          {requestError && <Notice tone="error">{requestError}</Notice>}
          <div className="dialog-actions">
            <button
              className="button quiet"
              disabled={requestBusy}
              onClick={() => setRequest(undefined)}
            >
              Cancel
            </button>
            <button
              className="button primary"
              disabled={requestBusy || !policy || policy.openai_configured === false}
              onClick={() => void prepare()}
            >
              {requestBusy ? <Loader2 size={15} className="spinner" /> : <Compass size={15} />}
              Confirm & start research
            </button>
          </div>
        </Modal>
      )}
      {review && (
        <Modal
          title={
            review.decision === 'APPROVED'
              ? 'Approve this campaign?'
              : review.decision === 'REVISION_REQUESTED'
                ? 'Request a revision?'
                : 'Reject this draft?'
          }
          onClose={() => {
            if (!busy) setReview(undefined)
          }}
        >
          <p className="dialog-description">
            {review.decision === 'REVISION_REQUESTED'
              ? 'This removes any current approval and allows a human edit. A newly edited version must be approved again. No paid AI revision is started.'
              : 'Your decision applies to the current saved version. Approval does not schedule or publish content.'}
          </p>
          <label className="field">
            Reviewer name
            <input
              value={reviewer}
              maxLength={120}
              onChange={(e) => setReviewer(e.target.value)}
              placeholder="Your name"
            />
          </label>
          {review.decision === 'APPROVED' && review.campaign.opportunity_id && (
            <label className="field">
              Planned launch date (optional)
              <input
                type="date"
                value={launchDate}
                onChange={(e) => setLaunchDate(e.target.value)}
              />
            </label>
          )}
          <label className="field">
            Review notes
            <textarea
              value={notes}
              maxLength={2000}
              dir="auto"
              onChange={(e) => setNotes(e.target.value)}
              placeholder="What informed your decision?"
            />
          </label>
          {actionError && <Notice tone="error">{actionError}</Notice>}
          <div className="dialog-actions">
            <button className="button quiet" disabled={busy} onClick={() => setReview(undefined)}>
              Cancel
            </button>
            <button className="button primary" disabled={busy} onClick={() => void saveReview()}>
              {busy ? <Loader2 size={16} className="spinner" /> : <Check size={16} />}
              Confirm{' '}
              {review.decision === 'APPROVED'
                ? 'approval'
                : review.decision === 'REVISION_REQUESTED'
                  ? 'revision request'
                  : 'rejection'}
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}
