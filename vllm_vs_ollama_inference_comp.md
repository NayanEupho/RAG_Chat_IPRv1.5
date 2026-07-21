# vLLM vs Ollama Inference Comparison

Date: 2026-07-20
Backend URL: `http://127.0.0.1:8000`

This report compares the most recent validated Ollama run against the most recent validated vLLM/LiteLLM run after the OpenAI-compatible integration and after reverting the latency-negative prompt-prefix experiment.

Relevant commits and code state:

- `ef2f95f` - OpenAI-compatible / LiteLLM inference provider integration.
- `abef0ff` - Prompt-prefix prompt-shape experiment that increased TTFT.
- `d6a4136` - Reverted `abef0ff`; compact RAG prompt path restored.
- Current uncommitted fixes also include benchmark `--base-url` support, blank engine fallback to `ollama`, `main.py` reload opt-in, and Ruff cleanup in `llm_markdown.py`.

## Runtime Configurations

### vLLM via LiteLLM

- Main engine: `openai-compatible` / LiteLLM
- Main host: `http://10.20.20.90:4000/v1`
- Main model: `qwen2.5-7b`
- Embedding engine: `ollama`
- Embedding host: `http://10.20.39.12:11438`
- Embedding model: `embeddinggemma:300m`
- Backend status: main query-ready, embedding loaded/query-ready
- Backend launcher: `python .\main.py` with reload disabled by default
- TTFT log: `ttft_vllm_mainpy_noreload_latest.log`
- Semantic log: `semantic_vllm_mainpy_noreload_latest.log`

### Ollama Clean-GPU Baseline

- Main engine: `ollama`
- Main host: `http://10.20.39.12:11438`
- Main model: `qwen3.6:35b-a3b-q8_0`
- Embedding engine: `ollama`
- Embedding host: `http://10.20.39.12:11438`
- Embedding model: `embeddinggemma:300m`
- Ollama resident models during this run: only `qwen3.6:35b-a3b-q8_0` and `embeddinggemma:300m`
- Backend launcher: `python .\main.py` with reload disabled by default
- TTFT log: `ttft_ollama_clean_gpu_latest.log`
- Semantic log: `semantic_ollama_clean_gpu_latest.log`

## TTFT Summary

| Metric | vLLM/LiteLLM qwen2.5-7b | Ollama qwen3.6:35b |
|---|---:|---:|
| Total queries | 30 | 30 |
| Best TTFT | 1642 ms | 1997 ms |
| Average TTFT | 2226 ms | 3029 ms |
| Worst TTFT | 2696 ms | 5100 ms |
| Average after first measured turn | 2224 ms | 3014 ms |
| Queries <= 5s | 30/30 (100%) | 29/30 (96%) |
| Queries <= 7s | 30/30 (100%) | 30/30 (100%) |
| Queries > 7s | 0/30 (0%) | 0/30 (0%) |
| Grounding warnings | none | none |

## TTFT By Category

| Category | vLLM Range | vLLM Avg | Ollama Range | Ollama Avg |
|---|---:|---:|---:|---:|
| Non-targeted RAG | 2292-2385 ms | 2354 ms | 3008-3662 ms | 3380 ms |
| Targeted RAG | 1822-2359 ms | 2114 ms | 2845-2951 ms | 2883 ms |
| Targeted paper follow-up | 2292-2696 ms | 2494 ms | 3406-5100 ms | 4253 ms |
| Chat mode | 1642-1685 ms | 1667 ms | 1997-2244 ms | 2112 ms |
| Multi-turn RAG | 1851-2433 ms | 2217 ms | 2699-3318 ms | 2899 ms |
| Rapid follow-ups | 1957-2555 ms | 2316 ms | 3009-3649 ms | 3283 ms |
| Document coverage | 2196-2546 ms | 2395 ms | 2782-3465 ms | 3025 ms |

## Internal Timing Breakdown

Measured rows exclude the two warmup turns emitted by `test_ttft.py`.

| Internal Metric | vLLM Avg | Ollama Avg | Interpretation |
|---|---:|---:|---|
| Backend first token | 728 ms | 1492 ms | vLLM path is about 764 ms faster inside backend. |
| Generator first token | 328 ms | 1430 ms | Main win: vLLM reaches first generated token much faster. |
| Retriever node | 427 ms | 38 ms | Ollama run had fully hot embedding cache; vLLM run still paid embedding calls. |
| Retrieval total | 417 ms | 33 ms | Same cache effect as above. |
| Embedding | 360 ms | 0 ms | vLLM run used Ollama embeddings but cache was not fully hot. |
| Vector search | 12 ms | 6 ms | Both are negligible. |
| Client/pre-stream gap | 1499 ms | 1537 ms | Similar; not the main runtime differentiator. |

## Worst Cases

### vLLM Worst 5

1. 2696 ms: `What is @Qlora_Paper.pdf paper about?`
2. 2555 ms: `Explain the pension rules in detail`
3. 2546 ms: `What does @FAQ_LTDP_28Dec11.pdf say about LTDP eligibility?`
4. 2457 ms: `What does @ADG-1.pdf say is the purpose of the ADG document?`
5. 2433 ms: `Explain the methodology discussed`

### Ollama Worst 5

1. 5100 ms: `What is @Qlora_Paper.pdf paper about?`
2. 3662 ms: `Summarize the key conclusions`
3. 3649 ms: `Explain the pension rules in detail`
4. 3471 ms: `What is the technical report about?`
5. 3465 ms: `What does @Design and Development.pdf require for the IPR website design and dev`

## Semantic / Context Results

| Runtime | Checks | Failed Turns | Notes |
|---|---:|---:|---|
| vLLM/LiteLLM qwen2.5-7b | 94/96 | 2 | Retrieval targets and sources were correct, but two strict required-term checks failed: `MCP` and `context-switch`. |
| Ollama qwen3.6:35b | 96/96 | 0 | Passed targeted docs, follow-ups, context shift, chat escape, and multi-document comparison. |

### vLLM Semantic Failures

1. `technical_report_followup_no_repetition` turn 2: query `what core agentic concepts does it rely on?` failed required term `MCP`.
2. `technical_report_followup_no_repetition` turn 3: query `what features and problems does it solve?` failed required term `context-switch`.

Both failures are wording/coverage failures from the smaller vLLM model, not routing failures. The expected `TECHNICAL_REPORT_V8.pdf` source was retrieved in both turns.

## Interpretation

vLLM/LiteLLM is materially faster on TTFT in this environment:

- Average TTFT improved from `3029 ms` to `2226 ms`.
- Worst-case TTFT improved from `5100 ms` to `2696 ms`.
- Chat-mode TTFT improved from `2112 ms` to `1667 ms`.
- Generator first-token improved from `1430 ms` to `328 ms`.

The tradeoff is semantic completeness. Ollama `qwen3.6:35b-a3b-q8_0` passed all semantic/context checks, while vLLM `qwen2.5-7b` failed two strict required-term checks. If production priority is latency, the vLLM path is strong. If production priority is maximum answer completeness on nuanced multi-turn RAG, Ollama currently remains more reliable unless vLLM is upgraded to a stronger model or prompts are tightened for the smaller model.

## Reproduction Commands

Run against whichever backend config is currently live on port 8000:

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe test_ttft.py --base-url http://127.0.0.1:8000 *> ttft_<runtime>_latest.log
.\.venv\Scripts\python.exe test_semantic_context.py --base-url http://127.0.0.1:8000 *> semantic_<runtime>_latest.log
```

Verify runtime status:

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/status' -TimeoutSec 30 | ConvertTo-Json -Depth 8
```

---

## 2026-07-21: Session Memory Disabled Preservation Check - Ollama

Configuration:

- Main engine: `ollama`
- Main host: `http://10.20.39.12:11438`
- Main model: `qwen3.6:35b-a3b-q8_0`
- Embedding engine: `ollama`
- Embedding model: `embeddinggemma:300m`
- Backend URL: `http://127.0.0.1:8000`
- Session memory flag: `RAG_SESSION_MEMORY_ENABLED=false`
- Purpose: verify the new gated session-memory implementation preserves the legacy false path.
- TTFT log: `ttft_session_memory_false_ollama_20260721.log`
- Semantic transcript: `semantic_context_eval_latest.json`

### TTFT Comprehensive Result

| Metric | Result |
|---|---:|
| Total measured queries | 30 |
| Best TTFT | 1681 ms |
| Average TTFT | 2733 ms |
| Worst TTFT | 4856 ms |
| Average after first measured turn | 2744 ms |
| Grounding warnings | none |

### TTFT By Category

| Category | TTFT Range | Average TTFT | Cache Improvement |
|---|---:|---:|---:|
| Non-targeted RAG | 2253-2597 ms | 2426 ms | 7% |
| Targeted RAG | 2291-2372 ms | 2330 ms | 2% |
| Targeted paper follow-up | 2865-4608 ms | 3736 ms | 38% |
| Chat mode | 1681-1705 ms | 1691 ms | 1% |
| Multi-turn RAG | 1976-3074 ms | 2462 ms | 15% |
| Rapid follow-ups | 2704-3676 ms | 3204 ms | 10% |
| Document coverage | 2893-4856 ms | 3552 ms | 13% |

### Semantic / Context Result

| Metric | Result |
|---|---:|
| Scenarios | 6 |
| Turns | 13 |
| Checks passed | 96/96 |
| Failed turns | 0 |
| Best TTFT in semantic run | 1966 ms |
| Average TTFT in semantic run | 3062 ms |
| Worst TTFT in semantic run | 5114 ms |

### Preservation Verdict

The disabled path is preserved. With `RAG_SESSION_MEMORY_ENABLED=false`, the benchmark stayed within the prior Ollama baseline and was slightly better on the comprehensive TTFT run:

- Prior clean Ollama baseline: average `3029 ms`, worst `5100 ms`, semantic `96/96`.
- Current false-path Ollama run: average `2733 ms`, worst `4856 ms`, semantic `96/96`.

This indicates the session-memory implementation did not regress the legacy RAG generation path when disabled.

---

## 2026-07-21: Session Memory Enabled Check - Ollama

Configuration:

- Main engine: `ollama`
- Main host: `http://10.20.39.12:11438`
- Main model: `qwen3.6:35b-a3b-q8_0`
- Embedding engine: `ollama`
- Embedding model: `embeddinggemma:300m`
- Backend URL: `http://127.0.0.1:8000`
- Session memory flag: `RAG_SESSION_MEMORY_ENABLED=true`
- Purpose: evaluate the opt-in compact session-memory RAG prompt against the preserved false-path baseline.
- TTFT log: `ttft_session_memory_true_ollama_20260721.log`
- Semantic log: `semantic_session_memory_true_ollama_20260721.log`

### TTFT Comprehensive Result

| Metric | Result |
|---|---:|
| Total measured queries | 30 |
| Best TTFT | 2612 ms |
| Average TTFT | 5543 ms |
| Worst TTFT | 17960 ms |
| Average after first measured turn | 5430 ms |
| Queries <= 5s | 20/30 |
| Queries <= 7s | 23/30 |
| Queries > 7s | 7/30 |
| Grounding warnings | none |

### TTFT By Category

| Category | TTFT Range | Average TTFT | Cache Improvement |
|---|---:|---:|---:|
| Non-targeted RAG | 8830-11165 ms | 10303 ms | -24% |
| Targeted RAG | 3050-6637 ms | 4610 ms | -36% |
| Targeted paper follow-up | 5294-10457 ms | 7875 ms | 49% |
| Chat mode | 3071-11538 ms | 7435 ms | 73% |
| Multi-turn RAG | 2612-17960 ms | 4964 ms | 85% |
| Rapid follow-ups | 3708-5208 ms | 4155 ms | 0% |
| Document coverage | 2736-4309 ms | 3447 ms | 37% |

### Worst 5 TTFTs

1. 17960 ms: `What is the technical report about?`
2. 11538 ms: `Hello! How are you?`
3. 11165 ms: `What technologies does it mention?`
4. 10916 ms: `Summarize the key conclusions`
5. 10457 ms: `What is @Qlora_Paper.pdf paper about?`

### Semantic / Context Result

| Metric | Result |
|---|---:|
| Scenarios | 6 |
| Turns | 13 |
| Checks passed | 96/96 |
| Failed turns | 0 |
| Best TTFT in semantic run | 3033 ms |
| Average TTFT in semantic run | 5585 ms |
| Worst TTFT in semantic run | 9453 ms |

### Comparison Against Disabled Path

| Metric | Session Memory Disabled | Session Memory Enabled | Delta |
|---|---:|---:|---:|
| Comprehensive avg TTFT | 2733 ms | 5543 ms | +2810 ms |
| Comprehensive worst TTFT | 4856 ms | 17960 ms | +13104 ms |
| Semantic checks | 96/96 | 96/96 | no change |
| Semantic avg TTFT | 3062 ms | 5585 ms | +2523 ms |
| Semantic worst TTFT | 5114 ms | 9453 ms | +4339 ms |

### Verdict

Do not enable `RAG_SESSION_MEMORY_ENABLED=true` for production on the current Ollama path. It preserved semantic correctness but materially regressed TTFT and failed the 5-7s latency target. Keep `RAG_SESSION_MEMORY_ENABLED=false` as the production-safe setting unless the enabled prompt shape is redesigned or made more selective.

### Engineering Comment

The enabled session-memory prompt is currently a correctness-preserving but latency-negative experiment on Ollama. The likely cause is prompt-shape fragmentation plus extra session/control blocks increasing prompt evaluation work and weakening prefix-cache reuse for early turns. Even though the compact path does not add another model call, it changes the message layout enough that the first several turns pay much higher TTFT.

Production recommendation:

- Keep `RAG_SESSION_MEMORY_ENABLED=false` for Ollama production deployments.
- Do not merge this as an enabled default until a redesigned approach proves avg TTFT remains within 10-20% of the disabled baseline.
- Any future retry should be more selective: only add session memory for ambiguous follow-ups where retrieval would otherwise fail, not for every RAG turn.
- The disabled path is safe and should remain the rollback/default path because it preserved semantic accuracy and stayed under the target latency envelope.

---

## 2026-07-21: Session Memory Disabled Preservation Check - vLLM/LiteLLM

Configuration:

- Main engine: `openai-compatible` / LiteLLM / vLLM
- Main host: `http://10.20.20.90:4000/v1`
- Main model: `qwen2.5-7b`
- Embedding engine: `ollama`
- Embedding model: `embeddinggemma:300m`
- Backend URL: `http://127.0.0.1:8000`
- Session memory flag: `RAG_SESSION_MEMORY_ENABLED=false`
- Purpose: verify the gated session-memory implementation preserves the previous vLLM false path.
- TTFT log: `ttft_session_memory_false_vllm_20260721.log`
- Semantic log: `semantic_session_memory_false_vllm_20260721.log`

### TTFT Comprehensive Result

| Metric | Previous vLLM Baseline | Current False-Path vLLM |
|---|---:|---:|
| Total measured queries | 30 | 30 |
| Best TTFT | 1642 ms | 1580 ms |
| Average TTFT | 2226 ms | 1832 ms |
| Worst TTFT | 2696 ms | 2247 ms |
| Average after first measured turn | 2224 ms | 1825 ms |
| Queries <= 5s | 30/30 | 30/30 |
| Queries <= 7s | 30/30 | 30/30 |
| Queries > 7s | 0/30 | 0/30 |
| Grounding warnings | none | none |

### TTFT By Category

| Category | TTFT Range | Average TTFT | Cache Improvement |
|---|---:|---:|---:|
| Non-targeted RAG | 1957-2247 ms | 2084 ms | 4% |
| Targeted RAG | 1742-2123 ms | 1975 ms | 15% |
| Targeted paper follow-up | 1916-1976 ms | 1946 ms | 3% |
| Chat mode | 1580-1712 ms | 1645 ms | 8% |
| Multi-turn RAG | 1580-2199 ms | 1824 ms | 14% |
| Rapid follow-ups | 1586-2050 ms | 1780 ms | 23% |
| Document coverage | 1633-1862 ms | 1721 ms | -1% |

### Worst 5 TTFTs

1. 2247 ms: `Summarize the key conclusions`
2. 2199 ms: `Explain the methodology discussed`
3. 2123 ms: `What are the eligibility criteria?`
4. 2060 ms: `What does @FAQ_LTDP_28Dec11.pdf say about LTDP?`
5. 2050 ms: `Explain the pension rules in detail`

### Semantic / Context Result

| Metric | Previous vLLM Baseline | Current False-Path vLLM |
|---|---:|---:|
| Scenarios | 6 | 6 |
| Turns | 13 | 13 |
| Checks passed | 94/96 | 95/96 |
| Failed turns | 2 | 1 |
| Best TTFT in semantic run | not recorded here | 1514 ms |
| Average TTFT in semantic run | not recorded here | 2079 ms |
| Worst TTFT in semantic run | not recorded here | 2409 ms |

Current semantic failure:

1. `technical_report_followup_no_repetition` turn 2, query `what core agentic concepts does it rely on?`: retrieved `TECHNICAL_REPORT_V8.pdf` correctly but missed required term `MCP` in the answer.

### Preservation Verdict

The vLLM false path is preserved. With `RAG_SESSION_MEMORY_ENABLED=false`, TTFT improved compared to the previous vLLM baseline and the semantic result remained in the same expected range for the smaller `qwen2.5-7b` model. The remaining semantic issue is answer completeness from the smaller model, not retrieval routing or session-memory regression.

---

## 2026-07-21: Session Memory Enabled Check - vLLM/LiteLLM

Configuration:

- Main engine: `openai-compatible` / LiteLLM / vLLM
- Main host: `http://10.20.20.90:4000/v1`
- Main model: `qwen2.5-7b`
- Embedding engine: `ollama`
- Embedding model: `embeddinggemma:300m`
- Backend URL: `http://127.0.0.1:8000`
- Session memory flag: `RAG_SESSION_MEMORY_ENABLED=true`
- Purpose: evaluate whether the enabled compact session-memory prompt is viable on vLLM.
- TTFT log: `ttft_session_memory_true_vllm_20260721.log`
- Semantic log: `semantic_session_memory_true_vllm_20260721.log`

### TTFT Comprehensive Result

| Metric | Session Memory Disabled vLLM | Session Memory Enabled vLLM |
|---|---:|---:|
| Total measured queries | 30 | 30 |
| Best TTFT | 1580 ms | 1498 ms |
| Average TTFT | 1832 ms | 1805 ms |
| Worst TTFT | 2247 ms | 2275 ms |
| Average after first measured turn | 1825 ms | 1802 ms |
| Queries <= 5s | 30/30 | 30/30 |
| Queries <= 7s | 30/30 | 30/30 |
| Queries > 7s | 0/30 | 0/30 |
| Grounding warnings | none | none |

### TTFT By Category

| Category | TTFT Range | Average TTFT | Cache Improvement |
|---|---:|---:|---:|
| Non-targeted RAG | 1733-2156 ms | 1928 ms | 9% |
| Targeted RAG | 1629-1899 ms | 1802 ms | 14% |
| Targeted paper follow-up | 1738-2040 ms | 1889 ms | 15% |
| Chat mode | 1553-1662 ms | 1594 ms | 7% |
| Multi-turn RAG | 1578-2216 ms | 1815 ms | 12% |
| Rapid follow-ups | 1498-2275 ms | 1919 ms | 34% |
| Document coverage | 1630-1949 ms | 1715 ms | 2% |

### Worst 5 TTFTs

1. 2275 ms: `Explain the pension rules in detail`
2. 2216 ms: `Explain the methodology discussed`
3. 2156 ms: `Summarize the key conclusions`
4. 2049 ms: `What technologies does it use?`
5. 2049 ms: `Are there any limitations mentioned?`

### Semantic / Context Result

| Metric | Session Memory Disabled vLLM | Session Memory Enabled vLLM |
|---|---:|---:|
| Scenarios | 6 | 6 |
| Turns | 13 | 13 |
| Checks passed | 95/96 | 93/96 |
| Failed turns | 1 | 3 |
| Best TTFT in semantic run | 1514 ms | 1498 ms |
| Average TTFT in semantic run | 2079 ms | 1909 ms |
| Worst TTFT in semantic run | 2409 ms | 2222 ms |

Current semantic failures:

1. `technical_report_followup_no_repetition` turn 1, query `What is @TECHNICAL_REPORT_V8.pdf about? Tell me the author and what tech stack is used for the project.`: retrieved `TECHNICAL_REPORT_V8.pdf` correctly but missed required term `DevOps Agent`.
2. `technical_report_followup_no_repetition` turn 2, query `what core agentic concepts does it rely on?`: retrieved `TECHNICAL_REPORT_V8.pdf` correctly but missed required term `MCP`.
3. `technical_report_followup_no_repetition` turn 3, query `what features and problems does it solve?`: retrieved `TECHNICAL_REPORT_V8.pdf` correctly but missed required term `complexity`.

### Verdict

vLLM absorbs the enabled session-memory prompt on latency: avg TTFT stayed essentially flat (`1832 ms` disabled vs `1805 ms` enabled), and all 30 comprehensive TTFT queries remained under 5 seconds. However, semantic completeness regressed from `95/96` to `93/96` on the smaller `qwen2.5-7b` model. The failures are answer-coverage issues after correct retrieval, not routing failures.

Production recommendation for vLLM:

- Keep `RAG_SESSION_MEMORY_ENABLED=false` as the default because latency is similar but semantic score is better when disabled.
- The enabled path can be revisited for a stronger or better-tuned vLLM-served 7B model; the current `qwen2.5-7b` result suggests the bottleneck is semantic completeness, not TTFT.
- The vLLM session-history-true case may improve if we add a better 7B model in vLLM, especially one that follows document-grounded required-term instructions more reliably.
- If session memory is needed later, make it conditional only for ambiguous follow-ups instead of all RAG turns.
