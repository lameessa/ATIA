import { useEffect, useState } from 'react'
import { ArrowUpRight, Info } from 'lucide-react'
import { safeUrl } from './components'
import { Plate, type PlateProps } from './Plate'
import type { MediaAsset } from './productTypes'

/** A provider-neutral image contract. No arbitrary URL fallback or unapproved pixels. */
export function Media({
  asset,
  alt,
  className = '',
  eager = false,
  plate,
}: {
  asset?: MediaAsset | null
  alt?: string
  className?: string
  eager?: boolean
  plate?: PlateProps
}) {
  const [failed, setFailed] = useState(false)
  useEffect(() => setFailed(false), [asset?.media_id])
  const approved = asset?.approval_status === 'APPROVED'
  const local = asset?.preview_url.startsWith('/api/images/')
  return (
    <div className={`media ${className}`}>
      {approved && local && !failed ? (
        <img
          src={asset.preview_url}
          alt={alt || 'Reviewed Saudi photograph; exact destination association unverified'}
          loading={eager ? 'eager' : 'lazy'}
          onError={() => setFailed(true)}
        />
      ) : (
        <Plate {...(plate || { seed: asset?.media_id || 'atia' })} />
      )}
      {failed && <span className="media-failed">Image unavailable</span>}
    </div>
  )
}

export function MediaCredit({ asset }: { asset: MediaAsset }) {
  return (
    <details className="media-credit">
      <summary aria-label="Photo attribution and license" title="Photo credits">
        <Info size={14} />
      </summary>
      <div>
        <a href={safeUrl(asset.source_url)} target="_blank" rel="noreferrer">
          {asset.provider === 'flickr'
            ? asset.source === 'afaq_historical'
              ? 'Flickr / Afaq archive'
              : 'Flickr'
            : asset.provider}{' '}
          <ArrowUpRight size={12} />
        </a>
        <p>{asset.attribution}</p>
        <p>
          {asset.license_name || 'Usage permission has not been verified.'}{' '}
          {asset.license_url && (
            <a href={safeUrl(asset.license_url)} target="_blank" rel="noreferrer">
              License ↗
            </a>
          )}
        </p>
        {asset.review_basis && <p>{asset.review_basis}</p>}
        <small>
          {asset.usage_scope === 'campaign_draft'
            ? 'Reviewed association · draft campaign asset.'
            : 'Internal reference only · not cleared for campaign use.'}
        </small>
      </div>
    </details>
  )
}
