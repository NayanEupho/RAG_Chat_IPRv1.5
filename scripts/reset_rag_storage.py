from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def resolve_inside_root(path: Path) -> Path:
    resolved = path.resolve()
    root = PROJECT_ROOT.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"Refusing to touch path outside project root: {resolved}")
    return resolved


def remove_path(path: Path, *, apply: bool) -> None:
    target = resolve_inside_root(path)
    if not target.exists():
        print(f"[skip] missing: {target}")
        return
    print(f"[delete] {target}")
    if not apply:
        return
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()


def ensure_dir(path: Path, *, apply: bool) -> None:
    target = resolve_inside_root(path)
    print(f"[mkdir] {target}")
    if apply:
        target.mkdir(parents=True, exist_ok=True)


def reset_admin_db(admin_data_dir: Path, *, apply: bool) -> None:
    for suffix in ("", "-wal", "-shm"):
        remove_path(admin_data_dir / f"admin.db{suffix}", apply=apply)
    ensure_dir(admin_data_dir, apply=apply)
    if not apply:
        print("[init] admin dashboard SQLite schema")
        return

    os.environ["ADMIN_DASHBOARD_DATA_DIR"] = str(admin_data_dir)
    from backend.admin.db import init_admin_db

    init_admin_db()
    print("[init] admin dashboard SQLite schema")


def init_chroma_collection(chroma_dir: Path, *, apply: bool) -> None:
    ensure_dir(chroma_dir, apply=apply)
    if not apply:
        print("[init] empty Chroma collection rag_documents")
        return

    from backend.rag.store import VectorStore

    store = VectorStore(persist_dir=str(chroma_dir))
    store.clear_all()
    print("[init] empty Chroma collection rag_documents")


def count_existing(paths: list[Path]) -> None:
    print("Current storage snapshot:")
    for path in paths:
        target = resolve_inside_root(path)
        if target.is_dir():
            files = sum(1 for item in target.rglob("*") if item.is_file())
            print(f"  {target}: directory, {files} files")
        elif target.exists():
            print(f"  {target}: file, {target.stat().st_size} bytes")
        else:
            print(f"  {target}: missing")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reset RAG storage roots and recreate directories needed by admin-dashboard ingestion.",
    )
    parser.add_argument("--apply", action="store_true", help="Actually delete and recreate storage. Without this, only prints planned actions.")
    parser.add_argument("--reset-admin-db", action="store_true", help="Delete and recreate admin_data/admin.db so dashboard history matches wiped files.")
    parser.add_argument("--keep-chroma-dir", action="store_true", help="Clear Chroma collection but do not delete the chroma_db directory first.")
    parser.add_argument("--upload-root", default="upload_docs", help="Source upload root relative to project root.")
    parser.add_argument("--generated-root", default="generated_doc_md", help="Generated artifact root relative to project root.")
    parser.add_argument("--chroma-root", default="chroma_db", help="Chroma persistence directory relative to project root.")
    parser.add_argument("--admin-data-root", default="admin_data", help="Admin dashboard SQLite/data directory relative to project root.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    upload_root = PROJECT_ROOT / args.upload_root
    generated_root = PROJECT_ROOT / args.generated_root
    chroma_root = PROJECT_ROOT / args.chroma_root
    admin_data_root = PROJECT_ROOT / args.admin_data_root

    print(f"Project root: {PROJECT_ROOT}")
    if not args.apply:
        print("DRY RUN: pass --apply to execute these actions.")
    count_existing([upload_root, generated_root, chroma_root, admin_data_root / "admin.db"])

    remove_path(upload_root, apply=args.apply)
    remove_path(generated_root, apply=args.apply)
    if args.keep_chroma_dir:
        ensure_dir(chroma_root, apply=args.apply)
    else:
        remove_path(chroma_root, apply=args.apply)

    ensure_dir(upload_root / "General", apply=args.apply)
    ensure_dir(upload_root / "QnA", apply=args.apply)
    ensure_dir(upload_root / "Admin_Dashboard", apply=args.apply)
    ensure_dir(generated_root / "Admin_Dashboard", apply=args.apply)
    init_chroma_collection(chroma_root, apply=args.apply)

    if args.reset_admin_db:
        reset_admin_db(admin_data_root, apply=args.apply)
    else:
        print("[keep] admin dashboard DB unchanged")
        print("       Use --reset-admin-db if you are wiping files and want to remove stale dashboard history.")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
