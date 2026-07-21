from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import responses as resp
from clip_weave.config import Config
from clip_weave.core.asset_resolver import search_pexels_videos, download_asset

CFG = Config(
    video_analysis_base_url=None, video_analysis_api_key="k",
    video_analysis_model="gemini-2.5-flash",
    html_gen_base_url=None, html_gen_api_key="k",
    html_gen_model="claude-sonnet-4-6",
    pexels_api_key="test-pex", scene_threshold=0.35,
)

PEXELS_RESPONSE = {
    "videos": [
        {"id": 1, "video_files": [{"link": "https://example.com/video.mp4", "quality": "hd"}]}
    ]
}


@resp.activate
def test_search_pexels_returns_urls():
    resp.add(resp.GET, "https://api.pexels.com/videos/search",
             json=PEXELS_RESPONSE, status=200)
    urls = search_pexels_videos("product lifestyle", CFG, count=1)
    assert len(urls) == 1
    assert "example.com" in urls[0]


def test_download_asset_saves_file(tmp_path):
    url = "https://example.com/video.mp4"
    mock_response = MagicMock()
    mock_response.iter_content.return_value = [b"fakevideo"]
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    with patch("clip_weave.core.asset_resolver.requests.get", return_value=mock_response):
        path = download_asset(url, tmp_path)
    assert path.exists()
    assert path.read_bytes() == b"fakevideo"
