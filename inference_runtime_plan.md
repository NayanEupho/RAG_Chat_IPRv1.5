# Inference Runtime Plan

Date: July 16, 2026

## Scope

This plan covers the non-prompt-caching inference concerns:

- context-window configuration clarity
- shared-model reload risk
- warm-up behavior
- manual warm-up operations
- runtime validation under load

Prompt/prefix caching details are intentionally excluded from this file and are covered in [prompt_prefix_caching_plan.md](C:/Users/Nayan/Desktop/RAG_Chat_IPRv1.5/prompt_prefix_caching_plan.md).

## Confirmed Current Behavior

### 1. Actual context window used by the app

The Python app does not use `RAG_CONTEXT_WINDOW` at runtime.

It uses `MODEL_CONTEXT_WINDOW` instead:

- default `model_context_window` is `16384` in [backend/config.py](C:/Users/Nayan/Desktop/RAG_Chat_IPRv1.5/backend/config.py:79)
- env override is read from `MODEL_CONTEXT_WINDOW` in [backend/config.py](C:/Users/Nayan/Desktop/RAG_Chat_IPRv1.5/backend/config.py:231)
- model auto-detection is capped to `16384` in [backend/llm/detection.py](C:/Users/Nayan/Desktop/RAG_Chat_IPRv1.5/backend/llm/detection.py:55)
- `ChatOllama` sends `num_ctx=cfg.model_context_window` and `keep_alive=-1` in [backend/llm/client.py](C:/Users/Nayan/Desktop/RAG_Chat_IPRv1.5/backend/llm/client.py:251)

Current conclusion:

- unless `MODEL_CONTEXT_WINDOW` is explicitly set differently, the deployed app is a `16384`-context client

### 2. Main chat model configuration is stable inside this app

The app caches the chat client by model/runtime settings.

Current conclusion:

- inside this app, repeated requests should not intentionally reload the model with different `num_ctx`
- repeated unload/reload is therefore more likely to come from outside this app or from eviction/pressure

### 3. Warm-up behavior is shallow and best-effort

Startup warm-up:

- is scheduled in [backend/app.py](C:/Users/Nayan/Desktop/RAG_Chat_IPRv1.5/backend/app.py:101)
- uses a tiny generic chat prompt in [backend/llm/warmup.py](C:/Users/Nayan/Desktop/RAG_Chat_IPRv1.5/backend/llm/warmup.py:57)
- can be skipped or cancelled if a real request arrives first in [backend/llm/warmup.py](C:/Users/Nayan/Desktop/RAG_Chat_IPRv1.5/backend/llm/warmup.py:120)

Current conclusion:

- current warm-up is not a true warm-up of the real RAG hot path

### 4. Existing TTFT evidence points to model-runtime first-token cost, not retrieval

Existing benchmark notes show:

- measured average TTFT after warmup was `2618 ms`
- measured worst TTFT was `4600 ms`
- excluded warmup outlier was `48148 ms`
- the outlier was generator first-token dominated, not retrieval dominated

Relevant benchmark note:

- [TTFT_and_Sematic_Context_Test_results.md](C:/Users/Nayan/Desktop/RAG_Chat_IPRv1.5/TTFT_and_Sematic_Context_Test_results.md:49)
- [TTFT_and_Sematic_Context_Test_results.md](C:/Users/Nayan/Desktop/RAG_Chat_IPRv1.5/TTFT_and_Sematic_Context_Test_results.md:139)

## Current Runtime Issues

### Issue 1. Stale configuration naming creates operator confusion

Symptoms:

- `.env` and `.env.example` advertise `RAG_CONTEXT_WINDOW=16384`
- runtime actually uses `MODEL_CONTEXT_WINDOW`

Impact:

- operators can misread the deployed context behavior
- reload/debug analysis becomes harder than necessary

### Issue 2. Shared Ollama model can be reconfigured externally

Symptoms:

- if another client hits the same model with a different large context or different runtime shape, Ollama may need to reload or reallocate

Impact:

- first-token latency spikes
- apparent unload/reload churn
- unstable user experience

### Issue 3. Current warm-up is not representative

Symptoms:

- generic warm-up prompt is much smaller than a real RAG request
- it does not exercise planner + retriever + generator shape together

Impact:

- startup can still appear warm while the first real user query pays the heavy cost

### Issue 4. Multiple main-model calls can consume latency budget

Symptoms:

- helper paths such as planner/router/rewriter can also call the main model before final generation

Impact:

- part of the latency budget is spent before the final answer stream even starts

## Root Cause Analysis

### Root Cause A. Runtime cold spikes come from model-load or model-wake behavior

Why:

- retrieval timings in existing benchmark notes are relatively small
- excluded warmup spike is dominated by generator first-token delay

Effect:

- the expensive latency spike is a runtime/model event, not primarily a vector-store event

### Root Cause B. Shared external usage can invalidate the warm loaded state

Why:

- this app keeps one stable runtime shape internally
- external clients using the same Ollama model can still trigger reallocation or reload

Effect:

- a model that was warm for this app may not stay warm if external use changes the serving conditions

### Root Cause C. Warm-up is operational, not structural

Why:

- current warm-up only proves the model handled one tiny request
- it does not guarantee the real RAG path is warm

Effect:

- manual real warm-up remains the more trustworthy operational step for now

## Manual Warm-Up Assessment

## Question

If one operator manually sends the first real RAG request after startup, will later users still pay the same warm-up cost?

## Static-analysis answer

If all of the following remain true:

- the model stays loaded
- the backend process is not restarted
- another client does not force a different runtime shape on the same model
- VRAM pressure does not evict the runner

then later users should generally not pay that same one-time cold-start cost merely because they are different users.

Reasoning:

- this app does not reconfigure the main model per user
- once the model is loaded at the app's configured context, later requests should reuse that loaded runtime state

Important limitation:

- this is not a guarantee that every later user's first query will have identical TTFT
- it is a statement that the cold model-load cost can be absorbed once per stable loaded period

Operational conclusion:

- keeping warm-up manual is acceptable for now
- a manual warm-up should be a real representative RAG query, not the current tiny generic warm-up prompt

## Fix Plan

### Priority 0. Clarify deployment configuration

Actions:

- explicitly set `MODEL_CONTEXT_WINDOW=16384` in the deployed environment
- stop relying on `RAG_CONTEXT_WINDOW`
- update `.env.example` and deployment docs so the active variable is unambiguous

### Priority 1. Document and standardize manual warm-up

Actions:

- keep warm-up manual for now
- use one representative real RAG query after startup
- repeat manual warm-up after:
  - service restart
  - confirmed model reload
  - external context/runtime reconfiguration
  - confirmed eviction

### Priority 2. Keep the main chat model isolated from non-chat workloads where possible

Actions:

- avoid running ingestion/VLM on the same main chat model if another model is available for those workloads
- avoid sharing the main RAG chat model with clients that need very different runtime settings

### Priority 3. Review pre-generator main-model calls

Actions:

- identify helper paths that call the main model before final generation
- keep only calls that materially improve answer quality
- reduce avoidable contention on the same model

## Robust Validation Plan

### Phase A. Static/local verification

Required checks:

1. verify `MODEL_CONTEXT_WINDOW` is the only active context override in the Python app
2. verify operator-facing docs no longer imply that `RAG_CONTEXT_WINDOW` is active runtime config
3. verify warm-up code path is still best-effort and non-blocking

### Phase B. Live one-time warm-up validation

Procedure:

1. restart backend and Ollama into a known clean state
2. manually send one representative real RAG query
3. record TTFT for that query
4. immediately send first queries from multiple other user sessions

Expected result:

- the manual warm-up query may pay the cold-start cost
- later users should not all pay the same cold-start penalty if the model stayed loaded and unchanged

Failure interpretation:

- if later users still pay the cold-start cost, then likely causes include:
  - model was not truly warmed by the manual query
  - model was reloaded by an external client
  - model was evicted
  - a different runtime path triggered a new heavy initialization

### Phase C. External interference validation

Procedure:

1. warm the RAG model with a real query
2. confirm a second RAG query has good TTFT
3. hit the same model externally with a materially different runtime profile
4. send another RAG query

Expected result:

- if TTFT spikes again and loaded state changes, shared-runner interference is confirmed

### Phase D. Concurrency validation

Procedure:

1. complete one real manual warm-up request
2. start 5 concurrent user sessions
3. run representative RAG requests in parallel
4. inspect TTFT, queueing, and model residency

Metrics:

- TTFT per request
- p50, p95, and max TTFT
- evidence of queueing
- model residency before and after the run

Target:

- at least 5 concurrent representative users should remain within the agreed operational TTFT budget if the model stays resident and is not reconfigured externally

## Success Criteria

This plan is successful when all of the following hold:

- deployment context configuration is explicit and unambiguous
- manual warm-up reliably absorbs the one-time cold-start cost for a stable loaded period
- later users do not repeatedly pay the same cold-start cost unless the model was reloaded or evicted
- shared-model interference can be detected and operationally explained
- concurrent-user TTFT stays within the agreed target under representative load

## Final Recommendation

Keep manual warm-up as an operational step for now.

The main runtime focus should be:

1. make the real active context setting explicit
2. keep the main RAG chat model stable and isolated from conflicting workloads
3. validate that one manual real warm-up is enough for the later users during the same loaded period
