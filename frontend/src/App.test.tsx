// @vitest-environment jsdom
// Synthetic fixtures exist only here. Paid services are never called by tests.
import { afterEach,beforeEach,describe,expect,it,vi } from 'vitest'
import { cleanup,fireEvent,render,screen,waitFor,within } from '@testing-library/react'
import App from './App'
import { Media } from './Media'
import type { Campaign,MediaAsset,Workspace,PreparationJob } from './productTypes'
const bilingual={en:'Test heritage concept',ar:'مفهوم تراثي للاختبار'}
const entity={entity_id:'test-entity',verified_name:'Test destination',entity_type:'destination',verification_status:'authoritative_source_name_confirmed',sources:[]}
const asset:MediaAsset={media_id:'fixture-image',provider:'flickr',source:'afaq_historical',photo_id:'fixture',preview_url:'/api/images/afaq_historical/fixture',source_url:'https://www.flickr.com/photo.gne?id=fixture',title:'Test archive photograph',attribution:'Test photographer',license_name:null,license_url:null,rights_status:'permission_not_verified',usage_scope:'internal_reference_only',association_status:'geographic_context_only',approval_status:'APPROVED',entity_id:null}
const campaign:Campaign={id:'test-campaign',kind:'campaign',cluster_id:'test-area',created_at:'2026-10-30T10:00:00Z',status:'PENDING_APPROVAL',revision:0,publishing_dates:{},content:{campaign_name:{en:'Test heritage pilot',ar:'تجربة تراثية'},central_concept:bilingual,creative_direction:bilingual,destination:{entity_id:'test-entity',name:{en:'Test destination',ar:'وجهة اختبار'}},objectives:[bilingual],social_posts:[{post_id:'p1',channel:'Instagram',caption:bilingual}],publishing_schedule:[{post_id:'p1',days_after_human_approved_launch:3,local_time:'18:30',timezone:'Asia/Riyadh',channel:'Instagram',activity:bilingual}]},media:[],sources:[],media_validation_required:false}
const empty:Workspace={campaigns:[],areas:[{cluster_id:'test-area',name:'Unidentified destination area',centroid:{latitude:24.7,longitude:46.7},regions:{Central:2},localities:[{name:'Test locality'}],photo_count:2,association_status:'not_researched',entities:[entity],relevance_coverage:{not_evaluated:2},media:null,context_media:[],hidden_gem_candidate:false}],entities:[entity],activity:[],archive:[],agent_status:'idle'}
let workspace:Workspace,job:PreparationJob|undefined,outcome='CREATE'
const json=(data:unknown)=>new Response(JSON.stringify(data),{status:200})
beforeEach(()=>{
 workspace=structuredClone(empty);job=undefined;outcome='CREATE';location.hash='';vi.stubGlobal('scrollTo',vi.fn())
 Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:function(this:HTMLDialogElement){this.setAttribute('open','')}})
 Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value:function(this:HTMLDialogElement){this.removeAttribute('open')}})
 vi.stubGlobal('fetch',vi.fn(async(path:string,options?:RequestInit)=>{
  if(path==='/api/workspace')return json(workspace)
  if(path==='/api/agent/policy')return json({limits:{model:'mock',max_steps:4,max_tool_calls:3,run_budget_usd:.05,lifetime_budget_usd:.25,max_searches:1}})
  if(path==='/api/calendar')return json({entries:workspace.campaigns.filter(c=>c.status==='APPROVED').map(c=>({campaign_id:c.id,campaign_name:c.content.campaign_name,post_id:'p1',proposed_date:c.publishing_dates?.p1||null,platform:'Instagram',local_time:'18:30',timezone:'Asia/Riyadh',relative_day:3,caption:(c.content.social_posts as {caption:unknown}[])[0].caption,media:[],status:'APPROVED_PLAN'}))})
  if(path==='/api/campaign-requests'&&options?.method==='POST'){
   const body=JSON.parse(String(options.body));expect(body.confirmed).toBe(true)
   job={job_id:'test-job',entity_id:body.entity_id,status:'queued',progress:[],message:'Investigation queued.'};return json(job)
  }
  if(path==='/api/campaign-requests')return json({jobs:job?[job]:[]})
  if(path==='/api/campaign-requests/test-job'){
   if(outcome==='CREATE')workspace.campaigns=[structuredClone(campaign)]
   job={...job,status:outcome==='FAIL'?'failed':'completed',campaign_id:outcome==='CREATE'?'test-campaign':undefined,outcome,message:outcome==='CREATE'?'Campaign prepared for human review.':outcome==='FAIL'?'Investigation failed safely.':'More evidence is needed before a campaign can be justified.',progress:[]};return json(job)
  }
  if(path==='/api/destinations/test-area')return json({cluster:{name:'Test area',warnings:[]},photos:[],research:{coverage_status:'insufficient_evidence',sources:[],limitations:['Photo mapping unverified.']},evidence:{visual:{possible_environment_counts:{}},sentiment:{distribution:{},classified_comments:0}}})
  if(path==='/api/campaigns/test-campaign/edit'){
   const body=JSON.parse(String(options?.body));expect(body.confirmed).toBe(true);const c=workspace.campaigns[0];c.content.campaign_name=body.title;c.content.central_concept=body.description;c.content.creative_direction=body.creative_direction;(c.content.social_posts as {post_id:string;caption:unknown}[]).forEach(p=>p.caption=body.captions[p.post_id]);c.publishing_dates=body.publishing_dates;c.revision=(c.revision||0)+1;c.status='PENDING_APPROVAL';c.review=null;return json(c)
  }
  if(path==='/api/campaigns/test-campaign/review'){
   const body=JSON.parse(String(options?.body));expect(body.confirmed).toBe(true);workspace.campaigns[0].status=body.decision;workspace.campaigns[0].review={decision:body.decision,reviewer:body.reviewer,notes:body.notes,reviewed_at:'2026-10-30T11:00:00Z'};return json({decision:body.decision})
  }
  throw Error(`Unexpected request ${path}`)
 }))
})
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
const loaded=async()=>{render(<App/>);await screen.findByText('No campaign justified yet')}
const openCampaign=()=>fireEvent.click(screen.getAllByRole('button',{name:/Test heritage pilot/})[0])

describe('ATIA functional tourism studio',()=>{
 it('has three sections, compact real empty states, and read-only startup',async()=>{
  await loaded();expect(within(screen.getByRole('navigation',{name:'Main navigation'})).getAllByRole('button').map(b=>b.textContent)).toEqual(['Studio','Discover','Calendar'])
  expect(screen.getByText('ATIA is idle')).toBeTruthy();expect(screen.queryByText(/Good stories start/)).toBeNull()
  expect(vi.mocked(fetch).mock.calls.every(([,o])=>!o?.method)).toBe(true)
 })
 it('opens destination research and preserves uncertainty and source detail',async()=>{
  await loaded();fireEvent.click(screen.getByRole('button',{name:/Explore destinations/}));fireEvent.click(screen.getByRole('button',{name:/Test destination.*View research/}))
  await screen.findByText('Promotional coverage');expect(screen.getAllByText(/Photo associations remain provisional/i)[0]).toBeTruthy()
  expect(screen.getByText('Sources & findings')).toBeTruthy();expect(screen.getAllByRole('button',{name:/Create Campaign/}).length).toBeGreaterThan(0)
 })
 it('requires a cost confirmation and permits cancellation without a paid job',async()=>{
  await loaded();fireEvent.click(screen.getByRole('button',{name:'Discover'}));fireEvent.click(screen.getByRole('button',{name:/Create Campaign/}))
  expect(screen.getByRole('dialog').textContent).toContain('$0.05')
  expect(vi.mocked(fetch).mock.calls.filter(([,o])=>o?.method==='POST')).toHaveLength(0)
  fireEvent.click(screen.getByRole('button',{name:'Cancel'}));expect(screen.queryByRole('dialog')).toBeNull()
 })
 it('completes Discover → request → Studio → edit → approve → Calendar with mocks',async()=>{
  await loaded();fireEvent.click(screen.getByRole('button',{name:'Discover'}));fireEvent.click(screen.getByRole('button',{name:/Create Campaign/}));fireEvent.click(screen.getByRole('button',{name:'Confirm & start research'}))
  await screen.findByText('Campaign research in progress')
  await screen.findByRole('button',{name:'Edit campaign'},{timeout:4000})
  expect(JSON.parse(String(vi.mocked(fetch).mock.calls.find(([p,o])=>p==='/api/campaign-requests'&&o?.method==='POST')?.[1]?.body)).entity_id).toBe('test-entity')
  fireEvent.click(screen.getByRole('button',{name:'Edit campaign'}));fireEvent.change(screen.getByLabelText('Campaign title English'),{target:{value:'Human-approved heritage plan'}})
  fireEvent.change(screen.getByLabelText('Proposed date · Instagram · post 1'),{target:{value:'2026-11-03'}})
  fireEvent.click(screen.getByRole('button',{name:'Save changes'}));await within(screen.getByRole('dialog')).findByRole('heading',{name:'Human-approved heritage plan'})
  fireEvent.click(screen.getByRole('button',{name:'العربية'}));expect(screen.getAllByText('مفهوم تراثي للاختبار')[0].getAttribute('dir')).toBe('rtl')
  fireEvent.click(screen.getByRole('button',{name:'Approve draft'}));fireEvent.change(screen.getByLabelText('Reviewer name'),{target:{value:'Test reviewer'}});fireEvent.click(screen.getByRole('button',{name:'Confirm approval'}));await screen.findByText('Reviewed by Test reviewer')
  fireEvent.click(screen.getByRole('button',{name:'Close dialog'}));fireEvent.click(screen.getByRole('button',{name:'Calendar'}));await screen.findByText('Approved content');expect(screen.getByText('2026-11-03')).toBeTruthy()
 })
 it('explains insufficient evidence without inserting a campaign',async()=>{
  outcome='INVESTIGATE';await loaded();fireEvent.click(screen.getByRole('button',{name:'Discover opportunities'}));fireEvent.click(screen.getByRole('button',{name:'Confirm & start research'}));await screen.findByText('Additional evidence required',{}, {timeout:4000});expect(workspace.campaigns).toHaveLength(0)
 })
 it('reports failed jobs without automatic paid retry',async()=>{
  outcome='FAIL';await loaded();fireEvent.click(screen.getByRole('button',{name:'Discover opportunities'}));fireEvent.click(screen.getByRole('button',{name:'Confirm & start research'}));await screen.findByText('Investigation stopped',{}, {timeout:4000});expect(vi.mocked(fetch).mock.calls.filter(([,o])=>o?.method==='POST')).toHaveLength(1)
 })
 it('opens an existing campaign rather than requesting another paid job',async()=>{
  workspace.campaigns=[structuredClone(campaign)];render(<App/>);await screen.findByText('Featured campaign');fireEvent.click(screen.getByRole('button',{name:'Discover'}));fireEvent.click(screen.getByRole('button',{name:/Create Campaign/}));expect(screen.getByRole('dialog').textContent).toContain('Test heritage pilot');expect(vi.mocked(fetch).mock.calls.filter(([,o])=>o?.method==='POST')).toHaveLength(0)
 })
 it('does not offer Create Campaign for an unverified area',async()=>{
  workspace.areas[0].entities=[];await loaded();fireEvent.click(screen.getByRole('button',{name:'Discover'}));expect(screen.queryByRole('button',{name:/Create Campaign/})).toBeNull();expect(screen.getByText(/Identity verification needed/)).toBeTruthy()
 })
 it('has searchable regions and no invented hidden-gem filter',async()=>{
  await loaded();fireEvent.click(screen.getByRole('button',{name:'Discover'}));fireEvent.change(screen.getByLabelText('Search destinations'),{target:{value:'No such place'}});expect(screen.getByText('No matching places')).toBeTruthy();expect(screen.queryByRole('button',{name:'Hidden-gem candidates'})).toBeNull()
 })
 it('keeps unapproved content out of Calendar',async()=>{
  workspace.campaigns=[structuredClone(campaign)];render(<App/>);await screen.findByText('Featured campaign');fireEvent.click(screen.getByRole('button',{name:'Calendar'}));expect(screen.getByText('No approved campaigns yet')).toBeTruthy()
 })
 it('requesting revision removes approval until a new version is reviewed',async()=>{
  workspace.campaigns=[{...structuredClone(campaign),status:'APPROVED'}];render(<App/>);await screen.findByText('Featured campaign');openCampaign();fireEvent.click(screen.getByRole('button',{name:'Request revision'}));fireEvent.click(screen.getByRole('button',{name:'Confirm revision request'}));await screen.findAllByText('Revision requested');expect(screen.getByRole('button',{name:'Edit campaign'})).toBeTruthy();expect(screen.queryByRole('button',{name:'Approve draft'})).toBeNull()
 })
 it('withholds approval while image permissions require validation',async()=>{
  workspace.campaigns=[{...structuredClone(campaign),media_validation_required:true}];render(<App/>);await screen.findByText('Featured campaign');openCampaign();expect(screen.queryByRole('button',{name:'Approve draft'})).toBeNull();expect(screen.getByRole('button',{name:'Reject draft'})).toBeTruthy()
 })
 it('has a recoverable backend error without fabricated records',async()=>{
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({detail:'Database unavailable'}),{status:503}));render(<App/>);await screen.findByText('Workspace unavailable');expect(screen.getByRole('button',{name:/Retry stored-data request/})).toBeTruthy()
 })
 it('hides unapproved and arbitrary remote media and handles broken previews',()=>{
  const {rerender}=render(<Media asset={{...asset,approval_status:'QUARANTINED' as MediaAsset['approval_status']}}/>);expect(screen.queryByRole('img')).toBeNull();rerender(<Media asset={{...asset,preview_url:'https://unverified.example/image.jpg'}}/>);expect(screen.queryByRole('img')).toBeNull();rerender(<Media asset={asset}/>);fireEvent.error(screen.getByRole('img'));expect(screen.getByText('Image unavailable')).toBeTruthy()
 })
})
