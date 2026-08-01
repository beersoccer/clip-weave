"""T2V prompt assembly and the T2V-PROMPTS.md round trip."""

import textwrap

from clip_weave.core.storyboard import parse_storyboard
from clip_weave.core.t2v_prompt import (
    PROMPTS_FILENAME,
    build_doc,
    literal_prompt,
    load_or_create,
    parse_markdown,
    render_markdown,
)

STORYBOARD = textwrap.dedent(
    """\
    ---
    format: 1920x1080
    duration: 12s
    message: "Data-defined driving"
    ---

    ## Video direction

    **Palette**:
    - canvas: `#12151A` (near-black)
    - accent: `#238AFF` (brand blue)

    **Motion grammar**: long-tail power3 easing; VO-paced reveal.

    **Negative list**: no purple AI bokeh; no nav chrome; no cursors.

    ---

    ## Frame 1 — Chassis
    - scene: 底盘俯视图全帧展示，镜头缓慢 push-in
    - voiceover: "蛟龙底盘"
    - duration: 6.4s
    - sfx: mechanical-click, riser
    - asset_candidates: assets/20-1.png (0.61) — 底盘高清俯视图；assets/v6s.png (0.31) — 电机
    - visual_type: live_action

    focal: assets/20-1.png
    narrativeRole: 把驾控性能变成精确数字
    keyMessage: 4×防滑响应

    Scene 1 (0–2s): asset scales in (gsap-effects, spring-pop-entrance).

    ## Frame 2 — CTA
    - scene: logo 拼合，价格大字滑入
    - duration: 5s
    - asset_candidates: assets/weak.png (0.12) — 关系不大的图
    """
)


def _project(tmp_path):
    (tmp_path / "STORYBOARD.md").write_text(STORYBOARD, encoding="utf-8")
    return tmp_path / "STORYBOARD.md"


# ── extraction from HF artifacts ──────────────────────────────────────────────

def test_direction_block_is_captured(tmp_path):
    sb = parse_storyboard(_project(tmp_path))
    assert "#12151A" in sb.direction_field("Palette")
    assert "power3" in sb.direction_field("Motion grammar")
    assert "cursors" in sb.direction_field("Negative list")


def test_asset_candidates_reused_with_scores(tmp_path):
    sb = parse_storyboard(_project(tmp_path))
    candidates = sb.frames[0].asset_candidates()
    assert candidates[0]["filename"] == "assets/20-1.png"
    assert candidates[0]["score"] == 0.61
    assert candidates[0]["description"] == "底盘高清俯视图"
    assert sb.frames[0].focal_asset() == "assets/20-1.png"


def test_reference_dropped_below_score_floor(tmp_path):
    sb = parse_storyboard(_project(tmp_path))
    doc = build_doc(sb, min_asset_score=0.35)
    assert doc.specs[0].reference == "assets/20-1.png"   # 0.61 ≥ floor
    assert doc.specs[1].reference == ""                   # 0.12 < floor


def test_prompt_slots_follow_vendor_order(tmp_path):
    sb = parse_storyboard(_project(tmp_path))
    spec = build_doc(sb).specs[0]
    prompt = spec.to_prompt()
    assert prompt.index("4×防滑响应") < prompt.index("底盘俯视图")     # subject before scene
    assert prompt.index("底盘俯视图") < prompt.index("Camera:")        # scene before camera
    assert "Camera: slow dolly-in" in prompt                          # push-in → dolly-in
    assert "gsap" not in prompt and "spring-pop" not in prompt        # motion jargon stripped


def test_negative_merges_storyboard_list_and_standing_rules(tmp_path):
    sb = parse_storyboard(_project(tmp_path))
    negative = build_doc(sb).specs[0].negative
    assert "cursors" in negative
    assert "subtitles" in negative


def test_voiceover_excluded_by_default(tmp_path):
    sb = parse_storyboard(_project(tmp_path))
    assert "蛟龙底盘" not in build_doc(sb).specs[0].audio
    assert "蛟龙底盘" in build_doc(sb, include_voiceover=True).specs[0].audio


def test_graphics_heavy_frame_is_flagged(tmp_path):
    sb = parse_storyboard(_project(tmp_path))
    assert build_doc(sb).specs[1].needs_review is True


# ── T2V-PROMPTS.md round trip ────────────────────────────────────────────────

def test_markdown_round_trip(tmp_path):
    sb = parse_storyboard(_project(tmp_path))
    doc = build_doc(sb, provider="doubao")
    reparsed = parse_markdown_from_text(tmp_path, render_markdown(doc))
    assert [s.index for s in reparsed.specs] == [1, 2]
    assert reparsed.specs[0].duration == 6
    assert reparsed.specs[0].reference == "assets/20-1.png"
    assert reparsed.globals["provider"] == "doubao"


def parse_markdown_from_text(tmp_path, text):
    path = tmp_path / PROMPTS_FILENAME
    path.write_text(text, encoding="utf-8")
    return parse_markdown(path)


def test_manual_edits_survive_regeneration_guard(tmp_path):
    sb_path = _project(tmp_path)
    load_or_create(sb_path)
    prompts = tmp_path / PROMPTS_FILENAME
    edited = prompts.read_text(encoding="utf-8").replace(
        "```prompt", "```prompt\nHAND WRITTEN SHOT", 1
    )
    prompts.write_text(edited, encoding="utf-8")

    doc, path, created = load_or_create(sb_path)
    assert created is False
    assert "HAND WRITTEN SHOT" in literal_prompt(doc.specs[0])

    doc, path, created = load_or_create(sb_path, regenerate=True)
    assert created is True
    assert "HAND WRITTEN SHOT" not in literal_prompt(doc.specs[0])
