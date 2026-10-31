// @vitest-environment jsdom
// Synthetic fixtures only. Covers behaviour specific to the visual redesign; paid services are never called.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import App from './App'
import { Media } from './Media'
import type {
  Campaign,
  Destination,
  MediaAsset,
  Opportunity,
  PreparationJob,
  Workspace,
} from './productTypes'

const entity = {
  entity_id: 'e1',
  verified_name: 'Test fort',
  entity_type: 'attraction',
  verification_status: 'authoritative_source_name_confirmed',
  sources: [],
}
const photo: MediaAsset = {
  media_id: 'afaq_historical:1',
  provider: 'flickr',
  source: 'afaq_historical',
  photo_id: '1',
  preview_url: '/api/images/afaq_historical/1',
  source_url: 'https://www.flickr.com/photo.gne?id=1',
  title: 'Old-village-view',
  attribution: 'Test photographer',
  license_name: null,
  license_url: null,
  rights_status: 'permission_not_verified',
  usage_scope: 'internal_reference_only',
  association_status: 'geographic_context_only',
  approval_status: 'APPROVED',
  entity_id: null,
}
const area = (over: Partial<Destination>): Destination => ({
  cluster_id: 'a1',
  name: 'Area',
  centroid: { latitude: 24.63, longitude: 46.71 },
  regions: { Central: 1 },
  localities: [],
  photo_count: 1,
  association_status: 'not_researched',
  entities: [],
  relevance_coverage: {},
  media: null,
  context_media: [],
  hidden_gem_candidate: false,
  ...over,
})
const staleJob: PreparationJob = {
  job_id: 'old',
  status: 'needs_review',
  outcome: 'INVESTIGATE',
  message: 'Investigation stopped safely.',
  progress: [],
}
const draft: Campaign = {
  id: 'draft',
  opportunity_id: 'qassim',
  kind: 'campaign',
  cluster_id: 'qassim',
  created_at: '2026-10-30T10:00:00Z',
  status: 'PENDING_APPROVAL',
  content: { campaign_name: { en: 'Palm Country', ar: 'بلاد النخيل' } },
  media: [],
  sources: [],
  media_validation_required: false,
}
let workspace: Workspace
const json = (data: unknown) => new Response(JSON.stringify(data), { status: 200 })

beforeEach(() => {
  location.hash = ''
  workspace = {
    campaigns: [],
    entities: [],
    agent_status: 'idle',
    archive: [],
    activity: [
      {
        id: 'r1',
        kind: 'discovery',
        created_at: '2026-10-30T10:00:00Z',
        status: 'completed',
        decision: 'INVESTIGATE',
        summary: 'Final decision failed schema validation.',
        uncertainties: [],
        errors: true,
        sources: [],
      },
    ],
    areas: [
      area({ cluster_id: 'named', entities: [entity], context_media: [photo] }),
      area({ cluster_id: 'plain', localities: [{ name: 'جدة' }], regions: { West: 1 } }),
      area({ cluster_id: 'plain-2', regions: { South: 1 } }),
    ],
  }
  vi.stubGlobal('scrollTo', vi.fn())
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true,
    value(this: HTMLDialogElement) {
      this.setAttribute('open', '')
    },
  })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', {
    configurable: true,
    value(this: HTMLDialogElement) {
      this.removeAttribute('open')
    },
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      if (path === '/api/workspace') return json(workspace)
      if (path === '/api/calendar') return json({ entries: [] })
      if (path === '/api/campaign-requests') return json({ jobs: [staleJob] })
      if (path === '/api/agent/policy')
        return json({
          limits: { run_budget_usd: 0.05, max_steps: 4, max_tool_calls: 3, max_searches: 1 },
        })
      throw Error(`Unexpected request ${path}`)
    }),
  )
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const ready = async () => {
  render(<App />)
  await screen.findByText('No campaign justified yet')
}
const openDiscover = () => fireEvent.click(screen.getByRole('button', { name: 'Discover' }))

const opportunity: Opportunity = {
  id: 'qassim',
  kind: 'regional_experience',
  title: { en: 'Agricultural tourism in Al Qassim', ar: 'السياحة الزراعية في القصيم' },
  angle: { en: 'Date-palm country', ar: 'موطن النخيل' },
  evidence_strength: 'thin',
  evidence_label: 'Exploratory',
  evidence: {
    photo_count: 1,
    distinct_photographers: 1,
    views: { total: 10, photos_reporting: 1 },
    favorites: { total: 1, photos_reporting: 1 },
    comments: { total: 0, photos_reporting: 1 },
  },
  regions: [{ key: 'qassim', en: 'Al Qassim', ar: 'القصيم', photos: 1 }],
  localities: [],
  identity_status: null,
  media: null,
  gallery: [],
  licensed_images: 0,
  evidence_photos: [],
  research: [],
  sensitive_note: null,
  campaign_id: null,
  campaign_status: null,
}

describe('Marketing opportunities', () => {
  const withOpportunity = () => {
    workspace.opportunities = [opportunity]
    workspace.areas = [area({ cluster_id: 'named', entities: [entity] })]
  }

  it('labels single-photo evidence honestly and asks to confirm the paid request', async () => {
    withOpportunity()
    await ready()
    openDiscover()
    expect(screen.getAllByText('Exploratory').length).toBe(1)
    expect(screen.getByText('1 photo · 1 photographer')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Create Campaign/ }))
    const dialog = screen.getByRole('dialog')
    expect(dialog.textContent).toContain('$0.05')
    expect(dialog.textContent).toContain('No Tavily search')
    expect(vi.mocked(fetch).mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(0)
  })

  it('explains a text-only opportunity and what has not been assessed', async () => {
    withOpportunity()
    await ready()
    openDiscover()
    fireEvent.click(screen.getByRole('button', { name: /Agricultural tourism.*View opportunity/ }))
    const dialog = within(screen.getByRole('dialog'))
    expect(dialog.getByText(/text-only draft is possible/)).toBeTruthy()
    expect(dialog.getByText(/low\s+engagement is not evidence of underpromotion/)).toBeTruthy()
    expect(dialog.getByText('موطن النخيل').getAttribute('dir')).toBe('rtl')
  })

  it('removes the older dead-end create path once opportunities exist', async () => {
    withOpportunity()
    await ready()
    openDiscover()
    expect(screen.getAllByRole('button', { name: /Create Campaign/ })).toHaveLength(1)
  })

  it('opens a draft from a job that finished before the first poll', async () => {
    withOpportunity()
    workspace.campaigns = []
    vi.mocked(fetch).mockImplementation(async (path, options) => {
      if (path === '/api/campaign-requests' && options?.method === 'POST')
        return json({ job_id: 'fast', status: 'queued', progress: [] })
      if (path === '/api/workspace') return json(workspace)
      if (path === '/api/calendar') return json({ entries: [] })
      if (path === '/api/campaign-requests') {
        const done = vi.mocked(fetch).mock.calls.some(([, o]) => o?.method === 'POST')
        if (done) workspace.campaigns = [draft]
        return json({
          jobs: done
            ? [
                {
                  job_id: 'fast',
                  status: 'completed',
                  outcome: 'CREATE',
                  campaign_id: 'draft',
                  progress: [],
                },
              ]
            : [],
        })
      }
      if (path === '/api/agent/policy')
        return json({
          limits: { run_budget_usd: 0.05, max_steps: 4, max_tool_calls: 3, max_searches: 1 },
        })
      throw Error(`Unexpected request ${path}`)
    })
    await ready()
    openDiscover()
    fireEvent.click(screen.getByRole('button', { name: /Create Campaign/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm & start research' }))
    await screen.findByRole('heading', { level: 2, name: 'Palm Country' })
    expect(screen.getByText(/Text-only draft/)).toBeTruthy()
    const body = vi.mocked(fetch).mock.calls.find(([, o]) => o?.method === 'POST')?.[1]?.body
    expect(JSON.parse(String(body)).opportunity_id).toBe('qassim')
  })
})

describe('Image display', () => {
  it('renders only images the server marks approved, and only from its own route', () => {
    const asset = {
      media_id: 'x',
      provider: 'flickr',
      source: 'afaq_historical',
      photo_id: '1',
      preview_url: '/api/images/afaq_historical/1',
      source_url: '',
      title: 'x',
      attribution: 'x',
      license_name: null,
      license_url: null,
      rights_status: 'reusable_with_attribution',
      usage_scope: 'campaign_draft',
      association_status: 'x',
      approval_status: 'CURATED',
      entity_id: null,
    } as unknown as MediaAsset
    const { rerender } = render(<Media asset={asset} />)
    expect(screen.queryByRole('img')).toBeNull()
    rerender(
      <Media
        asset={{
          ...asset,
          approval_status: 'APPROVED',
          preview_url: 'https://live.staticflickr.com/1/1_z.jpg',
        }}
      />,
    )
    expect(screen.queryByRole('img')).toBeNull()
    rerender(<Media asset={{ ...asset, approval_status: 'APPROVED' }} />)
    expect(screen.getByRole('img')).toBeTruthy()
  })
})

describe('Campaign evidence review', () => {
  const reviewed: Campaign = {
    ...draft,
    revision: 1,
    edited_by: 'Editor',
    content: {
      ...draft.content,
      positioning: { en: 'Original position', ar: 'تموضع' },
      opportunity_hypothesis: { en: 'A hypothesis', ar: 'فرضية' },
      key_messages: [
        { en: 'First message', ar: 'رسالة أولى' },
        { en: 'Second message', ar: 'رسالة ثانية' },
      ],
      creative_direction: { en: 'Direction', ar: 'توجه' },
    },
    evidence_review: {
      recommendation: 'Draft an awareness campaign.',
      claims: [
        {
          claim: 'Three photographers shared palm photographs.',
          sources: [
            { title: 'Palm', url: 'https://flickr.com/p', publisher: 'Flickr · Ibn Dzerir' },
          ],
        },
      ],
      raw_claims: [
        { claim: 'Three photographers shared palm photographs.', evidence_refs: ['photo:1'] },
      ],
      uncertainties: ['Farm access is unverified.'],
      edited: true,
      original: {
        recommendation: 'Old',
        claims: ['Engagement indicates interest.'],
        uncertainties: [],
      },
    },
  }
  const openDraft = async () => {
    workspace.campaigns = [reviewed]
    render(<App />)
    await screen.findByText('Featured campaign')
    fireEvent.click(screen.getAllByRole('button', { name: /Palm Country/ })[0])
    return within(screen.getByRole('dialog'))
  }

  it('shows claims, their sources and uncertainties before approval', async () => {
    const dialog = await openDraft()
    expect(dialog.getByText('Three photographers shared palm photographs.')).toBeTruthy()
    expect(dialog.getByRole('link', { name: /Flickr · Ibn Dzerir/ })).toBeTruthy()
    expect(dialog.getByText('Farm access is unverified.')).toBeTruthy()
    expect(dialog.getByRole('button', { name: 'Approve draft' })).toBeTruthy()
  })

  it('keeps the original AI claims visible and credits the editor accurately', async () => {
    const dialog = await openDraft()
    expect(dialog.getByText('Engagement indicates interest.')).toBeTruthy()
    expect(dialog.getByText(/Revision 1 by Editor/)).toBeTruthy()
    expect(dialog.queryByText(/Human revision/)).toBeNull()
  })

  it('offers every copy field for editing, and lets a message be removed', async () => {
    const dialog = await openDraft()
    fireEvent.click(dialog.getByRole('button', { name: 'Edit campaign' }))
    const editor = within(screen.getByRole('dialog'))
    expect(editor.getByLabelText('Positioning English')).toBeTruthy()
    expect(editor.getByLabelText('Opportunity hypothesis Arabic').getAttribute('dir')).toBe('rtl')
    expect(editor.getByLabelText('Key message 2 English')).toBeTruthy()
    expect(editor.getByLabelText('Claim 1')).toBeTruthy()
    fireEvent.click(editor.getByRole('button', { name: 'Remove key message 2' }))
    expect(editor.queryByLabelText('Key message 2 English')).toBeNull()
  })
})

describe('Tourism Studio redesign', () => {
  it('does not announce a past job or show operational detail on Studio', async () => {
    await ready()
    expect(screen.queryByText('Additional evidence required')).toBeNull()
    expect(screen.queryByText('Investigation stopped safely.')).toBeNull()
    expect(screen.queryByRole('status')).toBeNull()
    const history = screen.getByText('Research history').closest('details')!
    expect(history.open).toBe(false)
    expect(vi.mocked(fetch).mock.calls.every(([, o]) => !o?.method)).toBe(true)
  })

  it('renders missing imagery as silent decoration, not as images or warnings', async () => {
    await ready()
    openDiscover()
    expect(screen.queryByText(/image pending/i)).toBeNull()
    expect(screen.queryByText(/not available/i)).toBeNull()
    expect(screen.getAllByText(/Identity verification needed/)).toHaveLength(1)
    document.querySelectorAll('.plate svg').forEach((svg) => {
      expect(svg.getAttribute('aria-hidden')).toBe('true')
    })
    expect(screen.getAllByText('24.63° N · 46.71° E').length).toBeGreaterThan(0)
  })

  it('uses only local archive pixels and names no verified image rights', async () => {
    await ready()
    openDiscover()
    const images = screen.getAllByRole('img') as HTMLImageElement[]
    expect(images.map((i) => i.getAttribute('src'))).toEqual(['/api/images/afaq_historical/1'])
    fireEvent.click(screen.getByRole('button', { name: /Test fort.*View research/ }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getAllByText(/not verified campaign assets/).length).toBe(1)
    await waitFor(() => expect(within(dialog).getByText(/could not be loaded/)).toBeTruthy())
  })

  it('renders Arabic place names with automatic direction', async () => {
    await ready()
    openDiscover()
    expect(screen.getByRole('heading', { name: 'جدة' }).getAttribute('dir')).toBe('auto')
  })

  it('keeps the cost confirmation between Studio shortcuts and paid requests', async () => {
    await ready()
    fireEvent.click(screen.getByRole('button', { name: /Create Campaign/ }))
    expect(screen.getByRole('dialog').textContent).toContain('$0.05')
    expect(vi.mocked(fetch).mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(0)
  })
})
