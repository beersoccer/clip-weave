"""Asset Matcher — vision-enriched semantic matching of capture/ assets to STORYBOARD beats.

Three-phase approach (industry best practice):
  1. Enrich: Vision-describe each image asset via the VIDEO_ANALYSIS_* gateway,
     replacing catalog-derived DOM stubs with rich visual descriptions.
  2. Embed: Generate text embeddings for all descriptions + beat queries in one
     batched call to the same gateway (/embeddings endpoint). Cosine similarity
     gives semantic ranking that BM25 misses (synonyms, cross-lingual matches).
  3. Fallback: If the embedding endpoint is unavailable, fall back to BM25 keyword
     scoring against the enriched descriptions — still much better than raw DOM text.
"""

import base64
import json
import logging
import math
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

TOP_K = 5

# Minimum similarity for a candidate to be offered at all.
#
# Without a floor, top-K always returns K assets — even for a frame whose subject
# does not exist in capture/ — and the downstream consumer cannot tell "best match"
# from "least bad match". Cosine similarity on text-embedding-3-small style models
# sits around 0.25–0.35 for unrelated text and 0.45+ for genuinely related text,
# so 0.35 is a conservative floor. Override with ASSET_MIN_SCORE.
MIN_SCORE_EMBEDDING = 0.35
# BM25 is unbounded and sparse: a zero means not a single query term matched.
MIN_SCORE_BM25 = 0.30

# File extensions treated as visual assets eligible for Vision enrichment
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}

# ── Noise filter ──────────────────────────────────────────────────────────────
# Confirmed noise: browser favicons, QR codes, chat app icons, webpack-hashed
# sprite sheets, loading spinners, and explicit social media icon filenames.
_CAPTURE_NOISE = re.compile(
    r"(favicon\.ico"
    r"|\.ico$"
    r"|wechat[_-]?qrcode"
    r"|whatsapp"
    r"|svg-[0-9a-f]{8,}\.svg$"        # hash-named webpack sprite
    r"|[-_]sprite[-_.]"               # CSS sprite sheets
    r"|social[-_]icon(?:s)?[-_.]"     # explicit "social_icon." / "social-icons."
    r"|loader\.(gif|png|svg)$"        # loading animations
    r")",
    re.IGNORECASE,
)


def _load_asset_descriptions(capture_dir: Path) -> list[dict]:
    """Parse asset-descriptions.md into list of {filename, description, vision} dicts."""
    desc_file = capture_dir / "extracted" / "asset-descriptions.md"
    if not desc_file.exists():
        logger.warning("asset-descriptions.md not found at %s", desc_file)
        return []

    # Parse bullet-list format: "- filename.png — 56KB, above fold, ai logo"
    assets = []
    for line in desc_file.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^-\s+(.+?)\s+[—–-]\s+(.+)$", line)
        if m:
            fname, desc = m.group(1).strip(), m.group(2).strip()
            if not _CAPTURE_NOISE.search(fname):
                assets.append({"filename": fname, "description": desc, "vision": False})

    # Also handle heading-based format ("### filename")
    current: dict | None = None
    for line in desc_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("## ") or line.startswith("### "):
            if current:
                assets.append(current)
            fname = line.lstrip("#").strip()
            if not _CAPTURE_NOISE.search(fname):
                current = {"filename": fname, "description": "", "vision": False}
            else:
                current = None
        elif current and line.strip():
            current["description"] += " " + line.strip()
    if current:
        assets.append(current)

    # Deduplicate by filename
    seen: set[str] = set()
    deduped = []
    for a in assets:
        if a["filename"] not in seen:
            seen.add(a["filename"])
            deduped.append(a)

    return [a for a in deduped if a["description"].strip()]


# ── Vision enrichment ─────────────────────────────────────────────────────────

def _call_vision_gateway(
    image_path: Path,
    base_url: str,
    api_key: str,
    model: str,
) -> str | None:
    """Call the AI gateway chat-completions endpoint with an image, return description."""
    try:
        import requests  # type: ignore

        suffix = image_path.suffix.lower()
        if suffix == ".svg":
            svg_text = image_path.read_text(encoding="utf-8", errors="replace")[:4000]
            payload = {
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": (
                        "Describe this SVG icon/graphic for use in a brand video. "
                        "What does it depict? What brand element does it represent?\n\n"
                        f"SVG content:\n{svg_text}"
                    ),
                }],
                "max_tokens": 120,
            }
        else:
            mime = "image/png" if suffix == ".png" else "image/jpeg"
            img_b64 = base64.b64encode(image_path.read_bytes()).decode()
            payload = {
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{img_b64}"},
                        },
                        {
                            "type": "text",
                            "text": (
                                "Describe this image for use in a brand video. "
                                "Be specific: colors, content, mood, brand elements, "
                                "whether it's suitable as background or foreground. "
                                "One paragraph, ≤80 words."
                            ),
                        },
                    ],
                }],
                "max_tokens": 150,
            }

        endpoint = base_url.rstrip("/") + "/chat/completions"
        resp = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.debug("Vision gateway call failed for %s: %s", image_path.name, exc)
        return None


def _enrich_descriptions(
    assets: list[dict],
    capture_dir: Path,
    base_url: str,
    api_key: str,
    model: str,
) -> list[dict]:
    """Generate Vision descriptions for image assets that only have catalog text."""
    assets_dir = capture_dir / "assets"
    enriched = 0
    for asset in assets:
        fname = asset["filename"]
        ext = Path(fname).suffix.lower()
        if ext not in _IMAGE_EXTS:
            continue
        desc = asset["description"]
        if len(desc) > 120 and "KB" not in desc:
            asset["vision"] = True
            continue

        img_path = assets_dir / fname
        if not img_path.exists():
            continue

        if img_path.stat().st_size > 800_000:
            continue

        vision_desc = _call_vision_gateway(img_path, base_url, api_key, model)
        if vision_desc:
            asset["description"] = vision_desc
            asset["vision"] = True
            enriched += 1

    if enriched:
        logger.info("Vision-enriched %d asset description(s)", enriched)
        _write_enriched_descriptions(assets, capture_dir)

    return assets


def _write_enriched_descriptions(assets: list[dict], capture_dir: Path) -> None:
    """Overwrite asset-descriptions.md with enriched content."""
    desc_file = capture_dir / "extracted" / "asset-descriptions.md"
    lines = ["# Asset Descriptions (Vision-enriched)\n"]
    for asset in assets:
        tag = "🔍" if asset.get("vision") else "📋"
        lines.append(f"- {asset['filename']} — {tag} {asset['description']}")
    desc_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Embedding-based ranking (primary) ────────────────────────────────────────

_EMBED_MODEL_DEFAULT = "text-embedding-3-small"   # OpenAI-compatible default


def _call_embedding_gateway(
    texts: list[str],
    base_url: str,
    api_key: str,
    model: str = _EMBED_MODEL_DEFAULT,
) -> list[list[float]] | None:
    """Batch-embed texts via /embeddings endpoint. Returns None on any failure."""
    try:
        import requests  # type: ignore

        endpoint = base_url.rstrip("/") + "/embeddings"
        resp = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": texts},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        # OpenAI-compatible: {"data": [{"index": N, "embedding": [...]}, ...]}
        items = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in items]
    except Exception as exc:
        logger.debug("Embedding gateway unavailable: %s — falling back to BM25", exc)
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    return dot / (mag_a * mag_b) if mag_a and mag_b else 0.0


def _embed_and_rank(
    queries: list[str],
    assets: list[dict],
    top_k: int,
    base_url: str,
    api_key: str,
    model: str = _EMBED_MODEL_DEFAULT,
    min_score: float = MIN_SCORE_EMBEDDING,
) -> list[list[dict]] | None:
    """Semantic ranking via embeddings. Returns None if gateway unavailable."""
    all_texts = queries + [a["description"] for a in assets]
    vectors = _call_embedding_gateway(all_texts, base_url, api_key, model=model)
    if vectors is None:
        return None

    q_vecs = vectors[:len(queries)]
    a_vecs = vectors[len(queries):]

    results = []
    for q_vec in q_vecs:
        scored = [(_cosine(q_vec, a_vec), asset) for a_vec, asset in zip(a_vecs, assets)]
        scored.sort(key=lambda x: -x[0])
        results.append(_apply_floor(scored[:top_k], min_score, "embedding"))
    return results


def _apply_floor(
    scored: list[tuple[float, dict]], min_score: float, method: str
) -> list[dict]:
    """Attach scores and drop candidates below the quality floor."""
    kept: list[dict] = []
    for score, asset in scored:
        enriched = {**asset, "score": round(float(score), 4), "match_method": method}
        if score >= min_score:
            kept.append(enriched)
        else:
            logger.debug(
                "asset %s dropped: %s score %.4f < floor %.2f",
                asset.get("filename"), method, score, min_score,
            )
    return kept


# ── BM25 fallback ─────────────────────────────────────────────────────────────

def _bm25_score(query_terms: list[str], doc: str) -> float:
    k1, b, avgdl = 1.5, 0.75, 40.0
    doc_terms = re.findall(r"\w+", doc.lower())
    dl = len(doc_terms)
    tf_map: dict[str, int] = {}
    for t in doc_terms:
        tf_map[t] = tf_map.get(t, 0) + 1
    score = 0.0
    for term in query_terms:
        tf = tf_map.get(term, 0)
        if tf == 0:
            continue
        score += (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
    return score


def _bm25_rank(
    queries: list[str],
    assets: list[dict],
    top_k: int,
    min_score: float = MIN_SCORE_BM25,
) -> list[list[dict]]:
    results = []
    for query in queries:
        terms = re.findall(r"\w+", query.lower())
        scored = [(_bm25_score(terms, a["description"]), a) for a in assets]
        scored.sort(key=lambda x: -x[0])
        results.append(_apply_floor(scored[:top_k], min_score, "bm25"))
    return results


# ── Public API ────────────────────────────────────────────────────────────────

def match_assets(
    project_dir: Path,
    beat_queries: list[str],
    top_k: int = TOP_K,
    cfg=None,
    min_score: float | None = None,
) -> list[list[dict]]:
    """For each beat query, return top-K matching assets from capture/.

    Pipeline:
      1. Vision-enrich descriptions   — requires VIDEO_ANALYSIS_* (image understanding)
      2. Semantic embedding ranking   — requires EMBEDDING_* (text similarity)
      3. BM25 fallback                — always available, no config needed

    Phase 1 and Phase 2 are independent: missing one does not affect the other.
    Degradation: EMBEDDING unavailable → BM25 (VIDEO_ANALYSIS is never used for embedding).
    """
    from clip_weave.config import load_config

    if cfg is None:
        cfg = load_config(project_dir)

    capture_dir = project_dir / "capture"
    assets = _load_asset_descriptions(capture_dir)
    if not assets:
        return [[] for _ in beat_queries]

    has_gateway = bool(cfg.video_analysis_base_url and cfg.video_analysis_api_key)

    # Phase 1: Vision enrichment
    if has_gateway:
        assets = _enrich_descriptions(
            assets,
            capture_dir,
            base_url=cfg.video_analysis_base_url,
            api_key=cfg.video_analysis_api_key,
            model=cfg.video_analysis_model,
        )
    else:
        logger.info(
            "Vision enrichment skipped — set VIDEO_ANALYSIS_BASE_URL + VIDEO_ANALYSIS_API_KEY."
        )

    # Phase 2: Embedding-based semantic ranking
    has_embed = bool(cfg.embedding_base_url and cfg.embedding_api_key)

    env_floor = os.getenv("ASSET_MIN_SCORE", "").strip()
    override = min_score if min_score is not None else (float(env_floor) if env_floor else None)

    if has_embed:
        result = _embed_and_rank(
            beat_queries, assets, top_k,
            base_url=cfg.embedding_base_url,
            api_key=cfg.embedding_api_key,
            model=cfg.embedding_model or _EMBED_MODEL_DEFAULT,
            min_score=override if override is not None else MIN_SCORE_EMBEDDING,
        )
        if result is not None:
            logger.info(
                "Asset matching: embedding semantic ranking (%d assets, floor %.2f) — "
                "%s of %d queries got at least one candidate",
                len(assets),
                override if override is not None else MIN_SCORE_EMBEDDING,
                sum(1 for r in result if r),
                len(result),
            )
            return result
        logger.info("Embedding endpoint unavailable — falling back to BM25")
    else:
        logger.info("Embedding skipped — set EMBEDDING_BASE_URL + EMBEDDING_API_KEY.")

    # Phase 3: BM25 fallback
    logger.info("Asset matching: BM25 keyword ranking (%d assets)", len(assets))
    return _bm25_rank(
        beat_queries, assets, top_k,
        min_score=override if override is not None else MIN_SCORE_BM25,
    )
