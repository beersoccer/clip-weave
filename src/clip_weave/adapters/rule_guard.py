"""Rule Guard — Python pre-flight checks for HF-specific rules + Fix Registry.

Runs before `npx hyperframes check` to catch known violations deterministically
(<1s, 0 LLM tokens). Known patterns are fixed in-place; unknown errors fall through
to HF's own check/lint cycle.
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

RULE_IDS = [
    "media_in_subcomposition",
    "gsap_css_transform_conflict",
    "gsap_timeline_set_initial_hide",
    "preserve_3d_filter",
]


@dataclass
class Violation:
    rule_id: str
    file: Path
    line: int
    detail: str
    fingerprint: str = field(init=False)

    def __post_init__(self):
        self.fingerprint = hashlib.sha1(
            f"{self.rule_id}:{self.file.name}:{self.line}".encode()
        ).hexdigest()[:12]


@dataclass
class GuardResult:
    violations: list[Violation] = field(default_factory=list)
    fixed: list[Violation] = field(default_factory=list)
    unknown: list[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.unknown) == 0


def _check_media_in_subcomposition(html: str, path: Path) -> list[Violation]:
    """<video>/<audio> must be direct children of index.html root, not in compositions/."""
    violations = []
    for i, line in enumerate(html.splitlines(), 1):
        if re.search(r"<(video|audio)\b", line):
            violations.append(Violation(
                rule_id="media_in_subcomposition",
                file=path,
                line=i,
                detail=f"<video>/<audio> in composition file — must be in index.html root",
            ))
    return violations


def _check_gsap_css_transform_conflict(html: str, path: Path) -> list[Violation]:
    """CSS transform: translateX/Y() and GSAP x/y on same element."""
    violations = []
    lines = html.splitlines()
    for i, line in enumerate(lines, 1):
        if re.search(r"transform:\s*translate[XY]\(", line):
            violations.append(Violation(
                rule_id="gsap_css_transform_conflict",
                file=path,
                line=i,
                detail="CSS translateX/Y() found — may conflict with GSAP x/y; use xPercent/yPercent",
            ))
    return violations


def _check_gsap_timeline_set_initial_hide(html: str, path: Path) -> list[Violation]:
    """gsap.set() at page-load scope on clip elements not yet in DOM.

    Only flags calls with ≤4 spaces of leading indent (top-level / first-level
    scope). Calls inside callbacks or function bodies (indent ≥5) are skipped to
    avoid false positives from gsap.set() used inside ScrollTrigger, onComplete, etc.
    """
    violations = []
    for i, line in enumerate(html.splitlines(), 1):
        stripped = line.lstrip()
        if not re.search(r"\bgsap\.set\s*\(", stripped):
            continue
        if len(line) - len(stripped) > 4:  # inside a callback — skip
            continue
        violations.append(Violation(
            rule_id="gsap_timeline_set_initial_hide",
            file=path,
            line=i,
            detail="gsap.set() at page load — if targeting a later-scene clip, use tl.set() inside timeline",
        ))
    return violations


def _check_preserve_3d_filter(html: str, path: Path) -> list[Violation]:
    """transform-style:preserve-3d with filter on ancestor."""
    violations = []
    if "preserve-3d" in html and "filter:" in html:
        violations.append(Violation(
            rule_id="preserve_3d_filter",
            file=path,
            line=0,
            detail="preserve-3d + filter both present — verify filter is not on an ancestor of preserve-3d element",
        ))
    return violations


def _fix_gsap_css_transform_conflict(html: str) -> str:
    """Replace x:/y: with xPercent:/yPercent: inside GSAP call object literals only.

    Scopes the substitution to the vars object of gsap.to/from/fromTo/set calls so
    that non-GSAP JS objects (chart configs, SVG data, etc.) are not corrupted.
    """
    def _rewrite_vars(obj: str) -> str:
        obj = re.sub(r"\bx:\s*(-?[\d.]+)", lambda m: f"xPercent: {m.group(1)}", obj)
        obj = re.sub(r"\by:\s*(-?[\d.]+)", lambda m: f"yPercent: {m.group(1)}", obj)
        return obj

    def _replace_call(m: re.Match) -> str:
        return m.group(1) + _rewrite_vars(m.group(2))

    # Match (gsap|tl).to/from/fromTo/set(…, { … }) and rewrite only the vars object
    return re.sub(
        r"((?:gsap|tl)\s*\.\s*(?:to|from|fromTo|set)\s*\([^{]*?)(\{[^}]*\})",
        _replace_call,
        html,
        flags=re.DOTALL,
    )


_FIXERS = {
    "gsap_css_transform_conflict": _fix_gsap_css_transform_conflict,
}


def scan(compositions_dir: Path) -> GuardResult:
    """Scan all HTML files in compositions_dir for HF rule violations."""
    result = GuardResult()
    # **/*.html matches at all depths including root; no need for *.html separately
    html_files = list(compositions_dir.glob("**/*.html"))

    for path in html_files:
        html = path.read_text(encoding="utf-8", errors="replace")
        all_violations = (
            _check_media_in_subcomposition(html, path)
            + _check_gsap_css_transform_conflict(html, path)
            + _check_gsap_timeline_set_initial_hide(html, path)
            + _check_preserve_3d_filter(html, path)
        )

        for v in all_violations:
            fixer = _FIXERS.get(v.rule_id)
            if fixer:
                fixed_html = fixer(html)
                if fixed_html and fixed_html != html:
                    path.write_text(fixed_html, encoding="utf-8")
                    html = fixed_html
                    result.fixed.append(v)
                    logger.info("Fixed %s in %s:%d", v.rule_id, path.name, v.line)
                else:
                    result.violations.append(v)
                    result.unknown.append(v)
            else:
                result.violations.append(v)
                result.unknown.append(v)
                logger.warning("Rule violation (no auto-fix): %s in %s:%d — %s",
                               v.rule_id, path.name, v.line, v.detail)

    return result


def save_history(project_dir: Path, result: GuardResult) -> None:
    """Persist violation fingerprints so recurring errors skip LLM repair."""
    history_path = project_dir / ".clip-weave" / "guard-history.json"
    history_path.parent.mkdir(exist_ok=True)
    existing: dict = {}
    if history_path.exists():
        existing = json.loads(history_path.read_text())
    for v in result.fixed:
        existing[v.fingerprint] = {"rule_id": v.rule_id, "status": "fixed"}
    for v in result.unknown:
        existing.setdefault(v.fingerprint, {"rule_id": v.rule_id, "status": "unknown"})
    history_path.write_text(json.dumps(existing, indent=2))
