"""Tests for Project Factory capture-asset filtering."""

from clip_weave.core.project_factory import _filter_capture_assets


def test_filter_removes_noise_but_keeps_logos(tmp_path):
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()

    # Noise — should be removed
    noise = [
        "favicon.ico",
        "wechat_qrcode.png",
        "whatsapp.svg",
        "svg-a1b2c3d4.svg",
        "social-icons.png",
        "loader.gif",
    ]
    # Logos — must be preserved even though some have short/simple names
    logos = [
        "logo.svg",
        "brand-logo.png",
        "noah-wordmark.svg",
        "company_emblem.png",
    ]
    # Normal assets — not noise, not logo-flagged
    normal = ["hero-banner.png", "team-photo.jpg"]

    for name in noise + logos + normal:
        (assets_dir / name).write_bytes(b"x" * 100)

    _filter_capture_assets(assets_dir)

    remaining = {f.name for f in assets_dir.iterdir()}
    for name in logos + normal:
        assert name in remaining, f"Expected {name} to be kept"
    for name in noise:
        assert name not in remaining, f"Expected {name} to be removed"


def test_filter_keeps_small_svgs_unconditionally(tmp_path):
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    # An SVG with a plain name (not hash-named, no logo keyword) — keep it
    (assets_dir / "arrow-right.svg").write_bytes(b"<svg/>" * 10)
    # A hash-named SVG — remove
    (assets_dir / "svg-deadbeef.svg").write_bytes(b"<svg/>")

    _filter_capture_assets(assets_dir)

    assert (assets_dir / "arrow-right.svg").exists()
    assert not (assets_dir / "svg-deadbeef.svg").exists()
