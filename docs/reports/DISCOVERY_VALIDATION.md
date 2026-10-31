# Autonomous discovery validation — 30 October 2026

## Actual live cycle

Exactly one live cycle was authorized and executed from the Python CLI, without
a destination, campaign prompt, Codex web-search dependency, or uploaded images.
Run: `agent-3a8604c2735843688fd4d36666b9467d`.

- Eligible areas: 37. The LLM requested the first catalogue page and received eight
  areas: provisional Al Masmak, Farasan Islands, Maraya, Historic Jeddah, mixed
  Boulevard World/City, Yanbu locality, an unnamed area at 28.846478/34.837045,
  and Al Khar‘ā’ locality. Catalogue ordering reflects evidence completeness.
  These are candidate associations, not eight authenticated photo locations.
- Independently selected: `dest-6d4a76530a295c67`, associated provisionally with
  verified attraction **Al Masmak Palace**, broader Riyadh destination.
- Tools actually invoked: `list_candidates`, `inspect_candidate`, `get_memory`.
  No hardcoded destination or scripted tool sequence was supplied to the model.
- Source evidence was existing stored Tavily content, not a new search or fresh
  verification. No additional Tavily network requests or cache lookups occurred.
- Model decision: INVESTIGATE. Final guarded decision: INVESTIGATE.
- The generated supporting excerpt failed exact-source validation. The raw
  invalid decision was not accepted or persisted as factual evidence. The run
  records the validation error and requires further investigation.
- Campaigns generated: **0**. No hidden-gem opportunity was established.
- Model: `gpt-4o-mini`; 4 requests, 3 tool calls, 14,509 input / 516 output tokens.
- Execution time: **14.684 seconds**. Estimated OpenAI cost **$0.00248595**;
  no new Tavily usage. At $0.15/$0.60 per million input/output tokens, respectively;
  estimate is not an account billing statement. [Official model pricing](https://platform.openai.com/docs/models/gpt-4o-mini).
- No paid second attempt, repair, batch evaluation or unattended job was run.

## Evidence and ambiguity

The stored [Saudi Press Agency reopening report](https://www.spa.gov.sa/en/N2367669)
describes Masmak as “one of the most iconic heritage sites”. This contradicts an
unsupported lesser-known claim. [Saudipedia](https://saudipedia.com/en/historical-al-masmak-museum)
supports the museum's identity and historical role; a second
[SPA report](https://www.spa.gov.sa/en/N2368348) describes its museum history.
The returned [Visit Saudi Riyadh page](https://www.visitsaudi.com/en/riyadh)
was broad city content and its limited excerpt is not destination-specific proof.
Existing promotion and iconic status do not establish measured popularity, but
there is no affirmative hidden-gem evidence here. The approved historical photo
has no explicit reviewed photo-to-attraction mapping. Identity existence cannot
resolve that ambiguity. Generating a campaign from this evidence was unjustified.

## Tests and preservation

` .venv/bin/python -m pytest -q `: **163 passed** (2.10 seconds).
Nineteen new discovery tests use temporary synthetic fixtures and mocked model/search
responses. They validate dynamic selection, complete bilingual pending campaigns,
UPDATE with new evidence, cache reuse, duplicate prevention, absent mappings,
source quotation/publisher gates, contradictory evidence, invalid content/schedules,
shared spending limits, quarantined-photo exclusion, empty candidates, Tavily
provenance, and hiding a saved campaign after its image snapshot changes.
Mocked successful campaigns demonstrate code paths only; no synthetic campaigns
or sources were inserted into the real database.

SQLite `integrity_check`: **ok**; `foreign_key_check`: **no violations**.
Compared every original row against the pre-change SQLite backup: **39 pre-existing
tables preserved, zero original rows missing or changed**. Original photographs,
OpenCLIP/sentiment results, geographic mappings and research observations remain.
197 historical and 63 retained live photographs are stored; presentation filtering
returns **197 historical / 0 live**. Removed original live items remain tombstoned.
[photo] remains REJECTED; [photo] remains PENDING_REVIEW.
No approvals changed; no frontend changes, publication, push or recurring job.

Local details: `data/research/discovery-live.json`,
`data/research/discovery-preservation.json`, `data/research/discovery-baseline.json`,
and `data/atia-before-discovery.sqlite3` (private local artifacts).

## Remaining limitations

The live cycle did not produce a fully source-valid model decision or a campaign;
only the guarded fallback was accepted. Exact quotation compliance needs further
mocked prompt/evidence-format evaluation before another separately authorized live
validation. No thresholds or evidence checks were relaxed to manufacture success.

The default three-tool budget lets the model inspect only a small subset and it
spent one call rereading memory already available in its dossier. A later run can
paginate or choose a new area, but no exhaustive autonomous search is claimed.
Current photo-to-entity mappings are provisional; review is needed before using
specific attraction images. There is no fabricated mapping backfill.

Publisher diversity, literal quotation and conservative phrase checks cannot prove
semantic entailment, destination popularity, copyright permissions, Arabic copy
quality or campaign effectiveness. Bilingual completeness is validated structurally;
all audience/creative/KPI suggestions remain hypotheses requiring human review.
Campaigns are pending drafts and are not yet exposed in the unchanged frontend.
The scheduler option is a guarded terminal entry point, not an installed service.
