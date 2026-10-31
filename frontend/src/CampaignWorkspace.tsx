import { useState } from 'react'
import { Check, ChevronDown, Pencil, RotateCcw, ShieldCheck, X } from 'lucide-react'
import { Modal, Notice, SourceLink } from './components'
import CampaignEditor from './CampaignEditor'
import { Media, MediaCredit } from './Media'
import type { Bilingual, Campaign, EvidenceReview, PlannedPost, SocialPost } from './productTypes'

type Language = 'en' | 'ar'

const arabicLabels: Record<string, string> = {
  'Verified location': 'الموقع الموثق',
  'Location context': 'السياق الجغرافي',
  Positioning: 'التموضع',
  'The concept': 'الفكرة',
  'Campaign objectives': 'أهداف الحملة',
  'The opportunity hypothesis': 'فرضية الفرصة',
  'Target audience': 'الجمهور المستهدف',
  'Why this audience': 'لماذا هذا الجمهور',
  'Key messages': 'الرسائل الرئيسية',
  'Creative direction': 'التوجه الإبداعي',
  'Recommended channels': 'القنوات المقترحة',
  'Recommended activities': 'الأنشطة المقترحة',
  'Before this goes live': 'قبل الإطلاق',
  'Words that bring it to life': 'كلمات تنبض بالحملة',
  'Proposed content rhythm': 'إيقاع المحتوى المقترح',
  'What success could look like': 'كيف قد يبدو النجاح',
}

export const text = (value: unknown, lang: Language = 'en'): string =>
  typeof value === 'string'
    ? value
    : value && typeof value === 'object' && !Array.isArray(value)
      ? String((value as Bilingual)[lang] || '')
      : ''
export const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : [])
export const campaignTitle = (c: Campaign) =>
  text(c.content.campaign_name) || text(c.content.campaign_concept) || 'Campaign brief'
export const destinationName = (c: Campaign) => {
  const d = c.content.destination
  return typeof d === 'object' && d && 'name' in d ? text((d as { name: unknown }).name) : text(d)
}
export const statusLabel = (s: string) =>
  s === 'PENDING_APPROVAL'
    ? 'Awaiting approval'
    : s === 'APPROVED'
      ? 'Approved · not published'
      : s === 'REJECTED'
        ? 'Rejected'
        : s === 'REVISION_REQUESTED'
          ? 'Revision requested'
          : 'Draft'

/** A pending draft's status says what a reviewer can do with it. */
const reviewState = (c: Campaign) =>
  c.status === 'PENDING_APPROVAL' || c.status === 'REVISION_REQUESTED'
    ? c.validation?.state
    : undefined

export function ValidationBadge({ campaign }: { campaign: Campaign }) {
  const state = reviewState(campaign)
  if (!state) return null
  const warnings = campaign.validation?.warnings.length || 0
  const blocking = campaign.validation?.blocking.length || 0
  return (
    <span className={`validation-badge validation-${state.toLowerCase()}`}>
      {state === 'NEEDS_CORRECTION'
        ? `Needs correction · ${blocking} blocking`
        : state === 'WARNINGS'
          ? `Draft · ${warnings} ${warnings === 1 ? 'warning' : 'warnings'}`
          : 'Ready for approval'}
    </span>
  )
}

function ValidationFindings({ campaign }: { campaign: Campaign }) {
  const found = campaign.validation
  if (!reviewState(campaign) || !found || found.state === 'READY') return null
  return (
    <section className="validation-findings" aria-label="Validation findings">
      {found.blocking.length > 0 && (
        <div className="validation-group blocking">
          <h4>Must be corrected before approval</h4>
          <ul>
            {found.blocking.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      {found.warnings.length > 0 && (
        <div className="validation-group">
          <h4>For you to review</h4>
          <ul>
            {found.warnings.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

export function CampaignStatus({ value }: { value: string }) {
  return (
    <span className={`campaign-status status-${value.toLowerCase()}`}>
      <i />
      {statusLabel(value)}
    </span>
  )
}

function EvidenceSection({ review }: { review: EvidenceReview }) {
  return (
    <section className="evidence-review">
      <h3>What the evidence supports</h3>
      <p dir="auto">{review.recommendation}</p>
      <div className="claim-list">
        {review.claims.map((item, i) => (
          <article key={i}>
            <strong dir="auto">{item.claim}</strong>
            {item.sources.map((source) => (
              <SourceLink key={source.url} source={source} />
            ))}
          </article>
        ))}
      </div>
      <h4>Still uncertain</h4>
      <ul>
        {review.uncertainties.map((item, i) => (
          <li key={i} dir="auto">
            {item}
          </li>
        ))}
      </ul>
      {review.original && (
        <details className="evidence-drawer">
          <summary>
            <RotateCcw size={16} /> Original AI claims, before correction <ChevronDown size={16} />
          </summary>
          <div>
            <p dir="auto">{review.original.recommendation}</p>
            {review.original.claims.map((item, i) => (
              <p className="muted" key={i} dir="auto">
                {item}
              </p>
            ))}
          </div>
        </details>
      )}
    </section>
  )
}

export default function CampaignWorkspace({
  campaign,
  onClose,
  onReview,
  onSaved,
}: {
  campaign: Campaign
  onClose: () => void
  onReview: (c: Campaign, d: 'APPROVED' | 'REJECTED' | 'REVISION_REQUESTED') => void
  onSaved: () => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [lang, setLang] = useState<Language>('en')
  const c = campaign.content
  const dir = lang === 'ar' ? 'rtl' : 'ltr'
  if (editing)
    return (
      <Modal wide title="Edit campaign" onClose={() => setEditing(false)}>
        <CampaignEditor
          campaign={campaign}
          onCancel={() => setEditing(false)}
          onSaved={async () => {
            await onSaved()
            setEditing(false)
          }}
        />
      </Modal>
    )
  const posts = list(c.social_posts) as SocialPost[]
  const schedule = list(c.publishing_schedule) as PlannedPost[]
  const measures = list(c.kpis_and_measurement) as Record<string, unknown>[]
  const arabicTitle = text(c.campaign_name, 'ar')

  const heading = (en: string) => (lang === 'ar' && arabicLabels[en]) || en

  function section(label: string, value: unknown) {
    const values = Array.isArray(value) ? value : [value]
    const lines = values.map((v) => text(v, lang)).filter(Boolean)
    if (!lines.length) return null
    return (
      <section className="campaign-section">
        <h3>{label}</h3>
        {lines.map((line, i) => (
          <p key={i} dir={dir} lang={lang}>
            {line}
          </p>
        ))}
      </section>
    )
  }

  return (
    <Modal
      wide
      title={
        lang === 'ar' && arabicTitle ? (
          <span dir="rtl" lang="ar">
            {arabicTitle}
          </span>
        ) : (
          campaignTitle(campaign)
        )
      }
      onClose={onClose}
    >
      <div className="campaign-topline">
        <span dir="auto">{destinationName(campaign) || 'Location requires review'}</span>
        <CampaignStatus value={campaign.status} />
        <ValidationBadge campaign={campaign} />
      </div>
      <ValidationFindings campaign={campaign} />
      <div className="hero-frame">
        <Media
          asset={campaign.media[0]}
          className="campaign-hero"
          plate={{ seed: campaign.id }}
          alt={`Reviewed campaign image for ${destinationName(campaign)}`}
        />
        {campaign.media[0] && <MediaCredit asset={campaign.media[0]} />}
      </div>
      <div className="campaign-toolbar">
        <span>
          {campaign.kind === 'legacy_proposal'
            ? 'Preliminary campaign brief'
            : `Campaign workspace${
                campaign.revision
                  ? ` · Revision ${campaign.revision}${campaign.edited_by ? ` by ${campaign.edited_by}` : ''}`
                  : ''
              }`}
        </span>
        {campaign.kind === 'campaign' &&
          ['PENDING_APPROVAL', 'REVISION_REQUESTED'].includes(campaign.status) && (
            <button className="button quiet small" onClick={() => setEditing(true)}>
              <Pencil size={13} /> Edit campaign
            </button>
          )}
        <div className="language-switch" aria-label="Campaign language">
          <button className={lang === 'en' ? 'selected' : ''} onClick={() => setLang('en')}>
            English
          </button>
          <button className={lang === 'ar' ? 'selected' : ''} onClick={() => setLang('ar')}>
            العربية
          </button>
        </div>
      </div>
      {campaign.kind === 'legacy_proposal' && (
        <Notice>
          This saved brief predates the complete campaign format. Captions, schedules and
          measurement plans are shown only when saved.
        </Notice>
      )}
      {!!campaign.opportunity_id && !campaign.media.length && (
        <Notice>
          Text-only draft. No image has been approved for display, so none can be used yet.
        </Notice>
      )}
      {!!c.evidence_label && (
        <Notice>
          Evidence: {String(c.evidence_label)}. Based on Flickr photographs and their metadata,
          which do not establish visitor demand or promotional coverage.
        </Notice>
      )}
      {campaign.media_validation_required && (
        <Notice>
          Image rights or destination associations still need validation. Approval is unavailable
          until those checks are complete.
        </Notice>
      )}
      <div className="campaign-content" dir={dir} lang={lang}>
        {c.destination && typeof c.destination === 'object' && 'verified_location' in c.destination
          ? section(heading('Verified location'), c.destination.verified_location)
          : null}
        {section(
          heading('Location context'),
          (c.destination as { location_context?: unknown } | undefined)?.location_context,
        )}
        {section(heading('The concept'), c.central_concept || c.campaign_concept)}
        {section(heading('Positioning'), c.positioning)}
        {section(heading('Campaign objectives'), c.objectives)}
        {section(heading('The opportunity hypothesis'), c.opportunity_hypothesis)}
        <div className="two-col">
          {section(heading('Target audience'), c.target_audience || c.target_audience_hypothesis)}
          {section(heading('Why this audience'), c.audience_rationale_hypothesis)}
        </div>
        {section(heading('Key messages'), c.key_messages)}
        {section(heading('Creative direction'), c.creative_direction)}
        {!!posts.length && (
          <section className="campaign-section">
            <h3>{heading('Words that bring it to life')}</h3>
            <div className="caption-grid">
              {posts.map((post) => (
                <article className="caption-card" key={post.post_id}>
                  <span className="eyebrow">{post.channel} · Draft caption</span>
                  <p dir={dir} lang={lang}>
                    {text(post.caption, lang)}
                  </p>
                </article>
              ))}
            </div>
          </section>
        )}
        {section(heading('Recommended channels'), c.suggested_channels || c.recommended_channels)}
        {!!schedule.length && (
          <section className="campaign-section">
            <h3>{heading('Proposed content rhythm')}</h3>
            <p className="muted small">
              {lang === 'ar'
                ? 'بالنسبة إلى إطلاق مستقبلي يعتمده المراجع. لم تتم جدولة أي شيء خارجيًا.'
                : 'Relative to a future human-approved launch. Nothing has been scheduled externally.'}
            </p>
            <div className="schedule-list">
              {schedule.map((item, i) => (
                <div key={i}>
                  <span className="schedule-day">
                    {campaign.publishing_dates?.[item.post_id] ||
                      `Day ${item.days_after_human_approved_launch}`}
                  </span>
                  <div>
                    <strong>{item.channel}</strong>
                    <p dir={dir} lang={lang}>
                      {text(item.activity, lang)}
                    </p>
                  </div>
                  <small>
                    {item.local_time} · {item.timezone}
                  </small>
                </div>
              ))}
            </div>
          </section>
        )}
        {section(heading('Recommended activities'), c.recommended_activities)}
        {!!measures.length && (
          <section className="campaign-section">
            <h3>{heading('What success could look like')}</h3>
            <p className="muted small">
              {lang === 'ar'
                ? 'مقاييس مقترحة وليست نتائج موعودة. لم تُقَس خطوط الأساس بعد.'
                : 'Proposed measures, not promised outcomes. Baselines are unmeasured.'}
            </p>
            {measures.map((measure, i) => (
              <div className="measurement" key={i} dir={dir} lang={lang}>
                <strong>{text(measure.metric, lang)}</strong>
                <p>{text(measure.measurement_plan, lang)}</p>
                <small>{text(measure.proposed_target_hypothesis, lang)}</small>
              </div>
            ))}
          </section>
        )}
        {section(
          heading('Before this goes live'),
          c.risks_uncertainties_validation || c.uncertainties_and_required_validation,
        )}
      </div>
      {campaign.evidence_review && <EvidenceSection review={campaign.evidence_review} />}
      <details className="evidence-drawer">
        <summary>
          <ShieldCheck size={17} /> Why ATIA chose this destination <ChevronDown size={16} />
        </summary>
        <div>
          <p dir="auto">
            {campaign.opportunity?.hypothesis ||
              text(c.opportunity_hypothesis, lang) ||
              'See the saved proposal and its supporting sources.'}
          </p>
          {campaign.opportunity?.limitations?.map((s, i) => (
            <p className="muted" key={i} dir="auto">
              {s}
            </p>
          ))}
          {campaign.sources.map((s) => (
            <SourceLink key={s.url} source={s} />
          ))}
          {!campaign.sources.length && (
            <p className="muted">No source excerpts are attached to this preliminary brief.</p>
          )}
          <small>
            Source evidence supports an opportunity hypothesis, not guaranteed tourism demand. All
            copy and permissions require human review.
          </small>
        </div>
      </details>
      <div className="approval-bar">
        <div>
          <ShieldCheck size={18} />
          <span>
            {campaign.review
              ? `Reviewed by ${campaign.review.reviewer}`
              : 'Your approval comes first.'}
            <small>No automatic publishing. Ever.</small>
          </span>
        </div>
        <div className="action-group">
          {campaign.kind === 'campaign' && campaign.status !== 'REVISION_REQUESTED' && (
            <button
              className="button quiet"
              onClick={() => onReview(campaign, 'REVISION_REQUESTED')}
            >
              <RotateCcw size={15} /> Request revision
            </button>
          )}
          {campaign.status === 'PENDING_APPROVAL' && (
            <>
              <button className="button quiet" onClick={() => onReview(campaign, 'REJECTED')}>
                <X size={15} /> Reject draft
              </button>
              {!campaign.media_validation_required && (
                <button
                  className="button primary"
                  disabled={campaign.validation?.state === 'NEEDS_CORRECTION'}
                  title={
                    campaign.validation?.state === 'NEEDS_CORRECTION'
                      ? 'Fix the blocking issues first'
                      : undefined
                  }
                  onClick={() => onReview(campaign, 'APPROVED')}
                >
                  <Check size={15} /> Approve draft
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </Modal>
  )
}
