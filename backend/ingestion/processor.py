"""
Document Processing and Optimization Engine
------------------------------------------
This module handles the transformation of raw files (PDF, DOCX, etc.) into 
clean, hierarchical Markdown chunks suitable for vector embedding.
It includes advanced features like:
- Hardware-accelerated parsing via Docling.
- Smart OCR detection for scanned documents.
- Viterbi-based word segmentation for repairing structural artifacts.
- Platinum Hierarchical Chunking for preserving document context.
"""

from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat
from docling.document_converter import PdfFormatOption
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions, 
    AcceleratorOptions, 
    AcceleratorDevice,
    RapidOcrOptions,
    EasyOcrOptions,
    TesseractOcrOptions,
    TableFormerMode,
    TableStructureOptions
)
import logging
import os
import re
import html
from typing import List, Dict, Any, Optional
import torch
import multiprocessing
import math
from functools import lru_cache
from backend.config import get_config

# --- Probabilistic Viterbi Segmenter (Zero-Dependency) ---
class ViterbiSegmenter:
    """
    Elegant word segmentation using dynamic programming and unigram probabilities.
    Automatically repairs 'mashed' words (e.g., 'policyoverview' -> 'policy overview')
    by finding the most likely word sequence based on a Zipf-based language model.
    """
    def __init__(self):
        # Top 1000+ common words for high-fidelity split-guarding.
        # This acts as our "Language Model" to verify candidate words.
        # Sources: Google Trillion Word Corpus (Frequency-based subset)
        self.words = {
            "the", "of", "and", "to", "in", "is", "that", "it", "as", "for", "was", "with", "on", "are", "by", 
            "be", "this", "from", "at", "not", "or", "an", "have", "we", "can", "but", "all", "your", "if", 
            "their", "their", "will", "what", "there", "out", "been", "up", "about", "who", "more", "now",
            "isolated", "issue", "theory", "theatre", "today", "towards", "together", "install", "already", 
            "offered", "intended", "information", "important", "infrastructure", "instead", "into", 
            "increase", "indeed", "inside", "impact", "office", "official", "often", "introduction",
            "report", "overview", "policy", "guideline", "system", "architecture", "component", "platform",
            "service", "api", "database", "security", "network", "deployment", "configuration", "format",
            "standard", "protocol", "campus", "academic", "program", "faculty", "student", "research",
            "quick", "brown", "fox", "secure", "theory", "is", "this",
            "chroma", "ollama", "langgraph", "json", "sql", "sqlite", "vector", "embedding", "viterbi",
            "pydantic", "fastapi", "uvicorn", "asyncio", "threading", "multiprocessing", "watcher"
        }
        # Simplified probability model: Zipf's Law approximation
        # log(freq) is used to avoid floating point underflow
        self.word_model = {w: -math.log(i + 1) for i, w in enumerate(list(self.words))}
        self.total_words = len(self.words)
        self.max_word_len = 20

    @lru_cache(maxsize=1024)
    def segment(self, text: str) -> str:
        if not text: return ""
        if len(text) < 3: return text
        
        # If the word is already valid, don't touch it (Split-Guard)
        if text.lower() in self.words:
            return text

        # Logic: Find most likely path of words
        # Penalty for unknown words (high multiplier favors splitting known words)
        # Using a very high multiplier (1,000,000) to ensure multiple known words 
        # are almost always preferred over a single unknown mashed block.
        unknown_penalty = -math.log(self.total_words * 1000000)
        
        probs = [0.0] + [float('-inf')] * len(text)
        last = [0] * (len(text) + 1)
        
        for i in range(1, len(text) + 1):
            for j in range(max(0, i - self.max_word_len), i):
                word = text[j:i].lower()
                # Probability: Zipf Log + Length Bias (prefer longer words)
                word_prob = self.word_model.get(word, unknown_penalty)
                prob = probs[j] + word_prob
                
                if prob > probs[i]:
                    probs[i] = prob
                    last[i] = j
        
        # Backtrack
        res = []
        curr = len(text)
        while curr > 0:
            res.append(text[last[curr]:curr])
            curr = last[curr]
            
        return " ".join(reversed(res))

# Singleton for global reuse to maintain cache efficiency
viterbi = ViterbiSegmenter()

logger = logging.getLogger("rag_chat_ipr.processor")

class DocumentProcessor:
    """
    Orchestrates the conversion and refinement of documents.
    Detects hardware capabilities and chooses the optimal parsing strategy 
    (Digital vs. Scanned vs. Structured Fallbacks).
    """
    def __init__(self):
        # 1. Hardware Detection Strategy (Audit Refined: Centralized Config)
        cfg = get_config()
        force_cpu = cfg.ingest_force_cpu
        
        if force_cpu:
            self.device = AcceleratorDevice.CPU
            logger.info("[DOCLING] Manual CPU Override Enabled (INGEST_FORCE_CPU=true)")
        elif torch.cuda.is_available():
            self.device = AcceleratorDevice.CUDA
            device_name = torch.cuda.get_device_name(0)
            logger.info(f"[DOCLING] GPU Acceleration Enabled (CUDA: {device_name})")
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            # Support for Apple Silicon
            try:
                self.device = AcceleratorDevice.MPS
                logger.info("[DOCLING] Apple Silicon Acceleration Enabled (MPS)")
            except Exception:
                # Fallback if docling version doesn't support MPS enum yet
                self.device = AcceleratorDevice.CPU
                logger.warning("[DOCLING] MPS detected but enum not supported. Falling back to CPU.")
        else:
            self.device = AcceleratorDevice.CPU
            logger.info("[DOCLING] No hardware accelerator found. Using CPU.")
            
        # 2. Dynamic Threading Selection
        if self.device == AcceleratorDevice.CPU:
            # Parallelize across cores, but cap to avoid context-switch overhead
            self.num_threads = min(multiprocessing.cpu_count(), 8)
            logger.info(f"[DOCLING] CPU Threading optimized: {self.num_threads} threads.")
        else:
            # Accelerators handle batching; high CPU threading causes congestion
            self.num_threads = 4
            
        # Consolidate Accelerator Options
        self.accelerator_options = AcceleratorOptions(
            num_threads=self.num_threads, device=self.device
        )
            
    def _is_scanned_pdf(self, file_path: str) -> bool:
        """
        Detects if a PDF is scanned (image-based) or digital (text-based).
        Returns True if OCR is required (scanned), False if digital.
        Uses PyMuPDF (fitz) for fast inspection.
        """
        try:
            import fitz
            doc = fitz.open(file_path)
            pages_to_check = min(3, len(doc))
            
            text_content = ""
            for i in range(pages_to_check):
                text_content += doc[i].get_text()
            
            doc.close()
            
            # Heuristic: If we extracted less than 50 chars from up to 3 pages, it's likely scanned
            if len(text_content.strip()) < 50:
                logger.info(f"[SMART OCR] Low text density ({len(text_content.strip())} chars). Treating as SCANNED.")
                return True
            
            logger.info(f"[SMART OCR] High text density detected. Treating as DIGITAL.")
            return False
            
        except Exception as e:
            logger.warning(f"[SMART OCR] Detection failed: {e}. Defaulting to OCR enabled.")
            return True

    def _get_available_ocr_engine(self):
        """Detects the best available OCR engine supported by the environment."""
        import importlib.util
        
        has_easyocr = importlib.util.find_spec("easyocr") is not None
        has_rapidocr = importlib.util.find_spec("rapidocr_onnxruntime") is not None
        
        # Priority 1: EasyOCR on GPU
        if self.device != AcceleratorDevice.CPU and has_easyocr:
            logger.debug(f"[DOCLING] Selected Engine: EasyOCR (Hardware: {self.device})")
            return EasyOcrOptions()
            
        # Priority 2: RapidOCR (Fast on CPU/GPU)
        if has_rapidocr:
            logger.debug(f"[DOCLING] Selected Engine: RapidOCR (Hardware: {self.device})")
            return RapidOcrOptions()
            
        # Priority 3: EasyOCR on CPU (Fallback)
        if has_easyocr:
            logger.debug("[DOCLING] Selected Engine: EasyOCR (CPU Fallback)")
            return EasyOcrOptions()
            
        # Priority 4: Tesseract (Last Resort)
        has_tesseract = importlib.util.find_spec("pytesseract") is not None
        if has_tesseract:
            logger.debug("[DOCLING] Selected Engine: Tesseract")
            return TesseractOcrOptions()
            
        logger.warning("⚠️ [DOCLING] No OCR engines found (easyocr, rapidocr, pytesseract). Docling will use built-in defaults.")
        return None # Defaults to Docling's internal selection

    def _get_converter(self, enable_ocr: bool = False, force_ocr: bool = False, ocr_scale: float = 2.0) -> DocumentConverter:
        """Dynamically builds the converter based on requirements."""
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = enable_ocr
        if force_ocr:
            pipeline_options.ocr_options.force_full_page_ocr = True
            
        # 3. Resilient OCR Engine Selection
        ocr_engine = self._get_available_ocr_engine()
        if ocr_engine:
            pipeline_options.ocr_options = ocr_engine
        
        # 4. High-Resolution OCR (Configurable scale, defaults to 2.0 for clarity)
        if enable_ocr:
            pipeline_options.images_scale = ocr_scale
            
        # 5. Enhanced Table Extraction (ACCURATE mode for complex tables)
        pipeline_options.do_table_structure = True
        pipeline_options.table_structure_options = TableStructureOptions(
            mode=TableFormerMode.ACCURATE,  # Better multi-row header handling
            do_cell_matching=True           # Match cells to column headers
        )
        
        # GPU / CPU Accelerator Configuration
        pipeline_options.accelerator_options = self.accelerator_options
        
        return DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )

    def process_file(self, file_path: str, chunk_size: int = 1000, chunk_overlap: int = 200, mode: str = "auto") -> List[Dict]:
        """
        Ingests a file, converts it to Markdown, cleans it, and splits it into chunks.
        Mode: 'auto' (Hybrid), 'pymupdf4llm' (Force PyMuPDF), 'docling_vision' (Force OCR)
        """
        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()
        
        logger.info(f"Processing {filename} [Mode: {mode.upper()}]...")
        
        # Extension Whitelist (Docling + Fallbacks)
        if ext not in [".pdf", ".md", ".txt", ".docx", ".pptx", ".xlsx", ".html"]:
            logger.debug(f"Skipping unsupported file format: {ext}")
            return []

        try:
            # --- [CONVERSION STAGE] ---
            source_type = "docling" # Default
            md_content = ""
            
            if ext == ".txt":
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    md_content = f.read()
                source_type = "fastpath"
            
            elif ext == ".pdf":
                
                # Check for cached digital text first? No, we need Docling's output to validat quality.
                # Actually, for pure speed, we could try PyMuPDF first, but user wants "Both".
                # Let's stick to Docling Primary.
                
                logger.info(f"Initializing Docling Primary Pipeline... OCR={'ON' if needs_ocr else 'OFF'}")
                try:
                    converter = self._get_converter(enable_ocr=needs_ocr)
                    result = converter.convert(file_path)
                    doc = result.document
                    md_content = doc.export_to_markdown()
                    
                    # --- [Quality Gate] ---
                    # Check for artifacts (Mushing, Encoding errors, Missing headers)
                    quality_issues = self._should_retry_with_vision(md_content) # Reusing this detector
                    
                    if not needs_ocr and quality_issues:
                        logger.warning(f"[QUALITY] Detected potential text issues in Docling output for {filename}.")
                        
                        # Tier 1 Rescue: PyMuPDF4LLM (Digital Text Specialist)
                        try:
                            logger.info("Attempting Tier 1 Rescue: PyMuPDF4LLM...")
                            import pymupdf4llm
                            pymu_md = pymupdf4llm.to_markdown(file_path)
                            
                            # Verify PyMuPDF result isn't empty or garbage
                            if pymu_md and len(pymu_md) > 100:
                                logger.info("✅ Tier 1 Rescue Successful: Switched to PyMuPDF4LLM output.")
                                md_content = pymu_md
                                source_type = "pymupdf4llm"
                                # Clear flag fallback to vision
                                quality_issues = False 
                        except Exception as ep:
                            logger.warning(f"Tier 1 Rescue failed: {ep}")

                    # Tier 2 Rescue: Vision / OCR (If Tier 1 didn't solve it or wasn't applicable)
                    if not needs_ocr and quality_issues:
                        logger.info(f"[VISION] Tier 1 failed or insufficient. escalating to Tier 2: Vision-First (Scale=3.0)...")
                        converter = self._get_converter(enable_ocr=True, force_ocr=True, ocr_scale=3.0)
                        result = converter.convert(file_path)
                        md_content = result.document.export_to_markdown()
                        source_type = "docling_vision"

                except RuntimeError as e:
                    # [CRASH RECOVERY] Handle "Invalid code point" or Preprocess failures
                    err_msg = str(e).lower()
                    if "invalid code point" in err_msg or "preprocess failed" in err_msg:
                        logger.warning(f"[RECOVERY] Unicode corruption detected in {filename}. Forcing Vision-First recovery...")
                        converter = self._get_converter(enable_ocr=True, force_ocr=True, ocr_scale=3.0)
                        result = converter.convert(file_path)
                        source_type = "docling_recovery"
                        md_content = result.document.export_to_markdown()
                    else:
                        raise e
                    
                # --- [Refinement Layer] ---
                md_content = self._clean_markdown_artifacts(md_content)
                md_content = self._fix_header_hierarchy(md_content)
                
            # OTHER FORMATS (Docx, PPTX, etc) - Default to standard converter
            else:
                logger.info(f"Using standard Docling pipeline for {ext}")
                converter = self._get_converter(enable_ocr=True) # Usually safe to leave OCR on for images in PPTs
                result = converter.convert(file_path)
                doc = result.document
                md_content = doc.export_to_markdown()

            if not md_content.strip():
                raise ValueError("Extracted content is empty.")
                
        except Exception as e:
            logger.warning(f"Primary pipeline failed for {file_path}: {e}")
            logger.info("Retrying with PyMuPDF4LLM fallback...")
            source_type = "pymupdf4llm_fallback"
            try:
                import pymupdf4llm
                md_content = pymupdf4llm.to_markdown(file_path)
                
                if not md_content.strip():
                    logger.warning("PyMuPDF4LLM extracted empty content.")
                    return []
                    
                logger.info("Successfully extracted text via PyMuPDF4LLM.")
            except Exception as ep:
                logger.error(f"PyMuPDF4LLM fallback also failed: {ep}")
                return []

        # --- DEBUG: Save Intermediate Markdown ---
        try:
            debug_dir = os.path.join(os.getcwd(), "generated_doc_md")
            if not os.path.exists(debug_dir):
                os.makedirs(debug_dir)
            
            base_name = os.path.splitext(filename)[0]
            debug_filename = f"{base_name}_{source_type}.md"
            debug_path = os.path.join(debug_dir, debug_filename)
            
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            logger.info(f"🔬 [DEBUG] Saved intermediate Markdown to: {debug_path}")
        except Exception as edebug:
            logger.warning(f"Failed to save debug Markdown: {edebug}")

        # --- NEW: Folder-Based Strategy Selection ---
        normalized_path = file_path.replace('\\', '/')
        if '/qna/' in normalized_path.lower():
            logger.info(f"Folder-based routing: Treating {filename} as Q&A document.")
            qna_chunks = self.process_qna_content(md_content, file_path)
            if qna_chunks:
                return qna_chunks
            logger.info(f"No Q&A patterns found in {filename}, falling back to hierarchical chunking.")

        # Smarter Hierarchical Chunking (Platinum Implementation)
        import re
        
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
                
                header_stack = header_stack[:level-1] + [title]
                current_path = get_breadcrumb(header_stack)
                current_chunk = ""
                continue

            def smart_split_text(text, max_size, overlap):
                """
                Splits text with STRICT TABLE ISOLATION and FRE Metadata.
                """
                lines = text.split('\n')
                chunks = []
                current_chunk = []
                current_len = 0
                
                in_table = False
                table_header = [] 

                for i, line in enumerate(lines):
                    line_len = len(line) + 1 
                    is_table_row = line.strip().startswith('|')
                    
                    if is_table_row and not in_table:
                        in_table = True
                        if current_chunk:
                            chunks.append({
                                'text': '\n'.join(current_chunk),
                                'is_fragment': False,
                                'has_table': False
                            })
                            current_chunk = []
                            current_len = 0

                        # STICKY CAPTION & MULTI-LINE HEADER
                        caption_lines = []
                        if i > 0 and lines[i-1].strip():
                             prev_line = lines[i-1].strip()
                             if len(prev_line) < 100 or prev_line.lower().startswith("table") or prev_line.startswith("#"):
                                 caption_lines.insert(0, lines[i-1])
                                 current_chunk.extend(caption_lines)
                                 current_len += sum(len(c)+1 for c in caption_lines)
                        
                        # Capture FULL table header (Caption + Headers + Separator)
                        table_header = caption_lines + [line]
                        if i + 1 < len(lines) and '---' in lines[i+1]:
                             table_header.append(lines[i+1])

                    if not is_table_row and in_table:
                        in_table = False
                        table_header = []
                        if current_chunk:
                            chunks.append({
                                'text': '\n'.join(current_chunk),
                                'is_fragment': False,
                                'has_table': True
                            })
                            current_chunk = []
                            current_len = 0
                            
                    if current_len + line_len > max_size:
                        if current_chunk:
                            chunks.append({
                                'text': '\n'.join(current_chunk),
                                'is_fragment': True,
                                'has_table': in_table
                            })
                        current_chunk = []
                        current_len = 0
                        if in_table and table_header:
                            current_chunk.extend(table_header)
                            current_len += sum(len(h) + 1 for h in table_header)

                    current_chunk.append(line)
                    current_len += line_len

                if current_chunk:
                    chunks.append({
                        'text': '\n'.join(current_chunk),
                        'is_fragment': len(chunks) > 0,
                        'has_table': in_table
                    })
                
                # Add indices
                for idx, c in enumerate(chunks):
                    c['fragment_index'] = idx
                    c['total_fragments'] = len(chunks)
                
                return chunks

            # Trigger Smart Split if:
            # 1. Section is too large (needs chunking)
            # 2. Section contains a Table (needs Isolation/Sticky headers)
            has_table_marker = bool(re.search(r'(?m)^\|', part))
            
            if len(part) > 2000 or has_table_marker:
                # Save any existing chunk before split
                if current_chunk:
                    has_table_simple = '|' in current_chunk
                    raw_chunks.append({
                        "text": current_chunk.strip(),
                        "path": current_path,
                        "level": len(header_stack),
                        "has_table": has_table_simple
                    })
                
                sub_chunks = smart_split_text(part, 2000, 400)
                for i, sc in enumerate(sub_chunks):
                    raw_chunks.append({
                        "text": sc['text'].strip(),
                        "path": current_path + (f" (Part {i+1})" if len(sub_chunks) > 1 else ""),
                        "level": len(header_stack),
                        "is_fragment": sc['is_fragment'],
                        "has_table": sc['has_table']
                    })
                current_chunk = "" 
            else:
                if len(current_chunk) + len(part) > 2000:
                    if current_chunk:
                        has_table_simple = '|' in current_chunk
                        raw_chunks.append({
                            "text": current_chunk.strip(),
                            "path": current_path,
                            "level": len(header_stack),
                            "has_table": has_table_simple
                        })
                        
                        overlap_text = current_chunk[-400:] if len(current_chunk) > 400 else current_chunk
                        current_chunk = overlap_text + "\n" + part
                    else:
                        current_chunk = part
                else:
                    current_chunk += "\n" + part
        
        if current_chunk:
            has_table_simple = '|' in current_chunk
            raw_chunks.append({
                "text": current_chunk.strip(),
                "path": current_path,
                "level": len(header_stack),
                "has_table": has_table_simple
            })
            
        processed_chunks = []
        
        for idx, chunk_data in enumerate(raw_chunks):
            # Platinum Prefix Injunction
            path = chunk_data["path"]
            content = chunk_data["text"]
            platinum_text = f"[Doc: {filename} | Path: {path}]\n{content}"
            
            processed_chunks.append({
                "text": platinum_text,
                "metadata": {
                    "source": file_path,
                    "filename": filename,
                    "chunk_index": idx,
                    "next_index": idx + 1 if idx < len(raw_chunks) - 1 else -1,
                    "prev_index": idx - 1 if idx > 0 else -1,
                    "section_path": path,
                    "header_level": chunk_data.get("level", 0),
                    "is_fragment": chunk_data.get("is_fragment", False),
                    "fragment_index": chunk_data.get("fragment_index", 0),
                    "total_fragments": chunk_data.get("total_fragments", 1),
                    "has_table": chunk_data.get("has_table", False),
                    "doc_type": "general"
                }
            })
        
        logger.info(f"Successfully processed {filename} into {len(processed_chunks)} hierarchical chunks.")
        return processed_chunks

    def _clean_markdown_artifacts(self, text: str) -> str:
        """
        Surgically cleans Docling artifacts, especially from Vision Mode,
        without breaking legitimate content.
        """
        if not text:
            return ""
            
        # 1. Decode HTML entities (System-wide improvement)
        text = html.unescape(text)
        
        # 2. Clean 'Structural Brackets' (Docling artifacts)
        text = re.sub(r'(?m)^[ \t]*[-*+][ \t]+(#{1,6})', r'\1', text)
        text = re.sub(r'(?m)^[ \t]*[-*+][ \t]+(Q:|Question:|A:|Answer:)', r'\1', text)
        
        # 3. [Platinum Polish] Character Healing (Fix common OCR "leetspeak" misinterpretations)
        text = re.sub(r'[lLli]{2}MB', 'IIMB', text)
        text = re.sub(r'MD[l1]', 'MDI', text)
        text = re.sub(r'AP[l1]', 'API', text)
        text = re.sub(r'\b([dD]ev)[ \t]?([oO]ps)\b', r'\1\2', text, flags=re.I) 
        text = re.sub(r'\b[sS] Agent\b', 'DevOps Agent', text) 
        
        # 4. [Platinum Polish] Global Mashed Word Repair (Probabilistic Viterbi Segmentation)
        def repair_body_mashing(content):
            # Guardrails: Skip URLs, code snippets, and structural markers
            if any(marker in content for marker in ["://", "@", "/", "\\", "_", "```", "|"]):
                return content
            
            # Apply Viterbi Segmentation to likely mashed segments
            # Strategy: Only split words that looks like they are 10+ chars 
            # or follow specific particle patterns to avoid noise.
            words = content.split()
            repaired_words = []
            for w in words:
                # Heuristic: If word is long and lower-case, check for mashing
                if len(w) > 8 and w.islower() and not w.startswith(('http', 'www')):
                    repaired_words.append(viterbi.segment(w))
                else:
                    repaired_words.append(w)
            
            content = " ".join(repaired_words)
            
            # [PascalCase/Acronym Splitting]
            content = re.sub(r'([a-z])([A-Z][a-z])', r'\1 \2', content)
            content = re.sub(r'([A-Z]{2,})([A-Z][a-z])', r'\1 \2', content)
            
            # [Lower-to-Caps Transition] (e.g., campusofIIMB)
            content = re.sub(r'\b([a-z]+)(of|in|at|on|by|is|to)(?=[A-Z])', r'\1 \2 ', content)
            
            # [Acronym mashing] (e.g., AW S orGCP -> AWS or GCP)
            content = re.sub(r'AW\s?S', 'AWS', content)
            content = re.sub(r'(AWS)(or|and|to)', r'\1 \2 ', content)
            content = re.sub(r'\b(AWS)(or|and|to)([A-Z])', r'\1 \2 \3', content)
            
            # [Root Cause Fix] Digit.Word -> Digit. Word (e.g., "7.Multi-Host")
            content = re.sub(r'(\d)\.([A-Z][a-z])', r'\1. \2', content)

            # [Root Cause Fix] Word,Word -> Word, Word (e.g., "Division,DoP&T")
            content = re.sub(r'([a-z])\,([A-Z])', r'\1, \2', content)

            # [Root Cause Fix] WordandWord -> Word and Word (e.g., "Loadand")
            # Expanded list of common welding particles
            welding_particles = ['and', 'of', 'the', 'is', 'to', 'in', 'for', 'with']
            for p in welding_particles:
                # Fix "Loadand" -> "Load and" (Case-insensitive match for the particle)
                content = re.sub(r'([a-z])(' + p + r')([A-Z]?)', r'\1 \2 \3', content, flags=re.I)
            
            # word.Word -> word. Word
            content = re.sub(r'([a-z])\.([A-Z][a-z])', r'\1. \2', content)
            return content

        lines = text.split('\n')
        text = '\n'.join([repair_body_mashing(l) if not (l.strip().startswith('|') or l.strip().startswith('#')) else l for l in lines])
        
        # 5. [Platinum Polish] Fix Mashed Words in Headers (Structural Layer)
        def repair_mashed_header(match):
            header_line = match.group(0)
            # Insert space between Number and Capital: 1.1Introduction -> 1.1 Introduction
            header_line = re.sub(r'(\d)([A-Z])', r'\1 \2', header_line)
            # Insert space between colon and Capital: Problem:Cognitive -> Problem: Cognitive
            header_line = re.sub(r'(:)([A-Z])', r'\1 \2', header_line)
            # Handle PascalCase mashing in headers (e.g., PolicyOverview -> Policy Overview)
            # Only if it follows a structural '#' marker
            header_line = re.sub(r'([a-z])([A-Z])', r'\1 \2', header_line)
            # Handle Capital to Capital (e.g., REPORTIntroduction -> REPORT Introduction)
            header_line = re.sub(r'([A-Z]{2,})([A-Z][a-z])', r'\1 \2', header_line)
            return header_line

        text = re.sub(r'(?m)^#{1,6}\s+.*$', repair_mashed_header, text)
        
        # 4. [Platinum Polish] Universal TOC Suppression
        # Look for phrases starting with 'Table of Contents', 'Contents', etc.
        # followed by dotted lines and numbers.
        toc_keywords = ["Table of Contents", "Contents", "Index", "Inhalt", "Sommaire"]
        first_5k = text[:5000].lower()
        if any(kw.lower() in first_5k for kw in toc_keywords):
            # Regex to find a table that looks like a TOC (dots and numbers)
            text = re.sub(r'\|.*(?:Table of Contents|Contents).*\|(\n\|.*\|)+', '', text, count=1, flags=re.I)
            # Remove line patterns that are just Label + dots + Page Number
            text = re.sub(r'(?m)^.*(?:Table of Contents|Contents|Index)\s*[\.\s]{5,}\d+.*$', '', text, flags=re.I)

        # 5. [Platinum Polish] Strip redundant title repetitions at start
        lines = text.splitlines()
        if len(lines) > 20:
            first_header = next((l for l in lines[:15] if l.startswith("#")), None)
            if first_header:
                # Look for the exact same header repeated within the next 80 lines
                for i in range(lines.index(first_header) + 1, min(len(lines), 100)):
                    if lines[i].strip() == first_header.strip():
                        # Found a duplicate! Remove only the redundant header line
                        lines.pop(i)
                        text = "\n".join(lines)
                        break

        # 8. [Platinum Polish] Page-Break Healing (Join split sentences)
        # Join lines where a line ends in a lowercase word and next line starts with lowercase
        # But only if not in a list or table or header
        def heal_page_breaks(t):
            lines = t.split('\n')
            healed = []
            # Strict markers that shouldn't be joined (List bullets, headers, etc.)
            stop_markers = ('#', '|', '-', '*', '+', '>', '1.', '2.', '3.', '4.', '5.')
            
            for i in range(len(lines)):
                if (i > 0 and 
                    lines[i-1].strip() and 
                    lines[i].strip() and
                    not lines[i-1].strip().startswith(stop_markers) and
                    not lines[i].strip().startswith(stop_markers) and
                    re.search(r'[a-z]$', lines[i-1].strip()) and
                    re.match(r'[a-z]', lines[i].strip())):
                    # Merge with previous line (Sentences split across pages)
                    healed[-1] = healed[-1].rstrip() + " " + lines[i].lstrip()
                else:
                    healed.append(lines[i])
            return '\n'.join(healed)

        text = heal_page_breaks(text)

        return text.strip()

    def _fix_header_hierarchy(self, text: str) -> str:
        """
        Fixes flat header hierarchies by detecting numbering patterns (e.g., 3.1, 3.1.1)
        and demoting them to the appropriate depth.
        """
        if not text:
            return ""

        def demote_based_on_numbering(match):
            hashes = match.group(1)
            numbering = match.group(2)
            rest = match.group(3)
            
            # Count segments (e.g., "3.1" -> 2 segments)
            segments = len([s for s in numbering.split('.') if s.strip()])
            
            # Level 1 (e.g., "3") -> H2 (##)
            # Level 2 (e.g., "3.1") -> H3 (###)
            # Level 3 (e.g., "3.1.1") -> H4 (####)
            inferred_level = 1 + segments
            
            # Limit to H6
            if inferred_level > 6:
                inferred_level = 6
                
            return f"{'#' * inferred_level} {numbering}{rest}"

        # Regex: Look for headers that have numbering immediately after the hashes
        # Group 1: Hashes, Group 2: Numbering, Group 3: Text
        # Updated to handle '3.1', '3.1.1' and also '3. ' with trailing space
        return re.sub(r'(?m)^(#{2,6})\s+(\d+(?:\.\d+)*\.?)(.*)$', demote_based_on_numbering, text)

    def _should_retry_with_vision(self, text: str) -> bool:
        """
        Determines if a document needs a high-fidelity vision-based retry.
        """
        # Threshold: High density of unescaped artifacts in digital path
        artifact_count = len(re.findall(r'&[a-z0-9#]+;', text, re.I))
        bulleted_headers = len(re.findall(r'(?m)^[ \t]*[-*+][ \t]+#{1,6}', text))
        
        # [Heuristic] Broken Text / Bad Kerning Detection
        # Count isolated single letters that shouldn't be isolated (e.g., "r u n n i n g" or "Bridg in g")
        # We exclude 'a', 'A', 'I', 'i' (common valid single words) and bullet markers
        isolated_chars = len(re.findall(r'(?<![0-9])\b[b-hj-zB-HJ-Z]\b(?![0-9])', text))
        
        # Trigger vision if we see high corruption, missing headers, or broken text spacing
        if artifact_count > 10 or bulleted_headers > 5 or isolated_chars > 20:
            logger.info(f"[HEURISTIC] Vision Triggered: Artifacts={artifact_count}, Headers={bulleted_headers}, IsolatedChars={isolated_chars}")
            return True
            
        # Heuristic: If it's a multi-page likely report but has 0 headers after digital extraction
        if len(text) > 5000 and not re.search(r'(?m)^#{1,3}', text):
            return True
            
        return False


    def process_qna_content(self, md_content: str, file_path: str) -> List[Dict[str, Any]]:
        """
        Processes Q&A-style documents with atomic Q&A pair chunking.
        
        This method:
        1. Detects Q&A patterns (Q:, A:, numbered questions, etc.)
        2. Keeps each Q&A pair as a single atomic chunk
        3. Handles fragmentation for very long answers
        4. Preserves bullet points, numbering, and formatting
        
        Args:
            md_content: Markdown content of the document
            file_path: Original file path for metadata
            
        Returns:
            List of chunks with Q&A-specific metadata
        """
        from backend.ingestion.qna_patterns import extract_qa_pairs
        
        filename = os.path.basename(file_path)
        
        # Extract Q&A pairs using pattern detection
        qa_pairs = extract_qa_pairs(md_content, filename)
        
        if not qa_pairs:
            logger.warning(f"No Q&A pairs detected in {filename}. Falling back to hierarchical chunking.")
            return []  # Caller should fall back to hierarchical
            
        # [Platinum Polish] Sort Q&A pairs by their original index to fix OCR out-of-order extraction
        qa_pairs.sort(key=lambda x: x.get("pair_index", 0))
        
        # [Platinum Polish] Chronological Markdown Reconstruction (Debug Output)
        try:
            sorted_md_content = f"## 💎 [PLATINUM SORTED] {filename}\n\n"
            for pair in qa_pairs:
                sorted_md_content += f"Q: {pair['question_text']}\n\nA: {pair['answer_text']}\n\n---\n\n"
            
            debug_dir = os.path.join(os.getcwd(), "generated_doc_md")
            debug_filename = f"{filename.rsplit('.', 1)[0]}_docling_platinum.md"
            debug_path = os.path.join(debug_dir, debug_filename)
            
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(sorted_md_content)
            logger.info(f"🔬 [DEBUG] Saved reconstructed Platinum Markdown to: {debug_path}")
        except Exception as e_sort:
            logger.warning(f"Failed to save sorted debug Markdown: {e_sort}")

        logger.info(f"Extracted and sorted {len(qa_pairs)} Q&A pairs from {filename}")
        
        processed_chunks = []
        MAX_QA_CHUNK_SIZE = 2000  # Characters
        
        for pair in qa_pairs:
            question = pair["question_text"]
            answer = pair["answer_text"]
            section = pair["section_path"]
            qa_id = pair["qa_pair_id"]
            
            # Build full Q&A content preserving structure
            full_qa_content = f"Q: {question}\n\nA: {answer}"
            
            # Check if fragmentation is needed
            if len(full_qa_content) <= MAX_QA_CHUNK_SIZE:
                # Single atomic chunk
                platinum_text = f"[Doc: {filename} | Section: {section} | Q&A: {qa_id}]\n{full_qa_content}"
                
                processed_chunks.append({
                    "text": platinum_text,
                    "metadata": {
                        "source": file_path,
                        "filename": filename,
                        "doc_type": "qna",
                        "chunk_index": len(processed_chunks),
                        "section_path": section,
                        "qa_pair_id": qa_id,
                        "question_text": question[:200],  # Truncate for indexing
                        "is_atomic": True,
                        "is_fragment": False,
                        "fragment_index": 0,
                        "total_fragments": 1
                    }
                })
            else:
                # Fragment the Q&A pair
                # Strategy: Keep question + first part of answer together, then split remaining
                
                # First fragment: Question + beginning of answer
                first_chunk_size = MAX_QA_CHUNK_SIZE - len(f"Q: {question}\n\nA: ") - 100  # Buffer
                answer_lines = answer.split('\n')
                
                fragments = []
                current_fragment = []
                current_len = 0
                
                for line in answer_lines:
                    line_len = len(line) + 1
                    if current_len + line_len > first_chunk_size and current_fragment:
                        fragments.append('\n'.join(current_fragment))
                        current_fragment = []
                        current_len = 0
                        first_chunk_size = MAX_QA_CHUNK_SIZE - 100  # Subsequent fragments
                    
                    current_fragment.append(line)
                    current_len += line_len
                
                if current_fragment:
                    fragments.append('\n'.join(current_fragment))
                
                total_fragments = len(fragments)
                
                for frag_idx, frag_content in enumerate(fragments):
                    if frag_idx == 0:
                        # First fragment includes question
                        chunk_content = f"Q: {question}\n\nA: {frag_content}"
                    else:
                        # Subsequent fragments: include question for context
                        chunk_content = f"[Continued from Q: {question[:100]}...]\n\n{frag_content}"
                    
                    platinum_text = f"[Doc: {filename} | Section: {section} | Q&A: {qa_id} | Part {frag_idx+1}/{total_fragments}]\n{chunk_content}"
                    
                    processed_chunks.append({
                        "text": platinum_text,
                        "metadata": {
                            "source": file_path,
                            "filename": filename,
                            "doc_type": "qna",
                            "chunk_index": len(processed_chunks),
                            "section_path": section,
                            "qa_pair_id": qa_id,
                            "question_text": question[:200],
                            "is_atomic": False,
                            "is_fragment": True,
                            "fragment_index": frag_idx,
                            "total_fragments": total_fragments
                        }
                    })
        
        logger.info(f"Successfully processed {filename} into {len(processed_chunks)} Q&A chunks.")
        return processed_chunks

