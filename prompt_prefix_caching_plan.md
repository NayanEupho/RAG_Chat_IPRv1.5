# Prompt Prefix Caching Plan

Date: July 16, 2026

## Scope

This plan covers only prompt/prefix caching in the RAG chat path:

- current prompt-caching issues
- root-cause analysis
- concrete fixes
- robust validation for same-session cache preservation

This plan treats prompt caching as the highest-value software optimization currently available.

## Target Requirement

Prompt/prefix caching should be preserved as well as possible for all of the following within the same chat session:

1. the session remains in explicit `chat` mode
2. the session remains in explicit `rag` mode
3. the session remains in `auto` mode while effective behavior interleaves between chat and RAG over many turns
4. the user switches modes mid-session in any direction, including:
   - `chat -> auto`
   - `chat -> rag`
   - `rag -> auto`
   - `rag -> chat`
   - `auto -> chat`
   - `auto -> rag`
   - repeated switching across one thread

The cache design must treat the session thread as the primary unit of continuity, not the current mode of a single turn.

## Confirmed Current Behavior

### Chat mode

Chat mode is relatively favorable for prefix reuse:

- it preserves message history as a message list
- it uses deterministic local summary compaction when history gets long
- this keeps the leading prompt region comparatively stable across follow-up turns

Relevant code:

- [backend/graph/nodes/generate.py](C:/Users/Nayan/Desktop/RAG_Chat_IPRv1.5/backend/graph/nodes/generate.py:165)
- [backend/graph/nodes/generate.py](C:/Users/Nayan/Desktop/RAG_Chat_IPRv1.5/backend/graph/nodes/generate.py:315)

### RAG mode

RAG mode is much less favorable for prefix reuse:

- it builds a large synthetic user prompt
- retrieved docs are inlined into that prompt
- search metadata and targeting metadata are dynamic
- the final generator call does not preserve the same multi-turn structure used in chat mode

Relevant code:

- [backend/graph/nodes/generate.py](C:/Users/Nayan/Desktop/RAG_Chat_IPRv1.5/backend/graph/nodes/generate.py:217)
- [backend/graph/nodes/generate.py](C:/Users/Nayan/Desktop/RAG_Chat_IPRv1.5/backend/graph/nodes/generate.py:272)

### Mode transitions

Mode transitions are not currently treated as a first-class prompt-cache requirement:

- chat mode and RAG mode use materially different final prompt assembly paths
- auto mode can alternate between them inside the same session
- explicit mode switches can therefore collapse the reusable prefix

## Compaction and Cache Checkpoints

### Current behavior when the 16k context budget is exceeded

The app does not try to preserve literal full-session prompt continuity forever.

When message history exceeds the configured history budget, `_build_message_list(...)` compacts the older portion of the session into a stable summary checkpoint:

- it computes total history tokens
- if total history fits, it keeps the message list as-is
- if total history exceeds budget, it keeps only the newest tail that fits the recent-history budget
- it converts the dropped older turns into `next_summary`
- it injects that summary back as a `SystemMessage` prefixed with `[Stable summary of earlier conversation]`

Relevant code:

- [backend/graph/nodes/generate.py](C:/Users/Nayan/Desktop/RAG_Chat_IPRv1.5/backend/graph/nodes/generate.py:165)
- [backend/graph/nodes/generate.py](C:/Users/Nayan/Desktop/RAG_Chat_IPRv1.5/backend/graph/nodes/generate.py:185)
- [backend/graph/nodes/generate.py](C:/Users/Nayan/Desktop/RAG_Chat_IPRv1.5/backend/graph/nodes/generate.py:190)

### What this means for prompt/prefix caching

After the first compaction event, the effective reusable prefix is no longer anchored from turn 1 of the original chat session.

Instead, it is anchored from the latest stable compaction checkpoint:

- fixed system prompt
- stable summary checkpoint
- retained recent turns
- any stable mode-control layer
- retrieval tail when active

This is the correct design direction for a 16k window. Trying to preserve literal prefix continuity from the very first turn forever would eventually destroy cache efficiency and exceed budget.

### Cache epochs

The current design naturally creates cache epochs:

1. epoch 1: from session start until the first compaction
2. epoch 2: from the first summary checkpoint until the next compaction
3. epoch 3: from the next summary checkpoint onward

Within one epoch, prompt/prefix caching should remain as stable as possible.
When compaction happens again, a new checkpoint is created and the cache root moves forward to that new stable checkpoint.

### Current limitation

This checkpoint behavior is structurally reasonable for chat mode, but it is not yet fully exploited for RAG mode because the final RAG prompt shape still rebuilds too much dynamic content.

The ideal design is:

- do not try to cache forever from the literal first turn
- do cache from the latest stable compaction checkpoint
- keep that checkpoint stable across `chat`, `rag`, and `auto` mode behavior
- make mode switches and retrieval additions small tail deltas relative to that checkpoint
## Current Prompt-Caching Issues

### Issue 1. RAG follow-up turns rebuild too much of the prompt

Symptoms:

- retrieved docs are injected into a fresh large prompt block
- retrieval annotations vary by turn
- the final prompt body changes more than necessary

Impact:

- same-session RAG follow-ups lose much of the available prefix reuse
- generator prompt-eval work is repeated unnecessarily

### Issue 2. Chat and RAG use different prompt architectures

Symptoms:

- chat preserves conversational structure
- RAG collapses context into a synthetic retrieval-heavy prompt

Impact:

- cache preservation differs sharply by mode
- switching from one mode to another invalidates more of the prefix than necessary

### Issue 3. Auto mode is not cache-optimized for interleaving behavior

Symptoms:

- auto mode may route `chat -> rag -> chat -> rag` inside one thread
- those transitions can produce abrupt prompt-shape changes

Impact:

- a correct session can still be a cache-inefficient session
- first-token latency can stay unnecessarily volatile inside one thread

### Issue 4. Mode switching is not encoded compactly

Symptoms:

- mode affects top-level prompt construction strategy instead of only a compact control layer

Impact:

- switching modes can behave like a prompt reset instead of a small delta

## Root Cause Analysis

### Root Cause A. Prompt caching is optimized for chat mode, not for RAG mode

Why:

- chat mode keeps a stable message-list structure
- RAG mode rebuilds a large dynamic prompt containing retrieval payload
- retrieved evidence is often the largest changing part of the prompt

Effect:

- repeated chat turns can reuse prefix better
- repeated RAG turns in the same session lose much of that benefit

### Root Cause B. There is no unified session-prompt architecture across modes

Why:

- chat mode and RAG mode are built through different final-prompt paths
- mode is not represented as compact session state layered onto one common structure

Effect:

- mode transitions can invalidate most of the prefix
- auto mode inherits this problem whenever intent changes between turns

### Root Cause C. Retrieval formatting is too dynamic to maximize reuse

Why:

- search notes, retrieval notes, and docs are injected directly into the user prompt
- chunk selection and formatting can change across turns

Effect:

- even when the user stays in one topic, the final prompt tail changes more than necessary
- cache reuse becomes weaker than it should be for document follow-ups

### Root Cause D. Compaction is a valid cache-boundary mechanism, but it is not yet treated explicitly as the canonical cache root across all modes

Why:

- once history exceeds budget, the system already converts older turns into a stable summary checkpoint
- this naturally shifts the effective prefix root forward
- however, the broader prompt architecture does not yet consistently treat that checkpoint as the canonical reusable base across chat, RAG, auto-mode interleaving, and mode switches

Effect:

- chat mode benefits from checkpoint stability more than RAG mode
- repeated RAG turns after a compaction boundary still lose more prefix reuse than they should
- mode changes that happen after compaction can invalidate more of the reusable prefix than necessary
## Fix Plan

### Priority 1. Unify the final generator prompt architecture across chat, RAG, and auto

Target outcome:

- one session should preserve one stable prompt skeleton regardless of whether a given turn is chat or RAG

Recommended structure:

- `system`: stable generator instructions
- optional `system`: stable summary block when compaction is needed
- preserved prior `user` and `assistant` session turns
- optional compact session-control block for current mode or mode override
- optional retrieval block with deterministic formatting when retrieval is active
- current user question as the last message

Design rule:

- changing modes must not replace the overall prompt architecture
- changing modes should only alter the smallest possible control segment and retrieval segment

### Priority 2. Preserve session history in RAG mode instead of collapsing it away

Target outcome:

- same-session RAG follow-up turns should benefit from the same preserved conversational prefix that chat mode already uses better

Recommended changes:

- keep prior turns in the final RAG generator message list
- append retrieval context as an additional structured block rather than rebuilding everything as one fresh synthetic message
- keep the current user question as the final turn, not buried inside a large reconstructed prompt body

### Priority 3. Make retrieval payload deterministic and compact

Recommended changes:

- keep chunk ordering deterministic
- keep retrieval labels byte-stable
- avoid changing boilerplate wording across turns
- omit empty sections consistently
- keep only the minimum useful document subset for the generator

Target outcome:

- the retrieval block becomes a smaller, more stable tail
- the shared prefix becomes larger and more reusable

### Priority 4. Treat the latest compaction checkpoint as the canonical cache root

Recommended changes:

- explicitly design the prompt architecture around cache epochs
- after compaction, treat the stable summary checkpoint as the new canonical prefix root
- do not attempt to preserve cache continuity from the literal first session turn forever
- keep checkpoint updates rare and deterministic
- when a checkpoint changes, ensure the new post-compaction prompt skeleton is byte-stable from that point onward until the next compaction

Target outcome:

- prompt caching remains strong within each epoch
- compaction becomes an intentional and controlled cache-boundary event rather than an accidental cache reset
- the same checkpoint-root model applies to chat, ag, and uto sessions

### Priority 5. Encode mode changes compactly

Recommended changes:

- represent current mode as compact prompt state, not a different prompt-building branch
- keep `chat`, `rag`, and `auto` transitions within the same message skeleton
- make explicit overrides visible but small

Target outcome:

- `chat -> rag -> chat` in one session behaves like controlled tail variation, not repeated prompt resets

## Robust Validation Plan

Validation should focus on prompt shape and cache stability first, then latency.

### Phase A. Static prompt-shape verification

Add targeted tests that inspect the final generator message list.

Required tests:

1. Same-session chat follow-up preserves a stable prefix across turns.
2. Same-session RAG follow-up preserves prior session history in the final generator call.
3. Same-session auto-mode sequence `rag -> chat -> rag` preserves the same high-level prompt skeleton.
4. Explicit mode switch `chat -> rag` preserves the same high-level prompt skeleton.
5. Explicit mode switch `rag -> chat` preserves the same high-level prompt skeleton.
6. Explicit mode switch `auto -> chat`, `auto -> rag`, `chat -> auto`, and `rag -> auto` behaves deterministically.
7. Identical retrieved chunks in identical order produce identical prefix signatures across repeated requests.
8. Only the tail changes when the latest user question changes but prior history and retrieval are stable.

Pass criteria:

- `_cache_signature(...)` or equivalent debug output remains stable when the shared session prefix should be stable
- mode changes affect only the intended compact control segment and retrieval segment
- prompt skeleton does not fork into unrelated shapes by mode

### Phase B. Behavioral regression verification

Run and extend existing tests so prompt-cache fixes do not break correctness.

Required checks:

- targeted-document follow-ups still resolve correctly
- topic shifts still escape stale RAG grounding when appropriate
- chat mode still behaves like chat mode
- auto mode still routes correctly
- citations and grounding remain correct

### Phase C. Live same-session cache validation on the IPR network

#### C1. Pure RAG follow-up session

Procedure:

1. start one session
2. ask one RAG query against a stable document
3. ask 4 to 6 follow-up turns in the same topic
4. capture prompt signature, retrieval composition, and first-token timing

Expected result:

- stable or near-stable prefix signatures across follow-up turns
- lower and more consistent generator first-token latency than before

#### C1A. Compaction-boundary validation

Procedure:

1. start one long session and keep asking turns until history crosses the compaction threshold
2. capture the last pre-compaction prompt signature
3. capture the first post-compaction prompt signature
4. verify that the post-compaction prompt now uses the summary checkpoint as the root
5. continue with additional follow-up turns after compaction
6. inspect whether subsequent signatures remain stable within that new epoch

Expected result:

- the first post-compaction turn establishes a new stable checkpoint-root epoch
- subsequent turns reuse that checkpoint-root prefix
- the system does not attempt to preserve literal prompt continuity from the very first turn of the session
#### C2. Mixed-mode same-session validation

Procedure:

1. start one session in `auto` mode
2. send a pure chat query
3. send a RAG query
4. send a RAG follow-up
5. send a pure chat query again
6. send another RAG query
7. repeat the same pattern in explicit switched sessions:
   - `chat -> rag -> chat`
   - `rag -> chat -> rag`
   - `auto -> chat -> auto -> rag`

Metrics:

- prefix signature before and after each transition
- generator first-token time on each turn
- retrieved chunk identities and order when retrieval is active

Expected result:

- prompt architecture stays stable across mode changes
- mode switches do not behave like full prompt-cache resets
- only the smallest necessary tail/control changes appear

#### C2A. Post-compaction mixed-mode validation

Procedure:

1. force one session past the compaction threshold
2. from the new checkpoint-root epoch, run the following within the same session:
   - explicit `chat -> rag`
   - explicit `rag -> chat`
   - `auto` interleaving `rag -> chat -> rag`
   - explicit switches back into `auto`
3. capture prompt signatures and first-token timing for each turn

Expected result:

- all of these cases preserve prompt continuity from the latest checkpoint root
- compaction plus mode switching does not cause an unnecessary full prompt reset
- retrieval changes remain tail deltas relative to the checkpoint-root prefix
### Phase D. Concurrency verification after prompt-cache fix

Procedure:

1. perform one real manual warm-up request
2. start multiple active sessions
3. run repeated same-session follow-up patterns under concurrent load
4. compare first-turn vs follow-up-turn TTFT

Expected result:

- follow-up turns in the same session should benefit measurably from better prefix stability
- improvements should persist even when multiple users are active, subject to overall model capacity

## Success Criteria

This plan is successful when all of the following hold:

- same-session RAG follow-ups preserve a stable prompt prefix
- same-session `chat`, `rag`, and `auto` behavior uses one stable prompt architecture
- mode switches across one thread preserve prompt continuity instead of resetting it
- retrieval payload is deterministic enough to preserve a large reusable prefix
- follow-up TTFT becomes more stable without breaking routing, grounding, or citations

## Final Recommendation

Treat prompt caching as a session-architecture problem, not just a retrieval-formatting problem.

The highest-value fix is to stop treating RAG turns as synthetic prompt rebuilds and instead preserve one unified conversational prefix across chat, RAG, auto-mode interleaving, and explicit mode switching.

