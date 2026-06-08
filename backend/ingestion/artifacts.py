import json
import os
import re
from datetime import datetime
from typing import Dict, List

from backend.ingestion.models import ParsedDocument


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")


def artifact_dir_for(file_path: str, parser_name: str = "unknown", root: str = "generated_doc_md", timestamp: str | None = None) -> str:
    filename = os.path.basename(file_path)
    stem = os.path.splitext(filename)[0]
    run_id = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return os.path.join(os.getcwd(), root, _safe_name(stem), _safe_name(parser_name), run_id)


def save_parse_artifacts(parsed: ParsedDocument, chunks: List[Dict] | None = None, root: str = "generated_doc_md") -> str:
    target_dir = artifact_dir_for(parsed.file_path, parsed.selected_parser, root=root)
    os.makedirs(target_dir, exist_ok=True)
    clean_normalization_manifest = None

    if parsed.raw_markdown is not None:
        with open(os.path.join(target_dir, "raw.md"), "w", encoding="utf-8") as f:
            f.write(parsed.raw_markdown or "")

    for parser_name, markdown in parsed.parser_outputs.items():
        if parser_name.startswith("vision_page_"):
            pages_dir = os.path.join(target_dir, "vision_parsed_pages")
            os.makedirs(pages_dir, exist_ok=True)
            page_no = parser_name.rsplit("_", 1)[-1]
            path = os.path.join(pages_dir, f"page_{_safe_name(page_no)}.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(markdown or "")
            continue
        path = os.path.join(target_dir, f"parse_{_safe_name(parser_name)}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(markdown or "")

    with open(os.path.join(target_dir, "selected.md"), "w", encoding="utf-8") as f:
        f.write(parsed.markdown or "")

    if parsed.normalization_manifest:
        normalized = parsed.parser_outputs.get("llm_normalized")
        if normalized is not None:
            with open(os.path.join(target_dir, "normalized.md"), "w", encoding="utf-8") as f:
                f.write(normalized or "")

        batches_dir = os.path.join(target_dir, "normalized_batches")
        os.makedirs(batches_dir, exist_ok=True)
        for batch in parsed.normalization_manifest.get("batches", []):
            batch_id = str(batch.get("batch_id", "")).zfill(3)
            if "markdown" in batch:
                with open(os.path.join(batches_dir, f"batch_{batch_id}.md"), "w", encoding="utf-8") as f:
                    f.write(batch.get("markdown") or "")
            clean_batch = {k: v for k, v in batch.items() if k != "markdown"}
            with open(os.path.join(batches_dir, f"batch_{batch_id}.json"), "w", encoding="utf-8") as f:
                json.dump(clean_batch, f, indent=2)

        clean_normalization_manifest = {
            **parsed.normalization_manifest,
            "batches": [
                {k: v for k, v in batch.items() if k != "markdown"}
                for batch in parsed.normalization_manifest.get("batches", [])
            ],
        }
        with open(os.path.join(target_dir, "normalization_manifest.json"), "w", encoding="utf-8") as f:
            json.dump(clean_normalization_manifest, f, indent=2)

    with open(os.path.join(target_dir, "diagnostics.json"), "w", encoding="utf-8") as f:
        json.dump(parsed.diagnostics.to_dict(), f, indent=2)

    manifest = {
        "file_path": parsed.file_path,
        "filename": parsed.filename,
        "doc_type": parsed.doc_type,
        "selected_parser": parsed.selected_parser,
        "parser_outputs": sorted(parsed.parser_outputs.keys()),
        "normalization": clean_normalization_manifest,
    }
    with open(os.path.join(target_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    if chunks is not None:
        with open(os.path.join(target_dir, "chunks.jsonl"), "w", encoding="utf-8") as f:
            for chunk in chunks:
                f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    return target_dir
