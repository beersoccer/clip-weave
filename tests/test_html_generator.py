import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from clip_weave.schemas.shots import ShotsOutput
from clip_weave.schemas.brand_assets import BrandAssets
from clip_weave.config import Config
from clip_weave.core.html_generator import generate_html

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SHOTS = ShotsOutput.model_validate(json.loads((FIXTURE_DIR / "shots.json").read_text()))
BRAND = BrandAssets.model_validate(json.loads((FIXTURE_DIR / "brand_assets.json").read_text()))
CFG = Config(
    anthropic_api_key="k", openai_api_key="k",
    gemini_api_key="k", pexels_api_key="k",
    html_gen_model="claude", scene_threshold=0.35,
)


def _make_claude_response(html: str):
    msg = MagicMock()
    msg.content = [MagicMock(text=html)]
    return msg


def test_generate_html_returns_html_string(tmp_path):
    valid_html = "<html><body><div>Shot 1</div></body></html>"
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_claude_response(valid_html)
    with patch("clip_weave.core.html_generator._get_claude_client", return_value=mock_client):
        result = generate_html(SHOTS, BRAND, CFG, output_dir=tmp_path)
    assert "<html>" in result


def test_generate_html_retries_on_invalid_html(tmp_path):
    invalid = "not html at all %%"
    valid_html = "<html><body>ok</body></html>"
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _make_claude_response(invalid),
        _make_claude_response(valid_html),
    ]
    with patch("clip_weave.core.html_generator._get_claude_client", return_value=mock_client):
        result = generate_html(SHOTS, BRAND, CFG, output_dir=tmp_path)
    assert mock_client.messages.create.call_count == 2
    assert "<html>" in result


def test_generate_html_dumps_debug_after_max_retries(tmp_path):
    invalid = "not html"
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_claude_response(invalid)
    with patch("clip_weave.core.html_generator._get_claude_client", return_value=mock_client):
        with pytest.raises(ValueError, match="HTML generation failed"):
            generate_html(SHOTS, BRAND, CFG, output_dir=tmp_path)
    debug_files = list((tmp_path / "debug").glob("*.txt"))
    assert len(debug_files) == 1
