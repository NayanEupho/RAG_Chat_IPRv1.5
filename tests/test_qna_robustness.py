"""
Q&A Pattern Extraction Robustness Tests
---------------------------------------
Validates the resilience of the Q&A extraction regex against common 
document artifacts like HTML entities and hyphenated Markdown lists.
"""
import sys
import os
import unittest
import html

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.ingestion.qna_patterns import extract_qa_pairs
from backend.ingestion.processor import DocumentProcessor

class TestQnARobustness(unittest.TestCase):
    def setUp(self):
        self.processor = DocumentProcessor()

    def test_hyphenated_html_qna(self):
        """
        Tests extraction from the user's problematic snippet.
        """
        problematic_md = """
- Q1 What are the Long Term Domestic Training Programmes sponsored by
DoP&amp;T?
- A: At present, the three programmes mentioned below are being sponsored by Training Division, DoP&amp;T:
- (i) Post Graduate Programme in Public Policy and Management (PGPPM) offered by Indian Institute of Management, Bangalore (IIMB)
- (ii) Post Graduate Programme in Public Policy and Management (PGPPM) offered by Management Development Institute , Gurgaon (MDI -G)
- (iii) M.A. in Public Policy &amp; Sustainable Development [MA (PP&amp;SD)] offered by TERI, New Delhi
"""
        # Step 1: Manual Clean (mimicking processor.py)
        cleaned_md = self.processor._clean_markdown_artifacts(problematic_md)
        
        # Verify decoding
        self.assertNotIn("&amp;", cleaned_md)
        self.assertIn("DoP&T", cleaned_md)
        
        # Step 2: Extract pairs
        pairs = extract_qa_pairs(cleaned_md, "test_faq.pdf")
        
        self.assertEqual(len(pairs), 1)
        self.assertIn("Long Term Domestic Training Programmes", pairs[0]["question_text"])
        self.assertIn("Indian Institute of Management", pairs[0]["answer_text"])
        
        # Verify that sub-bullets in the answer are PRESERVED
        self.assertIn("- (i)", pairs[0]["answer_text"])
        self.assertIn("- (ii)", pairs[0]["answer_text"])

    def test_bullet_tolerant_regex(self):
        """
        Tests if the regex in qna_patterns.py handles hyphenated markers directly.
        """
        md = "- Q: What is X?\n- A: X is Y."
        pairs = extract_qa_pairs(md, "bullet_test.pdf")
        
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["question_text"], "What is X?")
        self.assertIn("X is Y", pairs[0]["answer_text"])

if __name__ == "__main__":
    unittest.main()
