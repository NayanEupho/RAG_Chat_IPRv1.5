# Session Memory Plan for Cache-Stable RAG

Date: 2026-07-21

## Objective

Add a cache-stable, compact session-memory layer for RAG prompts without regressing current TTFT, retrieval accuracy, response correctness, chat behavior, ingestion, admin dashboard, SAML, or existing vLLM/Ollama compatibility.

The feature must be fully gated by an environment variable and must pass through the current production path when disabled.

```env
RAG_SESSION_MEMORY_ENABLED=false
```

When this value is `false`, the code path must remain the current legacy RAG generation path. TTFT should remain the same as the current baseline, with at most normal runtime variance. The acceptance tolerance is no more than 10-20% difference versus the latest metrics in `vllm_vs_ollama_inference_comparasion.md`.

## Current Baseline

Current validated baseline from `vllm_vs_ollama_inference_comparasion.md`:

| Runtime | Avg TTFT | Worst TTFT | Semantic/Context |
|---|---:|---:|---:|
| vLLM/LiteLLM qwen2.5-7b | 2226 ms | 2696 ms | 94/96 |
| Ollama qwen3.6:35b-a3b-q8_0 | 3029 ms | 5100 ms | 96/96 |

The current RAG generator path is fast because it sends a compact prompt:

```text
system prompt
single synthetic RAG user prompt with current docs + latest question
```

The downside is weak prefix-cache reuse because most RAG prompt content changes every turn.

The previous prefix-cache experiment regressed TTFT because it included too much full conversation history in RAG prompts. This plan explicitly avoids that.

## Design Principle

Do not use an LLM call to construct session memory on the hot path.

Session memory must be built deterministically in Python from existing graph/session state. The generation model should only receive the small final memory block, not the full conversation history.

The target prompt shape when enabled is:

```text
system: stable generator instructions
system: [SESSION MEMORY] compact deterministic continuity hint
system: [SESSION CONTROL] compact deterministic current-mode/current-intent block
user/system: [RETRIEVAL CONTEXT] current retrieved chunks only
user: latest user question
```

The target prompt shape when disabled remains exactly the current legacy path.

## Offline / Non-Operational Response Requirement

If the system is not operational, the chat response must not attempt normal generation or RAG.

Non-operational cases include:

- backend is unreachable from the frontend;
- backend is running but `/api/status` reports chat unavailable;
- main model is unavailable, not query-ready, or unreachable;
- embedding model is unavailable, not query-ready, or unreachable for RAG requests;
- model health check detects that required Ollama models are listed but not loaded in `/api/ps`;
- OpenAI-compatible/LiteLLM/vLLM model check fails `/v1/models`, `/health`, or a lightweight readiness probe.

Required user-facing message:

```text
Askme IPR is down, please contact computer division for help and reporting
```

Implementation notes:

- Frontend should show this message when a send attempt fails because the backend is down or status is non-operational.
- Backend streaming endpoint should also emit this message if readiness fails after request admission.
- This must not add TTFT overhead on healthy requests. Use cached health status and background refresh where possible.
- This behavior must not mask normal retrieval failures. If the system is operational but no relevant chunks are found, keep the existing indexed-files response.
## Feature Flag Behavior

### Environment Variable

```env
RAG_SESSION_MEMORY_ENABLED=false
```

Rules:

- `false`: use current legacy RAG prompt assembly exactly.
- `true`: use compact session-memory RAG prompt assembly.
- Missing/invalid values should behave as `false`.
- Chat mode should remain unchanged in both cases.
- Retrieval should remain unchanged in both cases.
- Ingestion/admin/SAML should not import or depend on this feature.

## Ownership of Prompt Blocks

### Planner Responsibilities

Planner continues to set routing/context state:

- `intent`
- `mode`
- `query`
- `targeted_docs`
- `semantic_queries`
- `context_action`
- `last_targeted_docs`

No major planner changes should be required.

### Retriever Responsibilities

Retriever continues to produce current-turn evidence:

- `documents`
- `retrieval_metrics`

The `[RETRIEVAL CONTEXT]` block must use chunks retrieved for the current latest query or resolved follow-up query. It must not blindly carry stale chunks from older RAG turns.

### Generator Responsibilities

`backend/graph/nodes/generate.py` should construct:

- `[SESSION MEMORY]`
- `[SESSION CONTROL]`
- `[RETRIEVAL CONTEXT]`
- final model message list

This is the only intended hot-path code area for the feature.

## Session Memory Construction

Session memory should be deterministic, small, and bounded.

Inputs:

- `state["summary"]`
- `state["messages"]`
- `state["targeted_docs"]`
- `state["last_targeted_docs"]`
- `state["context_action"]`

Hard limits:

- `SESSION_MEMORY_MAX_CHARS`: 600-900 chars initially.
- Include at most last 1-2 user questions.
- Do not include full previous assistant answers.
- If assistant context is needed, include at most a tiny first-sentence snippet, capped around 120-160 chars, or omit assistant snippets entirely for the first implementation.

Example:

```text
[SESSION MEMORY]
Recent targets: Qlora_Paper.pdf.
Recent user questions: "What is Qlora_Paper.pdf paper about?"; "who are the authors".
```

This should add roughly 100-200 tokens, not thousands.

## Session Control Construction

Session control should also be deterministic and small.

Inputs:

- `state["mode"]`
- `state["intent"]`
- `state["targeted_docs"]`
- `state["context_action"]`

Example:

```text
[SESSION CONTROL]
mode=auto
intent=specific_doc_rag
context_action=retrieve
targeted_docs=Qlora_Paper.pdf
```

This should add roughly 20-60 tokens.

## Retrieval Context Construction

Retrieval context uses current retrieved chunks only:

```text
[RETRIEVAL CONTEXT]
<docs>
[1] chunk...
[2] chunk...
</docs>
```

Rules:

- Use current `state["documents"]` after retrieval.
- Keep chunk order deterministic.
- Use stable labels: `[1]`, `[2]`, `[3]`.
- Do not include dynamic verbose planner explanations unless needed for correctness.
- Omit this block entirely for `intent == "chat"`.
- Continue using current doc-budget and table-compaction functions.

## Prompt Size Guardrail

Before enabling compact session memory for a RAG turn, estimate prompt size against the legacy prompt.

Acceptance rule:

```text
compact_prompt_tokens <= legacy_prompt_tokens * 1.15
```

Initial hard ceiling:

```text
compact_prompt_tokens <= legacy_prompt_tokens + 300 tokens
```

If either guardrail fails, fallback to the legacy prompt for that turn.

This prevents the previous failure mode where prefix-cache improvement was attempted by adding too much prompt history.

## Implementation Phases

### Phase 1: Configuration Only

- Add `RAG_SESSION_MEMORY_ENABLED=false` to `.env.example` and local `.env`.
- Add `session_memory_enabled: bool = False` to `AppConfig`.
- Parse the env var with safe false-by-default behavior.
- Add tests confirming disabled config preserves legacy behavior.

### Phase 2: Prompt Builder Helpers

Add helper functions in `backend/graph/nodes/generate.py`:

- `_session_memory_enabled()`
- `_build_session_memory_block(state, max_chars=800)`
- `_build_session_control_block(state)`
- `_build_retrieval_context_block(selected_docs)`
- `_build_legacy_rag_messages(...)`
- `_build_compact_memory_rag_messages(...)`
- `_estimated_message_tokens(messages)`

Keep chat path unchanged.

### Phase 3: Disabled-Path Safety Tests

Required tests:

- With `RAG_SESSION_MEMORY_ENABLED=false`, RAG final messages match current legacy shape.
- With feature disabled, no `[SESSION MEMORY]` block appears.
- With feature disabled, no `[SESSION CONTROL]` block appears.
- With feature disabled, chat mode behavior is unchanged.

### Phase 4: Enabled-Path Prompt Tests

Required tests:

- Enabled RAG prompt includes `[SESSION MEMORY]` and `[SESSION CONTROL]`.
- Enabled RAG prompt includes current retrieved chunks only.
- Enabled prompt does not include long previous assistant answers.
- Enabled prompt keeps latest user question as the final message.
- Enabled `rag -> chat` does not leak retrieval chunks or stale sources.
- Enabled `chat -> rag` builds compact memory from recent user turns without full history.
- Prompt-size guardrail falls back to legacy when compact prompt is too large.

### Phase 5: Correctness and Latency Validation

Run with disabled mode first:

```powershell
$env:RAG_SESSION_MEMORY_ENABLED="false"
.\.venv\Scripts\python.exe test_ttft.py --base-url http://127.0.0.1:8000 *> ttft_session_memory_disabled.log
.\.venv\Scripts\python.exe test_semantic_context.py --base-url http://127.0.0.1:8000 *> semantic_session_memory_disabled.log
```

Disabled-mode acceptance:

- TTFT must match current baseline within 10-20% normal runtime variance.
- Semantic/context must not regress.
- Grounding warnings must remain `none`.

Run with enabled mode:

```powershell
$env:RAG_SESSION_MEMORY_ENABLED="true"
.\.venv\Scripts\python.exe test_ttft.py --base-url http://127.0.0.1:8000 *> ttft_session_memory_enabled.log
.\.venv\Scripts\python.exe test_semantic_context.py --base-url http://127.0.0.1:8000 *> semantic_session_memory_enabled.log
```

Enabled-mode acceptance:

- Ollama avg TTFT regression should be <= 10-20% versus latest clean baseline.
- vLLM avg TTFT regression should be <= 10-20% versus latest vLLM baseline.
- Worst-case TTFT must stay within the current target envelope.
- Retrieval accuracy must not regress.
- Response correctness must not regress materially.
- No stale-source leakage in chat mode.

## Rollout Strategy

1. Keep default `RAG_SESSION_MEMORY_ENABLED=false`.
2. Merge only after disabled-path tests prove zero functional behavior change.
3. Test enabled mode locally against both Ollama and vLLM.
4. If enabled mode meets acceptance gates, consider enabling in staging only.
5. Do not enable in production until TTFT and semantic/context tests pass on production-like GPU load.

## Non-Goals

This plan does not change:

- retriever ranking
- vector DB schema
- ingestion pipeline
- admin dashboard behavior
- SAML auth/session handling
- frontend chat UI
- model provider selection

## Production Safety Criteria

The feature is production-safe only if all are true:

- Disabled flag gives current legacy behavior.
- No TTFT degradation over 10-20% in disabled mode.
- Enabled mode has acceptable TTFT and no semantic regression.
- Chat mode remains unchanged.
- RAG retrieval/source accuracy remains unchanged.
- Prefix-cache improvement does not depend on increasing prompt size significantly.
- Rollback is one env var change: `RAG_SESSION_MEMORY_ENABLED=false`.

