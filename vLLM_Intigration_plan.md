# vLLM / LiteLLM Integration Plan

## Goal

Add support for vLLM through the existing LiteLLM proxy while preserving the current Ollama path as the default and without regressing:

- TTFT benchmarks.
- Prompt/prefix caching behavior.
- Retrieval accuracy.
- Response correctness.
- Ingestion/admin dashboard workflows.
- Existing SAML, session storage, Docker, and frontend chat behavior.

The integration should allow each model role to use either Ollama or an OpenAI-compatible LiteLLM endpoint independently.

## Current Production Model Shape

Current Ollama-style configuration:

```env
RAG_MAIN_HOST="http://10.20.39.12:11438"
RAG_MAIN_MODEL="qwen3.6:35b-a3b-q8_0"
RAG_MAIN_ENGINE="ollama"

RAG_NORMALIZATION_HOST="http://10.20.39.12:11438"
RAG_NORMALIZATION_MODEL="qwen3.6:35b-a3b-q8_0"
RAG_NORMALIZATION_ENGINE="ollama"

RAG_EMBED_HOST="http://10.20.39.12:11438"
RAG_EMBED_MODEL="embeddinggemma:300m"
RAG_EMBED_ENGINE="ollama"

RAG_VLM_HOST="http://10.20.39.12:11438"
RAG_VLM_MODEL="qwen3.6:35b-a3b-q8_0"
RAG_VLM_ENGINE="ollama"
```

The code currently assumes Ollama in several places:

- `backend/llm/client.py` builds `ChatOllama` and `ollama.AsyncClient`.
- `backend/llm/health.py` checks `/api/tags` and `/api/ps`.
- `backend/llm/warmup.py` uses Ollama keep-alive behavior.
- `backend/graph/nodes/retriever.py` embeds through Ollama.
- `backend/admin/worker.py` embeds chunks through `ollama.Client`.
- `backend/ingestion/watcher.py` embeds through Ollama.
- `backend/ingestion/normalizers/llm_markdown.py` normalizes through Ollama.
- `backend/ingestion/vision_parser.py` uses Ollama VLM payloads.
- `backend/startup.py` interactive wizard validates through Ollama.

Frontend status note:

- `frontend/src/components/Sidebar.tsx` does not directly call Ollama.
- The chat UI calls backend `/status`.
- Backend `/status` currently delegates to `backend/llm/health.py`, which is Ollama-specific and uses `/api/tags` plus `/api/ps`.
- For LiteLLM/vLLM support, the backend `/status` contract must stay stable for the frontend, but the backend implementation must become provider-aware.

## LiteLLM / vLLM Environment Observed

LiteLLM service:

```text
LiteLLM proxy: http://10.20.20.90:4000
OpenAI base:   http://10.20.20.90:4000/v1
Dashboard:     Streamlit on port 8080
vLLM backend:  http://10.20.39.12:11434/v1
```

Initial model assumption:

- The first integration phase will use non-thinking vLLM models such as Qwen2.5.
- LiteLLM/vLLM thinking controls will not be sent by default.
- Thinking-model handling for Qwen3/DeepSeek-R1-style vLLM deployments is a future extension.

LiteLLM proxy config shows:

```yaml
general_settings:
  disable_key_check: false
```

So virtual keys are required. Requests must include:

```http
Authorization: Bearer <LiteLLM virtual key>
```

The LiteLLM dashboard gives OpenAI-compatible usage:

```env
OPENAI_BASE_URL="http://10.20.20.90:4000/v1"
OPENAI_API_KEY="<virtual-key>"
```

## Required New Environment Variables

Add API key variables for every model role. Empty string remains valid for Ollama.

```env
RAG_MAIN_API_KEY=""
RAG_NORMALIZATION_API_KEY=""
RAG_EMBED_API_KEY=""
RAG_VLM_API_KEY=""
```

Supported engines should be normalized internally:

```text
ollama
litellm
openai
openai-compatible
vllm
```

Recommended internal behavior:

- `ollama` uses the existing Ollama path.
- `litellm`, `openai`, `openai-compatible`, and `vllm` use the same OpenAI-compatible provider path.
- Direct vLLM can work if its `/v1` API is exposed, but production should use LiteLLM because keys, routing, aliases, and usage tracking live there.

## Recommended Initial Production Configuration

Use LiteLLM for chat and normalization first, but keep embeddings on Ollama unless LiteLLM has a confirmed embedding model route.

```env
RAG_MAIN_HOST="http://10.20.20.90:4000/v1"
RAG_MAIN_MODEL="<litellm-model-alias>"
RAG_MAIN_ENGINE="litellm"
RAG_MAIN_API_KEY="<virtual-key>"

RAG_NORMALIZATION_HOST="http://10.20.20.90:4000/v1"
RAG_NORMALIZATION_MODEL="<litellm-model-alias>"
RAG_NORMALIZATION_ENGINE="litellm"
RAG_NORMALIZATION_API_KEY="<virtual-key>"

RAG_EMBED_HOST="http://10.20.39.12:11438"
RAG_EMBED_MODEL="embeddinggemma:300m"
RAG_EMBED_ENGINE="ollama"
RAG_EMBED_API_KEY=""
```

Reason: retrieval accuracy depends on embedding compatibility with the existing Chroma index. Changing the embedding model or embedding dimension requires re-indexing.

## Implementation Plan

### 1. Generalize Model Config

Extend the current model config object to include:

```python
host: str
model_name: str
api_key: str = ""
engine: str = "ollama"
```

To minimize regression risk, keep current public field names and methods initially. Existing code can keep reading `model.host` and `model.model_name`.

Config loading must read:

```env
RAG_MAIN_API_KEY
RAG_NORMALIZATION_API_KEY
RAG_EMBED_API_KEY
RAG_VLM_API_KEY
```

Backward compatibility criteria:

- Existing `.env` files without API key variables must continue working.
- Empty keys must not affect Ollama.
- Existing Docker compose values must still boot as Ollama.
- Existing tests must pass before switching any endpoint to LiteLLM.

### 2. Add Provider Abstraction

Introduce a backend provider layer instead of spreading engine conditionals across graph/admin/ingestion code.

Suggested shape:

```text
backend/llm/providers.py
backend/llm/openai_compatible.py
backend/llm/ollama_provider.py
```

The public methods should cover current needs:

```python
get_chat_model(role="main")
embed_texts(texts: list[str], role="embedding") -> list[list[float]]
health_probe(role)
```

Existing `OllamaClientWrapper` can remain as a compatibility facade while delegating to the provider layer. This reduces call-site churn.

### 3. Chat Streaming Path

For Ollama:

- Keep `ChatOllama`.
- Keep `reasoning=False` behavior for `RAG_NO_THINKING=true`.
- Keep `num_ctx`, `num_predict`, `temperature`, and `keep_alive`.

For LiteLLM/OpenAI-compatible:

- Call `/chat/completions` under the configured `/v1` base.
- Send `Authorization: Bearer <api-key>`.
- Use streaming mode for the final answer.
- Preserve message ordering and prompt shape.
- Map `RAG_NUM_PREDICT` to `max_tokens`.
- Map `RAG_TEMPERATURE` to `temperature`.
- Do not send Ollama-only fields such as `num_ctx`, `num_predict`, `keep_alive`, or `reasoning`.

Compatibility risk:

- Prompt/prefix caching is highly sensitive to stable prompt prefixes and provider-specific caching behavior.
- The integration must not reorder system/history/document messages.
- Static system prompt blocks should remain byte-stable.
- Dynamic fields should stay after stable prefix blocks where possible.

### 3B. Thinking / No-Thinking Behavior

Current Ollama behavior:

- Startup calls `backend/llm/detection.py::detect_model_capabilities`.
- Detection uses Ollama `show` model metadata to infer architecture and context window.
- Known thinking architectures include Qwen/Qwen3, DeepSeek, GPT-OSS, QwQ, and related families.
- If a thinking model is detected, `config.is_thinking_model=True`.
- If `RAG_NO_THINKING=true`, `config.no_thinking=True` and detection skips auto-thinking checks.
- `backend/llm/client.py` computes:

```python
disable_thinking = cfg.no_thinking or cfg.is_thinking_model
```

- When `disable_thinking=True`, `ChatOllama` is created with:

```python
reasoning=False
```

- `ChatOllama` maps this to Ollama's request-level `think: false`.

Important distinction:

- This does not permanently modify the model on the Ollama server.
- It does not create a global server-side no-thinking session.
- It is applied through the client/request configuration used for each chat call.
- The cached `ChatOllama` object includes this setting, so all calls through that cached client use no-thinking while the current process/config remains active.
- If `RAG_NO_THINKING` or model config changes, the chat-model cache key must include the thinking setting so stale clients are not reused.

LiteLLM/vLLM no-thinking strategy:

- OpenAI-compatible APIs do not have a universal `reasoning=False` standard that works across all vLLM-served models.
- vLLM behavior depends on the model, tokenizer chat template, served parameters, and LiteLLM parameter pass-through.
- The provider layer must support a model-specific no-thinking policy rather than assuming Ollama's `think:false` exists.
- For the first LiteLLM/vLLM rollout, assume the selected vLLM RAG model is non-thinking, for example Qwen2.5.
- Therefore, LiteLLM/vLLM requests should use provider defaults and send no no-thinking parameters.

Add explicit env controls:

```env
RAG_NO_THINKING=true
RAG_MAIN_THINKING_MODE=auto
RAG_NORMALIZATION_THINKING_MODE=auto
RAG_VLM_THINKING_MODE=auto
```

Allowed thinking modes:

```text
auto
disabled
enabled
provider-default
```

Meaning:

- `auto`: detect known thinking model names/families and disable thinking when supported.
- `disabled`: always send no-thinking controls for that role when the provider supports them.
- `enabled`: do not suppress reasoning.
- `provider-default`: send no reasoning/no-thinking parameter or prompt instruction.

Initial LiteLLM/vLLM recommendation:

```env
RAG_MAIN_THINKING_MODE=provider-default
RAG_NORMALIZATION_THINKING_MODE=provider-default
RAG_VLM_THINKING_MODE=provider-default
```

For Qwen2.5/non-thinking vLLM models, `provider-default` is correct because it produces a clean OpenAI-compatible request:

```json
{
  "model": "<litellm-model-alias>",
  "messages": ["..."],
  "stream": true,
  "temperature": 0.2,
  "max_tokens": 1024
}
```

It must not send fields like:

```json
{
  "reasoning": false,
  "chat_template_kwargs": {"enable_thinking": false}
}
```

Reason:

- Qwen2.5 is not a thinking model, so suppression is unnecessary.
- Extra unknown parameters can be rejected or ignored depending on LiteLLM/vLLM.
- Extra prompt instructions can change style, reduce prefix-cache stability, and affect semantic-test comparisons.

For Ollama:

- `auto` and `disabled` map to `reasoning=False` / `think:false`.
- `enabled` means do not pass `reasoning=False`.
- `provider-default` means do not pass `reasoning=False`.

For LiteLLM/vLLM:

- First preference: use a provider-supported request parameter if the served model/runtime supports it.
- Second preference: use model-specific extra body parameters only when verified.
- Last-resort preference: add a short stable system instruction to suppress hidden/visible reasoning only if no request parameter exists.
- These paths are future-only for now and should not be enabled in the first Qwen2.5 rollout.

Potential LiteLLM/vLLM parameter examples to evaluate per served model:

```json
{
  "chat_template_kwargs": {"enable_thinking": false}
}
```

or:

```json
{
  "extra_body": {"chat_template_kwargs": {"enable_thinking": false}}
}
```

These must not be hardcoded blindly. They should be enabled only after a smoke test confirms vLLM/LiteLLM forwards and honors them for the selected model.

No-thinking detection for LiteLLM/vLLM:

- `GET /v1/models` may not expose architecture details.
- Add name-based detection as a best-effort fallback for known thinking models:

```text
qwen3
qwq
deepseek-r1
gpt-oss
```

- Add an explicit override for reliability:

```env
RAG_MAIN_IS_THINKING_MODEL=true
RAG_NORMALIZATION_IS_THINKING_MODEL=true
RAG_VLM_IS_THINKING_MODEL=true
```

Recommended behavior:

- Prefer explicit env override for LiteLLM/vLLM production deployments.
- Use auto-detection only as a convenience.
- Log whether no-thinking was applied, but never log prompts or keys.
- For the first Qwen2.5 LiteLLM/vLLM deployment, log that thinking control is `provider-default` and no no-thinking parameter was sent.

TTFT requirement:

- Thinking suppression must not add an extra LLM call.
- Detection must happen at startup or config load, not on every chat request.
- Request-level no-thinking parameters must be part of the existing chat request.
- Prompt-level no-thinking text, if needed, must be stable and part of the static system prompt so prefix caching is not destroyed.

Validation:

- Compare TTFT with thinking enabled vs disabled for a thinking model.
- Confirm streamed output does not include `<think>...</think>` or reasoning traces.
- Confirm answer correctness does not regress below current semantic baseline.
- Confirm prefix/prompt cache hit behavior is not worsened by dynamic no-thinking prompt text.

### 4. Embedding Path

For Ollama:

- Keep current `ollama.embed` behavior.
- Keep embedding cache and in-flight de-duplication in `backend/graph/nodes/retriever.py`.

For LiteLLM/OpenAI-compatible:

- Call `/embeddings`.
- Normalize OpenAI response shape:

```json
{
  "data": [
    {"embedding": [...]}
  ]
}
```

to the current internal shape:

```python
list[list[float]]
```

Retrieval accuracy guardrails:

- Do not silently switch embedding models for an existing Chroma index.
- Include the embedding model name and engine in vector metadata where new chunks are indexed.
- Add a dimension mismatch check before writing/querying Chroma.
- If embedding model/engine changes, require explicit re-indexing.
- Keep `RAG_EMBED_ENGINE=ollama` for initial rollout unless LiteLLM embedding route is verified.

### 5. Health and Readiness Checks

Current health logic is Ollama-specific:

- `/api/tags`
- `/api/ps`
- loaded-in-VRAM readiness

New behavior:

- `ollama`: keep current tags/ps checks.
- `litellm/openai-compatible`: use `GET /v1/models` with bearer key.
- Do not run generation or embedding calls inside readiness checks.
- Do not block chat TTFT on slow background health refresh if cached status is still acceptable.

Provider-specific readiness meaning:

- Ollama has a meaningful `loaded` signal through `/api/ps`, so `loaded=true` means the model is resident and query-ready.
- LiteLLM/OpenAI-compatible endpoints generally do not expose "loaded in GPU VRAM" through the OpenAI API.
- For LiteLLM, readiness should mean "proxy reachable, key accepted, model listed/routable".
- LiteLLM `loaded` should be `null` or `"not_applicable"`, not falsely reported as `false`.
- If the LiteLLM proxy later exposes `/health/readiness`, use it as an additional proxy-health signal, but do not make it perform generation.

Backend `/status` must remain the single source for chat UI model status:

```json
{
  "status": "ok",
  "chat_available": true,
  "rag_available": true,
  "main_model_healthy": true,
  "embed_model_healthy": true,
  "main_model_name": "...",
  "embed_model_name": "...",
  "main_model": {
    "engine": "litellm",
    "listed": true,
    "loaded": null,
    "query_ready": true
  },
  "embedding_model": {
    "engine": "ollama",
    "listed": true,
    "loaded": true,
    "query_ready": true
  }
}
```

Chat frontend impact:

- `frontend/src/components/Sidebar.tsx` can continue to consume `chat_available`, `rag_available`, `main_model_healthy`, and `embed_model_healthy`.
- Add optional display support for `engine` only if useful.
- Do not make the frontend call Ollama `/api/ps` or LiteLLM `/v1/models` directly.
- API keys must never be available in the frontend.
- Frontend status polling must not trigger model loading or generation.

Admin dashboard impact:

- The admin backend already returns `engine`.
- The admin dashboard already displays model engine badges.
- No major admin frontend change is expected.
- Backend admin health should be updated so LiteLLM models show `online/offline` instead of permanent `unknown`.
- Add `api_key_configured: true/false` to backend runtime config only if useful.
- Never return the actual key to the frontend.

Admin frontend impact:

- `Admin_Dashboard/src/app/page.tsx` already renders `model.engine`.
- `Admin_Dashboard/src/lib/types.ts` already includes `engine`.
- The main required change is backend/admin health support for LiteLLM/OpenAI-compatible models.
- If `api_key_configured` is added, the admin UI may show a non-sensitive "key configured" badge, but this is optional.
- Admin UI must not call LiteLLM directly because that would expose keys and bypass backend policy.

### 6. Warmup and Keepalive

Warmup must remain engine-aware.

For Ollama:

- Keep existing warmup and keepalive behavior.
- Keep it non-competing with real user requests.

For LiteLLM/vLLM:

- Disable active warmup by default.
- Do not issue background chat completions unless explicitly enabled.
- Add optional flag only if needed:

```env
RAG_LITELLM_WARMUP=false
```

Reason:

- LiteLLM/vLLM latency should be measured from the real serving stack.
- Background warmups can compete with real requests and distort TTFT.
- The previous TTFT work should not be invalidated by new readiness probes.

### 7. Ingestion and Normalization

Update ingestion/admin code to use the provider abstraction:

- `backend/admin/worker.py`
- `backend/ingestion/watcher.py`
- `backend/ingestion/normalizers/llm_markdown.py`

Requirements:

- Ollama ingestion path remains unchanged by default.
- LiteLLM normalization can be used when `RAG_NORMALIZATION_ENGINE=litellm`.
- Embedding ingestion must use the same embedding provider as retrieval.
- Existing admin dashboard batch configuration must continue working.
- Existing parser/review/chunk/index pipeline must not change behavior unless the selected model endpoint changes.

### 8. VLM Support

VLM is separate from the main chat path.

Initial plan:

- Add `RAG_VLM_API_KEY` config support.
- Keep Ollama VLM path unchanged by default.
- Add LiteLLM/OpenAI-compatible VLM only if the selected LiteLLM model supports image inputs.

Do not block the first LiteLLM text integration on VLM unless VLM is required for the deployment.

### 9. Docker and `.env.example`

Update:

- `.env.example`
- `docker-compose-prod.yml`
- Any deployment notes/docs.

Ollama default must remain:

```env
RAG_MAIN_ENGINE=ollama
RAG_MAIN_API_KEY=""
```

LiteLLM production example:

```env
RAG_MAIN_HOST=http://10.20.20.90:4000/v1
RAG_MAIN_MODEL=<litellm-model-alias>
RAG_MAIN_ENGINE=litellm
RAG_MAIN_API_KEY=<virtual-key>
```

Do not expose keys to frontend containers. Keys belong only in backend runtime env.

### 10. Security Requirements

- API keys must never be returned by API responses.
- API keys must never be logged.
- Admin dashboard can show only whether a key is configured.
- `.env` must remain untracked.
- `.env.example` should use empty placeholders.
- Docker compose should use either server-local secrets or explicit deployment env substitution if keys should not be committed.

## TTFT Protection Criteria

The integration is acceptable only if:

- Ollama baseline TTFT is not regressed.
- LiteLLM TTFT is measured separately from Ollama TTFT.
- Health probes do not perform chat/embedding generation.
- Warmups do not compete with active chat requests.
- Streaming starts as soon as the upstream provider sends the first token.
- No extra LLM call is added to the hot path for normal chat/RAG turns.
- No duplicate embedding call is introduced for query planning/retrieval.
- Existing embedding cache remains effective.

Required benchmarks after implementation:

```powershell
python test_ttft.py
```

Run separately for:

```text
1. Ollama baseline config before switching runtime.
2. LiteLLM main + normalization, Ollama embeddings.
3. Optional full LiteLLM config if embedding route exists.
4. Switch back to the current Ollama config and rerun TTFT/semantic tests again.
```

The final Ollama re-test is mandatory. The vLLM integration is not acceptable if returning to the current Ollama configuration shows added TTFT latency or degraded response/retrieval accuracy.

## Prompt / Prefix Caching Protection Criteria

Do not change:

- Stable system prompt text unless required.
- Message ordering.
- Static prompt prefix layout.
- Retrieval context insertion order unless intentionally tested.
- Document citation/source formatting unless intentionally tested.

Provider-specific parameters should not be inserted into prompt text.

For LiteLLM/OpenAI-compatible mode:

- Keep the same message list shape as Ollama mode.
- Avoid adding per-request timestamps/random IDs into prompts.
- Keep dynamic retrieval context below the stable system/developer instructions.
- Do not add frontend/admin status metadata into prompts.
- Do not allow readiness probes or dashboard health checks to create additional prompt-cache entries.

## Retrieval Accuracy Criteria

Retrieval must remain at least at current standard:

- Same embedding model and same Chroma index should produce equivalent results.
- Query embedding cache should continue to work.
- Follow-up query behavior must still resolve targeted documents and context shifts.
- No fallback should answer from stale documents when chat mode is selected.
- Switching to LiteLLM for main generation must not alter retrieved chunks.

Embedding switch rule:

- If `RAG_EMBED_MODEL` or `RAG_EMBED_ENGINE` changes, run an explicit re-index.
- Do not reuse old `chroma_db` with a different embedding vector space.

## Semantic / LLM-as-Judge Test Plan

The semantic tests may vary more under LiteLLM because generation style and model behavior can differ even with identical retrieval.

Use LLM-as-judge tests as a quality gate, but evaluate failures in two buckets:

- Retrieval failure: wrong/missing chunks or wrong source documents.
- Generation failure: correct chunks retrieved but answer quality changed.

Required semantic coverage:

- Direct tagged-document RAG question.
- Follow-up question without re-tagging.
- Intentional topic shift to unrelated chat.
- Shift back to previous document.
- Multi-document ambiguity.
- Author/metadata extraction.
- Caveats/gotchas/fine-print question.
- Generic coding/chat question after a RAG turn with no stale sources.
- Ingestion-indexed document query after restart.

Run:

```powershell
python test_semantic_context.py
```

Acceptance:

- Retrieval correctness should not drop below the current Ollama baseline.
- Generation style may differ, but factual correctness must stay acceptable.
- If LiteLLM model gives weaker answers with correct chunks, tune generation prompt/model settings, not retrieval.

## Linter and Test Requirements

Run before committing:

```powershell
ruff check . --no-cache
pytest
python test_semantic_context.py
python test_ttft.py
```

If frontend/admin dashboard files are changed:

```powershell
cd frontend
bun run lint
bun run build

cd ..\Admin_Dashboard
bun run lint
bun run build
```

## Blind Spots Checked

### Admin Dashboard Frontend

The admin dashboard already displays model engine badges from `runtime-config.models[]`.

Observed frontend support:

- `Admin_Dashboard/src/lib/types.ts` includes `engine`.
- `Admin_Dashboard/src/app/page.tsx` renders `model.engine`.

Likely frontend changes are not required for basic engine visibility.

Backend admin runtime config should still be updated for:

- LiteLLM health checks.
- Optional `api_key_configured` boolean.
- Avoiding "Health check for litellm is not implemented" after integration.

### Current Admin Backend Health

`backend/admin/router.py` currently returns unknown for non-Ollama engines:

```text
Health check for <engine> is not implemented.
```

This must be fixed in the backend, not the dashboard UI.

### LiteLLM Embedding Availability

The current LiteLLM proxy config primarily routes chat models. It does not prove that an embedding model is exposed through LiteLLM.

Recommendation:

- Keep `RAG_EMBED_ENGINE=ollama` initially.
- Add LiteLLM embedding support in code, but enable it only after a `/v1/embeddings` smoke test succeeds.

### Startup Wizard

`backend/startup.py` is Ollama-specific. It is not on the production hot path, but should either:

- Remain Ollama-only and document that limitation, or
- Be updated later to validate LiteLLM `/v1/models`.

Do not block production LiteLLM support on the interactive wizard.

## Smoke Test Commands

LiteLLM model list:

```powershell
$env:LITELLM_API_KEY="<virtual-key>"
Invoke-RestMethod `
  -Uri "http://10.20.20.90:4000/v1/models" `
  -Headers @{ Authorization = "Bearer $env:LITELLM_API_KEY" }
```

LiteLLM non-streaming chat:

```powershell
$body = @{
  model = "<litellm-model-alias>"
  messages = @(@{ role = "user"; content = "Say hello in one sentence." })
  stream = $false
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Uri "http://10.20.20.90:4000/v1/chat/completions" `
  -Method Post `
  -Headers @{
    Authorization = "Bearer $env:LITELLM_API_KEY"
    "Content-Type" = "application/json"
  } `
  -Body $body
```

LiteLLM streaming chat:

```powershell
curl.exe "http://10.20.20.90:4000/v1/chat/completions" `
  -H "Authorization: Bearer $env:LITELLM_API_KEY" `
  -H "Content-Type: application/json" `
  -d "{`"model`":`"<litellm-model-alias>`",`"messages`":[{`"role`":`"user`",`"content`":`"Say hello.`"}],`"stream`":true}"
```

Embedding smoke test only if an embedding route exists:

```powershell
$body = @{
  model = "<embedding-model-alias>"
  input = @("test query")
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Uri "http://10.20.20.90:4000/v1/embeddings" `
  -Method Post `
  -Headers @{
    Authorization = "Bearer $env:LITELLM_API_KEY"
    "Content-Type" = "application/json"
  } `
  -Body $body
```

## Rollout Strategy

1. Implement provider abstraction and config keys.
2. Run full Ollama regression tests.
3. Enable LiteLLM only for `RAG_MAIN_*`.
4. Run TTFT and semantic tests.
5. Enable LiteLLM for normalization.
6. Run ingestion/admin pipeline tests.
7. Keep embeddings on Ollama until LiteLLM embedding support is verified.
8. Only then consider LiteLLM embeddings with a clean Chroma re-index.

## Acceptance Criteria

The integration is production-ready only when:

- Existing Ollama config behaves exactly as before.
- LiteLLM chat streams successfully through the backend SSE endpoint.
- Tagged-document RAG still retrieves the correct chunks.
- Follow-up RAG still resolves previous document context.
- Chat mode does not emit stale sources.
- Admin dashboard shows the configured engine.
- Backend/admin health works for LiteLLM without generation probes.
- API keys are not exposed in logs or frontend responses.
- `ruff check . --no-cache` passes.
- Backend tests pass.
- Semantic/context tests pass at or above current standard.
- TTFT remains within the current benchmark target for the selected runtime.
