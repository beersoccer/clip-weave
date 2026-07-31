"""Semantic workflow routing — pick the HF workflow by meaning, not keywords.

Keyword matching mis-routes in the ways substring matching always does:

  * "把这段采访里的**字幕**做成炸裂特效"     → hits 字幕 → embedded-captions ✅
  * "给这段采访配上**数据卡片**和下三分之一" → hits 采访 → talking-head-recut ✅
  * "我们不做**产品**广告,只讲讲这个概念"   → hits 产品 → product-launch-video ✗
                                              (真实意图 faceless-explainer)
  * "用这首歌的**节拍**剪我们**网站**素材"   → 先命中 网站 → product-launch ✗
                                              (真实意图 music-to-video)

So the primary path asks an LLM to classify against the workflow taxonomy, and
keyword matching stays as the offline fallback: no gateway config, no network,
or an unparseable answer all degrade to the old behaviour rather than failing.

Gateway config is reused, in order: `ROUTER_*` → `HTML_GEN_*` → `VIDEO_ANALYSIS_*`
(`*_BASE_URL` / `*_API_KEY` / `*_MODEL`).
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

Method = Literal["semantic", "keyword", "keyword-fallback"]

# Distilled from each skill's own `description` in .agents/skills/<name>/SKILL.md,
# trimmed to the discriminating signal so the classifier sees the boundaries.
WORKFLOW_TAXONOMY: dict[str, str] = {
    "product-launch-video": (
        "Market/launch/promote/reveal a product or company — SaaS promo, feature reveal, "
        "product demo, app launch, or a tour of a website shown as-is. Default for a "
        "commercial URL."
    ),
    "faceless-explainer": (
        "Explain a topic or concept from text (article, notes, brief) with invented visuals: "
        "typography, abstract graphics, diagrams, data-viz. No site or footage to capture. "
        "How-tos, concept breakdowns, listicles."
    ),
    "motion-graphics": (
        "A short design-led unit where motion IS the message — kinetic typography, stat "
        "count-up, chart hit, logo sting, lower-third/callout overlay, animated map or tweet, "
        "UI animation. Usually under 10s, no narration, no live-action subject."
    ),
    "embedded-captions": (
        "Add captions/subtitles to an existing talking-head video WITHOUT editing the footage — "
        "plain verbatim subtitles, cinematic captions behind the subject, or VFX/炸裂字幕."
    ),
    "talking-head-recut": (
        "Dress up an existing talking-head/interview/podcast video with designed GRAPHIC "
        "OVERLAY cards — kinetic titles, lower-thirds, data callouts, quotes, PiP — synced to "
        "the transcript. The clip plays untouched underneath. Not plain subtitles."
    ),
    "music-to-video": (
        "A music track drives all pacing — lyric video, beat-synced slideshow or kinetic promo. "
        "Any supplied images/footage are cut onto the beat grid."
    ),
    "slideshow": (
        "A navigable presentation/pitch deck with discrete slides, fragment reveals, branching, "
        "presenter mode. Output is a deck, not a rendered MP4."
    ),
    "pr-to-video": (
        "A code change is the input — a GitHub pull request, owner/repo#N, commits, a diff — "
        "turned into a code-change explainer or changelog video."
    ),
    "general-video": (
        "No specialised workflow fits: longer multi-scene pieces, brand/sizzle reels, montages, "
        "static loops or title cards, footage remixes, freeform builds."
    ),
}

_SYSTEM_PROMPT = """You classify a video request into exactly one HyperFrames workflow.

Workflows:
{taxonomy}

Rules:
- Judge the user's actual intent, not surface keywords. A word may appear while the
  intent is the opposite ("we are NOT making a product ad, just explaining a concept").
- The input source matters: a commercial URL leans product-launch-video, a PR/diff leans
  pr-to-video, an existing talking-head file leans embedded-captions or talking-head-recut.
- Prefer general-video when genuinely ambiguous rather than guessing a specialised one.
- Reply with JSON only: {{"workflow": "<one id>", "confidence": <0-1>, "reason": "<=15 words"}}
"""


@dataclass
class RouteDecision:
    workflow: str
    method: Method
    confidence: float
    reason: str


def _gateway() -> tuple[str, str, str] | None:
    """Return (base_url, api_key, model) from the first configured prefix."""
    # VIDEO_ANALYSIS_* first: on our gateway that route is OpenAI-compatible
    # (`/vertex/v1/chat/completions`), while HTML_GEN_* points at the Bedrock route,
    # which speaks Anthropic-native `/v1/messages` and 404s on `/chat/completions`.
    for prefix, default_model in (
        ("ROUTER", ""),
        ("VIDEO_ANALYSIS", "gemini-2.5-flash"),
        ("HTML_GEN", ""),
    ):
        base = (os.getenv(f"{prefix}_BASE_URL") or "").strip()
        key = (os.getenv(f"{prefix}_API_KEY") or "").strip()
        if base and key:
            model = (os.getenv(f"{prefix}_MODEL") or default_model).strip()
            if model:
                return base.rstrip("/"), key, model
    return None


def classify(
    user_input: str,
    source_type: str = "text",
    *,
    keyword_fallback: str | None = None,
    timeout: int = 20,
) -> RouteDecision:
    """Classify `user_input` into a workflow by meaning, falling back to keywords."""
    fallback = keyword_fallback or "general-video"
    gw = _gateway()
    if not gw:
        logger.info(
            "Semantic routing skipped (no ROUTER_*/HTML_GEN_*/VIDEO_ANALYSIS_* gateway) — "
            "using keyword routing"
        )
        return RouteDecision(fallback, "keyword", 0.0, "no LLM gateway configured")

    base_url, api_key, model = gw
    taxonomy = "\n".join(f"- {name}: {desc}" for name, desc in WORKFLOW_TAXONOMY.items())
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT.format(taxonomy=taxonomy)},
            {
                "role": "user",
                "content": f"input_source: {source_type}\nrequest: {user_input.strip()[:2000]}",
            },
        ],
        # Generous cap: reasoning models spend hidden tokens before the JSON answer
        # (gemini-2.5-flash measured ~490 reasoning tokens for this prompt), and a
        # truncated reply would silently degrade to keyword routing.
        "max_tokens": 1500,
        "temperature": 0,
    }

    try:
        import requests

        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001 - network/shape errors all degrade the same way
        logger.warning("Semantic routing failed (%s) — falling back to keyword routing", exc)
        return RouteDecision(fallback, "keyword-fallback", 0.0, f"LLM unavailable: {exc}"[:120])

    parsed = _parse(content)
    if not parsed:
        logger.warning(
            "Semantic routing returned an unusable answer (%r) — falling back to keywords",
            content[:120],
        )
        return RouteDecision(fallback, "keyword-fallback", 0.0, "unparseable LLM answer")

    workflow, confidence, reason = parsed
    return RouteDecision(workflow, "semantic", confidence, reason)


def _parse(content: str) -> tuple[str, float, str] | None:
    """Extract and validate the classifier's JSON answer."""
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    data: dict = {}
    if match:
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            data = {}
    if not data:
        # Truncated answer (hit max_tokens mid-JSON) — salvage the workflow id if present.
        salvaged = re.search(r'"workflow"\s*:\s*"([\w.-]+)"', text)
        if not salvaged:
            return None
        data = {"workflow": salvaged.group(1), "confidence": 0.0, "reason": "truncated answer"}

    workflow = str(data.get("workflow", "")).strip()
    if workflow not in WORKFLOW_TAXONOMY:
        return None
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    reason = str(data.get("reason", "")).strip()[:200]
    return workflow, max(0.0, min(1.0, confidence)), reason


__all__ = ["RouteDecision", "WORKFLOW_TAXONOMY", "classify"]
