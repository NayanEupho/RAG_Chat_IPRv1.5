"""
Retriever Stitching & FRE Tests
-------------------------------
Validates the Fragment Reconstruction Engine (FRE) and Q&A stitching logic.
Ensures that adjacent document chunks are correctly merged without breaking context.
"""
import unittest
import sys
import os
from collections import defaultdict

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.graph.nodes.retriever import stitch_fragments
from backend.graph.nodes.retriever import _apply_source_precision, _effective_top_k, _format_retrieved_docs, _hybrid_score, _query_variants

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
