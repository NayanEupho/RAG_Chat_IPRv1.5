from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat
from docling.document_converter import PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
import logging
import os
import asyncio
from typing import List, Dict, Any

from backend.config import get_config
from backend.ingestion.markdown_sanitizer import detect_visual_elements

logger = logging.getLogger("rag_chat_ipr.processor")


class DocumentProcessor:
    def __init__(self):
        # Configure Docling (default OCR engine)
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = True 
        pipeline_options.do_table_structure = True
        
        self.converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        
        # Vision handler is lazy-loaded only when needed
        self._vision_handler = None
    
    def _get_vision_handler(self):
        """Lazy-load VisionHandler to avoid import overhead when not using deepseek."""
        if self._vision_handler is None:
            from backend.ingestion.vision_handler import VisionHandler
            self._vision_handler = VisionHandler()
        return self._vision_handler
    
    async def _extract_with_vision(self, file_path: str) -> str:
        """Extract markdown using DeepSeek OCR vision pipeline."""
        handler = self._get_vision_handler()
        return await handler.process_pdf_with_vision(file_path)

    def process_file(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Converts a file to chunks.
        Returns a list of dicts with 'text' and 'metadata'.
        
        OCR Engine Selection (via .env):
        - RAG_VLM_MODEL="False": (default) Uses Docling text-based extraction
        - RAG_VLM_MODEL="deepseek-ocr:3b": Uses VLM OCR for high-fidelity extraction
        """

        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()
        
        # Extension Whitelist (Docling + Fallbacks)
        # We ignore system files (.gitkeep, .txt-placeholders) silently
        if ext not in [".pdf", ".md", ".txt", ".docx", ".pptx", ".xlsx", ".html"]:
            logger.debug(f"Skipping unsupported file format: {ext}")
            return []

        logger.info(f"Processing file: {file_path}")
        
        # Get configuration
        config = get_config()
        
        try:
            # 🚀 PLATINUM FAST-PATH: Simple Text/Markdown
            if ext in [".txt", ".md"]:
                logger.info(f"Using fast-path for {ext} file.")
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    md_content = f.read()
            
            # 🔬 VISION PATH: VLM OCR for PDFs (when enabled)
            elif ext == ".pdf" and config.is_vlm_enabled:
                logger.info(f"[VLM] Using VLM OCR engine ({config.vlm_model.model_name}) for {filename}")
                
                # Run async vision extraction in sync context
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    md_content = loop.run_until_complete(self._extract_with_vision(file_path))
                finally:
                    loop.close()
                
                # Apply conservative sanitization
                from backend.ingestion.markdown_sanitizer import sanitize_markdown
                md_content = sanitize_markdown(md_content)
                
            else:

                # Default: Docling Pipeline (OCR + Tables)
                result = self.converter.convert(file_path)
                doc = result.document
                
                try:
                    md_content = doc.export_to_markdown()
                except Exception as e:
                    logger.warning(f"Markdown export failed for {file_path}, falling back to raw text: {e}")
                    # Fallback: Just get raw text from all items
                    texts = []
                    for item, _ in doc.iterate_items():
                        if hasattr(item, 'text'):
                            texts.append(item.text)
                    md_content = "\n\n".join(texts)
                
            if not md_content.strip():
                raise ValueError("Extracted content is empty.")

            # DEBUG: Save generated Markdown to disk for inspection
            try:
                debug_dir = "VLM_generated_md_docs"
                os.makedirs(debug_dir, exist_ok=True)
                
                # Sanitize filename for disk storage (Remove illegal OS chars)
                safe_filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
                out_filename = f"{safe_filename}.md"
                out_path = os.path.join(debug_dir, out_filename)
                
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(md_content)
                logger.info(f"Saved debug markdown to: {out_path}")
            except Exception as e:
                logger.warning(f"Failed to save debug markdown: {e}")
                
        except Exception as e:
            logger.warning(f"Full pipeline failed for {file_path}: {e}")
            logger.info("Retrying with basic pipeline (No OCR/Tables)...")
            try:
                # Attempt 2: Basic Pipeline (Fast, less features)
                basic_options = PdfPipelineOptions()
                basic_options.do_ocr = False
                basic_options.do_table_structure = False
                
                fallback_converter = DocumentConverter(
                    format_options={
                        InputFormat.PDF: PdfFormatOption(pipeline_options=basic_options)
                    }
                )
                result = fallback_converter.convert(file_path)
                doc = result.document
                md_content = doc.export_to_markdown()
                logger.info("Basic pipeline succeeded.")
            except Exception as e2:
                 logger.error(f"All docling attempts failed for {file_path}. Error: {e2}")
                 # LAST RESORT: Try pypdf (pure python, very robust for text)
                 try:
                    import pypdf
                    logger.info("Retrying with pypdf fallback...")
                    reader = pypdf.PdfReader(file_path)
                    texts = []
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            texts.append(page_text)
                    md_content = "\n\n".join(texts)
                    if md_content.strip():
                        logger.info("Successfully extracted text via pypdf.")
                    else:
                        return []
                 except Exception as ep:
                    logger.error(f"pypdf fallback also failed: {ep}")
                    return []

        # Simple chunking by iterating over texts for now
        # ... (rest of processing)
        
        # Smarter Hierarchical Chunking (Platinum Implementation)
        # We look for markdown headers to build a recursive breadcrumb path
        import re
        
        # Split by H1 to H6 headers but keep the headers in the chunks
        # Regex updated to support H6 and optional space after '#'
        header_pattern = r'(?m)^(#{1,6}\s?.*)$'
        parts = re.split(header_pattern, md_content)
        
        raw_chunks = []
        header_stack = [] # Tracks levels: [H1, H2, H3, H4, H5, H6]
        current_path = "Intro"
        current_chunk = ""
        
        def get_breadcrumb(stack):
            return " > ".join(stack) if stack else "Intro"

        for part in parts:
            if not part.strip():
                continue
            
            # If it's a header, update the tracked header stack
            is_header = bool(re.match(header_pattern, part))
            if is_header:
                # Save previous accumulated chunk before switching path
                if current_chunk:
                    raw_chunks.append({
                        "text": current_chunk.strip(),
                        "path": current_path,
                        "level": len(header_stack)
                    })
                
                # Determine header level by counting '#'
                level = part.count('#')
                title = part.strip().lstrip('#').strip()
                
                # Update stack: keep parents, replace same-level or deeper
                # Note: header_stack uses 0-indexing, level is 1-6
                header_stack = header_stack[:level-1] + [title]
                current_path = get_breadcrumb(header_stack)
                current_chunk = ""
                continue

            # If the part itself is very large, we must split it recursively
            # Visual-Boundary-Aware Splitting: Prevents fragmentation of tables/figures
            def detect_visual_blocks(text):
                """
                Detect visual elements (tables, figures) and return their spans.
                Returns list of (start, end) tuples for visual blocks.
                """
                import re
                visual_spans = []
                
                # Detect markdown tables (| --- | format)
                # Match from first | to last | in a table block
                table_pattern = re.compile(
                    r'(\|[^\n]+\|\n)+',  # Consecutive lines starting and ending with |
                    re.MULTILINE
                )
                for match in table_pattern.finditer(text):
                    visual_spans.append((match.start(), match.end()))
                
                # Detect figure captions and their descriptions
                # Figure X: ... or Fig. X: ... followed by content until next header or double newline
                figure_pattern = re.compile(
                    r'((?:Figure|Fig\.?)\s*\d+[:\-.].*?)(?=\n\n|\n#|$)',
                    re.IGNORECASE | re.DOTALL
                )
                for match in figure_pattern.finditer(text):
                    # Avoid overlapping with tables
                    if not any(s <= match.start() < e for s, e in visual_spans):
                        visual_spans.append((match.start(), match.end()))
                
                return sorted(visual_spans, key=lambda x: x[0])
            
            def split_text_visual_aware(text, max_size, overlap):
                """
                Split text while respecting visual block boundaries.
                Visual blocks are kept intact even if slightly larger than max_size.
                """
                visual_spans = detect_visual_blocks(text)
                chunks = []
                start = 0
                prev_start = -1  # Track previous position for infinite loop guard
                
                while start < len(text):
                    end = start + max_size
                    
                    # Check if we're about to split inside a visual block
                    for v_start, v_end in visual_spans:
                        # If end falls within a visual block, extend to include the whole block
                        if v_start < end < v_end:
                            end = v_end
                            break
                        # If start falls within a visual block, include the whole block
                        if v_start < start < v_end:
                            start = v_start
                            end = max(end, v_end)
                            break
                    
                    # Ensure we don't exceed text length
                    end = min(end, len(text))
                    
                    chunk_text = text[start:end]
                    if chunk_text.strip():
                        chunks.append(chunk_text)
                    
                    if end >= len(text):
                        break
                    
                    # Apply overlap, but don't go back into a visual block
                    new_start = end - overlap
                    # Ensure we don't start in the middle of a visual block
                    for v_start, v_end in visual_spans:
                        if v_start < new_start < v_end:
                            new_start = v_end  # Start after the visual block
                            break
                    
                    start = max(new_start, end - overlap)
                    # Guard against infinite loop
                    if start <= prev_start:
                        start = end  # Force progress
                    if start >= len(text):
                        break
                    prev_start = start

                
                return chunks if chunks else [text]

            if len(part) > 2000:
                # Save any existing chunk before split
                if current_chunk:
                    raw_chunks.append({
                        "text": current_chunk.strip(),
                        "path": current_path,
                        "level": len(header_stack)
                    })
                
                # Use visual-aware splitting
                sub_chunks = split_text_visual_aware(part, 2000, 400)
                for i, sc in enumerate(sub_chunks):
                    is_frag = i < len(sub_chunks) - 1
                    raw_chunks.append({
                        "text": sc.strip(),
                        "path": current_path + (f" (Part {i+1})" if len(sub_chunks) > 1 else ""),
                        "level": len(header_stack),
                        "is_fragment": True if i > 0 else False
                    })
                current_chunk = "" # Reset after large split

            else:
                # Normal accumulation within current section
                if len(current_chunk) + len(part) > 2000:
                    if current_chunk:
                        raw_chunks.append({
                            "text": current_chunk.strip(),
                            "path": current_path,
                            "level": len(header_stack)
                        })
                        overlap_text = current_chunk[-400:] if len(current_chunk) > 400 else current_chunk
                        current_chunk = overlap_text + "\n" + part
                    else:
                        current_chunk = part
                else:
                    current_chunk += "\n" + part
        
        if current_chunk:
            raw_chunks.append({
                "text": current_chunk.strip(),
                "path": current_path,
                "level": len(header_stack)
            })
            
        filename = os.path.basename(file_path)
        processed_chunks = []
        
        for idx, chunk_data in enumerate(raw_chunks):
            # Platinum Prefix Injunction: [Doc: file | Path: path]
            path = chunk_data["path"]
            content = chunk_data["text"]
            platinum_text = f"[Doc: {filename} | Path: {path}]\n{content}"
            
            # Detect visual elements in this chunk
            visual_info = detect_visual_elements(content)
            
            processed_chunks.append({
                "text": platinum_text,
                "metadata": {
                    "source": file_path,
                    "filename": filename,
                    "chunk_index": idx,
                    "section_path": path,
                    "header_level": chunk_data.get("level", 0),
                    "is_fragment": chunk_data.get("is_fragment", False),
                    # Visual element metadata
                    "has_visual": visual_info.get("has_visual", False),
                    "visual_type": visual_info.get("visual_type"),
                    "visual_title": visual_info.get("visual_title"),
                    "visual_count": visual_info.get("visual_count", 0)
                }
            })

        
        logger.info(f"Successfully processed {filename} into {len(processed_chunks)} hierarchical chunks.")
        return processed_chunks

