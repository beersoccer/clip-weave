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
    results = match_assets(tmp_path, ["company logo colours"], top_k=1, cfg=cfg)
    assert len(results) == 1
    assert results[0][0]["filename"] == "logo.svg"
    assert results[0][0]["match_method"] == "bm25"
    assert results[0][0]["score"] > 0


def test_below_floor_candidates_are_dropped(tmp_path):
    """No lexical overlap yields nothing, rather than a least-bad guess."""
    _write_descriptions(tmp_path, "- logo.svg — gold and blue company logo\n")
    assert match_assets(tmp_path, ["雪山日落航拍"], top_k=3, cfg=Config()) == [[]]


def test_floor_can_be_lowered_per_call(tmp_path):
    _write_descriptions(tmp_path, "- logo.svg — gold and blue company logo\n")
    results = match_assets(tmp_path, ["雪山日落航拍"], top_k=3, cfg=Config(), min_score=0.0)
    assert results[0][0]["filename"] == "logo.svg"


def test_embedding_floor_filters_weak_matches(tmp_path, monkeypatch):
    """Cosine below the floor is dropped even when it is the top-ranked asset."""
    _write_descriptions(
        tmp_path,
        "- near.jpg — a red sports car on a coastal road\n"
        "- far.jpg — a spreadsheet of quarterly numbers\n",
    )
    # vectors: [query, near, far] — near ~parallel to query, far orthogonal.
    monkeypatch.setattr(
        asset_matcher,
        "_call_embedding_gateway",
        lambda *a, **k: [[1.0, 0.0], [0.99, 0.14], [0.0, 1.0]],
    )
    cfg = Config(embedding_base_url="https://embed.example.com/v1/", embedding_api_key="k")
    results = match_assets(tmp_path, ["red sports car"], top_k=2, cfg=cfg)
    assert [a["filename"] for a in results[0]] == ["near.jpg"]
    assert results[0][0]["match_method"] == "embedding"
