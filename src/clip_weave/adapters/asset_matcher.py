"""Asset Matcher — semantic matching of capture/ assets to STORYBOARD beats.

Reads capture/extracted/asset-descriptions.md, computes embeddings,
and writes asset_candidates into each STORYBOARD beat before HF skill runs.

Falls back to keyword matching when no embedding provider is configured.
"""

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

TOP_K = 5


def _load_asset_descriptions(capture_dir: Path) -> list[dict]:
    """Parse asset-descriptions.md into list of {path, description} dicts."""
    desc_file = capture_dir / "extracted" / "asset-descriptions.md"
    if not desc_file.exists():
        logger.warning("asset-descriptions.md not found at %s", desc_file)
        return []

    assets = []
    current: dict | None = None
    for line in desc_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("## ") or line.startswith("### "):
            if current:
                assets.append(current)
            # Extract filename from heading like "### 0-1-1.jpg"
            filename = line.lstrip("#").strip()
            current = {"filename": filename, "description": ""}
        elif current and line.strip():
            current["description"] += " " + line.strip()
    if current:
        assets.append(current)

    return [a for a in assets if a["description"].strip()]


def _keyword_match(query: str, assets: list[dict], top_k: int) -> list[dict]:
    """Naive keyword matching fallback — no embedding required."""
    query_words = set(re.findall(r"\w+", query.lower()))
    scored = []
    for asset in assets:
        desc_words = set(re.findall(r"\w+", asset["description"].lower()))
        score = len(query_words & desc_words)
        scored.append((score, asset))
    scored.sort(key=lambda x: -x[0])
    return [a for _, a in scored[:top_k]]


def _embedding_match(query: str, assets: list[dict], top_k: int, cache: dict) -> list[dict]:
    """Embedding-based matching via Gemini text-embedding-004."""
    try:
        import google.generativeai as genai  # type: ignore
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])

        def embed(text: str, task_type: str) -> list[float]:
            cache_key = f"{task_type}:{text}"
            if cache_key in cache:
                return cache[cache_key]
            result = genai.embed_content(
                model="models/text-embedding-004",
                content=text,
                task_type=task_type,
            )
            vec = result["embedding"]
            cache[cache_key] = vec
            return vec

        import math

        def cosine(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(x * x for x in b))
            return dot / (na * nb + 1e-9)

        q_vec = embed(query, "RETRIEVAL_QUERY")
        scored = []
        for asset in assets:
            a_vec = embed(asset["description"], "RETRIEVAL_DOCUMENT")
            score = cosine(q_vec, a_vec)
            scored.append((score, asset))
        scored.sort(key=lambda x: -x[0])
        return [a for _, a in scored[:top_k]]

    except Exception as exc:
        logger.warning("Embedding match failed (%s), falling back to keyword", exc)
        return _keyword_match(query, assets, top_k)


def match_assets(
    project_dir: Path,
    beat_queries: list[str],
    top_k: int = TOP_K,
) -> list[list[dict]]:
    """For each beat query, return top-K matching assets from capture/.

    Returns a list (one per beat) of lists of asset dicts with keys:
      filename, description, [score]
    """
    capture_dir = project_dir / "capture"
    assets = _load_asset_descriptions(capture_dir)
    if not assets:
        return [[] for _ in beat_queries]

    # Load or init embedding cache
    cache_path = capture_dir / "extracted" / "embeddings.json"
    cache: dict = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except Exception:
            pass

    use_embeddings = bool(os.environ.get("GEMINI_API_KEY"))
    results = []
    for query in beat_queries:
        if use_embeddings:
            candidates = _embedding_match(query, assets, top_k, cache)
        else:
            candidates = _keyword_match(query, assets, top_k)
        results.append(candidates)

    # Persist updated embedding cache
    if use_embeddings and cache:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=2))

    return results
