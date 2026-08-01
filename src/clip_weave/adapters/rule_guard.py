"""Rule Guard — pre-assembly pre-flight for the one HF rule that needs it.

Scope is deliberately narrow. Rule Guard used to carry four detectors; three
were removed after checking the HyperFrames source directly. Do not reintroduce
them — `tests/test_rule_guard.py` asserts the scope, and the design record is
`docs/superpowers/specs/2026-07-31-rule-guard-soundness-and-t2v-routing-design.md`.

Why the other three are gone:

* `gsap_css_transform_conflict` — HF implements it in
  `packages/lint/src/rules/gsap.ts` at error severity, on top of an acorn AST
  parser that resolves computed timelines, label positions and standalone
  `gsap.*` calls, and exempts both `from` and `fromTo`. A regex approximation is
  strictly worse and produces false positives on correct code.
* `gsap_timeline_set_initial_hide` — HF's rule of that name means the OPPOSITE.
  It warns about a zero-duration `tl.set(...)` at position 0 INSIDE the paused
  timeline (frame 0 renders un-hidden), and explicitly exempts off-timeline
  `gsap.set()`. `packages/lint/src/rules/gsap.test.ts:2492` asserts a top-level
  `gsap.set('#a', { opacity: 0 })` must NOT be flagged. The previous
  implementation flagged exactly that, and advised moving it into the timeline —
  which is what HF warns about.
* `preserve_3d_filter` — no HF lint code exists for it, but deciding whether a
  `filter` actually breaks a 3D context needs full CSS cascade resolution plus
  the ancestor chain. Not decidable at the regex layer, and the constraint is
  already inlined into each frame worker's packet.

What remains earns its place: `media_in_subcomposition` is a NON-NEGOTIABLE
constraint (`hyperframes-core/references/variables-and-media.md`) whose failure
mode is a black/blank render, and HF's own lint rule for it is inactive in two
windows that clip-weave operates in:

1. Pre-assembly — `packages/lint/src/project.ts:141` reads `index.html` first,
   so the whole lint cannot run before the project is assembled.
2. Single-file entry — `project.ts:165` skips the `compositions/` walk when an
   entry file is given and never sets `isSubComposition`, while the rule starts
   with `if (!options.isSubComposition) return findings;` (`media.ts:349`).
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

RULE_IDS = ["media_in_subcomposition"]

_MEDIA_TAG = re.compile(r"<(video|audio)\b")

_MEDIA_DETAIL = (
    "<video>/<audio> inside a composition file. HF requires media to be a DIRECT "
    "child of the host root (index.html); media inside a sub-composition is never "
    "seeked/decoded and renders BLANK/black. Move it to index.html root and drive "
    "per-scene motion from the MAIN timeline at global time."
)


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
    unknown: list[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.unknown) == 0


def _check_media_in_subcomposition(html: str, path: Path) -> list[Violation]:
    """<video>/<audio> must be a direct child of the index.html root."""
    violations = []
    for i, line in enumerate(html.splitlines(), 1):
        if _MEDIA_TAG.search(line):
            violations.append(
                Violation(
                    rule_id="media_in_subcomposition",
                    file=path,
                    line=i,
                    detail=_MEDIA_DETAIL,
                )
            )
    return violations


def scan(compositions_dir: Path) -> GuardResult:
    """Scan every HTML file under compositions_dir. No auto-fix by design.

    An auto-fixer would have to move the media node into `index.html`, which
    does not exist yet in the pre-assembly window this check exists for.
    """
    result = GuardResult()
    # **/*.html matches at all depths including the root of compositions_dir.
    for path in compositions_dir.glob("**/*.html"):
        html = path.read_text(encoding="utf-8", errors="replace")
        for v in _check_media_in_subcomposition(html, path):
            result.violations.append(v)
            result.unknown.append(v)
            logger.warning(
                "Rule violation: %s in %s:%d — %s", v.rule_id, path.name, v.line, v.detail
            )
    return result


def save_history(project_dir: Path, result: GuardResult) -> None:
    """Append violation fingerprints to a per-project log.

    This is a log, not a control signal: nothing reads it back to make
    decisions. With a single deterministic error-severity rule there is nothing
    for a "recurring violation" escalation to add.
    """
    history_path = project_dir / ".clip-weave" / "guard-history.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if history_path.exists():
        try:
            loaded = json.loads(history_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
            else:
                logger.warning("guard-history.json is not an object — rebuilding it")
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("guard-history.json unreadable (%s) — rebuilding it", exc)
    for v in result.unknown:
        existing.setdefault(v.fingerprint, {"rule_id": v.rule_id, "status": "unknown"})
    history_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
