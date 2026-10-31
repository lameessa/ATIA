# Phase 6 bounded agent

`runner.py` uses the official OpenAI SDK's Responses API. The model dynamically
selects strict function tools from `tools.py` and receives their real outputs in
subsequent requests. There is no scripted tool sequence, model training, external
publishing tool, or frontend.

- `contracts.py`: versioned prompt, tool/final-output contracts, prices and limits.
- `tools.py`: existing destination/evidence/identity services and cached Tavily;
  scoped to one selected geographic cluster. Photo URLs and stored visual results
  are inspected without rerunning CLIP or sending photographs to OpenAI.
- `storage.py`: additive run, request-budget, tool-result, observation and draft
  tables. Original tables and observations are never overwritten.
- `runner.py`: bounded loop, evidence-reference validation, memory, decision cache,
  and draft deduplication. It records evidence/explanations, not private reasoning.

The CLI loads environment variables with the existing `Settings.load()`.
Credentials are excluded from prompts, tool results and persisted configuration.
See the main README for commands and budget/validation details.
