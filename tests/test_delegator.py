from clip_weave.core.delegator import build_delegation_prompt


def test_t2v_profile_delegation_uses_video_generation_path(tmp_path):
    (tmp_path / "BRIEF.md").write_text(
        "---\nworkflow: product-launch-video\nproduction_profile: t2v_brand_film\n---\n",
        encoding="utf-8",
    )

    prompt = build_delegation_prompt(tmp_path)

    assert "gen-video" in prompt
    assert "/product-launch-video" not in prompt
