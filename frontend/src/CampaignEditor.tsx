import { useState, type FormEvent } from 'react'
import { Check, Loader2, X } from 'lucide-react'
import { api } from './api'
import { Notice } from './components'
import { list, text } from './CampaignWorkspace'
import type { Bilingual, Campaign, PlannedPost, SocialPost } from './productTypes'

const SINGLE_FIELDS: [string, string][] = [
  ['positioning', 'Positioning'],
  ['opportunity_hypothesis', 'Opportunity hypothesis'],
  ['target_audience', 'Target audience'],
  ['audience_rationale_hypothesis', 'Why this audience'],
]
const LIST_FIELDS: [string, string][] = [
  ['objectives', 'Objective'],
  ['key_messages', 'Key message'],
  ['risks_uncertainties_validation', 'Check before launch'],
]
const KPI_FIELDS: ['metric' | 'measurement_plan' | 'proposed_target_hypothesis', string][] = [
  ['metric', 'Measure'],
  ['measurement_plan', 'Measurement plan'],
  ['proposed_target_hypothesis', 'Target hypothesis'],
]

export default function CampaignEditor({
  campaign,
  onCancel,
  onSaved,
}: {
  campaign: Campaign
  onCancel: () => void
  onSaved: () => Promise<void>
}) {
  const content = campaign.content
  const bilingual = (value: unknown): Bilingual => ({ en: text(value), ar: text(value, 'ar') })
  const posts = list(content.social_posts) as SocialPost[]
  const [title, setTitle] = useState(bilingual(content.campaign_name))
  const [description, setDescription] = useState(bilingual(content.central_concept))
  const [creative, setCreative] = useState(bilingual(content.creative_direction))
  const [captions, setCaptions] = useState<Record<string, Bilingual>>(
    Object.fromEntries(posts.map((p) => [p.post_id, { ...p.caption }])),
  )
  const schedule = list(content.publishing_schedule) as PlannedPost[]
  const measures = list(content.kpis_and_measurement) as Record<string, unknown>[]
  const [singles, setSingles] = useState<Record<string, Bilingual>>(
    Object.fromEntries(
      SINGLE_FIELDS.filter(([key]) => content[key]).map(([key]) => [key, bilingual(content[key])]),
    ),
  )
  const [lists, setLists] = useState<Record<string, Bilingual[]>>(
    Object.fromEntries(
      LIST_FIELDS.filter(([key]) => list(content[key]).length).map(([key]) => [
        key,
        list(content[key]).map(bilingual),
      ]),
    ),
  )
  const [activities, setActivities] = useState<Record<string, Bilingual>>(
    Object.fromEntries(schedule.map((s) => [s.post_id, bilingual(s.activity)])),
  )
  const [kpis, setKpis] = useState(
    measures.map((m) => ({
      metric: bilingual(m.metric),
      measurement_plan: bilingual(m.measurement_plan),
      proposed_target_hypothesis: bilingual(m.proposed_target_hypothesis),
    })),
  )
  const review = campaign.evidence_review
  const [recommendation, setRecommendation] = useState(review?.recommendation || '')
  const [claims, setClaims] = useState(review?.raw_claims || [])
  const [uncertainties, setUncertainties] = useState(review?.uncertainties || [])
  const [dates, setDates] = useState<Record<string, string>>(campaign.publishing_dates || {})
  const [editor, setEditor] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function save(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api(`/campaigns/${encodeURIComponent(campaign.id)}/edit`, {
        revision: campaign.revision || 0,
        editor: editor.trim() || 'Local editor',
        confirmed: true,
        title,
        description,
        creative_direction: creative,
        captions,
        ...singles,
        ...lists,
        schedule_activities: activities,
        ...(kpis.length ? { kpis } : {}),
        ...(review ? { evidence: { recommendation, claims, uncertainties } } : {}),
        publishing_dates: Object.fromEntries(Object.entries(dates).filter(([, v]) => v)),
      })
      await onSaved()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function fields(label: string, value: Bilingual, set: (v: Bilingual) => void) {
    return (
      <fieldset className="bilingual-edit">
        <legend>{label}</legend>
        <label className="field">
          English
          <textarea
            aria-label={`${label} English`}
            required
            maxLength={4000}
            value={value.en}
            onChange={(e) => set({ ...value, en: e.target.value })}
          />
        </label>
        <label className="field">
          العربية
          <textarea
            aria-label={`${label} Arabic`}
            dir="rtl"
            lang="ar"
            required
            maxLength={4000}
            value={value.ar}
            onChange={(e) => set({ ...value, ar: e.target.value })}
          />
        </label>
      </fieldset>
    )
  }

  return (
    <form className="campaign-editor" onSubmit={(e) => void save(e)}>
      <Notice>
        Edits create a new human-reviewed version. The original AI draft and research evidence are
        preserved. Saving never publishes content.
      </Notice>
      <label className="field">
        Editor name
        <input
          value={editor}
          maxLength={120}
          onChange={(e) => setEditor(e.target.value)}
          placeholder="Your name"
        />
      </label>
      {fields('Campaign title', title, setTitle)}
      {fields('Description', description, setDescription)}
      {fields('Creative direction', creative, setCreative)}
      {SINGLE_FIELDS.filter(([key]) => singles[key]).map(([key, label]) => (
        <div key={key}>
          {fields(label, singles[key], (v) => setSingles({ ...singles, [key]: v }))}
        </div>
      ))}
      {LIST_FIELDS.filter(([key]) => lists[key]).map(([key, label]) => (
        <section key={key}>
          {lists[key].map((item, i) => (
            <div key={i} className="editable-item">
              {fields(`${label} ${i + 1}`, item, (v) =>
                setLists({ ...lists, [key]: lists[key].map((x, n) => (n === i ? v : x)) }),
              )}
              {lists[key].length > 1 && (
                <button
                  type="button"
                  className="button quiet small"
                  onClick={() =>
                    setLists({ ...lists, [key]: lists[key].filter((_, n) => n !== i) })
                  }
                >
                  Remove {label.toLowerCase()} {i + 1}
                </button>
              )}
            </div>
          ))}
        </section>
      ))}
      {posts.map((post, i) => (
        <section key={post.post_id}>
          {fields(`Caption ${i + 1} · ${post.channel}`, captions[post.post_id], (v) =>
            setCaptions({ ...captions, [post.post_id]: v }),
          )}
          <label className="field">
            Proposed date · {post.channel} · post {i + 1}
            <input
              type="date"
              value={dates[post.post_id] || ''}
              onChange={(e) => setDates({ ...dates, [post.post_id]: e.target.value })}
            />
          </label>
          {activities[post.post_id] &&
            fields(`Planned activity ${i + 1}`, activities[post.post_id], (v) =>
              setActivities({ ...activities, [post.post_id]: v }),
            )}
        </section>
      ))}
      {kpis.map((kpi, i) => (
        <section key={i}>
          {KPI_FIELDS.map(([key, label]) => (
            <div key={key}>
              {fields(`${label} ${i + 1}`, kpi[key], (v) =>
                setKpis(kpis.map((x, n) => (n === i ? { ...x, [key]: v } : x))),
              )}
            </div>
          ))}
        </section>
      ))}
      {review && (
        <fieldset className="campaign-editor">
          <legend>Evidence shown to reviewers</legend>
          <label className="field">
            Recommendation
            <textarea
              dir="auto"
              required
              maxLength={2000}
              value={recommendation}
              onChange={(e) => setRecommendation(e.target.value)}
            />
          </label>
          {claims.map((item, i) => (
            <label className="field" key={i}>
              Claim {i + 1}
              <textarea
                dir="auto"
                required
                maxLength={1000}
                value={item.claim}
                onChange={(e) =>
                  setClaims(claims.map((x, n) => (n === i ? { ...x, claim: e.target.value } : x)))
                }
              />
            </label>
          ))}
          {uncertainties.map((item, i) => (
            <label className="field" key={i}>
              Uncertainty {i + 1}
              <textarea
                dir="auto"
                required
                value={item}
                onChange={(e) =>
                  setUncertainties(uncertainties.map((x, n) => (n === i ? e.target.value : x)))
                }
              />
            </label>
          ))}
        </fieldset>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      <div className="dialog-actions">
        <button type="button" className="button quiet" disabled={busy} onClick={onCancel}>
          <X size={15} /> Cancel editing
        </button>
        <button className="button primary" disabled={busy} type="submit">
          {busy ? <Loader2 size={15} className="spinner" /> : <Check size={15} />}
          Save changes
        </button>
      </div>
    </form>
  )
}
