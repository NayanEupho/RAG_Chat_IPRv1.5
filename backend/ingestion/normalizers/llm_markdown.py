import logging
import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List

import ollama

from backend.config import get_config

logger = logging.getLogger("rag_chat_ipr.ingestion.normalizers")


GENERAL_NORMALIZATION_RULES = """You are a document normalization engine.

Input is Markdown/text extracted from a PDF parser. Rewrite it into clean, semantic, retrieval-ready Markdown.

Hard requirements:
- Preserve all factual content. Do not summarize, invent, or omit substantive details.
- Remove PDF presentation artifacts: page numbers, repeated headers/footers, decorative dividers, broken TOC dot leaders.
- Infer semantic heading hierarchy:
  - document title -> # heading
  - numbered top-level sections like "1." -> ## heading
  - numbered subsections like "1.1" or "5.3.1" -> ### / #### based on depth
  - bold labels that act as section labels -> proper Markdown subheadings or bold labels.
- Normalize code and commands:
  - inline commands/classes/functions -> backticks
  - shell commands -> ```bash fenced blocks
  - Python/class/config snippets -> ```python fenced blocks
  - JSON/tool-call examples -> ```json fenced blocks
  - CLI output examples -> plain fenced blocks
- Rebuild a Table of Contents as Markdown anchor links, not plain lines or dotted page-number entries.
- Preserve product and technical terms exactly when obvious from context:
  - "Dev Ops Agent" means "DevOps Agent"
  - "Dev Ops" means "DevOps"
  - "DSPy" must not become "DS Py"
  - "WSGI Server" must not become "WSGIServer"
  - "MCP endpoints" must not become "MCPendpoints"
- Normalize tables into Markdown pipe tables when rows/columns are clear.
- Preserve numbered and bulleted lists as Markdown lists.
- Preserve callouts as blockquotes.
- Preserve meaningful figures instead of silently dropping them:
  - if text extraction includes only a caption and surrounding prose explains it, write "[Figure N omitted: described in surrounding text]".
  - if a sequence/flow is clear from text, rewrite it as prose or an arrow chain.
  - if unique visual content is unavailable, write "[Figure N: image content not available in extracted text]".
- Keep page anchors like "<!-- page: 12 -->" if present.
- Do not include analysis notes or commentary outside the normalized Markdown.
- Do not wrap the result in code fences.
"""


QNA_NORMALIZATION_RULES = """You are a Q&A document normalization engine.

Input is Markdown/text extracted from a PDF parser. Rewrite it into strict Q&A Markdown for chunking.

Hard requirements:
- Preserve every Q&A pair.
- Use this exact shape:
  Q: <question>

  A: <answer>

  ---
- Do not merge separate questions.
- Preserve original question numbers inside question text when visible.
- Keep tables/lists/visual notes inside the relevant answer.
- Do not rewrite Q&A content into prose sections.
- Do not summarize, invent, or omit substantive details.
- Do not wrap the result in code fences.
"""


@dataclass
class NormalizationOptions:
    enabled: bool = False
    batch_chars: int = 45000
    overlap_chars: int = 2500
    min_word_ratio: float = 0.55
    num_predict: int = 12000
    temperature: float = 0.0


@dataclass
class NormalizationResult:
    markdown: str
    accepted: bool
    manifest: Dict[str, Any]


class LlmMarkdownNormalizer:
    def __init__(self, options: NormalizationOptions | None = None, client_factory: Callable[[str], Any] | None = None):
        self.options = options or NormalizationOptions(
            enabled=os.getenv("INGEST_LLM_NORMALIZE", "false").lower() == "true",
            batch_chars=int(os.getenv("INGEST_NORMALIZE_BATCH_CHARS", "45000")),
            overlap_chars=int(os.getenv("INGEST_NORMALIZE_OVERLAP_CHARS", "2500")),
            min_word_ratio=float(os.getenv("INGEST_NORMALIZE_MIN_WORD_RATIO", "0.55")),
            num_predict=int(os.getenv("INGEST_NORMALIZE_NUM_PREDICT", "12000")),
            temperature=float(os.getenv("INGEST_NORMALIZE_TEMPERATURE", "0")),
        )
        self.client_factory = client_factory or ollama.Client

    def normalize(self, markdown: str, *, filename: str, doc_type: str, parser: str) -> NormalizationResult:
        cfg = get_config()
        if not cfg.main_model:
            raise ValueError("Main model is not configured; cannot run LLM normalization")

        raw = markdown or ""
        batches = self._make_batches(raw)
        normalized_parts = []
        batch_manifests = []
        previous_tail = ""

        client = self.client_factory(host=cfg.main_model.host)
        rules = QNA_NORMALIZATION_RULES if doc_type == "qna" else GENERAL_NORMALIZATION_RULES

        for idx, batch_text in enumerate(batches, start=1):
            prompt = self._batch_prompt(
                rules=rules,
                filename=filename,
                doc_type=doc_type,
                parser=parser,
                batch_id=idx,
                batch_count=len(batches),
                previous_tail=previous_tail,
                batch_text=batch_text,
            )
            logger.info("[NORMALIZE] Normalizing %s batch %s/%s with %s", filename, idx, len(batches), cfg.main_model.model_name)
            response = client.chat(
                model=cfg.main_model.model_name,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                think=False,
                options={
                    "temperature": self.options.temperature,
                    "num_predict": self.options.num_predict,
                    "num_ctx": cfg.model_context_window,
                },
            )
            normalized = self._response_content(response)
            normalized = self._clean_model_markdown(normalized)
            normalized_parts.append(normalized)
            previous_tail = normalized[-1800:]
            batch_manifests.append({
                "batch_id": idx,
                "input_chars": len(batch_text),
                "output_chars": len(normalized),
                "headings": self._headings(normalized),
                "warnings": self._batch_warnings(normalized),
                "markdown": normalized,
            })

        stitched = self._post_process_markdown(self._stitch(normalized_parts))
        validation = self._validate(raw, stitched, doc_type=doc_type)
        accepted = not validation["errors"]
        manifest = {
            "enabled": True,
            "mode": "llm_markdown",
            "status": "accepted" if accepted else "rejected_fallback_to_raw",
            "source_parser": parser,
            "doc_type": doc_type,
            "model": cfg.main_model.model_name,
            "host": cfg.main_model.host,
            "raw_char_count": len(raw),
            "normalized_char_count": len(stitched),
            "raw_word_count": self._word_count(raw),
            "normalized_word_count": self._word_count(stitched),
            "batch_count": len(batches),
            "validation": validation,
            "batches": batch_manifests,
        }
        if not accepted:
            logger.warning("[NORMALIZE] Rejected normalized output for %s: %s", filename, validation["errors"])
        return NormalizationResult(markdown=stitched if accepted else raw, accepted=accepted, manifest=manifest)

    def _batch_prompt(
        self,
        *,
        rules: str,
        filename: str,
        doc_type: str,
        parser: str,
        batch_id: int,
        batch_count: int,
        previous_tail: str,
        batch_text: str,
    ) -> str:
        overlap_note = ""
        if previous_tail:
            overlap_note = (
                "\nPrevious normalized ending for continuity. Use only to avoid broken sections; "
                "do not duplicate it:\n"
                "<previous_normalized_tail>\n"
                f"{previous_tail}\n"
                "</previous_normalized_tail>\n"
            )
        return (
            f"{rules}\n\n"
            f"Document: {filename}\n"
            f"Document type: {doc_type}\n"
            f"Source parser: {parser}\n"
            f"Batch: {batch_id}/{batch_count}\n"
            f"{overlap_note}\n"
            "Normalize this batch now:\n"
            "<raw_extracted_markdown>\n"
            f"{batch_text}\n"
            "</raw_extracted_markdown>\n"
        )

    def _make_batches(self, markdown: str) -> List[str]:
        text = markdown.strip()
        if len(text) <= self.options.batch_chars:
            return [text]

        sections = self._split_on_headings(text)
        batches = []
        current = ""
        for section in sections:
            if current and len(current) + len(section) > self.options.batch_chars:
                batches.append(current.strip())
                overlap = current[-self.options.overlap_chars:] if self.options.overlap_chars > 0 else ""
                current = f"{overlap}\n\n{section}"
            else:
                current = f"{current}\n\n{section}" if current else section
        if current.strip():
            batches.append(current.strip())
        return batches

    def _split_on_headings(self, markdown: str) -> List[str]:
        parts = re.split(r"(?m)(?=^#{1,6}\s+\S)", markdown)
        return [part.strip() for part in parts if part.strip()] or [markdown]

    def _stitch(self, parts: List[str]) -> str:
        if not parts:
            return ""
        output = parts[0].strip()
        for part in parts[1:]:
            candidate = part.strip()
            candidate = self._remove_overlap(output, candidate)
            output = f"{output.rstrip()}\n\n{candidate.lstrip()}"
        output = re.sub(r"\n{4,}", "\n\n\n", output)
        return output.strip() + "\n"

    def _remove_overlap(self, previous: str, current: str) -> str:
        prev_tail = previous[-self.options.overlap_chars:] if self.options.overlap_chars > 0 else ""
        lines = current.splitlines()
        while lines and lines[0].strip() and lines[0].strip() in prev_tail:
            lines.pop(0)
        if lines and re.match(r"^#{1,6}\s+", lines[0].strip()):
            first = lines[0].strip()
            if previous.rstrip().endswith(first):
                lines.pop(0)
        return "\n".join(lines).strip()

    def _validate(self, raw: str, normalized: str, *, doc_type: str) -> Dict[str, Any]:
        raw_words = self._word_count(raw)
        normalized_words = self._word_count(normalized)
        ratio = normalized_words / max(raw_words, 1)
        errors = []
        warnings = []
        if normalized_words < 50:
            errors.append("normalized_output_too_short")
        if ratio < self.options.min_word_ratio:
            errors.append(f"word_retention_below_threshold:{ratio:.2f}")
        if normalized.count("```") % 2 != 0:
            errors.append("unclosed_code_fence")
        if doc_type == "qna":
            raw_q = len(re.findall(r"(?im)^\s*(?:Q|Question)\s*[:.]", raw))
            norm_q = len(re.findall(r"(?im)^\s*Q\s*:", normalized))
            if raw_q >= 3 and norm_q < max(1, int(raw_q * 0.8)):
                errors.append("qna_pair_loss")
        if "[unclear]" in normalized.lower():
            warnings.append("contains_unclear_markers")
        return {
            "raw_word_count": raw_words,
            "normalized_word_count": normalized_words,
            "word_retention_ratio": round(ratio, 3),
            "errors": errors,
            "warnings": warnings,
        }

    def _batch_warnings(self, markdown: str) -> List[str]:
        warnings = []
        if markdown.count("```") % 2 != 0:
            warnings.append("unclosed_code_fence")
        if not self._headings(markdown):
            warnings.append("no_headings")
        return warnings

    def _headings(self, markdown: str) -> List[str]:
        return re.findall(r"(?m)^#{1,6}\s+.+$", markdown or "")

    def _word_count(self, text: str) -> int:
        return len(re.findall(r"\b\w+\b", text or ""))

    def _response_content(self, response: Any) -> str:
        if isinstance(response, dict):
            return (response.get("message") or {}).get("content") or response.get("response") or ""
        message = getattr(response, "message", None)
        if isinstance(message, dict):
            return message.get("content", "")
        if message is not None:
            return getattr(message, "content", "") or str(message)
        return str(response or "")

    def _clean_model_markdown(self, text: str) -> str:
        text = (text or "").strip()
        text = re.sub(r"^```(?:markdown|md)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text.strip() + "\n"

    def _post_process_markdown(self, markdown: str) -> str:
        text = markdown or ""
        replacements = {
            "Dev Ops": "DevOps",
            "DS Py": "DSPy",
            "WSGIServer": "WSGI Server",
            "MCPendpoints": "MCP endpoints",
            "HumanGuard": "Human Guard",
            "CommandReference": "Command Reference",
            "SupportedCommands": "Supported Commands",
            "&Context": "& Context",
            "su bprocess": "subprocess",
            "sautÃ©": "saute",
            "â€”": "-",
            "â€“": "-",
            "â€˜": "'",
            "â€™": "'",
            "â€œ": '"',
            "â€\u009d": '"',
        }
        for bad, good in replacements.items():
            text = text.replace(bad, good)
        text = self._normalize_toc_links(text)
        return text.strip() + "\n"

    def _normalize_toc_links(self, markdown: str) -> str:
        lines = markdown.splitlines()
        out = []
        in_toc = False
        for line in lines:
            stripped = line.strip()
            if re.match(r"^##\s+Table of Contents\s*$", stripped, re.I):
                in_toc = True
                out.append("## Table of Contents")
                continue
            if in_toc:
                if not stripped or stripped == "---":
                    out.append(line)
                    if stripped == "---":
                        in_toc = False
                    continue
                match = re.match(r"^(\d+(?:\.\d+)*)\.\s+(.+?)\s*(?:\.{2,}\s*\d+)?$", stripped)
                if match:
                    label = f"{match.group(1)}. {match.group(2).strip()}"
                    out.append(f"- [{label}](#{self._anchor_slug(label)})")
                    continue
                if stripped.startswith("#"):
                    in_toc = False
            out.append(line)
        return "\n".join(out)

    def _anchor_slug(self, heading: str) -> str:
        slug = heading.strip().lower()
        slug = re.sub(r"[`*_']", "", slug)
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)
        slug = re.sub(r"\s", "-", slug)
        return slug
