"""
Vision Handler Module - DeepSeek OCR Integration

This module provides high-fidelity OCR extraction using DeepSeek's Vision-Language Model
via Ollama. It converts PDF pages to images and processes them through the VLM to extract
structured markdown text.

Key Features:
- PDF to image conversion using PyMuPDF (300 DPI for Gundam mode)
- Base64 encoding for Ollama Vision API
- Async processing for non-blocking ingestion
- Page-by-page reconstruction into unified markdown
"""

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

import base64
import io
import logging
import asyncio
from typing import List, Optional


from backend.config import get_config
from backend.llm.client import OllamaClientWrapper

# DeepSeek OCR prompts for different extraction modes
PROMPTS = {
    "grounding": "<|grounding|>Convert the document to markdown. Preserve all tables, figures, and structure.",
    "parse_figure": "Parse the figure.",
    "describe": "Describe this image in detail.",
    "free_ocr": "Free OCR."
}

logger = logging.getLogger("rag_chat_ipr.vision_handler")


class VisionHandler:
    """
    Handles vision-based PDF extraction using DeepSeek OCR via Ollama.
    
    This is an alternative to the standard Docling pipeline for handling
    scanned documents, handwriting, and complex layouts.
    
    Features:
    - Two-pass extraction for unlabeled visuals
    - Adaptive DPI based on document size
    - Concurrent page processing
    """
    
    def __init__(self, dpi: int = 300):
        """
        Initialize VisionHandler with rendering settings.
        
        Args:
            dpi: Resolution for PDF rendering (300 for Gundam mode, 150 for large docs)
        """
        self.dpi = dpi
        self.config = get_config()
        
    def _render_pages_to_images(self, file_path: str) -> List[bytes]:
        """
        Convert PDF pages to high-resolution images.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            List of image bytes (PNG format)
        """
        if fitz is None:
            raise ImportError("PyMuPDF (fitz) is not installed. Please run: uv add pymupdf")

        images = []
        try:
            doc = fitz.open(file_path)
            
            # Adaptive DPI: Use lower resolution for large documents to save memory
            effective_dpi = self.dpi
            if len(doc) > 20:
                effective_dpi = 150
                logger.info(f"Large document ({len(doc)} pages), reducing DPI to {effective_dpi}")
            
            zoom = effective_dpi / 72  # 72 is the default PDF DPI
            matrix = fitz.Matrix(zoom, zoom)
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                pix = page.get_pixmap(matrix=matrix)
                
                # Convert to PNG bytes
                img_bytes = pix.tobytes("png")
                images.append(img_bytes)
                
                logger.debug(f"Rendered page {page_num + 1}/{len(doc)}")
                
            doc.close()
            
        except Exception as e:
            logger.error(f"Failed to render PDF pages: {e}")
            raise
            
        return images
    
    def _to_base64(self, image_bytes: bytes) -> str:
        """Convert image bytes to base64 string for Ollama API."""
        return base64.b64encode(image_bytes).decode('utf-8')
    
    async def _call_vlm(self, b64_image: str, prompt: str) -> str:
        """
        Call VLM via Ollama with specified prompt.
        
        Args:
            b64_image: Base64-encoded image string
            prompt: The prompt to use for extraction
            
        Returns:
            VLM response text
        """
        config = get_config()
        
        if not config.vlm_model:
            raise ValueError("VLM model not configured. Set RAG_VLM_HOST and RAG_VLM_MODEL in .env")
        
        try:
            import ollama
            
            # Create async client for VLM model
            client = ollama.AsyncClient(host=config.vlm_model.host)
            
            response = await client.chat(
                model=config.vlm_model.model_name,
                messages=[{
                    "role": "user",
                    "content": prompt,
                    "images": [b64_image]
                }]
            )
            
            return response['message']['content']
            
        except Exception as e:
            logger.error(f"VLM call failed: {e}")
            return ""
    
    def _has_unlabeled_visuals(self, markdown: str) -> bool:
        """
        Detect if the page likely contains unlabeled visuals.
        
        Checks for indicators like:
        - Very short text (likely just an image page)
        - Image placeholder patterns from DeepSeek OCR
        - Low text-to-page ratio
        """
        import re
        
        if not markdown or len(markdown.strip()) < 50:
            # Very little text - likely an image-heavy page
            return True
        
        # Check for DeepSeek OCR image placeholder patterns
        image_patterns = [
            r'>\s*\[Image:',  # Recognized but undescribed image
            r'\[Figure\s*\]',  # Empty figure reference
            r'\[Diagram\s*\]',  # Empty diagram reference
            r'<image>',  # Raw image tag
            r'\[.*image.*\]',  # Generic image bracket
        ]
        
        for pattern in image_patterns:
            if re.search(pattern, markdown, re.IGNORECASE):
                return True
        
        # Check text density - if markdown is mostly whitespace/formatting
        text_only = re.sub(r'[#\|\-\*\s]+', '', markdown)
        if len(text_only) < len(markdown) * 0.3:  # Less than 30% actual text
            return True
        
        return False
    
    async def _enrich_with_descriptions(self, page_idx: int, b64_image: str, original_md: str) -> str:
        """
        Enrich a page with visual descriptions using second-pass VLM call.
        
        Args:
            page_idx: Page index for logging
            b64_image: Base64-encoded image
            original_md: Original markdown from first pass
            
        Returns:
            Enriched markdown with visual descriptions
        """
        logger.info(f"[VISION] Pass 2: Enriching page {page_idx + 1} with visual descriptions")
        
        # Use "Describe this image" for detailed visual analysis
        description = await self._call_vlm(b64_image, PROMPTS["describe"])
        
        if description.strip():
            # Append the description as a visual context block
            enriched = original_md + f"\n\n> [Visual Description]\n> {description.strip()}"
            return enriched
        
        return original_md
    
    async def process_pdf_with_vision(self, file_path: str) -> str:
        """
        Process an entire PDF using vision-based OCR.
        
        The processing strategy depends on RAG_VLM_PROMPT setting:
        - "auto": Two-pass (grounding + detect/describe unlabeled visuals)
        - "grounding": Single-pass document-to-markdown (fastest)
        - "describe": Single-pass detailed image description (slowest)
        - "parse_figure": Single-pass figure/chart parsing
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            Complete markdown text of the document
        """
        config = get_config()
        prompt_strategy = config.vlm_prompt
        
        logger.info(f"[VISION] Processing PDF with strategy '{prompt_strategy}': {file_path}")
        
        # 1. Render all pages to images
        page_images = self._render_pages_to_images(file_path)
        logger.info(f"[VISION] Rendered {len(page_images)} pages")
        
        CONCURRENCY_LIMIT = 3
        
        # Determine the primary prompt based on strategy
        if prompt_strategy == "auto":
            primary_prompt = PROMPTS["grounding"]
        elif prompt_strategy in PROMPTS:
            primary_prompt = PROMPTS[prompt_strategy]
        else:
            primary_prompt = PROMPTS["grounding"]  # Fallback
        
        # 2. PASS 1: Process each page with selected prompt
        markdown_pages = []
        b64_images = []  # Store for potential pass 2 (auto mode only)
        
        for i in range(0, len(page_images), CONCURRENCY_LIMIT):
            batch = page_images[i:i + CONCURRENCY_LIMIT]
            b64_batch = [self._to_base64(img) for img in batch]
            b64_images.extend(b64_batch)
            
            # Process batch concurrently with selected prompt
            results = await asyncio.gather(*[
                self._call_vlm(b64_img, primary_prompt) for b64_img in b64_batch
            ])
            
            markdown_pages.extend(results)
            logger.info(f"[VISION] Pass 1 ({prompt_strategy}): Processed pages {i+1}-{min(i+CONCURRENCY_LIMIT, len(page_images))}/{len(page_images)}")
        
        # 3. PASS 2: Only for "auto" mode - enrich pages with unlabeled visuals
        if prompt_strategy == "auto":
            enriched_pages = []
            pages_needing_enrichment = []
            
            for idx, (md, b64_img) in enumerate(zip(markdown_pages, b64_images)):
                if self._has_unlabeled_visuals(md):
                    pages_needing_enrichment.append((idx, b64_img, md))
                    enriched_pages.append(None)  # Placeholder
                else:
                    enriched_pages.append(md)
            
            if pages_needing_enrichment:
                logger.info(f"[VISION] Pass 2: {len(pages_needing_enrichment)} pages need visual enrichment")
                
                # Process enrichment concurrently
                enrichment_results = await asyncio.gather(*[
                    self._enrich_with_descriptions(idx, b64_img, md)
                    for idx, b64_img, md in pages_needing_enrichment
                ])
                
                # Fill in the enriched pages
                for (idx, _, _), enriched_md in zip(pages_needing_enrichment, enrichment_results):
                    enriched_pages[idx] = enriched_md
            
            final_pages = enriched_pages
        else:
            # Non-auto modes: just use Pass 1 results
            final_pages = markdown_pages
        
        # 4. Concatenate all pages with page separators
        full_markdown = "\n\n---\n\n".join([
            f"<!-- Page {i+1} -->\n{md}" 
            for i, md in enumerate(final_pages) 
            if md and md.strip()
        ])
        
        logger.info(f"[VISION] Extraction complete. Total length: {len(full_markdown)} chars")
        
        return full_markdown


    
    async def is_available(self) -> bool:
        """Check if the VLM model is available and responding."""
        config = get_config()
        
        if not config.vlm_model:
            return False
            
        try:
            import ollama
            client = ollama.AsyncClient(host=config.vlm_model.host)
            
            # Simple ping to check if model exists
            models = await client.list()
            model_names = [m['name'] for m in models.get('models', [])]
            
            return config.vlm_model.model_name in model_names
            
        except Exception as e:
            logger.warning(f"VLM model availability check failed: {e}")
            return False

