import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowUpRight, Check, Compass, Database, ImageOff, Info, Search, X } from 'lucide-react'
import type { Photo, Source } from './types'

export const human = (s: string) => s.replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())
export const date = (s?: string) =>
  s
    ? new Date(s).toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : 'Not recorded'
export const money = (n: number) => `$${n.toFixed(n < 0.01 ? 5 : 2)}`
export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: string }) {
  return <span className={`badge ${tone}`}>{children}</span>
}
export function Status({ value }: { value: string }) {
  const tone =
    /APPROVED|relevant|completed|confirmed/.test(value) && !/irrelevant|unconfirmed/.test(value)
      ? 'green'
      : /REJECTED|failed|irrelevant/.test(value)
        ? 'red'
        : /INVESTIGATE|uncertain|provisional|unresolved|PENDING|needs_review/.test(value)
          ? 'amber'
          : 'neutral'
  const label = value.startsWith('provisional')
    ? 'Provisional association'
    : value === 'authoritative_source_name_confirmed'
      ? 'Source-verified identity'
      : value.startsWith('unresolved')
        ? 'Unresolved identity'
        : human(value)
  return <Badge tone={tone}>{label}</Badge>
}
export function Empty({
  title,
  children,
  icon = 'search',
}: {
  title: string
  children: ReactNode
  icon?: string
}) {
  const Icon = icon === 'data' ? Database : icon === 'place' ? Compass : Search
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon size={25} />
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  )
}
export function Notice({ children, tone = 'info' }: { children: ReactNode; tone?: string }) {
  return (
    <div className={`notice ${tone}`}>
      <Info size={17} />
      <div>{children}</div>
    </div>
  )
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: ReactNode
  children: ReactNode
  onClose: () => void
  wide?: boolean
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const el = ref.current
    el?.showModal()
    return () => el?.close()
  }, [])
  return (
    <dialog
      ref={ref}
      className={`modal ${wide ? 'wide' : ''}`}
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose()
      }}
      aria-labelledby="dialog-title"
    >
      <div className="modal-content">
        <div className="modal-heading">
          <h2 id="dialog-title">{title}</h2>
          <button className="icon-btn" aria-label="Close dialog" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </dialog>
  )
}
export function SourceLink({ source }: { source: Source }) {
  return (
    <a className="source-link" href={safeUrl(source.url)} target="_blank" rel="noreferrer">
      <span className="source-mark">
        <Check size={14} />
      </span>
      <span>
        <strong>{source.title || source.url}</strong>
        <small>
          {source.publisher || host(source.url)}
          {source.observed_at ? ` · ${date(source.observed_at)}` : ''}
        </small>
      </span>
      <ArrowUpRight size={17} />
    </a>
  )
}
export function safeUrl(url: string) {
  try {
    return new URL(url).protocol === 'https:' ? url : undefined
  } catch {
    return undefined
  }
}
export function host(url: string) {
  try {
    return new URL(url).hostname.replace('www.', '')
  } catch {
    return 'Stored source'
  }
}
export function EvidenceRef({ value }: { value: string }) {
  return value.startsWith('https://') ? (
    <a className="evidence-ref" href={safeUrl(value)} target="_blank" rel="noreferrer">
      {host(value)} <ArrowUpRight size={12} />
    </a>
  ) : (
    <code className="evidence-ref" title={value}>
      {value}
    </code>
  )
}
export function Json({
  value,
  label = 'Inspect stored evidence',
}: {
  value: unknown
  label?: string
}) {
  return (
    <details className="json-detail">
      <summary>{label}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  )
}
export function Facts({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="facts">
      {Object.entries(data)
        .filter(
          ([k]) => !['note', 'interpretation', 'model', 'model_and_prompt_versions'].includes(k),
        )
        .map(([k, v]) => (
          <div key={k}>
            <span>{human(k)}</span>
            {typeof v === 'object' && v !== null ? (
              <Json label="View breakdown" value={v} />
            ) : (
              <strong>{v === null ? 'Not available' : String(v)}</strong>
            )}
          </div>
        ))}
    </div>
  )
}
export function Photograph({ photo }: { photo: Photo }) {
  const [failed, setFailed] = useState(false)
  return (
    <article className="photo-card">
      <a href={photo.flickr_url} target="_blank" rel="noreferrer" className="photo-preview">
        {photo.preview_url && !failed ? (
          <img
            src={photo.preview_url}
            alt={photo.title || `Flickr photograph ${photo.photo_id}`}
            onError={() => setFailed(true)}
            loading="lazy"
            referrerPolicy="no-referrer"
          />
        ) : (
          <div>
            <ImageOff size={25} />
            <span>Preview unavailable</span>
            <small>Open original on Flickr ↗</small>
          </div>
        )}
        <span className="photo-source">
          {photo.source === 'afaq_historical' ? 'Afaq archive' : 'Live Flickr'}
        </span>
      </a>
      <div className="photo-meta">
        <strong>{photo.title || 'Untitled photograph'}</strong>
        <code>{photo.photo_id}</code>
        <Status value={photo.relevance} />
        <dl>
          <div>
            <dt>Captured</dt>
            <dd>{date(photo.captured_at)}</dd>
          </div>
          <div>
            <dt>Uploaded</dt>
            <dd>{date(photo.uploaded_at)}</dd>
          </div>
          <div>
            <dt>Views</dt>
            <dd>{photo.views ?? 'Not available'}</dd>
          </div>
          <div>
            <dt>License</dt>
            <dd>{photo.license_name || 'Not recorded'}</dd>
          </div>
        </dl>
        {photo.visual ? (
          <Json label="Visual analysis & scores" value={photo.visual} />
        ) : photo.visual_dimensions.length > 0 ? (
          <Json label="Visual dimensions & scores" value={photo.visual_dimensions} />
        ) : (
          <small className="muted">No detailed visual analysis stored.</small>
        )}
      </div>
    </article>
  )
}
