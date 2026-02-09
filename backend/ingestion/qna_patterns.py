"""
Q&A Pattern Detection and Parsing Utilities.

This module provides regex patterns and utilities for detecting and parsing
Q&A-style documents (FAQs, knowledge bases, etc.).
"""
import re
from typing import List, Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# QUESTION DETECTION PATTERNS
# =============================================================================

# Patterns that indicate the start of a new question
QUESTION_START_PATTERNS = [
    # Optional bullet followed by Q: or Q1: or Q 1: formats (colon/dot optional)
    r'^(?:[ \t]*[-*+][ \t]+)?(?:Q\s*\d*\s*[:.]?|Q\s*[:.])\s*',
    # Optional bullet followed by Question: or Question 1: formats
    r'^(?:[ \t]*[-*+][ \t]+)?(?:Question\s*\d*\s*[:.]?)\s*',
    # Optional bullet followed by **Q:** or **Question:** (bold markdown)
    r'^(?:[ \t]*[-*+][ \t]+)?(?:\*\*\s*)?(?:Q|Question)\s*\d*\s*[:.]?\s*(?:\*\*\s*)?',
    # Numbered questions: 1. What is... / 1) How do...
    # Broadened to match any "Number followed by punctuation" at start of line
    r'^(?:[ \t]*[-*+][ \t]+)?\d+[.)]\s+.*[?:]\s*$',  # Question mark or colon at end of line
    r'^(?:[ \t]*[-*+][ \t]+)?\d+[.)]\s+(?:What|How|Why|When|Where|Who|Which|Can|Does|Do|Is|Are|Will|Would|Should|Could|May|Please|To)\s',
]

# Combined pattern for question detection
QUESTION_PATTERN = '|'.join(f'(?:{p})' for p in QUESTION_START_PATTERNS)
QUESTION_REGEX = re.compile(QUESTION_PATTERN, re.MULTILINE | re.IGNORECASE)

# =============================================================================
# ANSWER DETECTION PATTERNS
# =============================================================================

# Patterns that indicate the start of an answer
ANSWER_START_PATTERNS = [
    r'^(?:[ \t]*[-*+][ \t]+)?(?:A\s*\d*\s*[:.])\s*',           # A: or A1:
    r'^(?:[ \t]*[-*+][ \t]+)?(?:Answer\s*\d*\s*[:.])\s*',      # Answer: or Answer 1:
    r'^(?:[ \t]*[-*+][ \t]+)?\*\*(?:A|Answer)\s*\d*[:.]?\*\*', # **A:** or **Answer:**
]

ANSWER_PATTERN = '|'.join(f'(?:{p})' for p in ANSWER_START_PATTERNS)
ANSWER_REGEX = re.compile(ANSWER_PATTERN, re.MULTILINE | re.IGNORECASE)

# =============================================================================
# SECTION HEADER PATTERNS
# =============================================================================

# Markdown headers (# to ######)
SECTION_HEADER_PATTERN = r'^#{1,6}\s+.+$'
SECTION_HEADER_REGEX = re.compile(SECTION_HEADER_PATTERN, re.MULTILINE)

# =============================================================================
# Q&A PAIR EXTRACTION
# =============================================================================

def extract_qa_pairs(text: str, filename: str) -> List[Dict[str, Any]]:
    """
    Extracts Q&A pairs from text content.
    
    Returns a list of dicts with:
    - question_text: The question content
    - answer_text: The answer content (may include bullets, numbering, etc.)
    - section_path: Hierarchical section path
    - qa_pair_id: Unique identifier for this Q&A pair
    - start_pos: Character position in source
    """
    pairs = []
    
    # Track current section hierarchy
    current_section = "Root"
    header_stack = []
    
    # Find all questions
    question_matches = list(QUESTION_REGEX.finditer(text))
    
    if not question_matches:
        logger.debug(f"No Q&A patterns detected in {filename}")
        return []
    
    logger.info(f"Detected {len(question_matches)} questions in {filename}")
    
    # Also find section headers for context
    header_matches = list(SECTION_HEADER_REGEX.finditer(text))
    header_positions = [(m.start(), m.group().strip()) for m in header_matches]
    
    # Helper to get section context at a given position
    def get_section_at_pos(pos: int) -> str:
        relevant_headers = [(p, h) for p, h in header_positions if p < pos]
        if not relevant_headers:
            return "Root"
        
        # Build hierarchy from headers
        stack = []
        for _, header in relevant_headers:
            level = header.count('#')
            title = header.lstrip('#').strip()
            stack = stack[:level-1] + [title]
        
        return " > ".join(stack) if stack else "Root"
    
    # Extract each Q&A pair
    base_name = filename.rsplit('.', 1)[0].replace(' ', '_').lower()
    
    for i, q_match in enumerate(question_matches):
        q_start = q_match.start()
        q_text_match = q_match.group()
        
        # Try to extract a numeric index from the question marker (e.g., Q1 -> 1)
        numeric_id_match = re.search(r'(\d+)', q_text_match)
        numeric_id = int(numeric_id_match.group(1)) if numeric_id_match else (i + 1)
        
        # Determine answer boundary (next question or end of text)
        if i + 1 < len(question_matches):
            q_end = question_matches[i + 1].start()
        else:
            q_end = len(text)
        
        # Extract full Q&A block
        qa_block = text[q_start:q_end].strip()
        
        # Split into question and answer
        answer_match = ANSWER_REGEX.search(qa_block)
        
        if answer_match:
            question_text = qa_block[:answer_match.start()].strip()
            answer_text = qa_block[answer_match.start():].strip()
        else:
            lines = qa_block.split('\n', 1)
            question_text = lines[0].strip()
            answer_text = lines[1].strip() if len(lines) > 1 else ""
        
        # Clean question text
        question_text = re.sub(r'^[ \t]*[-*+][ \t]+', '', question_text)
        question_text = re.sub(r'^(?:Q\s*\d+\s*[:.]?|Q\s*[:.]|Question\s*\d*\s*[:.]?)\s*', '', question_text, flags=re.IGNORECASE)
        question_text = re.sub(r'^\*\*(?:Q|Question)\s*\d*[:.]?\*\*\s*', '', question_text, flags=re.IGNORECASE)
        question_text = re.sub(r'^\d+[.)]\s*', '', question_text)
        
        # Clean answer text
        answer_text = re.sub(r'^[ \t]*[-*+][ \t]+', '', answer_text)
        answer_text = re.sub(r'^(?:A\s*\d*\s*[:.]|Answer\s*\d*\s*[:.])?\s*', '', answer_text, flags=re.IGNORECASE)
        answer_text = re.sub(r'^\*\*(?:A|Answer)\s*\d*[:.]?\*\*\s*', '', answer_text, flags=re.IGNORECASE)
        
        # Get section context
        section_path = get_section_at_pos(q_start)
        
        # Generate unique ID - preserving the numeric ID if found
        qa_pair_id = f"{base_name}_q{numeric_id}"
        
        pairs.append({
            "question_text": question_text.strip(),
            "answer_text": answer_text.strip(),
            "full_content": qa_block,
            "section_path": section_path,
            "qa_pair_id": qa_pair_id,
            "start_pos": q_start,
            "pair_index": numeric_id  # Use for sorting
        })
    
    return pairs


def is_qna_document(text: str, threshold: float = 0.3) -> bool:
    """
    Heuristically determines if a document is Q&A-style.
    
    Args:
        text: Document content
        threshold: Minimum ratio of Q patterns to consider it Q&A
        
    Returns:
        True if document appears to be Q&A format
    """
    # Count question patterns
    question_count = len(QUESTION_REGEX.findall(text))
    
    # Estimate total "sections" (paragraphs or blocks)
    paragraph_count = max(1, len(re.split(r'\n\s*\n', text)))
    
    ratio = question_count / paragraph_count
    
    is_qna = question_count >= 3 and ratio >= threshold
    
    logger.debug(f"Q&A heuristic: {question_count} questions, {paragraph_count} paragraphs, ratio={ratio:.2f}, is_qna={is_qna}")
    
    return is_qna
