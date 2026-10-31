import type { Area, Entity, Source } from './types'
export interface MediaAsset {
  media_id:string; provider:string; source:string; photo_id:string; preview_url:string; source_url:string; title:string;
  attribution:string; license_name:string|null; license_url:string|null; rights_status:string; usage_scope:string;
  association_status:string; approval_status:'APPROVED'; review_basis?:string; entity_id:string|null;
}
export type Bilingual={en:string;ar:string}
export interface EvidenceReview {
 recommendation:string;claims:{claim:string;sources:Source[]}[];raw_claims:{claim:string;evidence_refs:string[]}[];uncertainties:string[];
 edited:boolean;original:{recommendation:string;claims:string[];uncertainties:string[]}|null;
}
export interface Campaign {
  id:string;kind:'campaign'|'legacy_proposal';cluster_id:string;created_at:string;status:string;
  content:Record<string,unknown>;media:MediaAsset[];sources:Source[];media_validation_required:boolean;
  validation?:{state:'READY'|'WARNINGS'|'NEEDS_CORRECTION';blocking:string[];warnings:string[]};evidence_review?:EvidenceReview;edited_by?:string|null;opportunity_id?:string;revision?:number;publishing_dates?:Record<string,string>;
  opportunity?:{hypothesis?:string;limitations?:string[]};
  review?:{decision:string;reviewer:string;notes:string;reviewed_at:string;launch_date?:string|null}|null;
}
export interface Destination extends Area {media:MediaAsset|null;context_media:MediaAsset[];hidden_gem_candidate:boolean}
export interface Discovery {
 id:string;kind:string;cluster_id?:string;created_at:string;status:string;decision?:string;summary:string;
 uncertainties:string[];errors:boolean;sources:Source[];
}
export interface OpportunityPhoto {evidence_ref:string;title:string;description:string;photographer:string|null;photo_url:string|null;engagement:{views:number|null;favorites:number|null;comments:number|null};region:string|null}
export interface Opportunity {
 id:string;kind:'named_destination'|'regional_experience'|'tourism_theme';title:{en:string|null;ar:string|null};angle:Bilingual;
 evidence_strength:'strong'|'moderate'|'thin';evidence_label:string;
 evidence:{photo_count:number;distinct_photographers:number;views:{total:number;photos_reporting:number};favorites:{total:number;photos_reporting:number};comments:{total:number;photos_reporting:number}};
 regions:{key:string;en:string;ar:string;photos:number}[];localities:string[];identity_status:string|null;
 media:MediaAsset|null;gallery:MediaAsset[];licensed_images:number;evidence_photos:OpportunityPhoto[];research:{evidence_ref:string;title:string;publisher:string;url:string;excerpt:string}[];
 sensitive_note:string|null;campaign_id:string|null;campaign_status:string|null;
}
export interface Workspace {campaigns:Campaign[];opportunities?:Opportunity[];areas:Destination[];entities:Entity[];activity:Discovery[];archive:MediaAsset[];agent_status:string}
export interface PlannedPost {post_id:string;days_after_human_approved_launch:number;local_time:string;timezone:string;channel:string;activity:Bilingual}
export interface SocialPost {post_id:string;channel:string;caption:Bilingual}
export interface PreparationJob {job_id?:string;entity_id?:string;status:string;campaign_id?:string;run_id?:string;outcome?:string;message?:string;progress:{at:string;message:string}[]}
export interface CalendarEntry {campaign_id:string;campaign_name:Bilingual;post_id:string;proposed_date:string|null;platform:string;local_time:string;timezone:string;relative_day:number;caption?:Bilingual;media:MediaAsset[];status:string}
