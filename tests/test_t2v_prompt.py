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
from clip_weave.core.t2v_prompt import _clean

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


def test_graphics_heavy_frame_is_flagged_without_a_gateway(tmp_path):
    """No ROUTER_*/HTML_GEN_*/VIDEO_ANALYSIS_* configured (the `offline_by_default`
    autouse fixture clears them) — the rewrite is skipped and the frame is
    flagged needs_review instead, same as before the rewrite feature existed."""
    sb = parse_storyboard(_project(tmp_path))
    spec = build_doc(sb).specs[1]
    assert spec.needs_review is True
    assert "no LLM gateway" in spec.notes


# ── LLM scene rewrite for graphics-intent frames ──────────────────────────────

def test_graphics_intent_scene_is_rewritten_via_gateway(tmp_path, monkeypatch):
    """A card/counter/typography scene line gets rewritten into a filmable shot
    when a gateway is configured, instead of being flagged needs_review."""
    monkeypatch.setenv("ROUTER_BASE_URL", "http://gateway.test/v1")
    monkeypatch.setenv("ROUTER_API_KEY", "k")
    monkeypatch.setenv("ROUTER_MODEL", "test-model")

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {"message": {"content": "低角度环绕底盘特写，金属反光随镜头运动流动"}}
                ]
            }

    calls = []

    def _post(url, **kwargs):
        calls.append((url, kwargs))
        return _Resp()

    import requests

    monkeypatch.setattr(requests, "post", _post)

    sb = parse_storyboard(_project(tmp_path))
    spec = build_doc(sb).specs[1]  # Frame 2 — "logo 拼合，价格大字滑入"

    assert spec.needs_review is False
    assert "rewritten" in spec.notes
    assert "低角度环绕底盘特写" in spec.scene
    assert "logo" not in spec.scene.lower()
    url, kwargs = calls[0]
    assert url == "http://gateway.test/v1/chat/completions"
    assert "价格大字滑入" in kwargs["json"]["messages"][1]["content"]


def test_rewrite_failure_falls_back_to_needs_review(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUTER_BASE_URL", "http://gateway.test/v1")
    monkeypatch.setenv("ROUTER_API_KEY", "k")
    monkeypatch.setenv("ROUTER_MODEL", "test-model")

    import requests

    def _boom(*a, **kw):
        raise requests.RequestException("connection refused")

    monkeypatch.setattr(requests, "post", _boom)

    sb = parse_storyboard(_project(tmp_path))
    spec = build_doc(sb).specs[1]

    assert spec.needs_review is True
    assert "logo" in spec.scene.lower() or "价格" in spec.scene


def test_non_graphics_frame_is_never_sent_to_the_rewrite_gateway(tmp_path, monkeypatch):
    """Frame 1's scene ("底盘俯视图...") has no card/counter/typography hint, so its
    text must never appear in a gateway call — only frame 2's graphics-intent
    scene should be sent for rewriting."""
    monkeypatch.setenv("ROUTER_BASE_URL", "http://gateway.test/v1")
    monkeypatch.setenv("ROUTER_API_KEY", "k")
    monkeypatch.setenv("ROUTER_MODEL", "test-model")

    sent_user_messages = []

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "改写后的镜头"}}]}

    def _post(url, **kwargs):
        sent_user_messages.append(kwargs["json"]["messages"][1]["content"])
        return _Resp()

    import requests

    monkeypatch.setattr(requests, "post", _post)

    sb = parse_storyboard(_project(tmp_path))
    specs = build_doc(sb).specs

    assert specs[0].needs_review is False  # frame 1 — no filmable-hint tokens
    assert len(sent_user_messages) == 1     # only frame 2 (graphics-intent) triggered a call
    assert "底盘俯视图" not in sent_user_messages[0]
    assert "价格大字滑入" in sent_user_messages[0]


# ── T2V-PROMPTS.md round trip ────────────────────────────────────────────────

def test_markdown_round_trip(tmp_path):
    sb = parse_storyboard(_project(tmp_path))
    doc = build_doc(sb, provider="doubao")
    reparsed = parse_markdown_from_text(tmp_path, render_markdown(doc))
    assert [s.index for s in reparsed.specs] == [1, 2]
    assert reparsed.specs[0].duration == 6
    assert reparsed.specs[0].reference == "assets/20-1.png"
    assert reparsed.globals["provider"] == "doubao"


def test_required_reference_requirement_round_trips(tmp_path):
    sb = parse_storyboard(_project(tmp_path))
    doc = build_doc(sb)
    doc.specs[0].reference_requirement = "required"

    rendered = render_markdown(doc)
    reparsed = parse_markdown_from_text(tmp_path, rendered)

    assert "- reference_requirement: required" in rendered
    assert reparsed.specs[0].reference_requirement == "required"


def test_reference_without_requirement_defaults_to_optional(tmp_path):
    doc = parse_markdown_from_text(
        tmp_path,
        "## Frame 1 — Chassis\n- reference: assets/chassis.png\n",
    )

    assert doc.specs[0].reference == "assets/chassis.png"
    assert doc.specs[0].reference_requirement == "optional"


def test_reference_metadata_round_trips(tmp_path):
    doc = parse_markdown_from_text(
        tmp_path,
        "## Frame 1 — Chassis\n"
        "- reference: assets/chassis.png\n"
        "- reference_source: Wikimedia Commons\n"
        "- reference_license: CC BY 4.0\n",
    )

    spec = doc.specs[0]
    assert spec.reference == "assets/chassis.png"
    assert spec.reference_source == "Wikimedia Commons"
    assert spec.reference_license == "CC BY 4.0"

    rendered = render_markdown(doc)
    assert "- reference_source: Wikimedia Commons" in rendered
    assert "- reference_license: CC BY 4.0" in rendered

    legacy = parse_markdown_from_text(
        tmp_path,
        "## Frame 1 — Chassis\n- reference: assets/chassis.png\n",
    )
    assert legacy.specs[0].reference_source is None
    assert legacy.specs[0].reference_license is None
    assert "reference_source" not in render_markdown(legacy)
    assert "reference_license" not in render_markdown(legacy)


def test_invalid_reference_requirement_defaults_to_optional(tmp_path):
    doc = parse_markdown_from_text(
        tmp_path,
        "## Frame 1 — Chassis\n- reference: assets/chassis.png\n"
        "- reference_requirement: preferred\n",
    )

    assert doc.specs[0].reference_requirement == "optional"


def parse_markdown_from_text(tmp_path, text):
    path = tmp_path / PROMPTS_FILENAME
    path.write_text(text, encoding="utf-8")
    return parse_markdown(path)


def test_clean_strips_bare_gsap_ease_names_outside_parens(tmp_path):
    """_clean() must not leak GSAP vocabulary that isn't inside parens/backticks.

    Regression for a leak found while reviewing a sibling fix in storyboard.py:
    _clean()'s regex only scrubbed tokens INSIDE (...) or `...`, so a bare ease
    name like `power3.out` sitting outside any bracket reached T2V-PROMPTS.md,
    the file handed to a video model.
    """
    body = """---
format: 1920x1080
message: "theme"
---

## Frame 1 - Chassis
- duration: 6s
- blueprint: dataviz-countup
- sfx: riser

Scene 1 (0-2s): asset scales in (gsap-effects, spring-pop-entrance), counter counts up with power3.out.
"""
    path = tmp_path / "STORYBOARD.md"
    path.write_text(body, encoding="utf-8")
    sb = parse_storyboard(path)

    doc = build_doc(sb)
    scene = doc.specs[0].scene

    for leaked in ("power3.out", "gsap-effects", "spring-pop-entrance"):
        assert leaked not in scene, f"{leaked!r} leaked into the T2V scene slot: {scene!r}"

    # Not just "the jargon is gone" — the surrounding legitimate content
    # must survive. A test that only checks absence would still pass if
    # _clean() became arbitrarily more destructive.
    assert "asset scales in" in scene
    assert "counter counts up" in scene


def test_clean_does_not_delete_ordinary_words_that_look_like_vocab():
    """Ordinary English/identifiers that happen to contain GSAP-ish substrings
    must survive _clean(). This is the regression for the over-match the
    reviewer found: a bare-token pass that includes generic words like
    `stagger`/`scaleX` deletes real prose, not just jargon.
    """
    sentence = "The actors stagger across the stage in disbelief."
    assert _clean(sentence) == sentence

    identifier_case = "value scaleXform"
    assert _clean(identifier_case) == identifier_case


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
