import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

API_BASE = os.getenv("SEMANTIC_API_BASE", os.getenv("TTFT_API_BASE", "http://localhost:8000"))
OUTPUT_PATH = Path(os.getenv("SEMANTIC_EVAL_OUTPUT", "semantic_context_eval_latest.json"))


def compact(text: str, limit: int = 700) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[:limit] + "..."


def source_filenames(sources: list[str]) -> list[str]:
    names = []
    for src in sources or []:
        match = re.search(r"(?:Source|Q&A):\s*([^|\]\n]+)", src)
        if match:
            names.append(match.group(1).strip())
    return names


@dataclass
class TurnSpec:
    query: str
    mode: str = "auto"
    expected_sources: list[str] = field(default_factory=list)
    forbidden_sources: list[str] = field(default_factory=list)
    expected_intents: set[str] = field(default_factory=set)
    required_terms: list[str] = field(default_factory=list)
    forbidden_terms: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class Scenario:
    name: str
    turns: list[TurnSpec]


class SemanticContextEval:
    def __init__(self, scenario_name: str):
        safe_name = re.sub(r"[^a-z0-9]+", "_", scenario_name.lower()).strip("_")
        self.session_id = f"semantic_{safe_name}_{int(time.time())}"
        self.results = []

    async def send_message(self, spec: TurnSpec) -> dict:
        import httpx

        payload = {"message": spec.query, "session_id": self.session_id, "mode": spec.mode}
        request_start = time.monotonic()
        full_response = ""
        status_events = []
        metadata = {}
        first_token_ms = 0

        try:
            async with httpx.AsyncClient(timeout=180) as client:
                async with client.stream("POST", f"{API_BASE}/api/chat/stream", json=payload) as resp:
                    current_event = None
                    async for raw_line in resp.aiter_lines():
                        line = raw_line.strip()
                        if not line:
                            continue
                        if line.startswith("event: "):
                            current_event = line[7:]
                            continue
                        if not line.startswith("data: ") or not current_event:
                            continue

                        data = line[6:]
                        if current_event == "status":
                            status_events.append(data)
                        elif current_event == "token":
                            if not first_token_ms:
                                first_token_ms = int((time.monotonic() - request_start) * 1000)
                            try:
                                full_response += json.loads(data)
                            except Exception:
                                full_response += data
                        elif current_event == "end":
                            try:
                                metadata = json.loads(data)
                            except Exception:
                                metadata = {"raw_end": data}
                        elif current_event == "error":
                            metadata["error"] = data
        except Exception as exc:
            metadata["stream_error"] = str(exc)

        result = {
            "query": spec.query,
            "mode": spec.mode,
            "response": full_response,
            "intent": metadata.get("intent", "?"),
            "sources": metadata.get("sources", []),
            "source_files": source_filenames(metadata.get("sources", [])),
            "targeted_docs": metadata.get("targeted_docs", []),
            "ttft_ms": first_token_ms,
            "backend_ttft_ms": metadata.get("ttft_ms"),
            "total_ms": int((time.monotonic() - request_start) * 1000),
            "timings": metadata.get("timings", {}),
            "retrieval_metrics": metadata.get("retrieval_metrics", {}),
            "status_events": status_events,
            "error": metadata.get("error") or metadata.get("stream_error"),
            "checks": self.evaluate(spec, full_response, metadata),
            "notes": spec.notes,
        }
        self.results.append(result)
        return result

    def evaluate(self, spec: TurnSpec, response: str, metadata: dict) -> list[dict]:
        checks = []
        response_lower = (response or "").lower()
        files = source_filenames(metadata.get("sources", []))
        intent = metadata.get("intent", "?")

        def add(name: str, passed: bool, detail: str):
            checks.append({"name": name, "passed": bool(passed), "detail": detail})

        add("no_stream_error", not (metadata.get("error") or metadata.get("stream_error")), metadata.get("error") or metadata.get("stream_error") or "ok")
        min_answer_len = 10 if intent == "chat" else 40
        add("non_empty_answer", len((response or "").strip()) >= min_answer_len, f"response_len={len(response or '')}, min={min_answer_len}")

        if spec.expected_intents:
            add("expected_intent", intent in spec.expected_intents, f"intent={intent}, expected={sorted(spec.expected_intents)}")
        for expected in spec.expected_sources:
            add("expected_source", expected in files, f"expected={expected}, files={files[:8]}")
        for forbidden in spec.forbidden_sources:
            add("forbidden_source_absent", forbidden not in files, f"forbidden={forbidden}, files={files[:8]}")
        for term in spec.required_terms:
            add("required_term", term.lower() in response_lower, f"term={term}")
        for term in spec.forbidden_terms:
            add("forbidden_term_absent", term.lower() not in response_lower, f"term={term}")

        return checks


SCENARIOS = [
    Scenario(
        name="targeted_leave_followup_and_correction",
        turns=[
            TurnSpec(
                query="What does @LeaveAtaGlance.pdf tell in brief? List important points.",
                expected_sources=["LeaveAtaGlance.pdf"],
                forbidden_sources=["attention_is_all_you_need.pdf", "Qlora_Paper.pdf"],
                expected_intents={"specific_doc_rag"},
                required_terms=["leave"],
                notes="Initial explicit target should retrieve leave rules.",
            ),
            TurnSpec(
                query="some other gotchas or catches that we need to keep in mind",
                expected_sources=["LeaveAtaGlance.pdf"],
                forbidden_sources=["attention_is_all_you_need.pdf", "Qlora_Paper.pdf"],
                expected_intents={"specific_doc_rag"},
                required_terms=["leave"],
                notes="Vague follow-up should stay in the recent LeaveAtaGlance target, not drift to transformer docs.",
            ),
            TurnSpec(
                query="I meant in LeaveAtaGlance.pdf",
                expected_sources=["LeaveAtaGlance.pdf"],
                forbidden_sources=["attention_is_all_you_need.pdf", "Qlora_Paper.pdf"],
                expected_intents={"specific_doc_rag"},
                required_terms=["leave"],
                notes="Target correction should reuse the previous substantive question with the corrected file.",
            ),
        ],
    ),
    Scenario(
        name="targeted_paper_followup",
        turns=[
            TurnSpec(
                query="What is @Qlora_Paper.pdf paper about?",
                expected_sources=["Qlora_Paper.pdf"],
                forbidden_sources=["LeaveAtaGlance.pdf"],
                expected_intents={"specific_doc_rag"},
                required_terms=["QLoRA"],
            ),
            TurnSpec(
                query="who are the authors",
                expected_sources=["Qlora_Paper.pdf"],
                forbidden_sources=["LeaveAtaGlance.pdf"],
                expected_intents={"specific_doc_rag"},
                required_terms=["Dettmers", "Pagnoni", "Holtzman", "Zettlemoyer"],
                notes="Short follow-up must retain the prior targeted paper context.",
            ),
        ],
    ),
    Scenario(
        name="topic_shift_from_leave_to_transformer",
        turns=[
            TurnSpec(
                query="What does @LeaveAtaGlance.pdf say about Casual Leave?",
                expected_sources=["LeaveAtaGlance.pdf"],
                expected_intents={"specific_doc_rag"},
                required_terms=["Casual Leave"],
            ),
            TurnSpec(
                query="explain transformer attention architecture",
                expected_sources=["attention_is_all_you_need.pdf"],
                forbidden_sources=["LeaveAtaGlance.pdf"],
                expected_intents={"direct_rag", "specific_doc_rag"},
                required_terms=["attention"],
                notes="Clear subject shift should not be overpowered by previous leave target.",
            ),
        ],
    ),
    Scenario(
        name="chat_escape_from_rag_context",
        turns=[
            TurnSpec(
                query="What does @FAQ_LTDP_28Dec11.pdf say about eligibility?",
                expected_sources=["FAQ_LTDP_28Dec11.pdf"],
                expected_intents={"specific_doc_rag"},
                required_terms=["eligible"],
            ),
            TurnSpec(
                query="What is the capital of Japan?",
                expected_sources=[],
                forbidden_sources=["FAQ_LTDP_28Dec11.pdf", "LeaveAtaGlance.pdf"],
                expected_intents={"chat"},
                required_terms=["Tokyo"],
                notes="General chat should not stay in RAG context.",
            ),
        ],
    ),
    Scenario(
        name="complex_compare",
        turns=[
            TurnSpec(
                query="Compare @FAQ_LTDP_28Dec11.pdf and @LeaveAtaGlance.pdf on eligibility and leave-related rules.",
                expected_sources=["FAQ_LTDP_28Dec11.pdf", "LeaveAtaGlance.pdf"],
                expected_intents={"specific_doc_rag"},
                required_terms=["eligibility", "leave"],
                notes="Multi-target query should retrieve both named documents.",
            ),
        ],
    ),
]


def print_result(scenario_name: str, idx: int, result: dict) -> None:
    failed = [c for c in result["checks"] if not c["passed"]]
    status = "PASS" if not failed else "FAIL"
    print(f"\n[{status}] {scenario_name} turn {idx}: {result['query']}")
    print(f"  intent={result['intent']} target={result['targeted_docs']} sources={result['source_files'][:6]}")
    print(f"  ttft={result['ttft_ms']}ms backend={result['backend_ttft_ms']}ms total={result['total_ms']}ms")
    if result.get("retrieval_metrics"):
        metrics = result["retrieval_metrics"]
        print(
            "  retrieval="
            f"total:{metrics.get('total_ms')} ready:{metrics.get('readiness_ms')} "
            f"emb:{metrics.get('embedding_ms')} vec:{metrics.get('vector_ms')} "
            f"candidates:{metrics.get('candidate_count')}"
        )
    print(f"  answer={compact(result['response'])}")
    for check in failed:
        print(f"  - {check['name']}: {check['detail']}")


async def run_all() -> int:
    import httpx

    print("=" * 80)
    print("  SEMANTIC + CONTEXT ROUTING EVALUATION")
    print(f"  API: {API_BASE}")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    try:
        async with httpx.AsyncClient() as client:
            status = await client.get(f"{API_BASE}/api/status", timeout=10)
        payload = status.json()
        print(f"  Server: {payload.get('status')} | Python: {payload.get('python_version')}")
    except Exception as exc:
        print(f"  Server check failed: {exc}")
        return 2

    all_results = []
    total_checks = 0
    failed_checks = 0
    failed_turns = 0

    for scenario in SCENARIOS:
        runner = SemanticContextEval(scenario.name)
        scenario_result = {"name": scenario.name, "session_id": runner.session_id, "turns": []}
        for idx, turn in enumerate(scenario.turns, start=1):
            result = await runner.send_message(turn)
            scenario_result["turns"].append(result)
            print_result(scenario.name, idx, result)
            total_checks += len(result["checks"])
            turn_failures = [check for check in result["checks"] if not check["passed"]]
            failed_checks += len(turn_failures)
            if turn_failures:
                failed_turns += 1
        all_results.append(scenario_result)

    OUTPUT_PATH.write_text(json.dumps(all_results, indent=2), encoding="utf-8")

    print("\n" + "=" * 80)
    print("  SUMMARY")
    print("=" * 80)
    print(f"  Scenarios: {len(SCENARIOS)}")
    print(f"  Turns: {sum(len(s.turns) for s in SCENARIOS)}")
    print(f"  Checks: {total_checks - failed_checks}/{total_checks} passed")
    print(f"  Failed turns: {failed_turns}")
    print(f"  Transcript: {OUTPUT_PATH}")
    print("  Judge note: review FAIL/WARN turns manually for answer quality before TTFT.")
    return 1 if failed_turns else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_all()))
