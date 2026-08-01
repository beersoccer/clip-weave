"""Tests for Rule Guard.

Scope note: Rule Guard deliberately implements ONE rule. The other three rules
it used to carry were removed after checking the HyperFrames source — see
docs/superpowers/specs/2026-07-31-rule-guard-soundness-and-t2v-routing-design.md
section 1. The zero-false-positive test below is the regression asset that keeps
them from being reintroduced.
"""

import json

from clip_weave.adapters.rule_guard import RULE_IDS, GuardResult, save_history, scan


# A composition built to HyperFrames' own canonical recipes:
#   - `.world` carries transform-style: preserve-3d and `.layer` carries the
#     leaf DoF filter — the placement 3d-camera-flight.md MANDATES.
#   - a top-level gsap.set() on a non-clip element — the pattern
#     packages/lint/src/rules/gsap.test.ts:2492 asserts must NOT be flagged,
#     and the fix gsap_fullscreen_overlay_starts_visible prescribes.
#   - a static transform: translateX(-50%) on an element animated only via
#     fromTo — both `from` and `fromTo` are exempt in HF's own rule.
# None of this is a violation. Rule Guard must stay silent.
HF_CANONICAL_COMPOSITION = """<template>
<div data-composition-id="03-flight" id="root">
  <div class="stage">
    <div class="world" id="world" data-layout-allow-overflow>
      <div class="card layer" id="card-a"></div>
    </div>
  </div>
  <div class="badge clip" data-start="0" data-duration="5" data-track-index="0"></div>
</div>
<style>
  .stage { position: absolute; inset: 0; perspective: 1200px; }
  .world { transform-style: preserve-3d; transform-origin: 50% 50%; }
  .layer { --dof: 0px; filter: blur(var(--dof)); }
  .badge { position: absolute; left: 50%; transform: translateX(-50%); }
</style>
<script>
  const tl = gsap.timeline({ paused: true });
  gsap.set(".layer", { opacity: 0 });
  tl.fromTo(".badge", { opacity: 0 }, { opacity: 1, duration: 0.4 }, 0);
  window.__timelines["03-flight"] = tl;
</script>
</template>"""


def test_only_one_rule_is_implemented():
    """Guards the scope decision: three rules were removed on purpose."""
    assert RULE_IDS == ["media_in_subcomposition"]


def test_hf_canonical_composition_produces_zero_violations(tmp_path):
    """HF's own documented-correct patterns must never be flagged."""
    (tmp_path / "hf-canonical.html").write_text(HF_CANONICAL_COMPOSITION, encoding="utf-8")

    result = scan(tmp_path)

    assert result.violations == [], [
        (v.rule_id, v.line, v.detail) for v in result.violations
    ]
    assert result.ok is True


def test_media_in_composition_is_flagged(tmp_path):
    (tmp_path / "01-hero.html").write_text(
        "<template>\n<video src='hero.mp4' muted playsinline></video>\n</template>",
        encoding="utf-8",
    )

    result = scan(tmp_path)

    assert len(result.violations) == 1
    assert result.violations[0].rule_id == "media_in_subcomposition"
    assert result.violations[0].line == 2
    assert result.ok is False


def test_audio_in_composition_is_flagged(tmp_path):
    (tmp_path / "01-hero.html").write_text(
        "<template>\n<audio src='bgm.mp3'></audio>\n</template>", encoding="utf-8"
    )

    result = scan(tmp_path)

    assert [v.rule_id for v in result.violations] == ["media_in_subcomposition"]


def test_scan_walks_nested_frame_directories(tmp_path):
    nested = tmp_path / "frames"
    nested.mkdir()
    (nested / "02-demo.html").write_text("<video src='x.mp4'></video>", encoding="utf-8")

    result = scan(tmp_path)

    assert len(result.violations) == 1
    assert result.violations[0].file.name == "02-demo.html"


def test_clean_composition_produces_no_violations(tmp_path):
    (tmp_path / "01-hero.html").write_text(
        "<template><div id='root'><h1>Hello</h1></div></template>", encoding="utf-8"
    )

    result = scan(tmp_path)

    assert result.violations == []
    assert result.ok is True


def test_save_history_creates_missing_parent_directories(tmp_path):
    project_dir = tmp_path / "videos" / "proj"  # does not exist yet
    (tmp_path / "01.html").write_text("<video src='x.mp4'></video>", encoding="utf-8")
    result = scan(tmp_path)

    save_history(project_dir, result)

    history = project_dir / ".clip-weave" / "guard-history.json"
    assert history.exists()
    assert list(json.loads(history.read_text()).values())[0]["rule_id"] == (
        "media_in_subcomposition"
    )


def test_save_history_rebuilds_corrupt_file(tmp_path):
    project_dir = tmp_path / "proj"
    history = project_dir / ".clip-weave" / "guard-history.json"
    history.parent.mkdir(parents=True)
    history.write_text("{not json at all", encoding="utf-8")

    (tmp_path / "01.html").write_text("<video src='x.mp4'></video>", encoding="utf-8")
    save_history(project_dir, scan(tmp_path))

    assert len(json.loads(history.read_text())) == 1


def test_save_history_is_additive(tmp_path):
    project_dir = tmp_path / "proj"
    (tmp_path / "01.html").write_text("<video src='a.mp4'></video>", encoding="utf-8")
    save_history(project_dir, scan(tmp_path))

    (tmp_path / "02.html").write_text("<audio src='b.mp3'></audio>", encoding="utf-8")
    save_history(project_dir, scan(tmp_path))

    history = project_dir / ".clip-weave" / "guard-history.json"
    assert len(json.loads(history.read_text())) == 2


def test_guard_result_has_no_fixed_field():
    """`fixed` was removed: it was always empty and misled callers."""
    assert not hasattr(GuardResult(), "fixed")
