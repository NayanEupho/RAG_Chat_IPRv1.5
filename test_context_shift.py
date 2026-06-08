import asyncio

from test_ttft import TTFTTest, source_filenames


async def main():
    tester = TTFTTest()
    turns = [
        ("Hello, just answer normally for now.", "chat"),
        ("What is the capital of Japan?", "auto"),
        ("Now use the technical report: what is the system architecture?", "auto"),
        ("What technologies does it use?", "auto"),
        ("Switch to the FAQ document. Who is eligible for LTDP?", "auto"),
        ("Tell me more about that eligibility from the same FAQ.", "auto"),
        ("Now back to the technical report. What limitations are mentioned?", "auto"),
        ("Forget the docs for a moment: give me one short fact about Mars.", "auto"),
        ("Return to FAQ_LTDP_28Dec11.pdf: what does it say about vigilance clearance?", "auto"),
    ]

    for text, mode in turns:
        await tester.send_message(text, mode=mode)

    print("\nCONTEXT SHIFT REVIEW")
    for idx, result in enumerate(tester.results, 1):
        sources = source_filenames(result["source_items"]) or "none"
        response = result["response"][:500].replace("\n", " ")
        timings = result.get("timings") or {}
        nodes = timings.get("nodes") or {}
        timing_parts = []
        for name in ["planner", "router", "rewriter", "retriever", "generator"]:
            data = nodes.get(name)
            if not data:
                continue
            if data.get("first_token_after_start_ms") is not None:
                timing_parts.append(f"{name}:first={data['first_token_after_start_ms']}ms")
            elif data.get("duration_ms") is not None:
                timing_parts.append(f"{name}:{data['duration_ms']}ms")
        print(
            f"{idx:02d}. mode={result['mode']} intent={result['intent']} "
            f"ttft={result['ttft_ms']}ms src={sources}"
        )
        if timing_parts:
            print(f"    Timings: {' | '.join(timing_parts)}")
        print(f"    Q: {result['query']}")
        print(f"    A: {response}")


if __name__ == "__main__":
    asyncio.run(main())
