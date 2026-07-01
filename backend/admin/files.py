from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import BinaryIO

from fastapi import HTTPException, UploadFile

from backend.admin.db import admin_data_dir
from backend.admin.inventory import ADMIN_FOLDER, GENERATED_ROOT, SOURCE_ROOT
from backend.admin.repository import new_id


ALLOWED_SOURCE_EXTENSIONS = {".pdf", ".docx"}
ALLOWED_MARKDOWN_EXTENSIONS = {".md", ".markdown"}


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.basename(name)).strip("_")
    return cleaned or "file"


def files_root() -> Path:
    root = SOURCE_ROOT / ADMIN_FOLDER
    root.mkdir(parents=True, exist_ok=True)
    return root


def generated_root() -> Path:
    root = GENERATED_ROOT / ADMIN_FOLDER
    root.mkdir(parents=True, exist_ok=True)
    return root


def document_root(batch_id: str, document_id: str, ingestion_type: str = "general") -> Path:
    type_folder = "QnA" if str(ingestion_type).lower() == "qna" else "General"
    root = files_root() / type_folder / "batches" / batch_id / "documents" / document_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_inside_admin_data(path: str | Path) -> Path:
    resolved = Path(path).resolve()
    roots = [admin_data_dir().resolve(), SOURCE_ROOT.resolve(), GENERATED_ROOT.resolve()]
    if not any(root == resolved or root in resolved.parents for root in roots):
        raise HTTPException(status_code=403, detail="Path is outside allowed project storage")
    return resolved


async def save_source_upload(batch_id: str, upload: UploadFile, config: dict, ingestion_type: str = "general") -> dict:
    filename = safe_name(upload.filename or "document")
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_SOURCE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX files are supported")

    document_id = new_id("doc")
    normalized_type = "qna" if str(ingestion_type).lower() == "qna" else "general"
    target_dir = document_root(batch_id, document_id, normalized_type) / "source"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename
    size = 0
    with target_path.open("wb") as out:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > 500 * 1024 * 1024:
                target_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="File exceeds 500 MB upload limit")
            out.write(chunk)

    return {
        "document_id": document_id,
        "original_filename": filename,
        "source_file_path": str(target_path),
        "file_type": ext.lstrip("."),
        "file_size_bytes": size,
        "effective_config": {**config, "ingestion_type": normalized_type},
    }


def variant_dir(batch_id: str, document_id: str, variant_id: str) -> Path:
    target = generated_root() / "batches" / batch_id / "documents" / document_id / "variants" / variant_id
    target.mkdir(parents=True, exist_ok=True)
    return target


def normalization_dir(batch_id: str, document_id: str, norm_variant_id: str) -> Path:
    target = generated_root() / "batches" / batch_id / "documents" / document_id / "normalizations" / norm_variant_id
    target.mkdir(parents=True, exist_ok=True)
    return target


def review_dir(batch_id: str, document_id: str) -> Path:
    target = generated_root() / "batches" / batch_id / "documents" / document_id / "review"
    target.mkdir(parents=True, exist_ok=True)
    return target


def write_text(path: str | Path, content: str) -> str:
    target = ensure_inside_admin_data(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return str(target)


def read_text(path: str | Path) -> str:
    target = ensure_inside_admin_data(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return target.read_text(encoding="utf-8", errors="ignore")


async def save_review_markdown(batch_id: str, document_id: str, upload: UploadFile) -> tuple[str, str]:
    filename = safe_name(upload.filename or "replacement.md")
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_MARKDOWN_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only markdown files are supported")
    target = review_dir(batch_id, document_id) / "uploaded.md"
    content = await upload.read()
    text = content.decode("utf-8", errors="ignore")
    write_text(target, text)
    return str(target), text[:2000]


def copy_to_review_approved(batch_id: str, document_id: str, source_path: str) -> str:
    source = ensure_inside_admin_data(source_path)
    target = review_dir(batch_id, document_id) / "approved.md"
    shutil.copyfile(source, target)
    return str(target.resolve())


def copy_text_to_review_approved(batch_id: str, document_id: str, content: str) -> str:
    return write_text(review_dir(batch_id, document_id) / "approved.md", content)


def delete_document_source_tree(source_file_path: str) -> None:
    try:
        source = ensure_inside_admin_data(source_file_path)
    except HTTPException:
        return
    document_dir = source.parent.parent
    delete_tree(document_dir)


def delete_tree(path: str | Path) -> None:
    target = ensure_inside_admin_data(path)
    if target.exists():
        shutil.rmtree(target)
