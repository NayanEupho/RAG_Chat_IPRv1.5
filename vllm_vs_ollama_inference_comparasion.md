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
