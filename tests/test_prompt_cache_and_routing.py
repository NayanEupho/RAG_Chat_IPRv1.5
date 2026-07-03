import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from backend.graph.nodes.generate import (
    _GENERATOR_SYSTEM_PROMPT,
    _SUMMARY_PREFIX,
    _build_message_list,
    _get_budgets,
    generate_answer,
    is_detail_request,
    prepare_docs_for_generation,
)
from backend.graph.nodes.planner import (
    _ACRONYM_CACHE,
    _contains_keyword,
    _context_action_for_followup,
    _contextual_followup_query,
    _extract_named_doc_references,
    _is_contextual_summary_request,
    _is_explicit_chat_shift,
    _is_general_chat_query,
    _is_rag_followup,
    _query_indexed_acronyms,
    planner_node,
)


def test_local_summary_compaction_is_stable_until_next_overflow():
    messages = []
    for idx in range(12):
        messages.append(HumanMessage(content=f"user turn {idx} " + ("details " * 80)))
        messages.append(AIMessage(content=f"assistant turn {idx} " + ("answer " * 80)))

    condensed, used_summary, summary = _build_message_list(messages, history_budget=500, summary="")
    assert used_summary is True
    assert summary
    assert isinstance(condensed[0], SystemMessage)
    assert condensed[0].content.startswith(_SUMMARY_PREFIX)

    # Same inputs produce the same compacted prefix, which is what Ollama
    # prefix caching needs after the compaction boundary.
    condensed2, used_summary2, summary2 = _build_message_list(messages, history_budget=500, summary="")
    assert used_summary2 is True
    assert summary2 == summary
    assert [m.content for m in condensed2] == [m.content for m in condensed]


def test_context_budget_prefers_docs_for_rag_and_history_for_chat():
    rag_budget = _get_budgets("specific_doc_rag")
    chat_budget = _get_budgets("chat")

    assert rag_budget["docs_budget"] > rag_budget["recent_history_budget"]
    assert rag_budget["summary_budget"] > 0
    assert chat_budget["docs_budget"] == 0
    assert chat_budget["recent_history_budget"] > rag_budget["recent_history_budget"]
    assert rag_budget["output_reserve"] > rag_budget["fixed_prompt_reserve"]


def test_table_docs_are_compacted_for_generation():
    docs = [
        "[Source: LeaveAtaGlance.pdf | Section: 11. Casual Leave (CL) | Path: Table 2 > 11. Casual Leave (CL)]\n"
        "[Doc: LeaveAtaGlance.pdf | Section: Table 2 > 11. Casual Leave (CL) | Table Row: 6]\n"
        "# 11. Casual Leave (CL)\n" + ("Casual leave details. " * 200),
        "[Source: LeaveAtaGlance.pdf | Section: 13. Extra Ordinary Leave (EOL) | Path: Table 3 > 13. Extra Ordinary Leave (EOL)]\n"
        "[Doc: LeaveAtaGlance.pdf | Section: Table 3 > 13. Extra Ordinary Leave (EOL) | Table Row: 1]\n"
        "# 13. Extra Ordinary Leave (EOL)\n" + ("EOL pension details. " * 200),
        "[Source: LeaveAtaGlance.pdf | Section: Document Summary | Path: Document Summary]\nsummary",
    ]

    selected = prepare_docs_for_generation(docs, docs_budget=4096)

    assert len(selected) == 2
    assert all("Table Row:" in doc for doc in selected)
    assert sum(len(doc) for doc in selected) < sum(len(doc) for doc in docs)


def test_generator_prompt_is_concise_but_not_artificially_capped():
    assert "Answer in < 4 sentences" not in _GENERATOR_SYSTEM_PROMPT
    assert "concise but complete" in _GENERATOR_SYSTEM_PROMPT
    assert "do not omit useful evidence" in _GENERATOR_SYSTEM_PROMPT
    assert "add inline numeric citations like [1] or [2]" in _GENERATOR_SYSTEM_PROMPT
    assert "Clearly separate documented facts from general guidance" in _GENERATOR_SYSTEM_PROMPT
    assert "not explicitly stated in the provided evidence" in _GENERATOR_SYSTEM_PROMPT
    assert "typically, generally, usually, likely, implies, or suggests" in _GENERATOR_SYSTEM_PROMPT


def test_detail_request_detection_expands_only_when_explicit():
    assert is_detail_request("Explain in detail how multi-head attention works")
    assert is_detail_request("Give a step by step explanation")
    assert not is_detail_request("What is this paper about?")


@pytest.mark.asyncio
async def test_simple_greeting_fast_path_skips_model_call():
    with patch(
        "backend.graph.nodes.generate.OllamaClientWrapper.get_chat_model",
        side_effect=AssertionError("model should not be called for pure greetings"),
    ):
        result = await generate_answer({
            "messages": [HumanMessage(content="Hi")],
            "query": "Hi",
            "intent": "chat",
            "mode": "auto",
            "documents": [],
            "summary": "",
        })

    assert result["messages"][0].content == "Hello! How can I help you today?"


def test_followup_context_action_reuses_existing_docs_for_more_detail():
    state = {
        "intent": "direct_rag",
        "documents": ["previous retrieved chunk"],
    }

    assert _context_action_for_followup("tell me more", state) == "answer_from_existing"
    assert _context_action_for_followup("what does that mean?", state) == "answer_from_existing"


def test_followup_context_action_retrieves_for_new_specific_fact_and_hybrid_for_compare():
    state = {
        "intent": "direct_rag",
        "documents": ["previous retrieved chunk"],
    }

    assert _context_action_for_followup("what about eligibility criteria?", state) == "retrieve"
    assert _context_action_for_followup("compare this with FAQ", state) == "hybrid"


def test_named_doc_reference_resolves_faq_without_at_mention():
    mock_store = MagicMock()
    mock_store.get_all_files.return_value = ["FAQ_LTDP_28Dec11.pdf", "TECHNICAL_REPORT_V8.pdf"]

    with patch("backend.rag.store.get_vector_store", return_value=mock_store):
        refs = _extract_named_doc_references("Compare this with the FAQ document")

    assert refs == ["FAQ_LTDP_28Dec11.pdf"]


def test_named_doc_reference_ignores_short_filename_tokens():
    mock_store = MagicMock()
    mock_store.get_all_files.return_value = ["Design and Development.pdf", "LeaveAtaGlance.pdf"]

    with patch("backend.rag.store.get_vector_store", return_value=mock_store):
        refs = _extract_named_doc_references("Can CL be combined with EL?")

    assert refs == []


def test_indexed_acronym_query_is_detected_from_metadata():
    mock_store = MagicMock()
    mock_store.collection.get.return_value = {
        "metadatas": [
            {
                "filename": "LeaveAtaGlance.pdf",
                "section_title": "13. Extra Ordinary Leave (EOL)",
                "section_path": "Table 3 > 13. Extra Ordinary Leave (EOL)",
            }
        ]
    }
    _ACRONYM_CACHE["terms"] = set()
    _ACRONYM_CACHE["loaded_at"] = 0.0

    with patch("backend.rag.store.get_vector_store", return_value=mock_store):
        assert _query_indexed_acronyms("Does EOL count for pension?") == {"eol"}


def test_common_words_do_not_match_indexed_acronyms():
    mock_store = MagicMock()
    mock_store.collection.get.return_value = {
        "metadatas": [
            {
                "filename": "attention_is_all_you_need.pdf",
                "section_title": "THE model architecture",
                "section_path": "Abstract",
            }
        ]
    }
    _ACRONYM_CACHE["terms"] = set()
    _ACRONYM_CACHE["loaded_at"] = 0.0

    with patch("backend.rag.store.get_vector_store", return_value=mock_store):
        assert _query_indexed_acronyms("who are the authors") == set()


def test_general_auto_queries_do_not_become_rag_followups():
    rag_state = {
        "intent": "specific_doc_rag",
        "documents": ["previous retrieved chunk"],
        "messages": [
            HumanMessage(content="What is the technical report about?"),
            AIMessage(content="It is about a Dev Ops Agent."),
            HumanMessage(content="What is the capital of Japan?"),
        ],
    }

    assert _is_general_chat_query("What is the capital of Japan?")
    assert not _is_rag_followup("What is the capital of Japan?", rag_state)


def test_short_chat_keyword_does_not_match_inside_everything():
    assert _contains_keyword("hi there", "hi")
    assert not _contains_keyword("summarize everything", "hi")


def test_explicit_chat_shift_leaves_document_context():
    rag_state = {
        "intent": "specific_doc_rag",
        "documents": ["previous retrieved chunk"],
        "messages": [
            HumanMessage(content="Who is eligible for LTDP?"),
            AIMessage(content="Group A officers are eligible."),
            HumanMessage(content="Forget the docs for a moment: give me one short fact about Mars."),
        ],
    }

    query = "Forget the docs for a moment: give me one short fact about Mars."
    assert _is_explicit_chat_shift(query)
    assert not _is_rag_followup(query, rag_state)


def test_real_short_rag_followup_still_stays_in_rag_context():
    rag_state = {
        "intent": "specific_doc_rag",
        "documents": ["previous retrieved chunk"],
        "messages": [
            HumanMessage(content="Who is eligible for LTDP?"),
            AIMessage(content="Group A officers are eligible."),
            HumanMessage(content="Tell me more about that eligibility."),
        ],
    }

    assert _is_rag_followup("Tell me more about that eligibility.", rag_state)


def test_targeted_author_followup_stays_in_previous_document_context():
    rag_state = {
        "intent": "specific_doc_rag",
        "targeted_docs": ["Qlora_Paper.pdf"],
        "documents": ["previous qlora context"],
        "messages": [
            HumanMessage(content="What is @Qlora_Paper.pdf paper about?"),
            AIMessage(content="The paper introduces QLoRA."),
            HumanMessage(content="who are the authors"),
        ],
    }

    assert _is_rag_followup("who are the authors", rag_state)
    assert _context_action_for_followup("who are the authors", rag_state, ["Qlora_Paper.pdf"]) == "retrieve"
    rewritten = _contextual_followup_query("who are the authors", rag_state)
    assert "Qlora_Paper.pdf" not in rewritten
    assert rewritten.startswith("What is")


def test_persisted_target_context_restores_short_author_followup():
    rag_state = {
        "last_targeted_docs": ["Qlora_Paper.pdf"],
        "messages": [
            HumanMessage(content="What is @Qlora_Paper.pdf paper about?"),
            AIMessage(content="The paper introduces QLoRA."),
            HumanMessage(content="who are the authors"),
        ],
    }

    assert _is_rag_followup("who are the authors", rag_state)
    rewritten = _contextual_followup_query("who are the authors", rag_state)
    assert rewritten == "What is paper about who are the authors"


def test_persisted_target_context_does_not_capture_unrelated_short_query():
    rag_state = {
        "last_targeted_docs": ["Qlora_Paper.pdf"],
        "messages": [
            HumanMessage(content="What is @Qlora_Paper.pdf paper about?"),
            AIMessage(content="The paper introduces QLoRA."),
            HumanMessage(content="what is mars"),
        ],
    }

    assert not _is_rag_followup("what is mars", rag_state)


def test_summarize_everything_stays_in_rag_context():
    rag_state = {
        "intent": "direct_rag",
        "documents": ["previous retrieved chunk"],
        "messages": [
            HumanMessage(content="Explain the pension rules in detail"),
            AIMessage(content="Only leave-related pension notes are present."),
            HumanMessage(content="summarize everything"),
        ],
    }

    assert _is_rag_followup("summarize everything", rag_state)
    assert _is_contextual_summary_request("summarize everything", rag_state)
    assert _contextual_followup_query("summarize everything", rag_state).startswith("Explain the pension rules")


def test_what_about_followup_does_not_become_new_topic_anchor():
    rag_state = {
        "intent": "direct_rag",
        "documents": ["previous retrieved chunk"],
        "messages": [
            HumanMessage(content="Explain the pension rules in detail"),
            AIMessage(content="Only leave-related pension notes are present."),
            HumanMessage(content="what about eligibility criteria"),
            AIMessage(content="No full pension eligibility details are present."),
            HumanMessage(content="summarize everything"),
        ],
    }

    rewritten = _contextual_followup_query("summarize everything", rag_state)

    assert rewritten.startswith("Explain the pension rules")
    assert "what about eligibility criteria" not in rewritten


@pytest.mark.asyncio
async def test_planner_contextual_summary_bypasses_guardrail():
    state = {
        "mode": "auto",
        "messages": [
            HumanMessage(content="Explain the pension rules in detail"),
            AIMessage(content="Only leave-related pension notes are present."),
            HumanMessage(content="summarize everything"),
        ],
        "retrieval_metrics": {"stale": True},
    }

    result = await planner_node(state)

    assert result["intent"] == "direct_rag"
    assert "Explain the pension rules" in result["query"]
    assert result["semantic_queries"]


@pytest.mark.asyncio
async def test_planner_named_doc_reference_forces_targeted_rag():
    mock_store = MagicMock()
    mock_store.get_all_files.return_value = ["FAQ_LTDP_28Dec11.pdf", "TECHNICAL_REPORT_V8.pdf"]
    state = {
        "mode": "auto",
        "messages": [HumanMessage(content="Compare this with the FAQ document")],
        "retrieval_metrics": {"stale": True},
    }

    with patch("backend.rag.store.get_vector_store", return_value=mock_store):
        result = await planner_node(state)

    assert result["intent"] == "specific_doc_rag"
    assert result["targeted_docs"] == ["FAQ_LTDP_28Dec11.pdf"]
    assert result["semantic_queries"]


@pytest.mark.asyncio
async def test_planner_chat_clears_stale_retrieval_metrics():
    state = {
        "mode": "auto",
        "messages": [HumanMessage(content="What is the capital of Japan?")],
        "retrieval_metrics": {"stale": True},
    }

    result = await planner_node(state)

    assert result["intent"] == "chat"
    assert result["retrieval_metrics"] == {}
