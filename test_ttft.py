import asyncio
import json
import time
import sys
import os
import re
from pathlib import Path

API_BASE = "http://localhost:8000"


def compact(text, limit=900):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[:limit] + "..."


def load_reference_corpus():
    corpus = {}
    for path in list(Path("generated_doc_md").glob("*.md")) + list(Path("generated_doc_md").rglob("selected.md")):
        try:
            corpus[str(path)] = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
    return corpus


def source_filenames(sources):
    names = []
    for src in sources or []:
        match = re.search(r"(?:Source|Q&A):\s*([^|\]\n]+)", src)
        if match:
            names.append(match.group(1).strip())
    return names


def score_grounding(query, response, sources, corpus):
    q_tokens = {
        t for t in re.findall(r"[a-z0-9][a-z0-9&./-]*", query.lower())
        if len(t) > 2 and t not in {"the", "and", "for", "what", "does", "about", "tell", "more", "with", "from"}
    }
    source_text = "\n".join(sources or "")
    corpus_text = "\n".join(corpus.values())
    source_hits = sum(1 for t in q_tokens if t in source_text.lower())
    corpus_hits = sum(1 for t in q_tokens if t in corpus_text.lower())
    response_hits = sum(1 for t in q_tokens if t in (response or "").lower())
    unsupported_warning = bool(
        sources and response and len(response) > 80 and response_hits == 0 and source_hits > 0
    )
    return {
        "query_terms": len(q_tokens),
        "source_hits": source_hits,
        "corpus_hits": corpus_hits,
        "response_hits": response_hits,
        "unsupported_warning": unsupported_warning,
    }


def expected_source_for_query(query):
    q = query.lower()
    if "@faq_ltdp_28dec11.pdf" in q or "ltdp" in q:
        return "FAQ_LTDP_28Dec11.pdf"
    if "@leaveataglance.pdf" in q or "casual leave" in q or "earned leave" in q or "pension" in q:
        return "LeaveAtaGlance.pdf"
    if "@technical_report_v8.pdf" in q or "technical report" in q or "devops agent" in q:
        return "TECHNICAL_REPORT_V8.pdf"
    if "@design and development.pdf" in q or "gigw" in q or "website" in q:
        return "Design and Development.pdf"
    if "@adg-1.pdf" in q or "three interactive design themes" in q or "single source of truth" in q:
        return "ADG-1.pdf"
    return None

class TTFTTest:
    def __init__(self, session_prefix="ttft_test"):
        self.session_id = f"{session_prefix}_{int(time.time())}"
        self.turn_count = 0
        self.results = []

    async def send_message(self, text, mode="auto", session_id=None):
        sid = session_id or self.session_id
        self.turn_count += 1
        turn = self.turn_count

        import httpx
        payload = {"message": text, "session_id": sid, "mode": mode}
        ttft = None
        request_start = time.monotonic()
        full_response = ""
        status_events = []
        end_metadata = {}

        try:
            async with httpx.AsyncClient(timeout=180) as client:
                async with client.stream("POST", f"{API_BASE}/api/chat/stream",
                                         json=payload) as resp:
                    current_event = None
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        if line.startswith("event: "):
                            current_event = line[7:]
                        elif line.startswith("data: "):
                            data = line[6:]
                            if current_event == "status":
                                status_events.append(data)
                            elif current_event == "token":
                                if ttft is None:
                                    ttft = time.monotonic() - request_start
                                try:
                                    token = json.loads(data)
                                    full_response += token
                                except:
                                    full_response += data
                            elif current_event == "end":
                                try:
                                    end_metadata = json.loads(data)
                                except:
                                    end_metadata = {"raw": data}
                            elif current_event == "error":
                                end_metadata["error"] = data
        except Exception as e:
            end_metadata["stream_error"] = str(e)

        ttft_ms = int((ttft or 0) * 1000)
        backend_ttft = end_metadata.get("ttft_ms", 0)
        total_time = int((time.monotonic() - request_start) * 1000)

        result = {
            "turn": turn, "mode": mode, "text": text[:80],
            "query": text,
            "ttft_ms": ttft_ms, "backend_ttft_ms": backend_ttft,
            "total_ms": total_time,
            "intent": end_metadata.get("intent", "?"),
            "sources": len(end_metadata.get("sources", [])),
            "source_items": end_metadata.get("sources", []),
            "targeted_docs": end_metadata.get("targeted_docs", []),
            "timings": end_metadata.get("timings", {}),
            "retrieval_metrics": end_metadata.get("retrieval_metrics", {}),
            "response": full_response,
            "response_len": len(full_response),
            "status_count": len(status_events),
            "error": end_metadata.get("error") or end_metadata.get("stream_error"),
        }
        self.results.append(result)

        status_str = "ERR" if result["error"] else f"{result['intent']:>12}"
        print(f"  Turn {turn:>2} | {mode:<6} | TTFT {ttft_ms:>5}ms | Backend {backend_ttft:>5}ms | "
              f"Total {total_time:>5}ms | {status_str} | src={result['sources']} | "
              f"{result['text'][:50]}")
        print(f"    Response: {compact(full_response, 700)}")
        timings = result.get("timings") or {}
        nodes = timings.get("nodes") or {}
        if nodes:
            parts = []
            for name in ["planner", "router", "rewriter", "retriever", "generator"]:
                data = nodes.get(name)
                if not data:
                    continue
                duration = data.get("duration_ms")
                start = data.get("start_ms")
                first = data.get("first_token_after_start_ms")
                if first is not None:
                    parts.append(f"{name}=start{start}ms/first{first}ms")
                elif duration is not None:
                    parts.append(f"{name}={duration}ms")
            if parts:
                print(f"    Timings: {' | '.join(parts)}")
        retrieval_metrics = result.get("retrieval_metrics") or {}
        if retrieval_metrics:
            print(
                "    Retrieval: "
                f"total={retrieval_metrics.get('total_ms', '?')}ms "
                f"emb={retrieval_metrics.get('embedding_ms', '?')}ms "
                f"vec={retrieval_metrics.get('vector_ms', '?')}ms "
                f"candidates={retrieval_metrics.get('candidate_count', '?')} "
                f"fallback={retrieval_metrics.get('fallback_used', False)} "
                f"reason={retrieval_metrics.get('reason')}"
            )
        if result["source_items"]:
            print(f"    Sources: {', '.join(source_filenames(result['source_items'])[:5])}")
        sys.stdout.flush()
        return result

    def print_summary(self, label=""):
        if not self.results:
            return
        ttfts = [r["ttft_ms"] for r in self.results if r["ttft_ms"] > 0]
        if not ttfts:
            print(f"\n  [{label}] TTFT unavailable: no response tokens were streamed.")
            return
        print(f"\n  [{label}] TTFT range: {min(ttfts)}ms - {max(ttfts)}ms | "
              f"Avg: {sum(ttfts)//len(ttfts)}ms", end="")
        if len(ttfts) >= 2:
            impr = ((ttfts[0] - min(ttfts[1:])) / ttfts[0]) * 100 if ttfts[0] > 0 else 0
            print(f" | Cache improvement: {impr:.0f}%", end="")
        print()


async def run_all_tests():
    import httpx
    print("=" * 70)
    print("  TTFT COMPREHENSIVE TEST SUITE")
    print(f"  API: {API_BASE}")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Check server health
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{API_BASE}/api/status", timeout=5)
        status_payload = r.json()
        print(f"\n  Server: {status_payload.get('status', '?')} | Python: {status_payload.get('python_version', '?')}")
        if str(status_payload.get("python_version", "")).startswith("3.14"):
            print("  Server is running on Python 3.14. ChromaDB is incompatible here; restart with .venv Python 3.13 before TTFT testing.")
            return
    except Exception as e:
        print(f"\n  Server DOWN: {e}")
        return

    # Check documents
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{API_BASE}/api/documents")
        docs = r.json().get("documents", [])
        print(f"  Documents: {docs}")
    except Exception as e:
        print(f"  Docs check failed: {e}")
        docs = ["FAQ_LTDP_28Dec11.pdf"]

    # Warmup
    print("\n>>> WARMUP...")
    w = TTFTTest("warmup")
    await w.send_message("Hello", mode="auto")
    print()

    # =========================================================
    # TEST 1: Non-targeted RAG (single + multi-turn)
    # =========================================================
    print(">>> TEST 1: Non-Targeted RAG")
    t1 = TTFTTest("rag_free")
    await t1.send_message("What is the technical report about?", mode="auto")
    await t1.send_message("What technologies does it mention?", mode="auto")
    await t1.send_message("Summarize the key conclusions", mode="auto")
    t1.print_summary("Non-Targeted RAG")
    print()

    # =========================================================
    # TEST 2: Targeted RAG (@mentions)
    # =========================================================
    print(">>> TEST 2: Targeted RAG (@mentions)")
    faq_doc = [d for d in docs if "FAQ" in d][0] if docs else "FAQ_LTDP_28Dec11.pdf"
    t2 = TTFTTest("rag_mention")
    await t2.send_message(f"What does @{faq_doc} say about LTDP?", mode="auto")
    await t2.send_message("What are the eligibility criteria?", mode="auto")
    await t2.send_message("Tell me more details from it", mode="auto")
    t2.print_summary("Targeted RAG")
    print()

    # =========================================================
    # TEST 3: Chat mode
    # =========================================================
    print(">>> TEST 3: Chat Mode")
    t3 = TTFTTest("chat")
    await t3.send_message("Hello! How are you?", mode="chat")
    await t3.send_message("What is the capital of Japan?", mode="chat")
    await t3.send_message("Tell me a fun fact about Mars", mode="chat")
    t3.print_summary("Chat Mode")
    print()

    # =========================================================
    # TEST 4: Long Multi-turn (caching + possible summarization)
    # =========================================================
    print(">>> TEST 4: Extended Multi-turn RAG (10 turns)")
    t4 = TTFTTest("multiturn")
    queries = [
        "What is the technical report about?",
        "What technologies does it use?",
        "Explain the methodology discussed",
        "What are the main conclusions?",
        "Are there any limitations mentioned?",
        "What future work is suggested?",
        "Compare this with the FAQ document",
        "What is the LTDP policy about?",
        "Who is eligible for LTDP?",
        "What are the key benefits of LTDP?",
    ]
    for q in queries:
        await t4.send_message(q, mode="auto")
    t4.print_summary("Multi-Turn RAG")
    print()

    # =========================================================
    # TEST 5: Rapid follow-ups (tests cache reuse best)
    # =========================================================
    print(">>> TEST 5: Rapid Follow-ups")
    t5 = TTFTTest("followup")
    await t5.send_message("Explain the pension rules in detail", mode="auto")
    await t5.send_message("tell me more", mode="auto")
    await t5.send_message("what about eligibility criteria", mode="auto")
    await t5.send_message("summarize everything", mode="auto")
    t5.print_summary("Rapid Follow-ups")
    print()

    # =========================================================
    # TEST 6: Indexed document coverage
    # =========================================================
    print(">>> TEST 6: Indexed Document Coverage")
    coverage_queries = [
        ("ADG-1.pdf", "What does @ADG-1.pdf say is the purpose of the ADG document?"),
        ("Design and Development.pdf", "What does @Design and Development.pdf require for the IPR website design and development work?"),
        ("FAQ_LTDP_28Dec11.pdf", "What does @FAQ_LTDP_28Dec11.pdf say about LTDP eligibility?"),
        ("LeaveAtaGlance.pdf", "What does @LeaveAtaGlance.pdf say about Casual Leave and Extra Ordinary Leave?"),
        ("TECHNICAL_REPORT_V8.pdf", "What does @TECHNICAL_REPORT_V8.pdf say about the DevOps Agent architecture?"),
    ]
    t6 = TTFTTest("doc_coverage")
    for expected_doc, q in coverage_queries:
        if expected_doc in docs:
            result = await t6.send_message(q, mode="auto")
            result["expected_source"] = expected_doc
    t6.print_summary("Document Coverage")
    print()

    # =========================================================
    # OVERALL SUMMARY
    # =========================================================
    print("=" * 70)
    print("  OVERALL RESULTS")
    print("=" * 70)
    all_results = [t1, t2, t3, t4, t5, t6]
    all_ttfts = [r for tr in all_results for r in tr.results if r["ttft_ms"] > 0]

    ttft_values = [r["ttft_ms"] for r in all_ttfts]
    print(f"\n  Total queries: {len(all_ttfts)}")
    print(f"  TTFT: {min(ttft_values)}ms - {max(ttft_values)}ms | Avg: {sum(ttft_values)//len(ttft_values)}ms")

    worst = sorted(all_ttfts, key=lambda x: x["ttft_ms"], reverse=True)[:5]
    print(f"\n  Worst 5 TTFTs:")
    for r in worst:
        print(f"    {r['ttft_ms']:>6}ms | {r['mode']:<8} | intent={r['intent']:<14} | \"{r['text']}\"")

    # Prefix caching analysis
    print(f"\n  Prefix Caching:")
    for label, tr in [("Non-Targeted RAG", t1), ("Targeted RAG", t2),
                       ("Chat", t3), ("Multi-Turn", t4), ("Follow-ups", t5),
                       ("Document Coverage", t6)]:
        ttfts = [r["ttft_ms"] for r in tr.results if r["ttft_ms"] > 0]
        if len(ttfts) >= 2:
            impr = ((ttfts[0] - min(ttfts[1:])) / ttfts[0]) * 100 if ttfts[0] > 0 else 0
            status = "WORKING" if impr > 15 else ("PARTIAL" if impr > 5 else "WEAK")
            print(f"    {label:<20}: Turn1={ttfts[0]}ms -> Best={min(ttfts[1:]):>5}ms ({impr:.0f}% {status})")

    # Target check
    under_5 = sum(1 for t in all_ttfts if t["ttft_ms"] <= 5000)
    under_7 = sum(1 for t in all_ttfts if t["ttft_ms"] <= 7000)
    over_7 = sum(1 for t in all_ttfts if t["ttft_ms"] > 7000)
    print(f"\n  Target: 5-7s worst case")
    print(f"    <=5s:  {under_5}/{len(all_ttfts)} ({under_5*100//len(all_ttfts)}%)")
    print(f"    <=7s:  {under_7}/{len(all_ttfts)} ({under_7*100//len(all_ttfts)}%)")
    print(f"    >7s:   {over_7}/{len(all_ttfts)} ({over_7*100//len(all_ttfts)}%)")

    if over_7 == 0:
        print(f"  [OK] TARGET MET: All queries under 7s!")
    elif under_7 >= len(all_ttfts) * 0.8:
        print(f"  [OK] MOSTLY MET: {under_7*100//len(all_ttfts)}% under 7s")
    else:
        print(f"  [FAIL] NOT MET: {under_7*100//len(all_ttfts)}% under 7s")

    # =========================================================
    # RESPONSE AND GROUNDING REVIEW
    # =========================================================
    print("\n" + "=" * 70)
    print("  RESPONSE / GROUNDING REVIEW")
    print("=" * 70)
    corpus = load_reference_corpus()
    print(f"\n  Reference markdown files loaded: {len(corpus)}")
    if corpus:
        for name in sorted(corpus)[:8]:
            print(f"    - {name}")

    all_turns = [r for tr in all_results for r in tr.results]
    warnings = []
    for idx, r in enumerate(all_turns, start=1):
        score = score_grounding(r["query"], r["response"], r["source_items"], corpus)
        expected_source = r.get("expected_source") or expected_source_for_query(r["query"])
        retrieved_sources = source_filenames(r["source_items"])
        if r["intent"] != "chat" and r["sources"] == 0:
            warnings.append((idx, "RAG intent returned no sources", r))
        if expected_source and expected_source not in retrieved_sources:
            warnings.append((idx, f"Expected source not retrieved: {expected_source}", r))
        if score["unsupported_warning"]:
            warnings.append((idx, "Response may not overlap query/source terms", r))

        print(f"\n  [{idx:02d}] {r['intent']} | TTFT {r['ttft_ms']}ms | {r['query']}")
        print(f"       Source files: {', '.join(retrieved_sources) or 'none'}")
        if expected_source:
            print(f"       Expected source: {expected_source}")
        print(
            "       Term hits: "
            f"query_terms={score['query_terms']} "
            f"source={score['source_hits']} "
            f"corpus={score['corpus_hits']} "
            f"response={score['response_hits']}"
        )
        print(f"       Answer: {compact(r['response'], 1100)}")

    print("\n  Grounding warnings:")
    if warnings:
        for idx, reason, r in warnings:
            print(f"    - Turn {idx}: {reason} | {r['query']}")
    else:
        print("    none")


def main():
    asyncio.run(run_all_tests())
    print("\nDone.")

if __name__ == "__main__":
    main()
