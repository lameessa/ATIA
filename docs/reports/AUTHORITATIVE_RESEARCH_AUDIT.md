# Phase 4/5 correction and live Tavily validation

Geographic clusters remain neutral, unchanged groups of geotagged photos. A verified destination is a named broader tourism entity; a verified attraction is a specific landmark. Regions are geographic context. Unresolved locations and provisional associations are not officially named clusters.

Provider: `tavily_live_api_v1`. 0 live HTTP requests; 18 query-cache hits; 0 assessment-cache hits. Execution: 0.013 seconds.

| Original cluster | Authoritatively confirmed entities | Parent destination/region | Association status | Coverage |
|---|---|---|---|---|
| dest-6d4a76530a295c67 | Al Masmak Palace (attraction) | Riyadh | provisional_metadata_match_not_authoritatively_mapped | coverage_found |
| dest-3bf62e49baff55ee | Maraya (attraction) | AlUla | provisional_metadata_match_not_authoritatively_mapped | coverage_found |
| dest-9b1561923af55275 | Historic Jeddah (Al Balad) (destination) | Jeddah | provisional_metadata_match_not_authoritatively_mapped | coverage_found |
| dest-33c40f18483657d7 | Farasan Islands (destination) | not established | provisional_metadata_match_not_authoritatively_mapped | coverage_found |
| dest-bc2ce41bd5235a49 | Boulevard World (attraction), Boulevard City (attraction) | Riyadh, Riyadh | unresolved_multiple_attractions | insufficient_evidence |

## dest-6d4a76530a295c67

Photo title names Masmak; geotag is Ad Dirah. Neither establishes an official cluster boundary.

Original cluster name: Unidentified destination area. Confirmed official cluster name: **none**. Source origin: live_tavily_api. Timestamp: 2026-10-30T17:10:10.214832+00:00.

### Al Masmak Palace — attraction

Status: authoritative_source_name_confirmed. Parent: Riyadh (source_supported). Coverage: coverage_found.
- [Museums Commission Reopens Al Masmak Palace Museum in Riyadh](https://www.spa.gov.sa/en/N2367669) — Saudi Press Agency; live Tavily retrieved content. Name/type confirmation does not authenticate the cluster.
- [Historical al-Masmak Museum - Saudipedia](https://saudipedia.com/en/historical-al-masmak-museum) — Saudipedia; live Tavily retrieved content. Name/type confirmation does not authenticate the cluster.
- [Al Masmak Palace Museum Tells the Story of Saudi Unification](https://www.spa.gov.sa/en/N2368348) — Saudi Press Agency; live Tavily retrieved content. Name/type confirmation does not authenticate the cluster.
- [What Is the Reason for Naming Al-Masmak Palace? - Saudipedia](https://saudipedia.com/en/what-is-the-reason-for-naming-al-masmak-palace) — Saudipedia; live Tavily retrieved content. Name/type confirmation does not authenticate the cluster.
- Coverage evidence: [Museums Commission Reopens Al Masmak Palace Museum in Riyadh](https://www.spa.gov.sa/en/N2367669) — Saudi Press Agency.
- Coverage evidence: [Historical al-Masmak Museum - Saudipedia](https://saudipedia.com/en/historical-al-masmak-museum) — Saudipedia.
- Coverage evidence: [Al Masmak Palace Museum Tells the Story of Saudi Unification](https://www.spa.gov.sa/en/N2368348) — Saudi Press Agency.
- Coverage evidence: [What Is the Reason for Naming Al-Masmak Palace? - Saudipedia](https://saudipedia.com/en/what-is-the-reason-for-naming-al-masmak-palace) — Saudipedia.

- Authoritative entity names/types are separate from a confirmed cluster identity.
- No source independently maps these Flickr photo IDs or the full cluster boundary to an attraction.
- Tavily returns retrieved source excerpts; no generated answer is used and full page completeness is not established.
- Limited source domains and English queries; no absence, underpromotion, demand, or reach inference.

## dest-3bf62e49baff55ee

Mirrored building observed in cached photo near AlUla. Flickr locality Madain Salih is not proof that this is Hegra; Maraya is a separate candidate attraction.

Original cluster name: Unidentified destination area. Confirmed official cluster name: **none**. Source origin: live_tavily_api. Timestamp: 2026-10-30T17:10:10.216859+00:00.

### Maraya — attraction

Status: authoritative_source_name_confirmed. Parent: AlUla (source_supported). Coverage: coverage_found.
- [Maraya | Places to Go | Experience AlUla](https://www.experiencealula.com/en/places-to-go/maraya) — Experience AlUla / Royal Commission for AlUla; live Tavily retrieved content. Name/type confirmation does not authenticate the cluster.
- Coverage evidence: [Maraya | Places to Go | Experience AlUla](https://www.experiencealula.com/en/places-to-go/maraya) — Experience AlUla / Royal Commission for AlUla.
- Coverage evidence: [Maraya Tour | Experiences | Experience AlUla](https://www.experiencealula.com/en/things-to-do/experiences/maraya-tour) — Experience AlUla / Royal Commission for AlUla.

- Authoritative entity names/types are separate from a confirmed cluster identity.
- No source independently maps these Flickr photo IDs or the full cluster boundary to an attraction.
- Tavily returns retrieved source excerpts; no generated answer is used and full page completeness is not established.
- Limited source domains and English queries; no absence, underpromotion, demand, or reach inference.

## dest-9b1561923af55275

Flickr locality Al Balad and Jeddah Downtown title support a hypothesis, not UNESCO boundary membership.

Original cluster name: Unidentified destination area. Confirmed official cluster name: **none**. Source origin: live_tavily_api. Timestamp: 2026-10-30T17:10:10.218814+00:00.

### Historic Jeddah (Al Balad) — destination

Status: authoritative_source_name_confirmed. Parent: Jeddah (source_supported). Coverage: coverage_found.
- [PIF Announces 'Al Balad Development Company' to Develop Jeddah's Historic District and Transform it into Global Cultural and Heritage Destination](https://www.spa.gov.sa/w1973726) — Saudi Press Agency; live Tavily retrieved content. Name/type confirmation does not authenticate the cluster.
- [Jeddah Historic District Program and Al Balad ...](https://spa.gov.sa/en/N2054918) — Saudi Press Agency; live Tavily retrieved content. Name/type confirmation does not authenticate the cluster.
- Coverage evidence: [PIF Announces 'Al Balad Development Company' to Develop Jeddah's Historic District and Transform it into Global Cultural and Heritage Destination](https://www.spa.gov.sa/w1973726) — Saudi Press Agency.
- Coverage evidence: [Jeddah Historic District Program and Al Balad ...](https://spa.gov.sa/en/N2054918) — Saudi Press Agency.
- Coverage evidence: [Historic Jeddah - Saudipedia](https://saudipedia.com/en/historic-jeddah) — Saudipedia.
- Coverage evidence: [Historic Jeddah (Al Balad) - Visit Saudi Official Website](https://www.visitsaudi.com/en/jeddah/attractions/summer-night-adventures-in-al-balad) — Visit Saudi / Saudi Tourism Authority.

- Authoritative entity names/types are separate from a confirmed cluster identity.
- No source independently maps these Flickr photo IDs or the full cluster boundary to an attraction.
- Tavily returns retrieved source excerpts; no generated answer is used and full page completeness is not established.
- Limited source domains and English queries; no absence, underpromotion, demand, or reach inference.

## dest-33c40f18483657d7

Farasan locality and fishing-trip title support a broader archipelago hypothesis, not the exact photographed fishing site.

Original cluster name: Unidentified destination area. Confirmed official cluster name: **none**. Source origin: live_tavily_api. Timestamp: 2026-10-30T17:10:10.220396+00:00.

### Farasan Islands — destination

Status: authoritative_source_name_confirmed. Parent: not established (not_established). Coverage: coverage_found.
- [Farasan Islands Fishing - Visit Saudi Official Website](https://www.visitsaudi.com/en/stories/farasan-islands-fishing) — Visit Saudi / Saudi Tourism Authority; live Tavily retrieved content. Name/type confirmation does not authenticate the cluster.
- [Farasan Islands Protected Area - UNESCO World Heritage Centre](https://whc.unesco.org/en/tentativelists/6370) — UNESCO World Heritage Centre; live Tavily retrieved content. Name/type confirmation does not authenticate the cluster.
- [Farasan Islands Reserved Area - Visit Saudi Official Website](https://www.visitsaudi.com/en/jazan/attraction/farasan-islands-protected-area) — Visit Saudi / Saudi Tourism Authority; live Tavily retrieved content. Name/type confirmation does not authenticate the cluster.
- Coverage evidence: [Farasan Islands Fishing - Visit Saudi Official Website](https://www.visitsaudi.com/en/stories/farasan-islands-fishing) — Visit Saudi / Saudi Tourism Authority.
- Coverage evidence: [Farasan Islands Reserved Area - Visit Saudi Official Website](https://www.visitsaudi.com/en/jazan/attraction/farasan-islands-protected-area) — Visit Saudi / Saudi Tourism Authority.
- Coverage evidence: [Farasan Islands: A Paradise for Nature and History ...](https://www.spa.gov.sa/en/N2145980) — Saudi Press Agency.

- Authoritative entity names/types are separate from a confirmed cluster identity.
- No source independently maps these Flickr photo IDs or the full cluster boundary to an attraction.
- Tavily returns retrieved source excerpts; no generated answer is used and full page completeness is not established.
- Limited source domains and English queries; no absence, underpromotion, demand, or reach inference.

## dest-bc2ce41bd5235a49

Titles mix Boulevard World and Boulevard Riyadh City; nearby attractions must not be merged into one officially named destination.

Original cluster name: Unidentified destination area. Confirmed official cluster name: **none**. Source origin: live_tavily_api. Timestamp: 2026-10-30T17:10:10.223728+00:00.

### Boulevard World — attraction

Status: authoritative_source_name_confirmed. Parent: Riyadh (source_supported). Coverage: coverage_found.
- [Riyadh Season Releases Tickets for Boulevard World Ahead of Opening](https://www.spa.gov.sa/en/N2709234) — Saudi Press Agency; live Tavily retrieved content. Name/type confirmation does not authenticate the cluster.
- [Boulevard World (BLVD World) - Saudipedia](https://saudipedia.com/en/boulevard-world-blvd-world) — Saudipedia; live Tavily retrieved content. Name/type confirmation does not authenticate the cluster.
- [Saudi Zone Welcomes Visitors to Boulevard World](https://www.spa.gov.sa/en/N2193086) — Saudi Press Agency; live Tavily retrieved content. Name/type confirmation does not authenticate the cluster.
- Coverage evidence: [Riyadh Season Releases Tickets for Boulevard World Ahead of Opening](https://www.spa.gov.sa/en/N2709234) — Saudi Press Agency.
- Coverage evidence: [Boulevard World (BLVD World) - Saudipedia](https://saudipedia.com/en/boulevard-world-blvd-world) — Saudipedia.
- Coverage evidence: [Saudi Zone Welcomes Visitors to Boulevard World](https://www.spa.gov.sa/en/N2193086) — Saudi Press Agency.

### Boulevard City — attraction

Status: authoritative_source_name_confirmed. Parent: Riyadh (source_supported). Coverage: coverage_found.
- [Boulevard City (BLVD CITY) - Saudipedia](https://saudipedia.com/en/boulevard-city-blvd-city) — Saudipedia; live Tavily retrieved content. Name/type confirmation does not authenticate the cluster.
- [Boulevard Riyadh City, A Thriving Entertainment Destination](https://www.spa.gov.sa/en/N2136128) — Saudi Press Agency; live Tavily retrieved content. Name/type confirmation does not authenticate the cluster.
- [You Guide to Boulevard City in Riyadh | Shopping & Entertainment](https://www.visitsaudi.com/en/riyadh/attractions/blvd-riyadh-city) — Visit Saudi / Saudi Tourism Authority; live Tavily retrieved content. Name/type confirmation does not authenticate the cluster.
- Coverage evidence: [Boulevard City (BLVD CITY) - Saudipedia](https://saudipedia.com/en/boulevard-city-blvd-city) — Saudipedia.
- Coverage evidence: [Boulevard Riyadh City, A Thriving Entertainment Destination](https://www.spa.gov.sa/en/N2136128) — Saudi Press Agency.
- Coverage evidence: [You Guide to Boulevard City in Riyadh | Shopping & Entertainment](https://www.visitsaudi.com/en/riyadh/attractions/blvd-riyadh-city) — Visit Saudi / Saudi Tourism Authority.

- Authoritative entity names/types are separate from a confirmed cluster identity.
- No source independently maps these Flickr photo IDs or the full cluster boundary to an attraction.
- Tavily returns retrieved source excerpts; no generated answer is used and full page completeness is not established.
- Limited source domains and English queries; no absence, underpromotion, demand, or reach inference.

## Audit conclusions

Already correct: bounded complete-link geographic clustering; neutral IDs; unassigned missing/coarse geotags; immutable snapshots; scoped coverage statuses; recorded-versus-live provenance; no underpromotion claim.

Fixed: the old research field verified_name could conflate existence of an attraction with identification of a cluster. New authoritative entities, verification records, parent links, and provisional/unresolved cluster associations separate those concepts. Old records are preserved and annotated in an additive audit table. No Flickr title, OpenCLIP category, or approximate coordinate alone verifies an identity.

Verification uses authoritative URL boundaries, an entity alias in the returned source title, meaningful source content, and source-supported type markers. This is an auditable rule, not independent field verification. Generic navigation mentions are not accepted as identity proof. Parent links require a separately confirmed parent and child-source location context.

Python calls the real Tavily HTTPS API with bearer authentication loaded from .env; no connected Codex tool is needed at runtime. Credentials are never placed in logs or stored responses. Only successful responses are cached. Credentials/quota errors, rate limiting, timeouts, and malformed results are handled explicitly. Old Codex-observation findings are not reused as live proof.

No models trained, no Phase 6, no frontend, no push.

## Final validation

**101 tests passed.** The standalone terminal workflow performed **16 real Tavily HTTP requests** in **39.427 seconds**, with two shared-parent query-cache hits. A separate connectivity probe also made one real request. Seventeen successful API request IDs are retained in the query cache. Later verification-rule review reused the existing Tavily responses without further requests; a full assessment replay returned five cache hits in **0.004 seconds**, with no network calls. These timings are actual Python execution, not recorded Codex-web replay timings.

All **22 pre-existing tables** retain exact before-run row checksums: all 297 photos, existing analyses, sentiment/comments, 90 geographic clusters and their mappings/snapshots, and all five historical research observations are unchanged. No API key appears in stored database content. SQLite integrity and foreign keys passed. Historical records received separate audit annotations, not replacements.

Current cluster catalogue: {'not_researched': 85, 'unresolved_multiple_attractions': 1, 'provisional_metadata_match_not_authoritatively_mapped': 4}. Four areas have provisional named-entity associations; one remains ambiguous; 85 have not been researched. None has an officially confirmed cluster name. Maraya and AlUla are separate typed entities, with a source-supported parent link. Boulevard World and Boulevard City are separate attractions, never one destination just because their photo cluster is nearby. Farasan's broader entity name has authoritative support, but its region-parent link remains unconfirmed in the current assessment. Visitor-information coverage was found for named entities; this does not certify exact cluster identity or marketing gaps.

Full terminal results: `data/research/tavily-live-results.json` and `tavily-final-results.json`. Catalogue: `data/research/entity-catalogue.json`. Preservation/security checks: `data/research/authority-audit-verification.json`. No Codex-connected search result was imported into these live verifications. Phase 6 was not started.
