from backend.graph.state import AgentState
from backend.llm.client import OllamaClientWrapper
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from backend.config import get_config
import logging
import re

logger = logging.getLogger(__name__)

_GENERATOR_SYSTEM_PROMPT = (
    "You are a helpful and intelligent AI assistant with access to a Knowledge Base.\n"
    "Session Awareness: You have access to the conversation history. Maintain continuity.\n"
    "Adaptive Knowledge Usage:\n"
    "1. If a <knowledge_base> is provided, use it ONLY if it is directly relevant to the user's latest query.\n"
    "2. If the provided documents are irrelevant to the user's question, ignore them and answer naturally or state that the info isn't in your files.\n"
    "3. Always prioritize a natural conversational flow and factual accuracy.\n"
    "STYLE: Be concise but complete. For simple chat, answer briefly. For RAG answers, include all directly relevant facts from the provided evidence. If the user asks for more detail, expand with structured bullets and cite the relevant document sections. Avoid filler, but do not omit useful evidence just to be short.\n"
    "CITATIONS: When answering from <docs>, add inline numeric citations like [1] or [2] after document-grounded claims. The citation number must refer to the retrieved chunk order shown in <docs>. Do not cite general guidance or inference unless it is explicitly tied to a retrieved chunk.\n"
    "GROUNDING: Clearly separate documented facts from general guidance. If a rule, exception, number, benefit, limitation, or procedure is explicit in the provided evidence, present it as document-grounded. If you add helpful context using phrases like typically, generally, usually, likely, implies, or suggests, label it as general guidance or an inference and say it is not explicitly stated in the provided evidence."
)

_SUMMARY_SYSTEM_PROMPT = (
    "Summarize the conversation exchange. Keep it concise (2-4 sentences). "
    "Capture key facts, questions, and answers that may be referenced later. "
    "Focus on information content, not pleasantries."
)

_SUMMARY_PREFIX = "[Stable summary of earlier conversation]"


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / 4))


def _get_budgets(intent: str = "chat"):
    cfg = get_config()
    total_window = cfg.model_context_window or 200000
    output_reserve = int(total_window * 0.20)
    fixed_prompt_reserve = int(total_window * 0.05)
    safety_margin = int(total_window * 0.05)
    usable_input = max(512, total_window - output_reserve - fixed_prompt_reserve - safety_margin)

    if intent in ["direct_rag", "specific_doc_rag"]:
        summary_budget = min(768, max(128, int(usable_input * 0.10)))
        recent_history_budget = min(1536, max(256, int(usable_input * 0.20)))
        docs_budget = min(4096, max(1024, int(usable_input * 0.40)))
        metadata_budget = max(128, usable_input - summary_budget - recent_history_budget - docs_budget)
    else:
        summary_budget = 0
        recent_history_budget = min(2048, max(512, int(usable_input * 0.50)))
        docs_budget = 0
        metadata_budget = max(128, usable_input - recent_history_budget)

    history_budget = summary_budget + recent_history_budget
    return {
        "total_window": total_window,
        "output_reserve": output_reserve,
        "fixed_prompt_reserve": fixed_prompt_reserve,
        "safety_margin": safety_margin,
        "usable_input": usable_input,
        "history_budget": history_budget,
        "summary_budget": summary_budget,
        "recent_history_budget": recent_history_budget,
        "docs_budget": docs_budget,
        "metadata_budget": metadata_budget,
    }


def select_docs_within_budget(docs: list, max_tokens: int) -> list:
    selected = []
    token_count = 0
    for doc in docs:
        doc_tokens = estimate_tokens(doc)
        if token_count + doc_tokens > max_tokens:
            if selected:
                break
            truncate_chars = max_tokens * 4
            selected.append(doc[:truncate_chars] + "\n[...truncated for length...]")
            break
        selected.append(doc)
        token_count += doc_tokens
    return selected


def _is_table_source(doc: str) -> bool:
    return "Table Row:" in doc or "chunk_kind: table_row" in doc or "[ChunkKind: table_row]" in doc


def _compact_table_doc(doc: str, max_chars: int = 1400) -> str:
    """
    Keep table-row evidence compact for low TTFT.

    Table-aware ingestion already made each row atomic, so the generator does
    not need several thousand characters from neighboring rows.
    """
    text = re.sub(r"\n{3,}", "\n\n", doc or "").strip()
    if len(text) <= max_chars:
        return text
    head = text[:max_chars]
    return head.rsplit("\n", 1)[0].rstrip() + "\n[...truncated table row...]"


def prepare_docs_for_generation(docs: list, docs_budget: int) -> list:
    if not docs:
        return []
    table_docs = [doc for doc in docs if _is_table_source(doc)]
    if table_docs and len(table_docs) >= max(1, len(docs) // 2):
        compacted = [_compact_table_doc(doc, max_chars=900) for doc in table_docs[:2]]
        return select_docs_within_budget(compacted, min(docs_budget, 700))
    return select_docs_within_budget(docs, docs_budget)


def _summarize_messages_locally(prev_summary: str, dropped_messages: list, max_chars: int = 1800) -> str:
    """
    Deterministic compaction for prefix-cache stability.

    This intentionally avoids an LLM summarization call on the hot path. The
    summary changes only when compaction is required, then remains byte-stable
    across subsequent turns until the retained tail exceeds budget again.
    """
    lines = []
    if prev_summary:
        cleaned = prev_summary.replace(_SUMMARY_PREFIX, "").strip(" :\n")
        if cleaned:
            lines.append(cleaned)

    for msg in dropped_messages:
        role = "User" if isinstance(msg, HumanMessage) else "Assistant"
        content = re.sub(r"\s+", " ", msg.content).strip()
        if not content:
            continue
        lines.append(f"{role}: {content[:420]}")

    summary = "\n".join(lines)
    if len(summary) > max_chars:
        summary = summary[-max_chars:]
        first_break = summary.find("\n")
        if first_break > 0:
            summary = summary[first_break + 1:]
    return summary.strip()


def _build_message_list(messages, history_budget, summary, summary_budget=None, recent_history_budget=None):
    total_history = sum(estimate_tokens(m.content) for m in messages)
    if total_history <= history_budget:
        return list(messages), False, summary

    summary_budget = summary_budget if summary_budget is not None else max(128, int(history_budget * 0.30))
    keep_budget = recent_history_budget if recent_history_budget is not None else max(128, history_budget - summary_budget)
    keep_budget = max(128, keep_budget)
    kept = []
    kept_tokens = 0
    kept_start = len(messages)
    for m in reversed(messages):
        tok = estimate_tokens(m.content)
        if kept_tokens + tok <= keep_budget:
            kept.insert(0, m)
            kept_tokens += tok
            kept_start -= 1
        else:
            break

    dropped = list(messages[:kept_start])
    next_summary = _summarize_messages_locally(summary, dropped, max_chars=summary_budget * 4)
    condensed = []
    summary_tokens = estimate_tokens(next_summary) if next_summary else 0
    if next_summary and summary_tokens < history_budget:
        condensed.append(SystemMessage(content=f"{_SUMMARY_PREFIX}:\n{next_summary}"))
    condensed.extend(kept)
    return condensed, True, next_summary


def _cache_signature(final_messages: list[dict]) -> str:
    prefix = "\n".join(f"{m['role']}:{m['content']}" for m in final_messages[:-1])
    import hashlib
    return hashlib.md5(prefix.encode("utf-8", errors="ignore")).hexdigest()[:12]


async def _update_summary(prev_summary: str, query: str, answer: str) -> str:
    try:
        client = OllamaClientWrapper.get_chat_model()
        exchange = f"User: {query}\nAssistant: {answer}"
        prompt = f"Previous summary: {prev_summary}\nNew exchange:\n{exchange}\n\nUpdated summary:" if prev_summary else f"Conversation:\n{exchange}\n\nSummary:"
        response = await client.ainvoke([
            {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ])
        summary = response.content.strip()
        return summary[:500] if len(summary) > 500 else summary
    except Exception as e:
        logger.warning(f"[GENERATE] Summary update failed: {e}")
        return prev_summary


async def generate_answer(state: AgentState):
    messages = state['messages']
    docs = state.get('documents', [])
    intent = state['intent']
    mode = state.get('mode', 'auto')
    prev_summary = state.get('summary', '')

    logger.info(f"[GENERATE] Intent: {intent}, Mode: {mode}, Docs count: {len(docs)}")

    client = OllamaClientWrapper.get_chat_model()
    budgets = _get_budgets(intent)
    history_budget = budgets["history_budget"]
    docs_budget = budgets["docs_budget"]
    logger.info(
        "[GENERATE] Context budget: "
        f"total={budgets['total_window']} output={budgets['output_reserve']} "
        f"fixed={budgets['fixed_prompt_reserve']} safety={budgets['safety_margin']} "
        f"history={history_budget} summary={budgets['summary_budget']} "
        f"recent={budgets['recent_history_budget']} docs={docs_budget} "
        f"metadata={budgets['metadata_budget']}"
    )

    prepared_msgs, used_summary, next_summary = _build_message_list(
        messages,
        history_budget,
        prev_summary,
        summary_budget=budgets["summary_budget"],
        recent_history_budget=budgets["recent_history_budget"],
    )
    if used_summary:
        logger.info("[GENERATE] History exceeded budget, injected stable local summary")

    context_block = ""
    selected_docs = []
    if docs:
        selected_docs = prepare_docs_for_generation(docs, docs_budget)
        if len(selected_docs) < len(docs):
            logger.info(f"[GENERATE] Token budget: {len(selected_docs)}/{len(docs)} docs selected")
        context_block = "\n\n".join(
            f"[{idx}] Retrieved chunk {idx}\n{doc}"
            for idx, doc in enumerate(selected_docs, start=1)
        )

    # Style hint is now baked into the static system prompt for prefix-caching stability.
    # The model is instructed to be crisp by default; if a detailed answer is needed,
    # it's signaled via the user message content rather than a dynamic style prefix.

    if intent in ["direct_rag", "specific_doc_rag"]:
        targeting_context = ""
        semantic_maps = state.get('semantic_queries', [])
        if semantic_maps:
            map_str = "\n".join([f"- Querying '{s['query']}' against '{s['target'] if s['target'] else 'Global Knowledge'}'" for s in semantic_maps])
            targeting_context = f"\n[SEARCH STRATEGY] I segmented your request as follows:\n{map_str}\n"
        elif intent == "specific_doc_rag" and state.get('targeted_docs'):
            targeting_list = ", ".join(state['targeted_docs'])
            targeting_context = f"\n[IMPORTANT] The user specifically requested info from: {targeting_list}."

        if not context_block.strip():
            context_block = (
                "No sufficiently relevant knowledge-base chunks were retrieved for this query. "
                "Do not answer from general knowledge. State that the requested information is not in the indexed files, "
                "and ask the user to upload or target the relevant document."
            )

        rag_prompt = f"""{targeting_context}
<docs>
{context_block}
</docs>
Q: {state.get('query', messages[-1].content)}
"""
        final_messages = [{"role": "system", "content": _GENERATOR_SYSTEM_PROMPT}]
        final_messages.append({"role": "user", "content": rag_prompt})
    else:
        final_messages = [{"role": "system", "content": _GENERATOR_SYSTEM_PROMPT}]
        for m in prepared_msgs:
            if isinstance(m, SystemMessage):
                role = "system"
            else:
                role = "user" if isinstance(m, HumanMessage) else "assistant"
            final_messages.append({"role": role, "content": m.content})

    logger.info(f"[GENERATE] Prefix cache signature: {_cache_signature(final_messages)} | messages={len(final_messages)} | summary={bool(next_summary)}")

    full_content = ""
    async for chunk in client.astream(final_messages):
        full_content += chunk.content

    result = {"messages": [AIMessage(content=full_content)], "summary": next_summary}
    if docs:
        result["documents"] = selected_docs
    return result
