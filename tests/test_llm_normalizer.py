import json
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.ingestion.artifacts import save_parse_artifacts
from backend.ingestion.models import ParseDiagnostics, ParsedDocument
from backend.ingestion.normalizers import LlmMarkdownNormalizer, NormalizationOptions


def test_normalizer_batches_on_heading_boundaries_and_stitches_overlap():
    normalizer = LlmMarkdownNormalizer(
        NormalizationOptions(enabled=True, batch_chars=80, overlap_chars=20)
    )
    markdown = "# Title\n\nIntro text.\n\n## First\n\n" + ("Alpha text. " * 8) + "\n\n## Second\n\n" + ("Beta text. " * 8)

    batches = normalizer._make_batches(markdown)
    stitched = normalizer._stitch(["# Title\n\nIntro text.\n\n## First\n\nAlpha", "## Second\n\nBeta"])

    assert len(batches) >= 2
    assert any(batch.startswith("## Second") or "## Second" in batch for batch in batches)
    assert stitched.count("## Second") == 1


def test_normalizer_validation_rejects_low_retention_output():
    normalizer = LlmMarkdownNormalizer(
        NormalizationOptions(enabled=True, min_word_ratio=0.8)
    )
    raw = " ".join(f"word{i}" for i in range(200))
    validation = normalizer._validate(raw, "# Tiny\n\nOnly a few words.", doc_type="general")

    assert any(error.startswith("word_retention_below_threshold") for error in validation["errors"])


def test_save_parse_artifacts_writes_raw_normalized_and_clean_manifest(tmp_path):
    parsed = ParsedDocument(
        file_path=str(tmp_path / "sample.pdf"),
        filename="sample.pdf",
        doc_type="general",
        markdown="# Normalized\n",
        selected_parser="docling_llm_normalized",
        diagnostics=ParseDiagnostics(parser="docling_llm_normalized", source_type="docling_llm_normalized"),
        parser_outputs={"docling": "# Raw\n", "llm_normalized": "# Normalized\n"},
        raw_markdown="# Raw\n",
        normalization_manifest={
            "enabled": True,
            "status": "accepted",
            "batches": [{"batch_id": 1, "markdown": "# Normalized\n", "input_chars": 6}],
        },
    )

    out_dir = save_parse_artifacts(parsed, root=str(tmp_path / "generated"))

    assert os.path.exists(os.path.join(out_dir, "raw.md"))
    assert os.path.exists(os.path.join(out_dir, "normalized.md"))
    assert os.path.exists(os.path.join(out_dir, "normalized_batches", "batch_001.md"))
    with open(os.path.join(out_dir, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    assert "markdown" not in manifest["normalization"]["batches"][0]
