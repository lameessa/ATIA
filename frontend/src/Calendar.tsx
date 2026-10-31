import { useState } from 'react'
import { ArrowRight, CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'
import type { Campaign, CalendarEntry } from './productTypes'
import { text } from './CampaignWorkspace'

const weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export default function Calendar({
  campaigns,
  entries = [],
  onCampaign,
}: {
  campaigns: Campaign[]
  entries?: CalendarEntry[]
  onCampaign: (c: Campaign) => void
}) {
  const today = new Date()
  // Open on the first planned post, so a future launch is visible straight away.
  const [month, setMonth] = useState(() => {
    const upcoming = entries
      .filter((e) => e.status === 'APPROVED_PLAN' && e.proposed_date)
      .map((e) => new Date(`${e.proposed_date}T00:00:00`))
      .filter((d) => d >= new Date(today.getFullYear(), today.getMonth(), 1))
      .sort((a, b) => a.getTime() - b.getTime())[0]
    const start = upcoming || today
    return new Date(start.getFullYear(), start.getMonth(), 1)
  })
  const start = (month.getDay() + 6) % 7
  const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate()
  const approved = entries.filter((e) => e.status === 'APPROVED_PLAN')
  const undated = approved.filter((e) => !e.proposed_date)
  const shift = (by: number) => setMonth(new Date(month.getFullYear(), month.getMonth() + by, 1))
  const open = (entry: CalendarEntry) => {
    const campaign = campaigns.find((c) => c.id === entry.campaign_id)
    if (campaign) onCampaign(campaign)
  }

  return (
    <div className="calendar-layout">
      <section className="calendar-panel">
        <div className="calendar-toolbar">
          <h2>{month.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}</h2>
          <div>
            <button
              className="button quiet small"
              onClick={() => setMonth(new Date(today.getFullYear(), today.getMonth(), 1))}
            >
              Today
            </button>
            <button className="icon-btn" aria-label="Previous month" onClick={() => shift(-1)}>
              <ChevronLeft size={16} />
            </button>
            <button className="icon-btn" aria-label="Next month" onClick={() => shift(1)}>
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
        <div className="calendar-week">
          {weekdays.map((day) => (
            <span key={day}>{day}</span>
          ))}
        </div>
        <div className="calendar-days" aria-label="Campaign planning calendar">
          {Array.from({ length: Math.ceil((start + days) / 7) * 7 }, (_, i) => {
            const day = i - start + 1
            const valid = day > 0 && day <= days
            const iso = `${month.getFullYear()}-${String(month.getMonth() + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
            const isToday =
              valid &&
              day === today.getDate() &&
              month.getMonth() === today.getMonth() &&
              month.getFullYear() === today.getFullYear()
            return (
              <div
                key={i}
                className={`calendar-cell ${valid ? '' : 'outside'} ${isToday ? 'today' : ''}`}
              >
                <span>{valid ? day : ''}</span>
                {valid &&
                  approved
                    .filter((e) => e.proposed_date === iso)
                    .map((e) => (
                      <button
                        key={`${e.campaign_id}-${e.post_id}`}
                        className="calendar-event"
                        onClick={() => open(e)}
                        title={text(e.caption)}
                      >
                        <strong dir="auto">{text(e.campaign_name)}</strong>
                        <small>
                          {e.platform} · {e.local_time}
                        </small>
                      </button>
                    ))}
              </div>
            )
          })}
        </div>
      </section>
      <aside className="side-panel calendar-agenda">
        <h2>{approved.length ? 'Approved content' : 'No approved campaigns yet'}</h2>
        {approved.length ? (
          <>
            <p className="muted small">
              {undated.length
                ? `${undated.length} approved posts still need a proposed date.`
                : 'Publishing dates are proposed, not external commitments.'}
            </p>
            {approved.map((e, i) => (
              <button className="agenda-card" key={i} onClick={() => open(e)}>
                <span className="eyebrow">
                  {e.proposed_date || `Undated · Day ${e.relative_day} after launch`}
                </span>
                <h3 dir="auto">{text(e.campaign_name)}</h3>
                <small>
                  {e.platform} · {e.local_time} {e.timezone}
                </small>
                {text(e.caption) && <p dir="auto">{text(e.caption)}</p>}
                <span className="text-link">
                  View campaign <ArrowRight size={13} />
                </span>
              </button>
            ))}
          </>
        ) : (
          <div className="agenda-empty">
            <CalendarDays size={26} strokeWidth={1.3} />
            <p>Approve a campaign in Studio and its content plan will appear here.</p>
          </div>
        )}
      </aside>
    </div>
  )
}
