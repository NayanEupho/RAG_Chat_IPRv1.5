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
        logger.info(f"Processing file: {file_path}")
        try:
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
        
        # Smarter Hierarchical Chunking
        # We look for markdown headers to keep sections together
        import re
        
        # Split by H1, H2, or H3 headers but keep the headers in the chunks
        header_pattern = r'(?m)^(#{1,3} .*)$'
        parts = re.split(header_pattern, md_content)
        
        raw_chunks = []
        current_header = "Intro"
        current_chunk = ""
        
        for part in parts:
            if not part.strip():
                continue
            
            # If it's a header, update the tracked header
            is_header = bool(re.match(header_pattern, part))
            if is_header:
                if current_chunk:
                    raw_chunks.append(f"[Section: {current_header}]\n{current_chunk.strip()}")
                current_header = part.strip().replace('#', '').strip()
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
                # If we had a previous chunk, save it
                if current_chunk:
                    raw_chunks.append(f"[Section: {current_header}]\n{current_chunk.strip()}")
                
                # Split the large part
                sub_chunks = split_text(part, 2000, 400)
                for i, sc in enumerate(sub_chunks):
                    if i < len(sub_chunks) - 1:
                        raw_chunks.append(f"[Section: {current_header} (cont.)]\n{sc.strip()}")
                    else:
                        current_chunk = sc # Keep last sub-chunk for next iteration
            else:
                # Normal accumulation
                if len(current_chunk) + len(part) > 2000:
                    if current_chunk:
                        raw_chunks.append(f"[Section: {current_header}]\n{current_chunk.strip()}")
                        overlap_text = current_chunk[-400:] if len(current_chunk) > 400 else current_chunk
                        current_chunk = overlap_text + "\n" + part
                    else:
                        current_chunk = part
                else:
                    current_chunk += "\n" + part
        
        if current_chunk:
            raw_chunks.append(f"[Section: {current_header}]\n{current_chunk.strip()}")
            
        filename = os.path.basename(file_path)
        processed_chunks = []
        
        for idx, text in enumerate(raw_chunks):
            processed_chunks.append({
                "text": text,
                "metadata": {
                    "source": file_path,
                    "filename": filename,
                    "chunk_index": idx
                }
            })
        
        logger.info(f"Successfully processed {filename} into {len(processed_chunks)} hierarchical chunks.")
        return processed_chunks

