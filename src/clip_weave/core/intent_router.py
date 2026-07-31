"""Intent Router — parses user input and writes BRIEF.md.

Handles 4 input types: website URL, Figma URL, uploaded local files, text-only.
Routes to the appropriate HF workflow and writes HF-standard BRIEF.md.
"""

import re
from pathlib import Path
from dataclasses import dataclass
from typing import Literal

WorkflowName = Literal[
    "product-launch-video",
    "faceless-explainer",
    "motion-graphics",
    "embedded-captions",
    "talking-head-recut",
    "music-to-video",
    "slideshow",
    "pr-to-video",
    "general-video",
]

FlowMode = Literal["automation", "companion"]

_WORKFLOW_KEYWORDS: list[tuple[list[str], WorkflowName]] = [
    (["产品", "品牌", "宣传", "网站", "product", "brand", "promo", "site"], "product-launch-video"),
    (["解说", "教程", "文字", "explainer", "tutorial", "faceless"], "faceless-explainer"),
    (["动效", "标题卡", "覆盖层", "motion", "kinetic", "lower-third", "overlay"], "motion-graphics"),
    (["字幕", "caption", "subtitle"], "embedded-captions"),
    (["采访", "播客", "overlay", "talking-head", "recut"], "talking-head-recut"),
    (["音乐", "节拍", "music", "beat", "lyric"], "music-to-video"),
    (["演示", "pitch", "deck", "幻灯片", "slideshow"], "slideshow"),
    (["PR", "commit", "pull request", "代码变更"], "pr-to-video"),
]

_COLLABORATIVE_SIGNALS = ["逐步", "审批", "一步步", "collaborative", "我想看"]
_COMPANION_SIGNALS = ["一起做", "companion", "共创"]


@dataclass
class RoutingResult:
    workflow: WorkflowName
    flow: FlowMode
    storyboard: bool
    source_url: str | None
    source_type: Literal["url", "figma", "files", "text"]
    message: str
    length: str = "30s"
    aspect: str = "1920x1080"
    # How the workflow was picked: "semantic" / "keyword" / "keyword-fallback"
    routing_method: str = "keyword"
    routing_confidence: float = 0.0
    routing_reason: str = ""


def detect_source_type(
    user_input: str, uploaded_files: list[Path] | None = None
) -> tuple[Literal["url", "figma", "files", "text"], str | None]:
    """Returns (source_type, source_url) from user input."""
    url_match = re.search(r"https?://\S+", user_input)
    if url_match:
        url = url_match.group(0).rstrip(".,)")
        if "figma.com" in url:
            return "figma", url
        return "url", url
    if uploaded_files:
        return "files", None
    return "text", None


def detect_workflow_by_keywords(user_input: str, source_type: str) -> WorkflowName:
    """Substring matching — the offline fallback for `detect_workflow`."""
    text_lower = user_input.lower()
    for keywords, workflow in _WORKFLOW_KEYWORDS:
        if any(kw.lower() in text_lower for kw in keywords):
            return workflow
    if source_type == "url":
        return "product-launch-video"
    if source_type == "figma":
        return "product-launch-video"
    return "faceless-explainer"


def detect_workflow(
    user_input: str, source_type: str, *, semantic: bool = True
) -> WorkflowName:
    """Route to an HF workflow. Semantic (LLM) first, keywords as fallback."""
    return detect_workflow_explained(user_input, source_type, semantic=semantic)[0]


def detect_workflow_explained(
    user_input: str, source_type: str, *, semantic: bool = True
) -> tuple[WorkflowName, "RouteDecision"]:
    """Same as `detect_workflow`, plus the decision record (method / confidence / reason)."""
    from clip_weave.core.workflow_router import RouteDecision, classify

    keyword_pick = detect_workflow_by_keywords(user_input, source_type)
    if not semantic:
        return keyword_pick, RouteDecision(keyword_pick, "keyword", 0.0, "semantic disabled")

    decision = classify(user_input, source_type, keyword_fallback=keyword_pick)
    return decision.workflow, decision  # type: ignore[return-value]


def detect_mode(user_input: str) -> tuple[FlowMode, bool]:
    """Returns (flow, storyboard_flag)."""
    text_lower = user_input.lower()
    if any(s in text_lower for s in _COMPANION_SIGNALS):
        return "companion", False
    if any(s in text_lower for s in _COLLABORATIVE_SIGNALS):
        return "automation", True
    return "automation", False  # autonomous default


def route(
    user_input: str,
    uploaded_files: list[Path] | None = None,
    message: str = "",
    length: str = "30s",
    aspect: str = "1920x1080",
    semantic: bool = True,
) -> RoutingResult:
    source_type, source_url = detect_source_type(user_input, uploaded_files)
    workflow, decision = detect_workflow_explained(user_input, source_type, semantic=semantic)
    flow, storyboard = detect_mode(user_input)
    return RoutingResult(
        workflow=workflow,
        flow=flow,
        storyboard=storyboard,
        source_url=source_url,
        source_type=source_type,
        message=message or user_input[:120],
        length=length,
        aspect=aspect,
        routing_method=decision.method,
        routing_confidence=decision.confidence,
        routing_reason=decision.reason,
    )


def write_brief(result: RoutingResult, project_dir: Path) -> Path:
    """Write HF-standard BRIEF.md to project_dir."""
    storyboard_val = "yes" if result.storyboard else "no"
    assets_section = ""
    if result.source_url:
        assets_section = f"\n## Assets\n{result.source_url}\n"

    brief = f"""---
workflow: {result.workflow}
flow: {result.flow}
storyboard: {storyboard_val}
message: "{result.message}"
destination: social-feed
aspect: {result.aspect}
language: zh
length: {result.length}
---

## Intent
{result.message}
{assets_section}
## Customizations

## Notes
"""
    project_dir.mkdir(parents=True, exist_ok=True)
    brief_path = project_dir / "BRIEF.md"
    brief_path.write_text(brief, encoding="utf-8")
    return brief_path
