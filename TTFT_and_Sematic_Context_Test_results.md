# TTFT and Semantic Context Test Results

Date: 2026-07-08  
Code baseline: latest validated local commits ending at `3731316 test: fix ttft stdout typing`  
Backend under test: local FastAPI/Uvicorn backend on `127.0.0.1:8019`  
Inference endpoint: IPR HPC Ollama API at `http://10.20.39.12:11438`

## Model Configuration

The latest validated run used the IPR HPC Ollama inference endpoint:

```text
RAG_MAIN_HOST=http://10.20.39.12:11438
RAG_MAIN_MODEL=qwen3.6:35b-a3b-q8_0
RAG_MAIN_ENGINE=ollama

RAG_EMBED_HOST=http://10.20.39.12:11438
RAG_EMBED_MODEL=embeddinggemma:300m
RAG_EMBED_ENGINE=ollama
```

Observed `/api/status` readiness during the run:

```text
chat_available=true
rag_available=true
main_model.loaded=true
main_model.query_ready=true
embedding_model.loaded=true
embedding_model.query_ready=true
main_model.latency_ms=4208
embedding_model.latency_ms=4212
```

## Summary

The final root-cause fix run passed both correctness and latency gates.

Semantic/context validation:

```text
Scenarios: 6
Turns: 13
Checks: 96/96 passed
Failed turns: 0
Transcript: semantic_context_eval_8019_rootfix.json
```

TTFT validation, excluding the benchmark's first two warmup turns:

```text
Measured turns: 30
Average TTFT: 2618 ms
Best TTFT: 1561 ms
Worst TTFT: 4600 ms
Queries <= 5s: 30/30
Queries <= 7s: 30/30
Queries > 7s: 0/30
Target result: PASS
Grounding warnings: none reported
```

Important note: `test_ttft.py` emits two pre-suite warmup turns before the measured groups. In this run, warmup turn 2 had a `48148 ms` TTFT caused by model runtime first-token delay:

```text
Warmup Turn 2: What are the authors of @Qlora_Paper.pdf?
TTFT: 48148 ms
retriever: 296 ms
generator first token: 46723 ms
```

That warmup outlier is not counted in the measured 30-turn benchmark. It is useful operationally because it shows that remaining cold/wake spikes can still come from model runtime even when retrieval is fast.

## TTFT Group Results

| Test group | TTFT range | Average | Notes |
| --- | ---: | ---: | --- |
| Non-Targeted RAG | 2425-2816 ms | 2680 ms | Stable direct/specific RAG over technical report queries |
| Targeted RAG with `@mentions` | 2319-2517 ms | 2428 ms | Tagged document retrieval remained fast |
| Targeted Paper Follow-up | 2739-4600 ms | 3669 ms | Worst measured case was generator first-token bound |
| Chat Mode | 1561-1640 ms | 1590 ms | No retrieval path involved |
| Extended Multi-turn RAG | 2163-3087 ms | 2615 ms | 10-turn conversation stayed under 3.1s TTFT |
| Rapid Follow-ups | 2604-3615 ms | 3009 ms | Follow-up reuse worked without exceeding target |
| Indexed Document Coverage | 2409-2869 ms | 2584 ms | Multi-document tagged coverage stayed stable |

Worst measured turn:

```text
Query: What is @Qlora_Paper.pdf paper about?
TTFT: 4600 ms
Backend: 3579 ms
Intent: specific_doc_rag
Sources: 2
Timings: planner=3ms | retriever=42ms | generator=start51ms/first3528ms
Retrieval: total=39ms ready=0ms search=25ms emb=0ms vec=10ms candidates=13 fallback=False
```

Best measured turn:

```text
Query: What is the capital of Japan?
TTFT: 1561 ms
Backend: 557 ms
Intent: chat
Sources: 0
Timings: planner=3ms | generator=start8ms/first549ms
```

## Semantic and Context Coverage

The semantic/context test validated behavior that had previously been fragile:

```text
[PASS] targeted_leave_followup_and_correction turn 1
[PASS] targeted_leave_followup_and_correction turn 2
[PASS] targeted_leave_followup_and_correction turn 3
[PASS] targeted_paper_followup turn 1
[PASS] targeted_paper_followup turn 2
[PASS] technical_report_followup_no_repetition turn 1
[PASS] technical_report_followup_no_repetition turn 2
[PASS] technical_report_followup_no_repetition turn 3
[PASS] topic_shift_from_leave_to_transformer turn 1
[PASS] topic_shift_from_leave_to_transformer turn 2
[PASS] chat_escape_from_rag_context turn 1
[PASS] chat_escape_from_rag_context turn 2
[PASS] complex_compare turn 1
```

Coverage areas:

- Tagged document grounding, including `@LeaveAtaGlance.pdf`, `@Qlora_Paper.pdf`, `@TECHNICAL_REPORT_V8.pdf`, `@FAQ_LTDP_28Dec11.pdf`.
- Follow-up resolution where the user asks "who are the authors" after tagging QLoRA.
- Correction handling where the user says "I meant in LeaveAtaGlance.pdf".
- Topic drift from leave rules to transformer attention.
- Escape from RAG context back to normal chat mode.
- Repetition regression check for technical report follow-ups.
- Cross-document comparison between FAQ and leave rules.

## Root-Cause Latency Findings

The latest measured slow paths were not retrieval dominated.

Evidence:

- Worst measured query had retrieval total `39 ms` and generator first-token `3528 ms`.
- The excluded warmup outlier had retrieval `293 ms` and generator first-token `46723 ms`.
- Typical embedding calls during measured RAG turns were around `173-368 ms`.
- Typical vector search/gather/post-processing stayed in the low tens to low hundreds of milliseconds.

Conclusion:

Retrieval-layer jitter was substantially reduced. Remaining large spikes are primarily from model runtime first-token behavior, not Chroma/vector retrieval or embedding latency.

## Commands to Recreate or Verify

Run from the project root:

```powershell
cd C:\Users\Nayan\Desktop\RAG_Chat_IPRv1.5
```

Start an isolated backend on port `8019`:

```powershell
$port=8019
$existing = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existing) { Stop-Process -Id $existing.OwningProcess -Force; Start-Sleep -Seconds 1 }
$out = Join-Path (Get-Location) 'ttft_backend_8019_rootfix.log'
$err = Join-Path (Get-Location) 'ttft_backend_8019_rootfix.err'
Start-Process -FilePath '.\.venv\Scripts\python.exe' `
  -ArgumentList @('-m','uvicorn','backend.app:app','--host','127.0.0.1','--port','8019') `
  -WorkingDirectory (Get-Location) `
  -RedirectStandardOutput $out `
  -RedirectStandardError $err `
  -WindowStyle Hidden
```

Check backend/model readiness:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8019/api/status -TimeoutSec 20 | ConvertTo-Json -Depth 6
```

Run semantic/context validation:

```powershell
$env:SEMANTIC_API_BASE='http://127.0.0.1:8019'
$env:SEMANTIC_EVAL_OUTPUT='semantic_context_eval_8019_rootfix.json'
.\.venv\Scripts\python.exe test_semantic_context.py *> semantic_context_eval_8019_rootfix.log
```

Extract semantic/context summary:

```powershell
Select-String -LiteralPath semantic_context_eval_8019_rootfix.log `
  -Pattern "SUMMARY|Scenarios:|Turns:|Checks:|Failed turns:|Transcript|\[FAIL\]"
```

Run TTFT validation:

```powershell
$env:TTFT_API_BASE='http://127.0.0.1:8019'
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe test_ttft.py *> ttft_8019_rootfix.log
```

Extract high-level TTFT summary:

```powershell
Select-String -LiteralPath ttft_8019_rootfix.log `
  -Pattern "TTFT range|Worst 5 TTFTs|Target:|TARGET MET|Grounding warnings"
```

Parse measured TTFT stats exactly as reported here:

```powershell
@'
import re
from pathlib import Path

p = Path("ttft_8019_rootfix.log")
text = ""
for enc in ("utf-16", "utf-8", "utf-8-sig"):
    try:
        candidate = p.read_text(encoding=enc, errors="ignore")
    except Exception:
        continue
    if "Turn" in candidate and len(candidate.strip()) > 100:
        text = candidate
        break
if not text:
    text = p.read_text(errors="ignore")

rows = []
current = None
for line in text.splitlines():
    m = re.search(
        r"Turn\s+(\d+) \| (\w+)\s+\| TTFT\s+(\d+)ms \| Backend\s+(\d+)ms \| Total\s+(\d+)ms \|\s+([^|]+?)\s+\| src=(\d+) \| (.*)",
        line,
    )
    if m:
        current = {
            "turn": int(m.group(1)),
            "mode": m.group(2),
            "ttft": int(m.group(3)),
            "backend": int(m.group(4)),
            "total": int(m.group(5)),
            "intent": m.group(6).strip(),
            "src": int(m.group(7)),
            "query": m.group(8).strip(),
            "timings": None,
            "retrieval": None,
        }
        rows.append(current)
        continue
    if current and "Timings:" in line:
        current["timings"] = line.strip()
    if current and "Retrieval:" in line:
        current["retrieval"] = line.strip()

measured = rows[2:]
vals = [r["ttft"] for r in measured]
best = min(measured, key=lambda r: r["ttft"])
worst = max(measured, key=lambda r: r["ttft"])

print("measured_count", len(vals))
print("avg_ms", round(sum(vals) / len(vals)))
print("best_ms", best["ttft"], best["query"])
print("worst_ms", worst["ttft"], worst["query"])
print("under_5s", sum(v <= 5000 for v in vals), "/", len(vals))
print("under_7s", sum(v <= 7000 for v in vals), "/", len(vals))
print("worst_timings", worst["timings"])
print("worst_retrieval", worst["retrieval"])
'@ | .\.venv\Scripts\python.exe -
```

Stop the isolated backend:

```powershell
$conn = Get-NetTCPConnection -LocalPort 8019 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force }
```

## Acceptance Criteria Used

- Semantic/context judge must pass all checks.
- Tagged-document follow-ups must preserve the correct target document.
- Topic shifts must not be overpowered by previous context.
- Normal chat must escape RAG when the user asks a general chat question.
- Measured average TTFT should be around `3s`.
- Worst measured TTFT should stay below `5-7s`.
- Prompt/prefix caching behavior must not be broken by retrieval or prompt-shape changes.
- Retrieval accuracy and response grounding must not regress while optimizing latency.

## Final Result

This run is production-candidate for the retrieval and chat-response path under the tested IPR HPC Ollama environment:

```text
Semantic/context: PASS
TTFT: PASS
Measured avg TTFT: 2618 ms
Measured worst TTFT: 4600 ms
Measured best TTFT: 1561 ms
Grounding warnings: none
```

