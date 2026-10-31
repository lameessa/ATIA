# Phase 6: autonomous agent validation

Actual standalone validation: one Maraya-associated geographic cluster (`dest-3bf62e49baff55ee`).
Model: `gpt-4o-mini` through the official OpenAI SDK / Responses API, function calling and strict JSON output.
Run: `agent-5d6a345d7b4945e0bedf67bb56f7a50f`. All automated OpenAI responses were mocked; no batch evaluation was run.

## Actual execution and cost

- **4 paid LLM requests**, **3 model-selected tool calls**.
- **16.042 seconds** summed execution time, including tool/API execution across the initial run and its bounded continuation; excludes the development pause.
- 15,894 input tokens, 361 output tokens.
- Conservative estimated OpenAI cost: **$0.0026007** (about 0.26 US cents).
- Pricing: $0.15/million input and $0.60/million output tokens, cached-input discounts ignored.
- These are token-based estimates, not an account balance or invoice. Tavily usage is separate.
- One additional live Tavily query was selected; one new provenance-bearing observation was appended.
- Repeated terminal execution returned the persisted decision in 0.016 seconds, with **0 new LLM requests, 0 tool calls, $0 additional OpenAI cost**.

[Official model/pricing source](https://developers.openai.com/api/docs/models/gpt-4o-mini).
The model is marked deprecated in current documentation but worked on this account during validation.
It remains configurable; no expensive automatic fallback was attempted.

## Observable autonomous sequence

1. The model chose `get_candidates` and received the original geographic cluster and provisional identity evidence.
2. It chose `inspect_evidence(view="dossier")`, receiving stored photograph/visual evidence, engagement and sentiment separately, and authoritative research.
3. It chose `research_live(query="AlUla tourism opportunities Maraya")` and received actual Tavily sources, timestamp/request provenance and content excerpts.
4. After receiving these outputs, it selected **INVESTIGATE** rather than proposing marketing.

This was not a predetermined sequence. Mocked regression tests also branch on actual tool results.
The cluster has one photograph, an uncertain relevance classification, and no classified sentiment distribution.
The existing primary source confirms [Maraya as an attraction in AlUla](https://www.experiencealula.com/en/places-to-go/maraya),
but does not authenticate that Flickr photo or the full cluster boundary as Maraya.
**No proposal was generated.** No marketing gap or tourism demand was established.

## Errors found and corrections

The first three requests accumulated repeated source content and hit the 32 KB input guard before the final request.
The guard stopped spending. Tool histories now omit repeated referenced payloads without LLM summarization,
and candidate lookup returns a compact identity summary. The same run was resumed for its **fourth and final**
allowed request, using persisted outputs without repeating the three tools or increasing its original budget.

The model correctly chose INVESTIGATE, but included an unsupported claim that AlUla was a "popular tourist destination"
with an existing research reference ID. This demonstrates that reference validity does not guarantee entailment.
Offline source review retained the model's decision, removed that unsupported assertion, and replaced the explanation
and next actions with evidence-scoped wording. **No further paid OpenAI call was made.** The complete original model
decision is retained in `unvalidated_model_decision` and the original live JSON. The accepted record explicitly labels
this offline correction in `decision_origin` and `quality_warnings`; it is not presented as pristine model output.
A targeted regression guard now rejects this observed unsupported popularity/demand/gap assertion. General semantic
entailment and resistance to prompt injection remain limitations; humans must review proposals and claims.

## Preservation, memory and tests

**124 automated tests passed**, including the original 101. Tests cover dynamic tool-result feedback, persistent memory,
cache replay, scoped mocked Tavily access, safe errors, 429 retry bounds, request/tool/spending limits, reference checks,
unsupported popularity, bilingual PENDING_APPROVAL drafts, proposal deduplication and missing prior proposal rejection.
Mocked CREATE exercises draft persistence; the real validation did not manufacture a proposal just to exercise this path.

All **28 pre-existing tables' original rows** were preserved. All 297 photos, previous AI analyses,
comments, sentiment, 90 geographic cluster identities/mappings and historical research are intact. Only the existing
Tavily observation table gained one row; its previous rows are unchanged. New agent memory uses five additive tables.
SQLite `integrity_check`: **ok**. `foreign_key_check`: **0 violations**. No configured Flickr, Tavily or OpenAI credential
appears in stored database content. Backup and per-table baseline are retained locally under ignored `data/`.

The actual run and tools are inspectable with:

```bash
.venv/bin/atia agent inspect --run-id agent-5d6a345d7b4945e0bedf67bb56f7a50f
.venv/bin/atia agent run --cluster-id dest-3bf62e49baff55ee
.venv/bin/atia agent proposals --cluster-id dest-3bf62e49baff55ee
.venv/bin/python -m pytest -q
```

Local validation artifacts: `data/research/phase6-live.json` (initial bounded stop),
`phase6-live-final.json` (raw live decision), `phase6-audited.json` (accepted audited decision),
`phase6-replay.json`, `phase6-memory.json`, `phase6-proposals.json`, `phase6-preservation.json`.

No model training, frontend, automatic publishing, GitHub push, or multi-destination paid evaluation.
