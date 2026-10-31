import { useId, useMemo } from 'react'

export interface PlateProps {
  seed: string
  region?: string
  latitude?: number
  longitude?: number
}

const palettes: Record<string, string[]> = {
  Central: ['#f0d9b5', '#e3b27e', '#fff1d6', '#cf9468', '#b0714c', '#7f4f38', '#4b3226'],
  West: ['#f3d3bd', '#d99b88', '#fff0e2', '#a8786f', '#6f6a6b', '#3f5a5c', '#1f3d40'],
  East: ['#efe3c4', '#c9c58f', '#fff8df', '#8fae97', '#5f8f83', '#356b64', '#174640'],
  North: ['#f5dcb9', '#e8a96f', '#fff0d4', '#c97f52', '#9c5a3c', '#6a3d2d', '#3d2620'],
  South: ['#dfe3c5', '#a9bd94', '#f8f6dd', '#7d9e7b', '#557f63', '#2f5f4b', '#163f35'],
  default: ['#efe6d3', '#d8c6a3', '#fff7e4', '#b29f7e', '#8a7c62', '#5f5a49', '#2f3a31'],
}

function random(seed: string) {
  let state = 2166136261
  for (const char of seed) state = Math.imul(state ^ char.charCodeAt(0), 16777619)
  return () => {
    state = (state + 0x6d2b79f5) | 0
    let t = Math.imul(state ^ (state >>> 15), 1 | state)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function ridge(next: () => number, base: number, height: number) {
  const phase = next() * 6.28
  const frequency = 0.008 + next() * 0.012
  const points = Array.from({ length: 19 }, (_, i) => {
    const x = i * 25 - 25
    const wave = Math.sin(x * frequency + phase) * height
    return [x, base - wave - next() * height * 0.28]
  })
  const curve = points
    .slice(1)
    .map(([x, y], i) => {
      const [px, py] = points[i]
      return `Q${px} ${py.toFixed(1)} ${(px + x) / 2} ${((py + y) / 2).toFixed(1)}`
    })
    .join(' ')
  return `M-25 ${points[0][1].toFixed(1)} ${curve} L425 280 L-25 280Z`
}

export function formatCoordinates(latitude?: number, longitude?: number) {
  if (typeof latitude !== 'number' || typeof longitude !== 'number') return ''
  return `${Math.abs(latitude).toFixed(2)}° ${latitude < 0 ? 'S' : 'N'} · ${Math.abs(longitude).toFixed(2)}° ${longitude < 0 ? 'W' : 'E'}`
}

/**
 * An abstract atlas plate for places with no approved photograph. It is generated from the
 * place's id, region and stored coordinates, and is never presented as a picture of the place.
 */
export function Plate({ seed, region, latitude, longitude }: PlateProps) {
  const id = useId()
  const colors = palettes[region || ''] || palettes.default
  const shapes = useMemo(() => {
    const next = random(seed)
    const sun = { x: 60 + next() * 280, y: 84 + next() * 30, r: 14 + next() * 12 }
    const layers = [
      ridge(next, 150 + next() * 16, 22),
      ridge(next, 182 + next() * 14, 20),
      ridge(next, 214 + next() * 10, 16),
      ridge(next, 242 + next() * 8, 12),
    ]
    return { sun, layers }
  }, [seed])
  const coordinates = formatCoordinates(latitude, longitude)
  return (
    <div className="plate">
      <svg viewBox="0 0 400 260" preserveAspectRatio="xMidYMax slice" aria-hidden="true">
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={colors[0]} />
            <stop offset="0.72" stopColor={colors[1]} />
          </linearGradient>
        </defs>
        <rect width="400" height="260" fill={`url(#${id})`} />
        <circle
          cx={shapes.sun.x}
          cy={shapes.sun.y}
          r={shapes.sun.r}
          fill={colors[2]}
          opacity="0.9"
        />
        {shapes.layers.map((path, i) => (
          <path key={i} d={path} fill={colors[i + 3]} />
        ))}
      </svg>
      {coordinates && <span className="plate-coordinates">{coordinates}</span>}
    </div>
  )
}
