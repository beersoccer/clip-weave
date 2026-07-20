import json
from pathlib import Path
import pytest
from clip_weave.schemas.shots import ShotsOutput, Shot, StyleInfo
from clip_weave.schemas.brand_assets import BrandAssets

FIXTURES = Path(__file__).parent / "fixtures"

def test_shots_output_parses_fixture():
    data = json.loads((FIXTURES / "shots.json").read_text())
    result = ShotsOutput.model_validate(data)
    assert result.shot_count == 2
    assert result.shots[0].type == "hook"
    assert result.style.pacing == "fast"

def test_shot_invalid_type_raises():
    data = json.loads((FIXTURES / "shots.json").read_text())
    data["shots"][0]["type"] = "unknown_type"
    with pytest.raises(Exception):
        ShotsOutput.model_validate(data)

def test_brand_assets_parses_fixture():
    data = json.loads((FIXTURES / "brand_assets.json").read_text())
    result = BrandAssets.model_validate(data)
    assert result.brand_name == "TestBrand"
    assert result.target_aspect_ratio == "9:16"

def test_brand_assets_defaults():
    result = BrandAssets(brand_name="X")
    assert result.product_images == []
    assert result.color_palette == []
    assert result.target_aspect_ratio == "9:16"
