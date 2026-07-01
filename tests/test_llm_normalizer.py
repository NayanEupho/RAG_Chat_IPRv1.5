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


def test_qna_normalization_prompt_uses_qna_structure_rules():
    normalizer = LlmMarkdownNormalizer(NormalizationOptions(enabled=True))

    prompt = normalizer._batch_prompt(
        rules="Use this exact shape:\nQ: <question>\n\nA: <answer>",
        filename="faq.pdf",
        doc_type="qna",
        parser="docling",
        batch_id=1,
        batch_count=1,
        previous_tail="",
        batch_text="Q1: What is X?\nA: X is Y.",
    )

    assert "Document type: qna" in prompt
    assert "Q: <question>" in prompt
    assert "A: <answer>" in prompt


def test_normalizer_uses_separate_normalization_model(monkeypatch):
    from backend import config as config_module
    from backend.config import OllamaConfig

    calls = []

    class FakeClient:
        def __init__(self, host):
            calls.append({"host": host})

        def chat(self, **kwargs):
            calls.append(kwargs)
            return {"message": {"content": "alpha beta gamma delta epsilon zeta eta theta iota kappa"}}

    config_module._runtime_config.main_model = OllamaConfig(host="http://main-host:11434", model_name="main-model")
    config_module._runtime_config.embedding_model = OllamaConfig(host="http://embed-host:11434", model_name="embed-model")
    config_module._runtime_config.normalization_model = OllamaConfig(host="http://norm-host:11434", model_name="norm-model")
    monkeypatch.setenv("INGEST_NORMALIZE_MIN_WORD_RATIO", "0")

    normalizer = LlmMarkdownNormalizer(
        NormalizationOptions(enabled=True, batch_chars=1000, min_word_ratio=0),
        client_factory=FakeClient,
    )
    result = normalizer.normalize("alpha beta gamma delta", filename="sample.pdf", doc_type="general", parser="docling")

    assert calls[0]["host"] == "http://norm-host:11434"
    assert calls[1]["model"] == "norm-model"
    assert result.manifest["model"] == "norm-model"
    assert result.manifest["host"] == "http://norm-host:11434"


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
