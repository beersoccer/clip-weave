from pathlib import Path
from urllib.parse import urlparse
import requests
from clip_weave.config import Config

_PEXELS_VIDEO_SEARCH = "https://api.pexels.com/videos/search"


def search_pexels_videos(query: str, cfg: Config, count: int = 5) -> list[str]:
    headers = {"Authorization": cfg.pexels_api_key}
    params = {"query": query, "per_page": count, "orientation": "portrait"}
    response = requests.get(_PEXELS_VIDEO_SEARCH, headers=headers, params=params, timeout=10)
    response.raise_for_status()
    videos = response.json().get("videos", [])
    urls = []
    for v in videos:
        hd_files = [f for f in v.get("video_files", []) if f.get("quality") == "hd"]
        if hd_files:
            urls.append(hd_files[0]["link"])
    return urls


def download_asset(url: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(urlparse(url).path).name or "asset.mp4"
    dest = dest_dir / filename
    with requests.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    return dest
