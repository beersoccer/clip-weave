"""Tests for the STORYBOARD.md parser and the text-to-video prompt builder."""

import textwrap

import pytest

from clip_weave.core.storyboard import (
    build_prompt,
    frame_negative_prompt,
    parse_storyboard,
)

FULL_STORYBOARD = """---
format: 1920x1080
duration: 47s
message: "小米 SU7 好看·好开·舒适·安全"
---

## Frame 1 — 爆点数据
- scene: 城市夜景中一辆红色轿车驶过湿滑路面
- voiceover: "2.78 秒破百"
- duration: 5.851s
- beat: hook
- blueprint: counting-dynamic-scale
- roles: hero=counter, support=grid
- sfx: whoosh

narrativeRole: 开场钩子
自由叙述段落，解析器应收进 narrative。

## Frame 2 — 底盘
- scene: 底盘爆炸图缓慢旋转
- duration: 6s
- negative_prompt: 文字, 水印
"""


def _write(tmp_path, body: str, name: str = "STORYBOARD.md"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_parses_frontmatter_and_frames(tmp_path):
    sb = parse_storyboard(_write(tmp_path, FULL_STORYBOARD))

    assert sb.format == "1920x1080"
    assert sb.message == "小米 SU7 好看·好开·舒适·安全"
    assert len(sb.frames) == 2
    assert sb.warnings == []


def test_frame_fields_and_indexes(tmp_path):
    sb = parse_storyboard(_write(tmp_path, FULL_STORYBOARD))
    first, second = sb.frames

    assert (first.index, first.number, first.title) == (1, 1, "爆点数据")
    assert first.scene == "城市夜景中一辆红色轿车驶过湿滑路面"
    assert first.voiceover == "2.78 秒破百"  # quotes stripped
    assert first.duration_seconds == pytest.approx(5.851)
    assert "自由叙述段落" in first.narrative
    assert (second.index, second.number) == (2, 2)


def test_bare_key_value_lines_land_in_meta(tmp_path):
    sb = parse_storyboard(_write(tmp_path, FULL_STORYBOARD))
    assert sb.frames[0].meta.get("narrativeRole") == "开场钩子"


def test_negative_prompt_is_exposed(tmp_path):
    sb = parse_storyboard(_write(tmp_path, FULL_STORYBOARD))
    assert frame_negative_prompt(sb.frames[1]) == "文字, 水印"
    assert frame_negative_prompt(sb.frames[0]) is None


def test_missing_frontmatter_is_tolerated(tmp_path):
    sb = parse_storyboard(_write(tmp_path, "## Frame 1 — A\n- scene: 一只猫\n"))
    assert sb.globals == {}
    assert len(sb.frames) == 1
    assert sb.aspect_ratio() == "16:9"  # default when format is absent


def test_non_mapping_frontmatter_records_warning(tmp_path):
    sb = parse_storyboard(_write(tmp_path, "---\n- just\n- a list\n---\n\n## Frame 1\n- scene: x\n"))
    assert any("not a mapping" in w for w in sb.warnings)
    assert len(sb.frames) == 1


def test_no_frames_records_warning(tmp_path):
    sb = parse_storyboard(_write(tmp_path, "---\nformat: 1080x1920\n---\n\nprose only\n"))
    assert sb.frames == []
    assert any("no `## Frame N` sections" in w for w in sb.warnings)


@pytest.mark.parametrize("heading", ["## Frame 1", "### Beat 1: Title", "## Scene 1 — Title"])
def test_frame_beat_and_scene_headings_all_parse(tmp_path, heading):
    sb = parse_storyboard(_write(tmp_path, f"{heading}\n- scene: 一个镜头\n"))
    assert len(sb.frames) == 1
    assert sb.frames[0].scene == "一个镜头"


@pytest.mark.parametrize(
    "alias,expected_key",
    [
        ("description", "scene"),
        ("summary", "scene"),
        ("caption", "scene"),
        ("vo", "voiceover"),
        ("narration", "voiceover"),
    ],
)
def test_metadata_aliases_are_normalised(tmp_path, alias, expected_key):
    sb = parse_storyboard(_write(tmp_path, f"## Frame 1\n- {alias}: 值\n"))
    assert sb.frames[0].meta[expected_key] == "值"


@pytest.mark.parametrize(
    "fmt,expected",
    [
        ("1920x1080", "16:9"),
        ("1080x1920", "9:16"),
        ("1080x1080", "1:1"),
        ("1600x1200", "4:3"),
        ("2520x1080", "21:9"),
        ("", "16:9"),
        ("garbage", "16:9"),
        ("0x0", "16:9"),
    ],
)
def test_aspect_ratio_mapping(tmp_path, fmt, expected):
    body = f"---\nformat: {fmt}\n---\n\n## Frame 1\n- scene: x\n"
    assert parse_storyboard(_write(tmp_path, body)).aspect_ratio() == expected


def test_slug_handles_chinese_and_falls_back(tmp_path):
    sb = parse_storyboard(_write(tmp_path, "## Frame 1 — 爆点数据\n- scene: x\n\n## Frame 2\n- scene: y\n"))
    assert sb.frames[0].slug() == "爆点数据"
    assert sb.frames[1].slug() == "y"  # falls back to scene when there is no title


def test_non_frame_heading_closes_the_current_frame(tmp_path):
    body = "## Frame 1\n- scene: a\n\n## Notes\n- scene: should-not-attach\n"
    sb = parse_storyboard(_write(tmp_path, body))
    assert len(sb.frames) == 1
    assert sb.frames[0].scene == "a"


# ── build_prompt ──────────────────────────────────────────────────────────────

def test_build_prompt_drops_html_motion_metadata(tmp_path):
    sb = parse_storyboard(_write(tmp_path, FULL_STORYBOARD))
    prompt = build_prompt(sb, sb.frames[0])

    assert "城市夜景" in prompt
    # Motion-implementation metadata describes an HTML composition, not a shot.
    for leaked in ("counting-dynamic-scale", "hero=counter", "whoosh"):
        assert leaked not in prompt


def test_build_prompt_includes_narrative_role_and_beat(tmp_path):
    sb = parse_storyboard(_write(tmp_path, FULL_STORYBOARD))
    prompt = build_prompt(sb, sb.frames[0])
    assert "开场钩子" in prompt
    assert "hook" in prompt


def test_build_prompt_voiceover_is_opt_in(tmp_path):
    sb = parse_storyboard(_write(tmp_path, FULL_STORYBOARD))
    assert "2.78" not in build_prompt(sb, sb.frames[0])
    assert "2.78" in build_prompt(sb, sb.frames[0], include_voiceover=True)


def test_build_prompt_style_replaces_global_theme(tmp_path):
    sb = parse_storyboard(_write(tmp_path, FULL_STORYBOARD))
    with_theme = build_prompt(sb, sb.frames[0])
    with_style = build_prompt(sb, sb.frames[0], style="anamorphic 35mm")

    assert "小米 SU7" in with_theme
    assert "anamorphic 35mm" in with_style
    assert "小米 SU7" not in with_style


def test_build_prompt_falls_back_to_narrative_then_title(tmp_path):
    narrative_only = parse_storyboard(
        _write(tmp_path, "## Frame 1 — T\n\n一段叙述。\n", name="a.md")
    )
    assert "一段叙述" in build_prompt(narrative_only, narrative_only.frames[0])

    bare = parse_storyboard(_write(tmp_path, "## Frame 1 — 只有标题\n", name="b.md"))
    assert build_prompt(bare, bare.frames[0]) == "只有标题"


# ── Frame.asset_candidates ────────────────────────────────────────────────────

def _one_frame(tmp_path, meta_line: str, name: str = "STORYBOARD.md"):
    """A single frame carrying exactly one extra metadata bullet."""
    body = f"## Frame 1 — T\n- scene: x\n{meta_line}\n"
    return parse_storyboard(_write(tmp_path, body, name=name)).frames[0]


def test_asset_candidates_with_scores_split_on_chinese_semicolon(tmp_path):
    frame = _one_frame(
        tmp_path,
        "- asset_candidates: assets/a.png (0.62) — 红色轿车；assets/b.mp4 (0.55) — 电机特写",
    )
    assert frame.asset_candidates() == [
        {"filename": "assets/a.png", "score": 0.62, "description": "红色轿车"},
        {"filename": "assets/b.mp4", "score": 0.55, "description": "电机特写"},
    ]


def test_asset_candidates_split_on_ascii_semicolon(tmp_path):
    frame = _one_frame(
        tmp_path,
        "- asset_candidates: assets/image-3.png — 背景配图; assets/ai-logo.png — 品牌标识",
    )
    assert [c["filename"] for c in frame.asset_candidates()] == [
        "assets/image-3.png",
        "assets/ai-logo.png",
    ]
    assert [c["description"] for c in frame.asset_candidates()] == ["背景配图", "品牌标识"]


def test_asset_candidates_keep_hyphenated_filenames_intact(tmp_path):
    """The separator is a *spaced* hyphen or an em/en dash — never a hyphen inside a name."""
    frame = _one_frame(
        tmp_path,
        "- asset_candidates: 20-1.png (0.62) — a red car；hero-logo.png — the logo",
    )
    assert frame.asset_candidates() == [
        {"filename": "20-1.png", "score": 0.62, "description": "a red car"},
        {"filename": "hero-logo.png", "score": None, "description": "the logo"},
    ]


@pytest.mark.parametrize("dash", ["—", "–", " - "])
def test_asset_candidates_accept_every_separator_form(tmp_path, dash):
    frame = _one_frame(tmp_path, f"- asset_candidates: assets/20-1.png{dash}底盘俯视图")
    assert frame.asset_candidates() == [
        {"filename": "assets/20-1.png", "score": None, "description": "底盘俯视图"}
    ]


@pytest.mark.parametrize(
    "chunk",
    [
        "hero.png",              # no separator at all
        "hero.png (0.62)",       # score but no description
        "20-1.png-no-spaces",    # unspaced hyphen is part of the name, not a separator
    ],
)
def test_asset_candidates_degrade_to_the_whole_chunk(tmp_path, chunk):
    frame = _one_frame(tmp_path, f"- asset_candidates: {chunk}")
    assert frame.asset_candidates() == [
        {"filename": chunk, "score": None, "description": ""}
    ]


@pytest.mark.parametrize("meta_line", ["- scene: only", "- asset_candidates:"])
def test_asset_candidates_empty_when_field_missing_or_blank(tmp_path, meta_line):
    body = f"## Frame 1 — T\n{meta_line}\n"
    frame = parse_storyboard(_write(tmp_path, body)).frames[0]
    assert frame.asset_candidates() == []


# ── Frame.focal_asset ─────────────────────────────────────────────────────────

def test_focal_asset_prefers_the_focal_field(tmp_path):
    body = (
        "## Frame 1 — T\n"
        "- asset_candidates: assets/a.png (0.62) — 候选\n"
        "- focal: assets/hero.png, assets/second.png\n"
    )
    frame = parse_storyboard(_write(tmp_path, body)).frames[0]
    # first whitespace-delimited token, trailing `,;` stripped
    assert frame.focal_asset() == "assets/hero.png"


def test_focal_asset_falls_back_to_the_top_candidate(tmp_path):
    frame = _one_frame(
        tmp_path,
        "- asset_candidates: assets/a.png (0.62) — 红车；assets/b.png (0.55) — 电机",
    )
    assert frame.focal_asset() == "assets/a.png"


def test_focal_asset_is_none_without_focal_or_candidates(tmp_path):
    frame = parse_storyboard(_write(tmp_path, "## Frame 1 — T\n- scene: x\n")).frames[0]
    assert frame.focal_asset() is None


def test_focal_asset_returns_prose_verbatim_when_hf_writes_prose(tmp_path):
    """HF writes `focal: (typography-only, no asset)` for asset-free frames.

    Pinning the current behaviour: the prose is truncated to its first token
    rather than recognised as "no asset". Callers must tolerate a non-filename.
    """
    body = "## Frame 1 — T\n- asset_candidates:\n- focal: (typography-only, no asset)\n"
    frame = parse_storyboard(_write(tmp_path, body)).frames[0]
    assert frame.focal_asset() == "(typography-only"


# ── Storyboard.direction / direction_field ────────────────────────────────────

WITH_DIRECTION = textwrap.dedent(
    """\
    ---
    format: 1080x1920
    message: "夜色驾控"
    ---

    ## Video direction

    **Palette** (nightscape):
    - canvas: `#12151A` (near-black)
    - accent: `#238AFF` (brand blue)

    **Motion grammar**: long-tail power3 easing; VO-paced reveal.

    **Negative list**: no text overlays; no cursors.

    ---

    ## Frame 1 — 起势
    - scene: 湿滑路面上的红色轿车
    """
)


def test_direction_block_captured_between_frontmatter_and_first_frame(tmp_path):
    sb = parse_storyboard(_write(tmp_path, WITH_DIRECTION))

    assert "**Palette**" in sb.direction
    assert "power3" in sb.direction
    # headings are consumed by the heading branch, so they never reach `direction`
    assert "Video direction" not in sb.direction
    # and the block stops at the first frame
    assert "湿滑路面" not in sb.direction
    assert len(sb.frames) == 1


def test_direction_field_flattens_a_bulleted_list_and_drops_code_ticks(tmp_path):
    sb = parse_storyboard(_write(tmp_path, WITH_DIRECTION))
    palette = sb.direction_field("Palette")

    assert palette == "canvas: #12151A (near-black); accent: #238AFF (brand blue)"


def test_direction_field_reads_the_inline_form(tmp_path):
    sb = parse_storyboard(_write(tmp_path, WITH_DIRECTION))

    assert sb.direction_field("Motion grammar") == "long-tail power3 easing; VO-paced reveal."
    assert sb.direction_field("Negative list") == "no text overlays; no cursors."


def test_direction_field_is_empty_for_an_unknown_label(tmp_path):
    sb = parse_storyboard(_write(tmp_path, WITH_DIRECTION))
    assert sb.direction_field("Camera") == ""


def test_direction_absent_yields_empty_string_and_empty_fields(tmp_path):
    body = "---\nformat: 1920x1080\n---\n\n## Frame 1 — T\n- scene: x\n"
    sb = parse_storyboard(_write(tmp_path, body))

    assert sb.direction == ""
    assert sb.direction_field("Palette") == ""
