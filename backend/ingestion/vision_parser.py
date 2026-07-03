"""
Vision-first PDF parser.

Renders each PDF page to an image and asks a multimodal Ollama model to
transcribe the page into strict Markdown. This parser is intentionally isolated
from DocumentProcessor so the ingestion layer can switch parsers without
changing retrieval/chunking contracts.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

import ollama

logger = logging.getLogger("rag_chat_ipr.vision_parser")


DEFAULT_VISION_MARKDOWN_PROMPT = """You are a document transcription engine.

Convert this single PDF page image into faithful Markdown.

Rules:
- Transcribe visible text only. Do not summarize, explain, infer, or invent.
- Preserve reading order.
- Preserve headings with Markdown # levels when visually clear.
- Preserve tables as Markdown tables. Keep every row and column. If a table cell spans lines, keep the full cell text in that row.
- Preserve lists, numbering, footnotes, formulas, captions, and key-value fields.
- If text is unreadable, write [unclear] in place of the unreadable text.
- Do not include code fences.
- Do not mention that you are an AI or that this is an image.
"""


@dataclass
class VisionPage:
    page_number: int
    markdown: str
    image_b64: str


def clean_page_markdown(markdown: str) -> str:
    text = (markdown or "").strip()
    text = re.sub(r"^\s*```(?:markdown|md)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```\s*$", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = normalize_mojibake(text)
    text = remove_model_commentary(text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def normalize_mojibake(text: str) -> str:
    """Fix common UTF-8-as-Windows-1252 artifacts produced by VLM OCR."""
    sequence_replacements = {
        "\u00e2\u20ac\u02dc": "'",
        "\u00e2\u20ac\u2122": "'",
        "\u00e2\u20ac\u0153": '"',
        "\u00e2\u20ac\u009d": '"',
        "\u00e2\u20ac\u201c": "-",
        "\u00e2\u20ac\u201d": "-",
        "\u00e2\u20ac\u00a6": "...",
        "\u00e2\u20ac\u00a2": "-",
        "\u00c2 ": " ",
    }
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
        "\u2022": "-",
        "\ufe0f": "",
        "\U0001f50d": "[search]",
        "\U0001f680": "[rocket]",
        "\U0001f6e0": "[tool]",
        "\U0001f5e3": "[voice]",
        "\U0001f916": "[agent]",
        "\U0001f4ad": "[thought]",
        "\U0001f4a1": "[idea]",
        "\U0001f534": "[red]",
        "\U0001f310": "[web]",
        "â€˜": "'",
        "â€™": "'",
        "â€œ": '"',
        "â€": '"',
        "â€“": "-",
        "â€”": "-",
        "â€¦": "...",
        "â€¢": "-",
        "â‚¹": "Rs.",
        "Â ": " ",
        "Â": "",
    }
    for bad, good in sequence_replacements.items():
        text = text.replace(bad, good)
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def remove_model_commentary(text: str) -> str:
    """Remove common non-document commentary from VLM transcription output."""
    cleaned = []
    skip_rest = False
    commentary_patterns = [
        r"^\s*page\s+number\s*:\s*\d+\s*$",
        r"^\s*here\s+is\s+(?:your\s+)?(?:the\s+)?(?:data|content|text).*?:\s*$",
        r"^\s*here\s+it\s+is\s+in\s+a\s+.*?:\s*$",
        r"^\s*if\s+you\s+want,\s+i\s+can\s+also\b.*$",
        r"^\s*i\s+can\s+also\s+format\b.*$",
    ]
    for line in text.splitlines():
        if skip_rest:
            continue
        stripped = line.strip()
        if any(re.match(pattern, stripped, flags=re.I) for pattern in commentary_patterns):
            if re.match(r"^\s*if\s+you\s+want,\s+i\s+can\s+also\b", stripped, flags=re.I):
                skip_rest = True
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def merge_page_markdown(pages: Iterable[VisionPage], title: Optional[str] = None) -> str:
    parts = []
    if title:
        parts.append(f"# {title.strip()}")
    for page in pages:
        body = clean_page_markdown(page.markdown)
        if not body:
            body = "[unclear]"
        parts.append(f"<!-- page:{page.page_number} -->\n\n## Page {page.page_number}\n\n{body}")
    return "\n\n".join(parts).strip() + "\n"


def response_content(response) -> str:
    """Extract assistant content from dict or ollama typed responses."""
    if isinstance(response, dict):
        return (response.get("message") or {}).get("content", "")
    message = getattr(response, "message", None)
    if isinstance(message, dict):
        return message.get("content", "")
    return getattr(message, "content", "") or ""


class VisionMarkdownParser:
    def __init__(
        self,
        host: str,
        model: str,
        prompt: str = "auto",
        dpi: int = 220,
        timeout_seconds: int = 300,
        concurrency: int = 1,
        retries: int = 1,
        client_factory: Optional[Callable[[str], ollama.AsyncClient]] = None,
    ):
        if not model or model.lower() == "false":
            raise ValueError("Vision parser requires RAG_VLM_MODEL to be configured.")
        self.host = host
        self.model = model
        self.prompt = DEFAULT_VISION_MARKDOWN_PROMPT if prompt in {"", "auto", None} else prompt
        self.dpi = dpi
        self.timeout_seconds = timeout_seconds
        self.concurrency = max(1, concurrency)
        self.retries = max(0, retries)
        self.client_factory = client_factory or (lambda h: ollama.AsyncClient(host=h))

    def render_pdf_pages(self, file_path: str) -> list[tuple[int, str]]:
        """Return (page_number, base64_png) for each PDF page."""
        import fitz

        doc = fitz.open(file_path)
        try:
            zoom = self.dpi / 72.0
            matrix = fitz.Matrix(zoom, zoom)
            pages = []
            for index, page in enumerate(doc, start=1):
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                png_bytes = pix.tobytes("png")
                pages.append((index, base64.b64encode(png_bytes).decode("ascii")))
            return pages
        finally:
            doc.close()

    async def parse_page(self, page_number: int, image_b64: str) -> VisionPage:
        client = self.client_factory(self.host)
        prompt = self.prompt.format(page_number=page_number) if "{page_number}" in self.prompt else self.prompt
        response = await client.chat(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": f"{prompt}\n\nPage number: {page_number}",
                    "images": [image_b64],
                }
            ],
            stream=False,
            think=False,
            options={
                "temperature": 0,
                "num_predict": 4096,
            },
        )
        return VisionPage(
            page_number=page_number,
            markdown=clean_page_markdown(response_content(response)),
            image_b64=image_b64,
        )

    async def parse_pdf_async(self, file_path: str, title: Optional[str] = None) -> tuple[str, list[VisionPage]]:
        rendered_pages = self.render_pdf_pages(file_path)
        semaphore = asyncio.Semaphore(self.concurrency)

        async def run_one(page_number: int, image_b64: str) -> VisionPage:
            async with semaphore:
                last_error: Optional[BaseException] = None
                for attempt in range(self.retries + 1):
                    try:
                        return await asyncio.wait_for(
                            self.parse_page(page_number, image_b64),
                            timeout=self.timeout_seconds,
                        )
                    except Exception as exc:
                        last_error = exc
                        if attempt >= self.retries:
                            break
                        logger.warning(
                            "[VISION_LLM] Page %s failed on attempt %s/%s: %r. Retrying.",
                            page_number,
                            attempt + 1,
                            self.retries + 1,
                            exc,
                        )
                raise RuntimeError(f"Vision parsing failed for page {page_number}: {last_error!r}") from last_error

        pages = await asyncio.gather(*(run_one(n, img) for n, img in rendered_pages))
        pages = sorted(pages, key=lambda p: p.page_number)
        return merge_page_markdown(pages, title=title), pages

    def parse_pdf(self, file_path: str, title: Optional[str] = None) -> tuple[str, list[VisionPage]]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.parse_pdf_async(file_path, title=title))

        # process_file is synchronous and can be called from watcher threads.
        # If a caller is already inside an event loop, use an isolated loop in a
        # worker thread to avoid nested-loop failures.
        result: list[tuple[str, list[VisionPage]]] = []
        error: list[BaseException] = []

        def worker():
            try:
                result.append(asyncio.run(self.parse_pdf_async(file_path, title=title)))
            except BaseException as exc:
                error.append(exc)

        import threading

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join()
        if error:
            raise error[0]
        return result[0]
