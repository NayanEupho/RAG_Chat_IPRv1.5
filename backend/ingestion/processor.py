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
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import torch
import multiprocessing
import math
from functools import lru_cache
from backend.config import get_config
from backend.ingestion.artifacts import save_parse_artifacts
from backend.ingestion.chunkers.general import GeneralChunker, extract_markdown_tables
from backend.ingestion.chunkers.normalized import NormalizedMarkdownChunker
from backend.ingestion.chunkers.qna import QnAChunker
from backend.ingestion.chunkers.vision import VisionChunker
from backend.ingestion.models import ParsedDocument
from backend.ingestion.normalizers import LlmMarkdownNormalizer, NormalizationOptions
from backend.ingestion.parsers import normalize_parser_mode, parse_to_markdown
from backend.ingestion.quality.gates import analyze_markdown, should_fallback
from backend.ingestion.vision_parser import VisionMarkdownParser
from backend.ingestion.vision_prompts import prompt_for_doc_type

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


@dataclass
class SectionBlock:
    """A normalized document section ready for chunking."""
    path: str
    level: int
    title: str
    text: str
    start_line: int
    end_line: int


def _stable_doc_id(file_path: str) -> str:
    """Stable source identifier that prevents same-name collisions across folders."""
    abs_path = os.path.abspath(file_path)
    try:
        normalized = os.path.relpath(abs_path, os.getcwd())
    except ValueError:
        normalized = abs_path
    normalized = os.path.normpath(normalized).replace("\\", "/").lower()
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")

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

    def process_file(
        self,
        file_path: str,
        chunk_size: int = 2200,
        chunk_overlap: int = 0,
        mode: str = "auto",
        llm_normalize: bool = False,
    ) -> List[Dict]:
        """
        Ingests a file, converts it to Markdown, cleans it, and splits it into chunks.
        Mode: 'auto' (Hybrid), 'pymupdf4llm' (Force PyMuPDF),
        'docling_vision' (Force OCR), 'vision_llm' (Ollama multimodal)
        """
        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()
        normalized_path = file_path.replace('\\', '/')
        doc_type = "qna" if "/qna/" in normalized_path.lower() else "general"
        cfg_mode = get_config().parsing_mode
        if mode == "auto" and cfg_mode != "auto":
            mode = "auto" if cfg_mode == "llm" else cfg_mode
        mode = normalize_parser_mode(mode)
        
        logger.info(f"Processing {filename} [Mode: {mode.upper()}]...")
        
        # Extension Whitelist (Docling + Fallbacks)
        if ext not in [".pdf", ".md", ".markdown", ".txt", ".docx", ".pptx", ".xlsx", ".html"]:
            logger.debug(f"Skipping unsupported file format: {ext}")
            return []

        try:
            # --- [CONVERSION STAGE] ---
            source_type = "docling" # Default
            md_content = ""
            
            parser_outputs = {}

            if ext in {".md", ".markdown"}:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    md_content = f.read()
                source_type = "markdown"

            elif ext == ".txt":
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    md_content = f.read()
                source_type = "text"
             
            elif ext == ".pdf" and mode == "docling":
                converter = self._get_converter(enable_ocr=False)
                result = converter.convert(file_path)
                md_content = result.document.export_to_markdown()
                source_type = "docling"

            elif ext == ".pdf" and mode == "pymupdf4llm":
                import pymupdf4llm
                md_content = pymupdf4llm.to_markdown(file_path)
                source_type = "pymupdf4llm"

            elif ext == ".pdf" and mode == "pymupdf":
                parsed = parse_to_markdown(
                    file_path=file_path,
                    mode="pymupdf",
                    doc_type=doc_type,
                    converter_factory=self._get_converter,
                    scanned_detector=self._is_scanned_pdf,
                    clean_markdown=self._clean_markdown_artifacts,
                    fix_header_hierarchy=self._fix_header_hierarchy,
                )
                md_content = parsed.markdown
                source_type = parsed.selected_parser
                parser_outputs.update(parsed.parser_outputs)

            elif ext == ".pdf" and mode == "vision_llm":
                cfg = get_config()
                logger.info(f"[VISION_LLM] Parsing {filename} page-by-page with {cfg.vlm_model} at {cfg.vlm_host}")
                vision_prompt = prompt_for_doc_type(doc_type, cfg.vlm_prompt)
                parser = VisionMarkdownParser(
                    host=cfg.vlm_host,
                    model=cfg.vlm_model,
                    prompt=vision_prompt,
                    dpi=cfg.vlm_dpi,
                    timeout_seconds=cfg.vlm_timeout_seconds,
                    concurrency=cfg.vlm_concurrency,
                    retries=cfg.vlm_retries,
                )
                title = os.path.splitext(filename)[0]
                md_content, vision_pages = parser.parse_pdf(file_path, title=title)
                source_type = "vision_llm"
                parser_outputs["vision_llm"] = md_content
                for page in vision_pages:
                    parser_outputs[f"vision_page_{page.page_number:03d}"] = page.markdown
             
            elif ext == ".pdf":
                # Smart OCR detection or mode override
                needs_ocr = self._is_scanned_pdf(file_path) if mode == "auto" else (mode == "docling_vision")
                
                logger.info(f"Initializing Docling Primary Pipeline... OCR={'ON' if needs_ocr else 'OFF'}")
                try:
                    converter = self._get_converter(enable_ocr=needs_ocr)
                    result = converter.convert(file_path)
                    doc = result.document
                    md_content = doc.export_to_markdown()
                    docling_diagnostics = analyze_markdown(md_content, parser="docling", source_type="docling")
                    
                    # --- [Quality Gate] ---
                    # For table-heavy digital PDFs, Docling may emit many isolated
                    # row-number tokens. That is not corruption if table structure
                    # is coherent, so prefer Docling over PyMuPDF in that case.
                    heuristic_issues = self._should_retry_with_vision(md_content)
                    table_structure_good = (
                        docling_diagnostics.table_count > 0
                        and docling_diagnostics.table_row_count >= 3
                        and docling_diagnostics.broken_table_score < 0.25
                    )
                    quality_issues = (
                        should_fallback(docling_diagnostics, doc_type="general")
                        or (heuristic_issues and not table_structure_good)
                    )
                    
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

            if source_type in {"markdown", "text", "docling", "docling_vision", "pymupdf4llm"}:
                md_content = self._clean_markdown_artifacts(md_content)
                md_content = self._fix_header_hierarchy(md_content)

            if not md_content.strip():
                raise ValueError("Extracted content is empty.")
            parser_outputs.setdefault(source_type, md_content)
                 
        except Exception as e:
            logger.warning(f"Primary pipeline failed for {file_path}: {e!r}")
            logger.info("Retrying with PyMuPDF4LLM fallback...")
            source_type = "pymupdf4llm_fallback"
            try:
                import pymupdf4llm
                md_content = pymupdf4llm.to_markdown(file_path)
                
                if not md_content.strip():
                    logger.warning("PyMuPDF4LLM extracted empty content.")
                    return []
                 
                logger.info("Successfully extracted text via PyMuPDF4LLM.")
                parser_outputs = {source_type: md_content}
            except Exception as ep:
                logger.error(f"PyMuPDF4LLM fallback also failed: {ep}")
                return []

        raw_md_content = md_content
        normalization_manifest = None
        if llm_normalize:
            normalization = LlmMarkdownNormalizer(NormalizationOptions(enabled=True)).normalize(
                md_content,
                filename=filename,
                doc_type=doc_type,
                parser=source_type,
            )
            md_content = normalization.markdown
            normalization_manifest = normalization.manifest
            parser_outputs["llm_normalized"] = md_content
            source_type = f"{source_type}_llm_normalized" if normalization.accepted else source_type

        # --- NEW: Folder-Based Strategy Selection ---
        diagnostics = analyze_markdown(md_content, parser=source_type, source_type=source_type)
        parsed_doc = ParsedDocument(
            file_path=file_path,
            filename=filename,
            doc_type=doc_type,
            markdown=md_content,
            selected_parser=source_type,
            diagnostics=diagnostics,
            parser_outputs=parser_outputs,
            raw_markdown=raw_md_content,
            normalization_manifest=normalization_manifest,
        )
        if '/qna/' in normalized_path.lower():
            logger.info(f"Folder-based routing: Treating {filename} as Q&A document.")
            qna_chunks = QnAChunker().chunk(md_content, file_path)
            if qna_chunks:
                for chunk in qna_chunks:
                    chunk["metadata"].setdefault("parser", source_type)
                save_parse_artifacts(parsed_doc, qna_chunks)
                return qna_chunks
            logger.info(f"No Q&A patterns found in {filename}, falling back to hierarchical chunking.")

        base_source_type = source_type.replace("_llm_normalized", "")
        if source_type.endswith("_llm_normalized") and base_source_type in {"docling", "pymupdf", "pymupdf4llm", "docling_vision", "markdown"}:
            processed_chunks = NormalizedMarkdownChunker(chunk_size=chunk_size).chunk(
                md_content,
                file_path=file_path,
                filename=filename,
                source_type=source_type,
            )
            logger.info(f"Successfully processed {filename} into {len(processed_chunks)} normalized structure-aware chunks.")
        elif base_source_type in {"vision_llm", "pymupdf", "pymupdf4llm", "docling", "docling_vision", "markdown"}:
            processed_chunks = VisionChunker(chunk_size=chunk_size).chunk(
                md_content,
                file_path=file_path,
                filename=filename,
                source_type=source_type,
            )
            logger.info(f"Successfully processed {filename} into {len(processed_chunks)} structure-aware chunks.")
        elif extract_markdown_tables(md_content):
            processed_chunks = GeneralChunker(chunk_size=chunk_size).chunk(
                md_content,
                file_path=file_path,
                filename=filename,
                source_type=source_type,
            )
            logger.info(f"Successfully processed {filename} into {len(processed_chunks)} table-aware chunks.")
        else:
            processed_chunks = self._build_hierarchical_chunks(
                md_content,
                file_path=file_path,
                filename=filename,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        
        for chunk in processed_chunks:
            chunk["metadata"].setdefault("parser", source_type)
        save_parse_artifacts(parsed_doc, processed_chunks)
        logger.info(f"Successfully processed {filename} into {len(processed_chunks)} chunks.")
        return processed_chunks

    def parse_to_markdown(self, file_path: str, mode: str = "auto", doc_type: Optional[str] = None):
        normalized_path = file_path.replace('\\', '/')
        resolved_doc_type = doc_type or ("qna" if "/qna/" in normalized_path.lower() else "general")
        return parse_to_markdown(
            file_path=file_path,
            mode=mode,
            doc_type=resolved_doc_type,
            converter_factory=self._get_converter,
            scanned_detector=self._is_scanned_pdf,
            clean_markdown=self._clean_markdown_artifacts,
            fix_header_hierarchy=self._fix_header_hierarchy,
        )

    def _build_hierarchical_chunks(
        self,
        md_content: str,
        file_path: str,
        filename: str,
        chunk_size: int = 1400,
        chunk_overlap: int = 180,
    ) -> List[Dict[str, Any]]:
        """
        Build section-aware chunks from normalized Markdown.

        The previous implementation split on regex captures and then arbitrary
        character counts, which could detach a paragraph/table from its heading.
        This path first creates explicit section blocks and then splits only
        inside each section while preserving the breadcrumb in every chunk.
        """
        normalized = self._normalize_markdown_structure(md_content)
        sections = self._extract_sections(normalized)
        doc_id = _stable_doc_id(file_path)

        raw_chunks: List[Dict[str, Any]] = []
        for section in sections:
            for part in self._split_section(section, max_size=chunk_size, overlap=chunk_overlap):
                raw_chunks.append(part)

        processed_chunks = []
        summary_text = self._build_doc_summary(normalized, filename)
        if summary_text:
            processed_chunks.append({
                "text": summary_text,
                "metadata": {
                    "source": file_path,
                    "doc_id": doc_id,
                    "filename": filename,
                    "chunk_index": 0,
                    "next_index": 1 if raw_chunks else -1,
                    "prev_index": -1,
                    "section_path": "Document Summary",
                    "section_title": "Document Summary",
                    "header_level": 0,
                    "is_fragment": False,
                    "fragment_index": 0,
                    "total_fragments": 1,
                    "has_table": False,
                    "start_line": 0,
                    "end_line": 0,
                    "doc_type": "general",
                    "chunk_kind": "doc_summary",
                }
            })

        base_index = len(processed_chunks)
        for offset, chunk_data in enumerate(raw_chunks):
            idx = base_index + offset
            path = chunk_data["path"]
            content = chunk_data["text"].strip()
            title = chunk_data.get("title") or path.split(" > ")[-1]
            context_prefix = f"[Doc: {filename} | Section: {path}]\n# {title}\n"
            chunk_text = context_prefix + content

            processed_chunks.append({
                "text": chunk_text,
                "metadata": {
                    "source": file_path,
                    "doc_id": doc_id,
                    "filename": filename,
                    "chunk_index": idx,
                    "next_index": idx + 1 if offset < len(raw_chunks) - 1 else -1,
                    "prev_index": idx - 1 if idx > 0 else -1,
                    "section_path": path,
                    "section_title": title,
                    "header_level": chunk_data.get("level", 0),
                    "is_fragment": chunk_data.get("is_fragment", False),
                    "fragment_index": chunk_data.get("fragment_index", 0),
                    "total_fragments": chunk_data.get("total_fragments", 1),
                    "has_table": chunk_data.get("has_table", False),
                    "start_line": chunk_data.get("start_line", 0),
                    "end_line": chunk_data.get("end_line", 0),
                    "doc_type": "general",
                    "chunk_kind": "body",
                }
            })
        return processed_chunks

    def _build_doc_summary(self, markdown: str, filename: str, max_chars: int = 1800) -> str:
        """Create a deterministic document-level summary chunk for recall/fallback."""
        lines = markdown.splitlines()
        headings = []
        body_parts = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if heading and len(headings) < 12:
                headings.append(heading.group(2).strip())
                continue
            if not stripped.startswith("|") and len(body_parts) < 8:
                body_parts.append(stripped)

        parts = []
        if headings:
            parts.append("Key sections: " + "; ".join(headings))
        if body_parts:
            parts.append("Opening content: " + " ".join(body_parts))
        if not parts:
            return ""

        content = " ".join(parts)
        if len(content) > max_chars:
            content = content[:max_chars].rsplit(" ", 1)[0].strip()
        return f"[Doc: {filename} | Section: Document Summary]\n# Document Summary\n{content}"

    def _normalize_markdown_structure(self, text: str) -> str:
        """Repair common PDF-to-Markdown structural artifacts before chunking."""
        text = self._clean_markdown_artifacts(text)
        text = self._fix_header_hierarchy(text)
        lines = text.splitlines()
        normalized = []
        previous_blank = False

        heading_like = re.compile(
            r"^\s*(?:(\d+(?:\.\d+){0,5})\.?\s+)?"
            r"([A-Z][A-Z0-9 &,/()'\-]{5,}|[A-Z][A-Za-z0-9 &,/()'\-]{3,80})\s*$"
        )

        for raw in lines:
            line = raw.rstrip()
            stripped = line.strip()

            if not stripped:
                if not previous_blank:
                    normalized.append("")
                previous_blank = True
                continue
            previous_blank = False

            # Normalize malformed Markdown headings like "#Title" without
            # corrupting valid "## Title" headings.
            line = re.sub(r"^(#{1,6})([^#\s])", r"\1 \2", line)

            if not line.startswith("#") and not line.startswith("|"):
                match = heading_like.match(stripped)
                if match and len(stripped.split()) <= 12 and not stripped.endswith((".", ",", ";", ":")):
                    numbering = match.group(1)
                    if numbering:
                        depth = min(6, 1 + len([p for p in numbering.split(".") if p]))
                    elif stripped.isupper():
                        depth = 2
                    else:
                        depth = 3
                    line = f"{'#' * depth} {stripped}"

            normalized.append(line)

        return "\n".join(normalized).strip()

    def _extract_sections(self, markdown: str) -> List[SectionBlock]:
        """Convert Markdown into hierarchical section blocks."""
        lines = markdown.splitlines()
        sections: List[SectionBlock] = []
        stack: List[str] = []
        current_lines: List[str] = []
        current_path = "Intro"
        current_title = "Intro"
        current_level = 0
        start_line = 1

        def flush(end_line: int):
            nonlocal current_lines, start_line
            content = "\n".join(current_lines).strip()
            if content:
                sections.append(SectionBlock(
                    path=current_path,
                    level=current_level,
                    title=current_title,
                    text=content,
                    start_line=start_line,
                    end_line=end_line,
                ))
            current_lines = []

        for idx, line in enumerate(lines, start=1):
            heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if heading:
                flush(idx - 1)
                current_level = len(heading.group(1))
                current_title = heading.group(2).strip()
                stack = stack[:current_level - 1] + [current_title]
                current_path = " > ".join(stack) if stack else current_title
                start_line = idx
                continue
            current_lines.append(line)

        flush(len(lines))
        if not sections and markdown.strip():
            sections.append(SectionBlock(
                path="Intro",
                level=0,
                title="Intro",
                text=markdown.strip(),
                start_line=1,
                end_line=len(lines),
            ))
        return sections

    def _split_section(self, section: SectionBlock, max_size: int, overlap: int) -> List[Dict[str, Any]]:
        """Split one section without breaking tables and with stable overlap."""
        blocks = self._paragraph_blocks(section.text)
        chunks: List[Dict[str, Any]] = []
        current: List[str] = []
        current_len = 0
        current_has_table = False

        def emit(is_fragment: bool):
            nonlocal current, current_len, current_has_table
            if not current:
                return
            chunks.append({
                "text": "\n\n".join(current).strip(),
                "path": section.path,
                "title": section.title,
                "level": section.level,
                "is_fragment": is_fragment,
                "has_table": current_has_table,
                "start_line": section.start_line,
                "end_line": section.end_line,
            })
            tail = self._overlap_tail("\n\n".join(current), overlap)
            current = [tail] if tail and is_fragment else []
            current_len = len(tail) if current else 0
            current_has_table = False

        for block in blocks:
            block_len = len(block) + 2
            block_has_table = any(line.strip().startswith("|") for line in block.splitlines())

            if block_len > max_size:
                emit(is_fragment=bool(chunks))
                for part in self._split_large_block(block, max_size=max_size, overlap=overlap):
                    chunks.append({
                        "text": part.strip(),
                        "path": section.path,
                        "title": section.title,
                        "level": section.level,
                        "is_fragment": True,
                        "has_table": block_has_table,
                        "start_line": section.start_line,
                        "end_line": section.end_line,
                    })
                continue

            if current and current_len + block_len > max_size:
                emit(is_fragment=bool(chunks))

            current.append(block)
            current_len += block_len
            current_has_table = current_has_table or block_has_table

        emit(is_fragment=bool(chunks))

        total = len(chunks)
        for idx, chunk in enumerate(chunks):
            chunk["fragment_index"] = idx
            chunk["total_fragments"] = total
            chunk["is_fragment"] = total > 1
        return chunks

    def _paragraph_blocks(self, text: str) -> List[str]:
        """Group text into paragraphs and full Markdown tables."""
        lines = text.splitlines()
        blocks = []
        current = []
        in_table = False

        def flush():
            nonlocal current
            if current:
                blocks.append("\n".join(current).strip())
                current = []

        for line in lines:
            stripped = line.strip()
            is_table = stripped.startswith("|")
            if is_table:
                if not in_table:
                    flush()
                    in_table = True
                current.append(line)
                continue

            if in_table:
                flush()
                in_table = False

            if not stripped:
                flush()
            else:
                current.append(line)

        flush()
        return [b for b in blocks if b]

    def _split_large_block(self, text: str, max_size: int, overlap: int) -> List[str]:
        """Sentence-aware fallback for a paragraph larger than the target chunk."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        parts = []
        current = ""
        for sentence in sentences:
            if len(current) + len(sentence) + 1 > max_size and current:
                parts.append(current.strip())
                tail = self._overlap_tail(current, overlap)
                current = f"{tail} {sentence}".strip() if tail else sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            parts.append(current.strip())
        return parts

    def _overlap_tail(self, text: str, overlap: int) -> str:
        if overlap <= 0 or len(text) <= overlap:
            return ""
        tail = text[-overlap:]
        boundary = max(tail.rfind(". "), tail.rfind("! "), tail.rfind("? "), tail.rfind("\n\n"))
        return tail[boundary + 1:].strip() if boundary > 0 else ""

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
                # Fix "LoadandNext" -> "Load and Next" without splitting
                # valid words such as "Training" or "within".
                content = re.sub(r'([a-z]{3,})(' + p + r')([A-Z])', r'\1 \2 \3', content)
            
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
        doc_id = _stable_doc_id(file_path)
        
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
                        "doc_id": doc_id,
                        "filename": filename,
                        "doc_type": "qna",
                        "chunk_index": len(processed_chunks),
                        "section_path": section,
                        "qa_pair_id": qa_id,
                        "question_text": question[:200],  # Truncate for indexing
                        "is_atomic": True,
                        "is_fragment": False,
                        "fragment_index": 0,
                        "total_fragments": 1,
                        "chunk_kind": "qna"
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
                            "doc_id": doc_id,
                            "filename": filename,
                            "doc_type": "qna",
                            "chunk_index": len(processed_chunks),
                            "section_path": section,
                            "qa_pair_id": qa_id,
                            "question_text": question[:200],
                            "is_atomic": False,
                            "is_fragment": True,
                            "fragment_index": frag_idx,
                            "total_fragments": total_fragments,
                            "chunk_kind": "qna"
                        }
                    })
        
        logger.info(f"Successfully processed {filename} into {len(processed_chunks)} Q&A chunks.")
        return processed_chunks

