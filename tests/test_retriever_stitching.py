"""
Retriever Stitching & FRE Tests
-------------------------------
Validates the Fragment Reconstruction Engine (FRE) and Q&A stitching logic.
Ensures that adjacent document chunks are correctly merged without breaking context.
"""
import unittest
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.graph.nodes.retriever import stitch_fragments
from backend.graph.nodes.retriever import (
    _apply_source_precision,
    _dedupe_docs,
    _effective_top_k,
    _ensure_target_coverage,
    _format_retrieved_docs,
    _hybrid_score,
    _query_variants,
    _should_fetch_intro_context,
    _should_run_target_lexical_scan,
    _target_lexical_score,
)

class TestRetrieverStitching(unittest.TestCase):
    def test_basic_stitching(self):
        """Test simple text stitching of fragments."""
        doc1 = {"page_content": "Part 1 text.", "metadata": {"filename": "A", "chunk_index": 1, "is_fragment": False}}
        doc2 = {"page_content": "Part 2 text.", "metadata": {"filename": "A", "chunk_index": 2, "is_fragment": True}}
        
        result = stitch_fragments([doc1, doc2])
        
        self.assertEqual(len(result), 1)
        self.assertIn("Part 1 text.\nPart 2 text.", result[0]['page_content'])

    def test_table_stitching_header_removal(self):
        """Test that repeated headers are stripped when stitching tables."""
        header = "| H1 | H2 |\n|---|---|" # Real tables have 2 lines
        row1 = "| A  | B  |"
        row2 = "| C  | D  |"
        
        # Chunk 1: Header + Row 1
        content1 = f"{header}\n{row1}" 
        # Chunk 2: Header + Row 2 (Fragment)
        content2 = f"{header}\n{row2}"
        
        doc1 = {"page_content": content1, "metadata": {"filename": "T", "chunk_index": 1, "is_fragment": False, "has_table": True}}
        doc2 = {"page_content": content2, "metadata": {"filename": "T", "chunk_index": 2, "is_fragment": True, "has_table": True}}
        
        result = stitch_fragments([doc1, doc2])
        
        merged_text = result[0]['page_content']
        
        # Expectation: Header appears ONCE. Row 1 then Row 2.
        self.assertEqual(merged_text.count(header), 1, "Header should appear only once after merge")
        self.assertIn("| A  | B  |", merged_text)
        self.assertIn("| C  | D  |", merged_text)

    def test_missing_middle_safety(self):
        """Test that non-adjacent chunks are NOT merged."""
        doc1 = {"page_content": "Start", "metadata": {"filename": "A", "chunk_index": 1}}
        doc3 = {"page_content": "End", "metadata": {"filename": "A", "chunk_index": 3, "is_fragment": True}} # Index 3! Gap of 2.
        
        result = stitch_fragments([doc1, doc3])
        
        self.assertEqual(len(result), 2, "Should NOT stitch because of gap")

    def test_qna_stitching(self):
        """Test that Q&A fragments are correctly merged by qa_pair_id."""
        from backend.graph.nodes.retriever import stitch_qna_fragments
        
        doc1 = {
            "page_content": "Q: Question\nA: Part 1", 
            "metadata": {"doc_type": "qna", "qa_pair_id": "QA123", "fragment_index": 0, "total_fragments": 2}
        }
        doc2 = {
            "page_content": "Part 2", 
            "metadata": {"doc_type": "qna", "qa_pair_id": "QA123", "fragment_index": 1, "total_fragments": 2}
        }
        doc3 = {
            "page_content": "Random General Doc", 
            "metadata": {"doc_type": "general"}
        }
        
        result = stitch_qna_fragments([doc1, doc2, doc3])
        
        self.assertEqual(len(result), 2)
        # Check merged Q&A
        merged_qna = next(d for d in result if d['metadata'].get('doc_type') == 'qna')
        self.assertIn("Q: Question\nA: Part 1\n\nPart 2", merged_qna['page_content'])
        self.assertEqual(merged_qna['metadata']['stitched_from'], 2)
        
        # Check general doc preserved
        general_doc = next(d for d in result if d['metadata'].get('doc_type') == 'general')
        self.assertEqual(general_doc['page_content'], "Random General Doc")

    def test_hybrid_score_uses_section_metadata(self):
        doc = {
            "page_content": "Applicants must complete ten years of service.",
            "metadata": {
                "filename": "policy.pdf",
                "section_title": "Eligibility Criteria",
                "section_path": "Policy > Eligibility Criteria",
                "doc_type": "general",
            },
            "_vector_score": 0.4,
        }

        score = _hybrid_score("eligibility criteria for applicants", doc)
        assert score > 0.8

    def test_query_variants_expand_technology_stack_questions(self):
        variants = _query_variants(
            "What technologies does TECHNICAL_REPORT_V8.pdf mention?",
            semantic_maps=[],
            targeted_docs=["TECHNICAL_REPORT_V8.pdf"],
        )

        assert any("component breakdown" in item["query"] for item in variants)
        assert all(item["target"] == "TECHNICAL_REPORT_V8.pdf" for item in variants)

    def test_hybrid_score_boosts_component_breakdown_for_technology_query(self):
        overview = {
            "page_content": "The agent is built on a carefully selected stack of modern technologies.",
            "metadata": {
                "filename": "TECHNICAL_REPORT_V8.pdf",
                "section_title": "4. Technology Stack Overview",
                "section_path": "4. Technology Stack Overview",
            },
            "_vector_score": 0.62,
        }
        component_breakdown = {
            "page_content": "Component: Python 3.11+; Component: DSPy; Component: Ollama; Component: docker-py",
            "metadata": {
                "filename": "TECHNICAL_REPORT_V8.pdf",
                "section_title": "4.2 Component Breakdown",
                "section_path": "4. Technology Stack Overview > 4.2 Component Breakdown",
            },
            "_vector_score": 0.48,
        }

        assert _hybrid_score("What technologies does it use?", component_breakdown) > _hybrid_score(
            "What technologies does it use?", overview
        )

    def test_hybrid_score_boosts_intro_for_about_query(self):
        summary = {
            "page_content": "QLoRA is an efficient finetuning approach for quantized large language models.",
            "metadata": {
                "filename": "Qlora_Paper.pdf",
                "chunk_kind": "doc_summary",
                "section_title": "Document Summary",
                "chunk_index": 0,
            },
            "_vector_score": 0.42,
        }
        later_section = {
            "page_content": "Guanaco qualitative evaluation benchmark examples and hyperparameters.",
            "metadata": {
                "filename": "Qlora_Paper.pdf",
                "section_title": "6.1 Qualitative Analysis of Example Generations",
                "chunk_index": 29,
            },
            "_vector_score": 0.72,
        }

        assert _hybrid_score("What is this paper about?", summary) > _hybrid_score(
            "What is this paper about?", later_section
        )

    def test_source_precision_prefers_relevant_table_file(self):
        leave_table = {
            "page_content": "Extra Ordinary Leave EOL medical certificate pension increment",
            "metadata": {
                "filename": "LeaveAtaGlance.pdf",
                "chunk_kind": "table_row",
                "section_title": "13. Extra Ordinary Leave (EOL)",
                "section_path": "Table > EOL",
            },
            "_vector_score": 0.55,
        }
        leave_summary = {
            "page_content": "Leave rules at a glance EOL pension",
            "metadata": {"filename": "LeaveAtaGlance.pdf", "chunk_kind": "doc_summary"},
            "_vector_score": 0.48,
        }
        faq = {
            "page_content": "LTDP salary age relaxation officers",
            "metadata": {"filename": "FAQ_LTDP_28Dec11.pdf", "chunk_kind": "qna"},
            "_vector_score": 0.62,
        }
        docs = [faq, leave_table, leave_summary]
        for doc in docs:
            doc["_score"] = _hybrid_score("Does EOL count for pension?", doc)
        docs.sort(key=lambda d: d["_score"], reverse=True)

        filtered = _apply_source_precision("Does EOL count for pension?", docs, top_k=3)

        assert filtered[0]["metadata"]["filename"] == "LeaveAtaGlance.pdf"
        assert all(d["metadata"]["filename"] == "LeaveAtaGlance.pdf" for d in filtered)

    def test_target_lexical_score_recovers_exact_section_title(self):
        casual_leave = {
            "page_content": "Maximum of 08 days of casual leave is granted during a calendar year.",
            "metadata": {
                "filename": "LeaveAtaGlance.pdf",
                "section_title": "Casual Leave (CL)",
                "section_path": "IPR Leave Rules at a Glance > Types of Leave > Casual Leave (CL)",
            },
        }
        paternity_leave = {
            "page_content": "Paternity leave is granted for 15 days.",
            "metadata": {
                "filename": "LeaveAtaGlance.pdf",
                "section_title": "Paternity Leave",
                "section_path": "IPR Leave Rules at a Glance > Types of Leave > Paternity Leave",
            },
        }

        assert _target_lexical_score("What does the document say about Casual Leave?", casual_leave) >= 1.5
        assert _target_lexical_score("What does the document say about Casual Leave?", paternity_leave) < 1.0

    def test_hybrid_score_uses_targeted_lexical_boost(self):
        exact_section = {
            "page_content": "Maximum of 08 days of casual leave is granted during a calendar year.",
            "metadata": {
                "filename": "LeaveAtaGlance.pdf",
                "section_title": "Casual Leave (CL)",
                "section_path": "IPR Leave Rules at a Glance > Types of Leave > Casual Leave (CL)",
            },
            "_vector_score": 0.48,
            "_lexical_score": 1.8,
        }
        noisy_table = {
            "page_content": "Paternity leave is granted for 15 days.",
            "metadata": {
                "filename": "LeaveAtaGlance.pdf",
                "section_title": "Paternity Leave",
                "section_path": "Table 3 > Paternity Leave",
                "chunk_kind": "table_row",
            },
            "_vector_score": 0.82,
        }

        assert _hybrid_score("What does the document say about Casual Leave?", exact_section) > _hybrid_score(
            "What does the document say about Casual Leave?", noisy_table
        )

    def test_target_lexical_score_matches_eligibility_to_eligible(self):
        faq = {
            "page_content": "Group A officers with at least 7 years of service are eligible.",
            "metadata": {
                "filename": "FAQ_LTDP_28Dec11.pdf",
                "question_text": "Officers of which services are eligible for these programmes?",
                "doc_type": "qna",
            },
        }

        assert _target_lexical_score("eligibility criteria eligible services officers", faq) >= 1.5

    def test_dedupe_keeps_lexically_stronger_duplicate(self):
        vector_doc = {
            "page_content": "Q: Officers of which services are eligible?",
            "metadata": {"filename": "FAQ_LTDP_28Dec11.pdf", "chunk_index": 3},
            "_vector_score": 0.62,
        }
        lexical_doc = {
            "page_content": "Q: Officers of which services are eligible?",
            "metadata": {"filename": "FAQ_LTDP_28Dec11.pdf", "chunk_index": 3},
            "_vector_score": 0.48,
            "_lexical_score": 2.4,
        }

        deduped = _dedupe_docs([vector_doc, lexical_doc])

        assert len(deduped) == 1
        assert deduped[0]["_lexical_score"] == 2.4

    def test_target_lexical_scan_skips_when_vector_candidates_are_strong(self):
        candidates = [{
            "page_content": "The authors are Tim Dettmers and colleagues.",
            "metadata": {"section_title": "Authors", "filename": "paper.pdf"},
            "_score": 0.88,
        }]

        assert not _should_run_target_lexical_scan("who are the authors", candidates, top_k=5, min_score=0.20)

    def test_target_lexical_scan_runs_when_candidates_do_not_cover_detail_query(self):
        candidates = [{
            "page_content": "This paper discusses memory efficient finetuning.",
            "metadata": {"section_title": "Overview", "filename": "paper.pdf"},
            "_score": 0.72,
        }]

        assert _should_run_target_lexical_scan("who are the authors", candidates, top_k=5, min_score=0.20)

    def test_intro_fetch_skips_when_vector_candidates_cover_overview(self):
        candidates = [{
            "page_content": "The technical report describes a DevOps Agent for infrastructure orchestration.",
            "metadata": {"filename": "report.pdf", "section_title": "Executive Summary"},
            "_score": 0.82,
        }]

        assert not _should_fetch_intro_context("what is the technical report about", candidates, min_score=0.20)

    def test_intro_fetch_runs_when_overview_candidates_are_weak(self):
        candidates = [{
            "page_content": "Appendix references and unrelated deployment notes.",
            "metadata": {"filename": "report.pdf", "section_title": "Appendix"},
            "_score": 0.12,
        }]

        assert _should_fetch_intro_context("what is the technical report about", candidates, min_score=0.20)

    def test_target_coverage_keeps_each_explicit_target_when_candidates_exist(self):
        ranked = [
            {
                "page_content": "Earned Leave can be accumulated up to 300 days.",
                "metadata": {"filename": "LeaveAtaGlance.pdf", "chunk_index": 4},
                "_score": 0.92,
            },
            {
                "page_content": "Restricted Holiday can be prefixed or suffixed to other leave.",
                "metadata": {"filename": "LeaveAtaGlance.pdf", "chunk_index": 5},
                "_score": 0.88,
            },
        ]
        candidates = ranked + [
            {
                "page_content": "LTDP eligibility covers service criteria and salary protections.",
                "metadata": {"filename": "FAQ_LTDP_28Dec11.pdf", "chunk_index": 3},
                "_score": 0.57,
            },
            {
                "page_content": "LTDP age limits and service requirements.",
                "metadata": {"filename": "FAQ_LTDP_28Dec11.pdf", "chunk_index": 4},
                "_score": 0.54,
            }
        ]

        covered = _ensure_target_coverage(
            ranked_docs=ranked,
            candidate_pool=candidates,
            targeted_docs=["FAQ_LTDP_28Dec11.pdf", "LeaveAtaGlance.pdf"],
            top_k=4,
        )

        files = [doc["metadata"]["filename"] for doc in covered]
        assert files.count("FAQ_LTDP_28Dec11.pdf") >= 2
        assert files.count("LeaveAtaGlance.pdf") >= 2

    def test_exact_acronym_title_beats_near_acronym_table_row(self):
        eol = {
            "page_content": "Extra Ordinary Leave EOL medical certificate pension increment",
            "metadata": {
                "filename": "LeaveAtaGlance.pdf",
                "section_title": "13. Extra Ordinary Leave (EOL)",
                "section_path": "Table 3 > 13. Extra Ordinary Leave (EOL)",
                "chunk_kind": "table_row",
            },
            "_vector_score": 0.55,
        }
        el = {
            "page_content": "Earned Leave retirement pension balance",
            "metadata": {
                "filename": "LeaveAtaGlance.pdf",
                "section_title": "8. Earned Leave (EL)",
                "section_path": "Table 2 > 8. Earned Leave (EL)",
                "chunk_kind": "table_row",
            },
            "_vector_score": 0.60,
        }

        assert _hybrid_score("Does EOL count for pension?", eol) > _hybrid_score("Does EOL count for pension?", el)

    def test_format_retrieved_docs_renders_platinum_envelope_from_metadata(self):
        docs = [{
            "page_content": "Technical Report > 4. Stack\n\n## 4. Stack\n\nPython and DSPy are used.",
            "metadata": {
                "filename": "TECHNICAL_REPORT_V8.pdf",
                "doc_type": "general",
                "parser": "docling_llm_normalized",
                "chunk_kind": "section",
                "section_title": "4. Stack",
                "section_path": "Technical Report > 4. Stack",
                "heading_level": 2,
                "chunk_index": 7,
                "prev_index": 6,
                "next_index": 8,
                "normalized": True,
            },
        }]

        formatted = _format_retrieved_docs(docs)[0]

        assert "[Source: TECHNICAL_REPORT_V8.pdf]" in formatted
        assert "[Parser: docling_llm_normalized]" in formatted
        assert "[ChunkKind: section]" in formatted
        assert "[SectionPath: Technical Report > 4. Stack]" in formatted
        assert "[Normalized: true]" in formatted
        assert "Python and DSPy are used." in formatted

    def test_effective_top_k_expands_for_detail_and_deep_queries(self):
        class Cfg:
            retrieval_top_k = 5
            retrieval_detail_top_k = 8
            retrieval_deep_top_k = 10

        assert _effective_top_k("Can CL be combined with EL?", "retrieve", Cfg) == 5
        assert _effective_top_k("explain the rule in detail", "retrieve", Cfg) == 8
        assert _effective_top_k("compare everything in full details", "hybrid", Cfg) == 10
         
if __name__ == '__main__':
    unittest.main()
