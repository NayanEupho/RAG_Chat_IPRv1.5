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
from unittest.mock import MagicMock

# Define mocks BEFORE importing modules that might use them
sys.modules['chromadb'] = MagicMock()
sys.modules['chromadb.config'] = MagicMock()
sys.modules['langchain_chroma'] = MagicMock()
sys.modules['langchain_openai'] = MagicMock()
sys.modules['langchain_ollama'] = MagicMock()
sys.modules['backend.rag.store'] = MagicMock()

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.graph.nodes.retriever import stitch_fragments

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
        
if __name__ == '__main__':
    unittest.main()
