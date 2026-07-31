"""Tests for Asset Matcher ranking and degradation."""

from clip_weave.adapters import asset_matcher
from clip_weave.adapters.asset_matcher import match_assets
from clip_weave.config import Config


def _write_descriptions(tmp_path, body: str):
    desc_file = tmp_path / "capture" / "extracted" / "asset-descriptions.md"
    desc_file.parent.mkdir(parents=True)
    desc_file.write_text(body, encoding="utf-8")
    return desc_file


def test_asset_matcher_bm25_fallback(tmp_path):
    """Without gateway config, should fall back to BM25 and return ranked results."""
    _write_descriptions(
        tmp_path,
        "- team.jpg — professional executives in formal meeting room\n"
        "- chart.png — bar chart showing revenue growth data\n"
        "- office.jpg — modern corporate office interior\n",
    )

    cfg = Config()  # no gateway configured
    results = match_assets(tmp_path, ["executive team meeting", "financial data"], top_k=2, cfg=cfg)

    assert len(results) == 2
    assert len(results[0]) > 0
    assert results[0][0]["filename"] == "team.jpg"


def test_asset_matcher_embedding_fallback_to_bm25(tmp_path, monkeypatch):
    """When embedding endpoint fails, should silently fall back to BM25."""
    _write_descriptions(tmp_path, "- logo.svg — gold and blue company logo\n")

    monkeypatch.setattr(asset_matcher, "_call_embedding_gateway", lambda *a, **k: None)

    cfg = Config(
        embedding_base_url="https://embed.example.com/v1/",
        embedding_api_key="test-key",
    )
    results = match_assets(tmp_path, ["brand identity"], top_k=1, cfg=cfg)
    assert len(results) == 1
    assert results[0][0]["filename"] == "logo.svg"
