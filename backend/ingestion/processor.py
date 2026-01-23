from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat
from docling.document_converter import PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
import logging
import os
from typing import List, Dict, Any

logger = logging.getLogger("rag_chat_ipr.processor")

class DocumentProcessor:
    def __init__(self):
        # Configure Docling
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = True 
        pipeline_options.do_table_structure = True
        
        self.converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )

    def process_file(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Converts a file to chunks.
        Returns a list of dicts with 'text' and 'metadata'.
        """
        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()
        
        # Extension Whitelist (Docling + Fallbacks)
        # We ignore system files (.gitkeep, .txt-placeholders) silently
        if ext not in [".pdf", ".md", ".txt", ".docx", ".pptx", ".xlsx", ".html"]:
            logger.debug(f"Skipping unsupported file format: {ext}")
            return []

        logger.info(f"Processing file: {file_path}")
        try:
            # 🚀 PLATINUM FAST-PATH: Simple Text/Markdown
            if ext in [".txt", ".md"]:
                logger.info(f"Using fast-path for {ext} file.")
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    md_content = f.read()
            else:
                # Attempt 1: Full Pipeline (OCR + Tables)
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
            def split_text(text, max_size, overlap):
                chunks = []
                start = 0
                while start < len(text):
                    end = start + max_size
                    chunks.append(text[start:end])
                    if end >= len(text):
                        break
                    start = end - overlap
                return chunks

            if len(part) > 2000:
                # Save any existing chunk before split
                if current_chunk:
                    raw_chunks.append({
                        "text": current_chunk.strip(),
                        "path": current_path,
                        "level": len(header_stack)
                    })
                
                sub_chunks = split_text(part, 2000, 400)
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
            
            processed_chunks.append({
                "text": platinum_text,
                "metadata": {
                    "source": file_path,
                    "filename": filename,
                    "chunk_index": idx,
                    "section_path": path,
                    "header_level": chunk_data.get("level", 0),
                    "is_fragment": chunk_data.get("is_fragment", False)
                }
            })
        
        logger.info(f"Successfully processed {filename} into {len(processed_chunks)} hierarchical chunks.")
        return processed_chunks

