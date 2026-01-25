"""
Markdown Sanitizer Module - Conservative OCR Output Cleanup

This module provides detection-first cleanup for OCR output.
It only applies fixes when specific noise patterns are detected,
preserving original content whenever possible.

Philosophy:
- Preserve First: Never alter content unless a specific noise pattern is confirmed.
- Detection-First: Calculate a noise score before any modification.
- Targeted Fixes: Only apply the specific fix for the detected issue.
"""

import re
import logging
from typing import Tuple

logger = logging.getLogger("rag_chat_ipr.sanitizer")

# Noise detection thresholds
NOISE_THRESHOLD = 0.05  # 5% of content being noise triggers cleanup

# Patterns for noise detection
CONTROL_CHAR_PATTERN = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')
GARBLED_UNICODE_PATTERN = re.compile(r'[ï¿½□]{2,}|[\ufffd]{2,}')
BROKEN_TABLE_PATTERN = re.compile(r'\|\s*\||\|{3,}')
EXCESSIVE_WHITESPACE_PATTERN = re.compile(r'\n{4,}')


def _calculate_noise_score(text: str) -> Tuple[float, dict]:
    """
    Calculate a noise score for the text and identify specific issues.
    
    Args:
        text: The markdown text to analyze
        
    Returns:
        Tuple of (noise_score, detected_issues_dict)
    """
    if not text:
        return 0.0, {}
    
    text_len = len(text)
    issues = {}
    noise_chars = 0
    
    # Check for control characters
    control_matches = CONTROL_CHAR_PATTERN.findall(text)
    if control_matches:
        issues['control_chars'] = len(control_matches)
        noise_chars += len(control_matches)
    
    # Check for garbled unicode
    garbled_matches = GARBLED_UNICODE_PATTERN.findall(text)
    if garbled_matches:
        issues['garbled_unicode'] = len(garbled_matches)
        noise_chars += sum(len(m) for m in garbled_matches)
    
    # Check for broken tables
    broken_table_matches = BROKEN_TABLE_PATTERN.findall(text)
    if broken_table_matches:
        issues['broken_tables'] = len(broken_table_matches)
        noise_chars += sum(len(m) for m in broken_table_matches)
    
    # Check for excessive whitespace
    whitespace_matches = EXCESSIVE_WHITESPACE_PATTERN.findall(text)
    if whitespace_matches:
        # Count excess newlines (beyond 3)
        excess = sum(len(m) - 3 for m in whitespace_matches)
        if excess > 0:
            issues['excessive_whitespace'] = len(whitespace_matches)
            noise_chars += excess
    
    noise_score = noise_chars / text_len if text_len > 0 else 0.0
    
    return noise_score, issues


def _has_control_chars(text: str) -> bool:
    """Check if text contains control characters."""
    return bool(CONTROL_CHAR_PATTERN.search(text))


def _has_garbled_unicode(text: str) -> bool:
    """Check if text contains garbled unicode sequences."""
    return bool(GARBLED_UNICODE_PATTERN.search(text))


def _has_broken_tables(text: str) -> bool:
    """Check if text contains broken table delimiters."""
    return bool(BROKEN_TABLE_PATTERN.search(text))


def _has_excessive_whitespace(text: str) -> bool:
    """Check if text contains excessive whitespace."""
    return bool(EXCESSIVE_WHITESPACE_PATTERN.search(text))


def sanitize_markdown(raw_md: str) -> str:
    """
    Conservative, detection-first cleanup of markdown text.
    
    Only applies fixes when the noise score exceeds the threshold,
    and only applies the specific fixes needed for detected issues.
    
    Args:
        raw_md: Raw markdown text from OCR
        
    Returns:
        Cleaned markdown text (or original if clean enough)
    """
    if not raw_md:
        return raw_md
    
    # Calculate noise score
    noise_score, issues = _calculate_noise_score(raw_md)
    
    if noise_score < NOISE_THRESHOLD and not issues:
        logger.debug("Markdown is clean, no sanitization needed")
        return raw_md
    
    logger.info(f"[SANITIZER] Noise score: {noise_score:.2%}, Issues: {list(issues.keys())}")
    
    md = raw_md
    
    # Apply ONLY the fixes needed based on detected issues
    if 'control_chars' in issues:
        # Remove control characters but keep \n and \t
        md = CONTROL_CHAR_PATTERN.sub('', md)
        logger.debug(f"Removed {issues['control_chars']} control characters")
    
    if 'garbled_unicode' in issues:
        # Replace garbled unicode with empty string
        md = GARBLED_UNICODE_PATTERN.sub('', md)
        logger.debug(f"Removed {issues['garbled_unicode']} garbled unicode sequences")
    
    if 'broken_tables' in issues:
        # Fix consecutive pipes
        md = re.sub(r'\|\s*\|', '|', md)
        md = re.sub(r'\|{3,}', '||', md)
        logger.debug(f"Fixed {issues['broken_tables']} broken table delimiters")
    
    if 'excessive_whitespace' in issues:
        # Reduce to maximum 3 newlines
        md = re.sub(r'\n{4,}', '\n\n\n', md)
        logger.debug(f"Reduced {issues['excessive_whitespace']} excessive whitespace blocks")
    
    return md


def detect_visual_elements(text: str) -> dict:
    """
    Detect figures, tables, diagrams, and images in the text.
    
    Supports:
    - Explicit captions: Figure X:, Table X:, Diagram X:
    - Markdown tables: |...|
    - DeepSeek OCR image descriptions: > [Image: ...]
    
    Args:
        text: Markdown text to analyze
        
    Returns:
        Dict with visual element information
    """
    visuals = {
        'has_visual': False,
        'visual_type': None,
        'visual_title': None,
        'visual_count': 0
    }
    
    # Patterns for explicit caption formats
    figure_pattern = re.compile(
        r'(?:Figure|Fig\.?)\s*(\d+)(?:\s*[-:.]?\s*(.+?))?(?:\n|$)',
        re.IGNORECASE
    )
    table_pattern = re.compile(
        r'(?:Table)\s*(\d+)(?:\s*[-:.]?\s*(.+?))?(?:\n|$)',
        re.IGNORECASE
    )
    diagram_pattern = re.compile(
        r'(?:Diagram|Chart)\s*(\d+)(?:\s*[-:.]?\s*(.+?))?(?:\n|$)',
        re.IGNORECASE
    )
    
    # Detect markdown tables
    md_table_pattern = re.compile(r'\|.+\|.*\n\|[-:| ]+\|', re.MULTILINE)
    
    # NEW: DeepSeek OCR image description pattern
    # Matches: > [Image: description] or similar blockquote image markers
    deepseek_image_pattern = re.compile(
        r'>\s*\[(?:Image|Picture|Photo|Visual|Screenshot)[:\s]+(.+?)\]',
        re.IGNORECASE
    )
    
    # Find all matches
    figures = figure_pattern.findall(text)
    tables = table_pattern.findall(text)
    diagrams = diagram_pattern.findall(text)
    md_tables = md_table_pattern.findall(text)
    images = deepseek_image_pattern.findall(text)
    
    total_visuals = len(figures) + len(tables) + len(diagrams) + len(md_tables) + len(images)
    
    if total_visuals > 0:
        visuals['has_visual'] = True
        visuals['visual_count'] = total_visuals
        
        # Determine primary visual type (priority order)
        if figures:
            visuals['visual_type'] = 'diagram'
            visuals['visual_title'] = f"Fig. {figures[0][0]}" + (f" - {figures[0][1].strip()}" if figures[0][1] else "")
        elif tables or md_tables:
            visuals['visual_type'] = 'table'
            if tables:
                visuals['visual_title'] = f"Table {tables[0][0]}" + (f" - {tables[0][1].strip()}" if tables[0][1] else "")
        elif diagrams:
            visuals['visual_type'] = 'chart'
            visuals['visual_title'] = f"Diagram {diagrams[0][0]}" + (f" - {diagrams[0][1].strip()}" if diagrams[0][1] else "")
        elif images:
            # NEW: Handle DeepSeek OCR image descriptions
            visuals['visual_type'] = 'image'
            # Clean up the description for title
            img_desc = images[0].strip()[:50]  # Limit to 50 chars
            visuals['visual_title'] = f"Image: {img_desc}..." if len(images[0]) > 50 else f"Image: {img_desc}"
    
    return visuals
