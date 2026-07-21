import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clip_weave.config import Config
from clip_weave.core.html_generator import generate_html
from clip_weave.schemas.brand_assets import BrandAssets
from clip_weave.schemas.shots import ShotsOutput

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SHOTS = ShotsOutput.model_validate(json.loads((FIXTURE_DIR / "shots.json").read_text()))
BRAND = BrandAssets.model_validate(json.loads((FIXTURE_DIR / "brand_assets.json").read_text()))
CFG = Config(
    video_analysis_base_url=None, video_analysis_api_key="k",
    video_analysis_model="gemini-2.0-flash-exp",
    html_gen_base_url=None, html_gen_api_key="k",
    html_gen_model="claude-sonnet-4-6",
    pexels_api_key="k", scene_threshold=0.35,
)


def _make_openai_mock(responses: list[str]) -> MagicMock:
    """Return a mock OpenAI class whose instances cycle through responses."""
    side_effects = []
    for content in responses:
        mock_message = MagicMock()
        mock_message.content = content
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        side_effects.append(mock_response)

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = side_effects
    return MagicMock(return_value=mock_client)


def test_generate_html_returns_html_string(tmp_path):
    valid_html = "<html><body><div>Shot 1</div></body></html>"
    mock_openai = _make_openai_mock([valid_html])
    with patch("clip_weave.core.html_generator.OpenAI", mock_openai):
        result = generate_html(SHOTS, BRAND, CFG, output_dir=tmp_path)
    assert "<html>" in result


def test_generate_html_retries_on_invalid_html(tmp_path):
    invalid = "not html at all %%"
    valid_html = "<html><body>ok</body></html>"
    mock_openai = _make_openai_mock([invalid, valid_html])
    with patch("clip_weave.core.html_generator.OpenAI", mock_openai):
        result = generate_html(SHOTS, BRAND, CFG, output_dir=tmp_path)
    assert mock_openai.return_value.chat.completions.create.call_count == 2
    assert "<html>" in result


def test_generate_html_dumps_debug_after_max_retries(tmp_path):
    mock_openai = _make_openai_mock(["not html", "not html", "not html"])
    with patch("clip_weave.core.html_generator.OpenAI", mock_openai):
        with pytest.raises(ValueError, match="HTML generation failed"):
            generate_html(SHOTS, BRAND, CFG, output_dir=tmp_path)
    debug_files = list((tmp_path / "debug").glob("*.txt"))
    assert len(debug_files) == 1
