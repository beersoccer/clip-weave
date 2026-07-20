# clip-weave Phase 1 + 2a Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI pipeline that analyzes a sample marketing video via VideoAgent (Phase 1) and renders a new branded video through HyperFrames (Phase 2a).

**Architecture:** Adapter Pattern — `adapters/` wraps external submodules (VideoAgent, HyperFrames), `core/` contains business logic operating on Pydantic schemas, `pipeline.py` is the only layer that connects them.

**Tech Stack:** Python 3.11+, Pydantic v2, Click, Anthropic SDK, OpenAI SDK, google-generativeai, requests, pytest, pytest-mock

## Global Constraints

- Python ≥ 3.11
- Pydantic v2 (use `model_validate`, not `parse_obj`)
- All LLM API keys loaded from `.env` via `python-dotenv`; never hardcoded
- `HTML_GEN_MODEL` env var controls HTML generator LLM: `claude` | `gpt4o`, default `claude`
- `SCENE_THRESHOLD` env var controls FFmpeg scene detection, default `0.35`
- `adapters/` must not import from `core/`; `core/` must not import from `adapters/`
- `pipeline.py` is the only file that imports from both layers
- All output files go under `output/`; frames under `output/frames/`; debug dumps under `output/debug/`
- HTML generation retries maximum 2 times before dumping raw LLM output to `output/debug/`
- VideoAgent failure raises `VideoAnalysisError`; HyperFrames failure preserves `output/frames/`
- `shots.json` is persisted after Phase 1 so Phase 2a can re-run independently
- git submodule paths: `vendors/VideoAgent` (HKUDS/VideoAgent), `vendors/hyperframes` (heygen-com/hyperframes)

---

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml` | Project metadata and dependencies |
| `.env.example` | API key template (no real values) |
| `src/clip_weave/schemas/shots.py` | `Shot`, `StyleInfo`, `ShotsOutput` Pydantic models |
| `src/clip_weave/schemas/brand_assets.py` | `BrandAssets` Pydantic model |
| `src/clip_weave/config.py` | Load env vars, expose typed `Config` dataclass |
| `src/clip_weave/adapters/videoagent.py` | Wrap VideoAgent submodule; raise `VideoAnalysisError` |
| `src/clip_weave/core/html_generator.py` | `ShotsOutput + BrandAssets → HTML string`, retry logic |
| `src/clip_weave/core/asset_resolver.py` | Pexels/Pixabay search → download assets to `assets/downloaded/` |
| `src/clip_weave/adapters/hyperframes.py` | Wrap HyperFrames CLI; HTML → `output/final.mp4` |
| `src/clip_weave/pipeline.py` | `analyze()` and `render()` orchestration |
| `src/clip_weave/__main__.py` | Click CLI: `analyze`, `run`, `render` commands |
| `tests/test_schemas.py` | Schema parse/validate unit tests |
| `tests/test_config.py` | Config loading unit tests |
| `tests/test_videoagent_adapter.py` | VideoAgent adapter with mocked subprocess |
| `tests/test_html_generator.py` | HTML generator with mocked LLM |
| `tests/test_asset_resolver.py` | Asset resolver with mocked HTTP |
| `tests/test_hyperframes_adapter.py` | HyperFrames adapter with mocked CLI |
| `tests/test_pipeline.py` | Pipeline with mocked adapters |
| `tests/test_cli.py` | CLI commands via Click test runner |
| `tests/fixtures/shots.json` | Minimal valid ShotsOutput fixture |
| `tests/fixtures/brand_assets.json` | Minimal valid BrandAssets fixture |

---

### Task 1: Project Scaffold & Git Submodules

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `src/clip_weave/__init__.py`
- Create: `src/clip_weave/adapters/__init__.py`
- Create: `src/clip_weave/core/__init__.py`
- Create: `src/clip_weave/schemas/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/fixtures/` (directory + placeholder files)

**Interfaces:**
- Produces: installable package `clip_weave`, importable as `from clip_weave.schemas.shots import ShotsOutput`

- [ ] **Step 1: Initialize git and create directory structure**

```bash
cd /Users/beersoccer/workspace/clip-weave
git init
mkdir -p src/clip_weave/adapters src/clip_weave/core src/clip_weave/schemas
mkdir -p tests/fixtures vendors assets/brand assets/downloaded output/frames output/debug
touch src/clip_weave/__init__.py
touch src/clip_weave/adapters/__init__.py
touch src/clip_weave/core/__init__.py
touch src/clip_weave/schemas/__init__.py
touch tests/__init__.py
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "clip-weave"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.0",
    "anthropic>=0.40",
    "openai>=1.50",
    "google-generativeai>=0.8",
    "requests>=2.31",
    "python-dotenv>=1.0",
    "click>=8.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
    "responses>=0.25",
]

[tool.hatch.build.targets.wheel]
packages = ["src/clip_weave"]
```

- [ ] **Step 3: Write `.env.example`**

```
GEMINI_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
PEXELS_API_KEY=
HTML_GEN_MODEL=claude
SCENE_THRESHOLD=0.35
```

- [ ] **Step 4: Add git submodules**

```bash
git submodule add https://github.com/HKUDS/VideoAgent.git vendors/VideoAgent
git submodule add https://github.com/heygen-com/hyperframes.git vendors/hyperframes
git submodule update --init --recursive
```

After cloning, read `vendors/VideoAgent/README.md` and identify the main entry point. Note the command used to run analysis — you will need this in Task 4.

- [ ] **Step 5: Install dependencies**

```bash
pip install -e ".[dev]"
```

Expected: `Successfully installed clip-weave-0.1.0`

- [ ] **Step 6: Commit scaffold**

```bash
git add pyproject.toml .env.example src/ tests/ .gitmodules vendors/
git commit -m "chore: project scaffold, submodules, package structure"
```

---

### Task 2: Pydantic Schemas

**Files:**
- Create: `src/clip_weave/schemas/shots.py`
- Create: `src/clip_weave/schemas/brand_assets.py`
- Create: `tests/test_schemas.py`
- Create: `tests/fixtures/shots.json`
- Create: `tests/fixtures/brand_assets.json`

**Interfaces:**
- Produces: `ShotsOutput`, `Shot`, `StyleInfo` from `clip_weave.schemas.shots`
- Produces: `BrandAssets` from `clip_weave.schemas.brand_assets`

- [ ] **Step 1: Write fixture files**

`tests/fixtures/shots.json`:
```json
{
  "style": {
    "pacing": "fast",
    "color_tone": "warm",
    "typography": "bold-sans",
    "transition": "cut",
    "aspect_ratio": "9:16"
  },
  "shots": [
    {
      "index": 1, "start": 0.0, "end": 2.5, "duration": 2.5,
      "type": "hook", "composition": "centered",
      "text_overlay": "痛点文案", "visual_element": "人物特写",
      "audio_cue": "节奏感强的背景音乐起"
    },
    {
      "index": 2, "start": 2.5, "end": 5.0, "duration": 2.5,
      "type": "product", "composition": "rule-of-thirds",
      "text_overlay": null, "visual_element": "产品特写",
      "audio_cue": null
    }
  ],
  "narrative_structure": "AIDA",
  "total_duration": 30.0,
  "shot_count": 2
}
```

`tests/fixtures/brand_assets.json`:
```json
{
  "brand_name": "TestBrand",
  "tagline": "Better Every Day",
  "logo_path": null,
  "product_images": [],
  "color_palette": ["#FF5733", "#FFFFFF"],
  "copy_points": ["高品质原料", "限时优惠"],
  "target_aspect_ratio": "9:16"
}
```

- [ ] **Step 2: Write failing tests**

`tests/test_schemas.py`:
```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_schemas.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` — schemas not yet defined.

- [ ] **Step 4: Write `src/clip_weave/schemas/shots.py`**

```python
from typing import Literal, Optional
from pydantic import BaseModel


class Shot(BaseModel):
    index: int
    start: float
    end: float
    duration: float
    type: Literal["hook", "product", "testimonial", "cta"]
    composition: str
    text_overlay: Optional[str] = None
    visual_element: str
    audio_cue: Optional[str] = None


class StyleInfo(BaseModel):
    pacing: Literal["fast", "medium", "slow"]
    color_tone: Literal["warm", "cool", "neutral"]
    typography: str
    transition: Literal["cut", "fade", "swipe", "zoom"]
    aspect_ratio: str


class ShotsOutput(BaseModel):
    style: StyleInfo
    shots: list[Shot]
    narrative_structure: Literal["AIDA", "PAS", "Hook-Story-Offer", "Before-After-Bridge"]
    total_duration: float
    shot_count: int
```

- [ ] **Step 5: Write `src/clip_weave/schemas/brand_assets.py`**

```python
from pathlib import Path
from typing import Optional
from pydantic import BaseModel


class BrandAssets(BaseModel):
    brand_name: str
    tagline: Optional[str] = None
    logo_path: Optional[Path] = None
    product_images: list[Path] = []
    color_palette: list[str] = []
    copy_points: list[str] = []
    target_aspect_ratio: str = "9:16"
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_schemas.py -v
```

Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add src/clip_weave/schemas/ tests/test_schemas.py tests/fixtures/
git commit -m "feat: Pydantic schemas for ShotsOutput and BrandAssets"
```

---

### Task 3: Config Module

**Files:**
- Create: `src/clip_weave/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Produces: `Config` dataclass and `load_config() -> Config` from `clip_weave.config`
- Consumes: env vars `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `PEXELS_API_KEY`, `HTML_GEN_MODEL`, `SCENE_THRESHOLD`

- [ ] **Step 1: Write failing tests**

`tests/test_config.py`:
```python
import os
import pytest
from unittest.mock import patch
from clip_weave.config import load_config

def test_load_config_defaults():
    env = {
        "ANTHROPIC_API_KEY": "test-ant",
        "OPENAI_API_KEY": "test-oai",
        "GEMINI_API_KEY": "test-gem",
        "PEXELS_API_KEY": "test-pex",
    }
    with patch.dict(os.environ, env, clear=False):
        cfg = load_config()
    assert cfg.html_gen_model == "claude"
    assert cfg.scene_threshold == 0.35

def test_load_config_custom_model():
    env = {
        "ANTHROPIC_API_KEY": "k", "OPENAI_API_KEY": "k",
        "GEMINI_API_KEY": "k", "PEXELS_API_KEY": "k",
        "HTML_GEN_MODEL": "gpt4o",
        "SCENE_THRESHOLD": "0.5",
    }
    with patch.dict(os.environ, env, clear=False):
        cfg = load_config()
    assert cfg.html_gen_model == "gpt4o"
    assert cfg.scene_threshold == 0.5

def test_load_config_invalid_model_raises():
    env = {
        "ANTHROPIC_API_KEY": "k", "OPENAI_API_KEY": "k",
        "GEMINI_API_KEY": "k", "PEXELS_API_KEY": "k",
        "HTML_GEN_MODEL": "unknown",
    }
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ValueError, match="HTML_GEN_MODEL"):
            load_config()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write `src/clip_weave/config.py`**

```python
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

VALID_HTML_MODELS = {"claude", "gpt4o"}


@dataclass
class Config:
    anthropic_api_key: str
    openai_api_key: str
    gemini_api_key: str
    pexels_api_key: str
    html_gen_model: str
    scene_threshold: float


def load_config() -> Config:
    model = os.getenv("HTML_GEN_MODEL", "claude")
    if model not in VALID_HTML_MODELS:
        raise ValueError(f"HTML_GEN_MODEL must be one of {VALID_HTML_MODELS}, got '{model}'")
    return Config(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        pexels_api_key=os.getenv("PEXELS_API_KEY", ""),
        html_gen_model=model,
        scene_threshold=float(os.getenv("SCENE_THRESHOLD", "0.35")),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/clip_weave/config.py tests/test_config.py
git commit -m "feat: config module with env-var loading and validation"
```

---

### Task 4: VideoAgent Adapter

**Files:**
- Create: `src/clip_weave/adapters/videoagent.py`
- Create: `tests/test_videoagent_adapter.py`

**Interfaces:**
- Consumes: `Config` from `clip_weave.config`; video file path as `str`
- Produces: `ShotsOutput` from `clip_weave.schemas.shots`; raises `VideoAnalysisError` on failure

**Before coding:** Read `vendors/VideoAgent/README.md` to find the CLI entry point and JSON output format. The adapter calls VideoAgent as a subprocess so the actual command may need adjustment — update `_build_command()` in Step 4 based on what you find.

- [ ] **Step 1: Write failing tests**

`tests/test_videoagent_adapter.py`:
```python
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from clip_weave.adapters.videoagent import analyze_video, VideoAnalysisError
from clip_weave.schemas.shots import ShotsOutput

FIXTURE_SHOTS = json.loads(
    (Path(__file__).parent / "fixtures" / "shots.json").read_text()
)


def test_analyze_video_returns_shots_output(tmp_path):
    fake_video = tmp_path / "test.mp4"
    fake_video.write_bytes(b"fake")
    mock_result = MagicMock(returncode=0, stdout=json.dumps(FIXTURE_SHOTS), stderr="")
    with patch("clip_weave.adapters.videoagent.subprocess.run", return_value=mock_result):
        result = analyze_video(str(fake_video))
    assert isinstance(result, ShotsOutput)
    assert result.shot_count == 2


def test_analyze_video_nonzero_exit_raises(tmp_path):
    fake_video = tmp_path / "test.mp4"
    fake_video.write_bytes(b"fake")
    mock_result = MagicMock(returncode=1, stdout="", stderr="ffmpeg error")
    with patch("clip_weave.adapters.videoagent.subprocess.run", return_value=mock_result):
        with pytest.raises(VideoAnalysisError) as exc_info:
            analyze_video(str(fake_video))
    assert "ffmpeg error" in exc_info.value.stderr


def test_analyze_video_invalid_json_raises(tmp_path):
    fake_video = tmp_path / "test.mp4"
    fake_video.write_bytes(b"fake")
    mock_result = MagicMock(returncode=0, stdout="not-json", stderr="")
    with patch("clip_weave.adapters.videoagent.subprocess.run", return_value=mock_result):
        with pytest.raises(VideoAnalysisError, match="invalid JSON"):
            analyze_video(str(fake_video))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_videoagent_adapter.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write `src/clip_weave/adapters/videoagent.py`**

```python
import json
import subprocess
import sys
from pathlib import Path
from clip_weave.schemas.shots import ShotsOutput

_VENDOR_DIR = Path(__file__).parent.parent.parent.parent / "vendors" / "VideoAgent"


class VideoAnalysisError(Exception):
    def __init__(self, message: str, stderr: str = "", raw_response: str = ""):
        super().__init__(message)
        self.stderr = stderr
        self.raw_response = raw_response


def _build_command(video_path: str, scene_threshold: float) -> list[str]:
    # Adjust this command after reading vendors/VideoAgent/README.md
    return [
        sys.executable, "run_demo.py",
        "--video", video_path,
        "--output_format", "json",
        "--scene_threshold", str(scene_threshold),
    ]


def analyze_video(video_path: str, scene_threshold: float = 0.35) -> ShotsOutput:
    cmd = _build_command(video_path, scene_threshold)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(_VENDOR_DIR),
    )
    if result.returncode != 0:
        raise VideoAnalysisError(
            f"VideoAgent exited with code {result.returncode}",
            stderr=result.stderr,
        )
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise VideoAnalysisError(
            "VideoAgent returned invalid JSON",
            raw_response=result.stdout,
        ) from exc
    return ShotsOutput.model_validate(raw)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_videoagent_adapter.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/clip_weave/adapters/videoagent.py tests/test_videoagent_adapter.py
git commit -m "feat: VideoAgent adapter with VideoAnalysisError"
```

---

### Task 5: HTML Generator

**Files:**
- Create: `src/clip_weave/core/html_generator.py`
- Create: `tests/test_html_generator.py`

**Interfaces:**
- Consumes: `ShotsOutput`, `BrandAssets`, `Config`
- Produces: `str` (valid HTML document); raises `ValueError` after 2 retries, dumps raw to `output/debug/`

- [ ] **Step 1: Write failing tests**

`tests/test_html_generator.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_html_generator.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write `src/clip_weave/core/html_generator.py`**

```python
import re
from datetime import datetime
from pathlib import Path
import anthropic
import openai
from clip_weave.schemas.shots import ShotsOutput
from clip_weave.schemas.brand_assets import BrandAssets
from clip_weave.config import Config

_HTML_RE = re.compile(r"<html[\s>]", re.IGNORECASE)
_MAX_RETRIES = 2


def _get_claude_client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key)


def _get_openai_client(api_key: str) -> openai.OpenAI:
    return openai.OpenAI(api_key=api_key)


def _build_prompt(shots: ShotsOutput, brand: BrandAssets) -> str:
    shots_desc = "\n".join(
        f"Shot {s.index} ({s.type}, {s.duration}s): {s.visual_element}"
        + (f', text: "{s.text_overlay}"' if s.text_overlay else "")
        for s in shots.shots
    )
    colors = ", ".join(brand.color_palette) if brand.color_palette else "#000000, #FFFFFF"
    copy = "\n".join(f"- {p}" for p in brand.copy_points)
    return f"""Generate a single self-contained HTML file that renders a {brand.target_aspect_ratio} marketing video sequence using CSS animations and GSAP.

Brand: {brand.brand_name}
Tagline: {brand.tagline or ""}
Colors: {colors}
Copy points:
{copy}

Shots to animate ({shots.style.pacing} pacing, {shots.style.transition} transitions):
{shots_desc}

Requirements:
- Single HTML file with all CSS and JS inline
- Use GSAP (load from CDN) for animations
- Each shot auto-advances after its duration
- Aspect ratio {brand.target_aspect_ratio} viewport
- Output ONLY the HTML, no explanation
"""


def _call_llm(prompt: str, cfg: Config) -> str:
    if cfg.html_gen_model == "claude":
        client = _get_claude_client(cfg.anthropic_api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    client = _get_openai_client(cfg.openai_api_key)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4096,
    )
    return response.choices[0].message.content


def _is_valid_html(text: str) -> bool:
    return bool(_HTML_RE.search(text))


def generate_html(
    shots: ShotsOutput,
    brand: BrandAssets,
    cfg: Config,
    output_dir: Path = Path("output"),
) -> str:
    prompt = _build_prompt(shots, brand)
    last_raw = ""
    for attempt in range(_MAX_RETRIES + 1):
        last_raw = _call_llm(prompt, cfg)
        if _is_valid_html(last_raw):
            return last_raw
    debug_dir = output_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    (debug_dir / f"html_gen_raw_{ts}.txt").write_text(last_raw, encoding="utf-8")
    raise ValueError(f"HTML generation failed after {_MAX_RETRIES + 1} attempts; raw saved to {debug_dir}")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_html_generator.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/clip_weave/core/html_generator.py tests/test_html_generator.py
git commit -m "feat: HTML generator with configurable LLM and retry logic"
```

---

### Task 6: Asset Resolver

**Files:**
- Create: `src/clip_weave/core/asset_resolver.py`
- Create: `tests/test_asset_resolver.py`

**Interfaces:**
- Consumes: `Config`; query string; download destination `Path`
- Produces: `list[Path]` of downloaded files

- [ ] **Step 1: Write failing tests**

`tests/test_asset_resolver.py`:
```python
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import responses as resp
from clip_weave.config import Config
from clip_weave.core.asset_resolver import search_pexels_videos, download_asset

CFG = Config(
    anthropic_api_key="k", openai_api_key="k",
    gemini_api_key="k", pexels_api_key="test-pex",
    html_gen_model="claude", scene_threshold=0.35,
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_asset_resolver.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write `src/clip_weave/core/asset_resolver.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_asset_resolver.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/clip_weave/core/asset_resolver.py tests/test_asset_resolver.py
git commit -m "feat: Pexels asset resolver with search and download"
```

> **Note:** `asset_resolver` is a standalone utility. In Phase 2a it is called optionally from `html_generator._build_prompt()` to resolve and embed B-roll asset URLs. Wire it in by adding a `search_pexels_videos(shot.visual_element, cfg)` call inside `_build_prompt` when `copy_points` include asset keywords — or leave it available for Phase 3 enhancement.

---

### Task 7: HyperFrames Adapter

**Files:**
- Create: `src/clip_weave/adapters/hyperframes.py`
- Create: `tests/test_hyperframes_adapter.py`

**Interfaces:**
- Consumes: `html_content: str`; `output_dir: Path`; `video_name: str`
- Produces: `Path` to `output/final.mp4`; preserves `output/frames/` on failure

**Before coding:** Read `vendors/hyperframes/README.md` to confirm the CLI command for rendering HTML to video. Update `_build_render_command()` in Step 3 if needed.

- [ ] **Step 1: Write failing tests**

`tests/test_hyperframes_adapter.py`:
```python
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from clip_weave.adapters.hyperframes import render_html_to_video, HyperFramesError

HTML = "<html><body>test</body></html>"


def test_render_returns_mp4_path(tmp_path):
    output_mp4 = tmp_path / "final.mp4"
    mock_result = MagicMock(returncode=0, stderr="")
    with patch("clip_weave.adapters.hyperframes.subprocess.run", return_value=mock_result):
        output_mp4.write_bytes(b"fake")
        with patch("clip_weave.adapters.hyperframes._output_path", return_value=output_mp4):
            result = render_html_to_video(HTML, tmp_path)
    assert result == output_mp4


def test_render_nonzero_exit_raises_and_preserves_frames(tmp_path):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "frame_0001.jpg").write_bytes(b"img")
    mock_result = MagicMock(returncode=1, stderr="chromium error")
    with patch("clip_weave.adapters.hyperframes.subprocess.run", return_value=mock_result):
        with patch("clip_weave.adapters.hyperframes._frames_dir", return_value=frames_dir):
            with pytest.raises(HyperFramesError) as exc_info:
                render_html_to_video(HTML, tmp_path)
    assert "chromium error" in str(exc_info.value)
    assert (frames_dir / "frame_0001.jpg").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_hyperframes_adapter.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write `src/clip_weave/adapters/hyperframes.py`**

```python
import subprocess
import sys
from pathlib import Path

_VENDOR_DIR = Path(__file__).parent.parent.parent.parent / "vendors" / "hyperframes"


class HyperFramesError(Exception):
    pass


def _output_path(output_dir: Path, video_name: str) -> Path:
    return output_dir / video_name


def _frames_dir(output_dir: Path) -> Path:
    return output_dir / "frames"


def _build_render_command(html_path: Path, output_path: Path) -> list[str]:
    # Adjust after reading vendors/hyperframes/README.md
    return [
        sys.executable, "-m", "hyperframes",
        "--input", str(html_path),
        "--output", str(output_path),
    ]


def render_html_to_video(
    html_content: str,
    output_dir: Path,
    video_name: str = "final.mp4",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    comp_dir = output_dir / "compositions"
    comp_dir.mkdir(exist_ok=True)
    html_path = comp_dir / "composition.html"
    html_path.write_text(html_content, encoding="utf-8")

    out_path = _output_path(output_dir, video_name)
    cmd = _build_render_command(html_path, out_path)
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_VENDOR_DIR))

    if result.returncode != 0:
        raise HyperFramesError(
            f"HyperFrames failed (code {result.returncode}): {result.stderr}\n"
            f"Frames preserved at {_frames_dir(output_dir)}"
        )
    return out_path
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_hyperframes_adapter.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/clip_weave/adapters/hyperframes.py tests/test_hyperframes_adapter.py
git commit -m "feat: HyperFrames adapter with frame-preservation on failure"
```

---

### Task 8: Pipeline Orchestration

**Files:**
- Create: `src/clip_weave/pipeline.py`
- Create: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `analyze_video` from `clip_weave.adapters.videoagent`; `generate_html` from `clip_weave.core.html_generator`; `render_html_to_video` from `clip_weave.adapters.hyperframes`; `Config`; `BrandAssets`
- Produces: `analyze(video_path, cfg) -> ShotsOutput` (and persists to JSON); `render(shots, brand, cfg, output_dir) -> Path`

- [ ] **Step 1: Write failing tests**

`tests/test_pipeline.py`:
```python
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from clip_weave.schemas.shots import ShotsOutput
from clip_weave.schemas.brand_assets import BrandAssets
from clip_weave.config import Config
from clip_weave.pipeline import analyze, render

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SHOTS = ShotsOutput.model_validate(json.loads((FIXTURE_DIR / "shots.json").read_text()))
BRAND = BrandAssets.model_validate(json.loads((FIXTURE_DIR / "brand_assets.json").read_text()))
CFG = Config(
    anthropic_api_key="k", openai_api_key="k",
    gemini_api_key="k", pexels_api_key="k",
    html_gen_model="claude", scene_threshold=0.35,
)


def test_analyze_returns_and_persists(tmp_path):
    with patch("clip_weave.pipeline.analyze_video", return_value=SHOTS):
        result = analyze("sample.mp4", CFG, output_dir=tmp_path)
    assert isinstance(result, ShotsOutput)
    shots_file = tmp_path / "shots.json"
    assert shots_file.exists()
    loaded = ShotsOutput.model_validate(json.loads(shots_file.read_text()))
    assert loaded.shot_count == SHOTS.shot_count


def test_render_calls_adapters(tmp_path):
    mp4_path = tmp_path / "final.mp4"
    mp4_path.write_bytes(b"fake")
    with patch("clip_weave.pipeline.generate_html", return_value="<html></html>") as mock_html, \
         patch("clip_weave.pipeline.render_html_to_video", return_value=mp4_path) as mock_render:
        result = render(SHOTS, BRAND, CFG, output_dir=tmp_path)
    mock_html.assert_called_once_with(SHOTS, BRAND, CFG, output_dir=tmp_path)
    mock_render.assert_called_once()
    assert result == mp4_path
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pipeline.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write `src/clip_weave/pipeline.py`**

```python
import json
from pathlib import Path
from clip_weave.adapters.videoagent import analyze_video
from clip_weave.adapters.hyperframes import render_html_to_video
from clip_weave.core.html_generator import generate_html
from clip_weave.schemas.shots import ShotsOutput
from clip_weave.schemas.brand_assets import BrandAssets
from clip_weave.config import Config


def analyze(
    video_path: str,
    cfg: Config,
    output_dir: Path = Path("output"),
) -> ShotsOutput:
    shots = analyze_video(video_path, scene_threshold=cfg.scene_threshold)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "shots.json").write_text(
        shots.model_dump_json(indent=2), encoding="utf-8"
    )
    return shots


def render(
    shots: ShotsOutput,
    brand: BrandAssets,
    cfg: Config,
    output_dir: Path = Path("output"),
) -> Path:
    html = generate_html(shots, brand, cfg, output_dir=output_dir)
    return render_html_to_video(html, output_dir)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_pipeline.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/clip_weave/pipeline.py tests/test_pipeline.py
git commit -m "feat: pipeline orchestration with shots.json persistence"
```

---

### Task 9: CLI Entry Point

**Files:**
- Create: `src/clip_weave/__main__.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: `analyze`, `render` from `clip_weave.pipeline`; `load_config` from `clip_weave.config`; `BrandAssets`, `ShotsOutput`
- Produces: CLI commands `analyze`, `run`, `render` invokable as `python -m clip_weave <cmd>`

- [ ] **Step 1: Write failing tests**

`tests/test_cli.py`:
```python
import json
from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner
from clip_weave.__main__ import cli
from clip_weave.schemas.shots import ShotsOutput
from clip_weave.schemas.brand_assets import BrandAssets

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SHOTS = ShotsOutput.model_validate(json.loads((FIXTURE_DIR / "shots.json").read_text()))
BRAND = BrandAssets.model_validate(json.loads((FIXTURE_DIR / "brand_assets.json").read_text()))


def test_analyze_command(tmp_path):
    fake_video = tmp_path / "test.mp4"
    fake_video.write_bytes(b"fake")
    out_file = tmp_path / "shots.json"
    runner = CliRunner()
    with patch("clip_weave.__main__.analyze", return_value=SHOTS) as mock_analyze:
        result = runner.invoke(cli, [
            "analyze", "--video", str(fake_video), "--output", str(out_file)
        ])
    assert result.exit_code == 0, result.output
    mock_analyze.assert_called_once()


def test_run_command(tmp_path):
    fake_video = tmp_path / "test.mp4"
    fake_video.write_bytes(b"fake")
    brand_dir = tmp_path / "brand"
    brand_dir.mkdir()
    (brand_dir / "brand_assets.json").write_text(
        json.dumps({"brand_name": "T", "target_aspect_ratio": "9:16"})
    )
    runner = CliRunner()
    with patch("clip_weave.__main__.analyze", return_value=SHOTS), \
         patch("clip_weave.__main__.render", return_value=tmp_path / "final.mp4"):
        result = runner.invoke(cli, [
            "run", "--video", str(fake_video),
            "--brand", str(brand_dir), "--mode", "hyperframes"
        ])
    assert result.exit_code == 0, result.output


def test_render_command(tmp_path):
    shots_file = tmp_path / "shots.json"
    shots_file.write_text(SHOTS.model_dump_json())
    brand_dir = tmp_path / "brand"
    brand_dir.mkdir()
    (brand_dir / "brand_assets.json").write_text(
        json.dumps({"brand_name": "T", "target_aspect_ratio": "9:16"})
    )
    runner = CliRunner()
    with patch("clip_weave.__main__.render", return_value=tmp_path / "final.mp4"):
        result = runner.invoke(cli, [
            "render", "--shots", str(shots_file),
            "--brand", str(brand_dir), "--mode", "hyperframes"
        ])
    assert result.exit_code == 0, result.output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cli.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write `src/clip_weave/__main__.py`**

```python
import json
from pathlib import Path
import click
from clip_weave.config import load_config
from clip_weave.pipeline import analyze, render
from clip_weave.schemas.shots import ShotsOutput
from clip_weave.schemas.brand_assets import BrandAssets


def _load_brand(brand_dir: str) -> BrandAssets:
    p = Path(brand_dir) / "brand_assets.json"
    if p.exists():
        return BrandAssets.model_validate(json.loads(p.read_text()))
    return BrandAssets(brand_name=Path(brand_dir).name)


@click.group()
def cli():
    pass


@cli.command()
@click.option("--video", required=True, help="Path to sample video")
@click.option("--output", default="output/shots.json", help="Output shots.json path")
def analyze_cmd(video: str, output: str):
    cfg = load_config()
    out_path = Path(output)
    shots = analyze(video, cfg, output_dir=out_path.parent)
    click.echo(f"Analysis complete: {out_path} ({shots.shot_count} shots)")


@cli.command()
@click.option("--video", required=True)
@click.option("--brand", required=True, help="Brand assets directory")
@click.option("--mode", default="hyperframes", type=click.Choice(["hyperframes"]))
@click.option("--html-model", default=None, help="claude or gpt4o (overrides env)")
def run_cmd(video: str, brand: str, mode: str, html_model: str):
    cfg = load_config()
    if html_model:
        cfg.html_gen_model = html_model
    brand_assets = _load_brand(brand)
    shots = analyze(video, cfg)
    output = render(shots, brand_assets, cfg)
    click.echo(f"Done: {output}")


@cli.command()
@click.option("--shots", required=True, help="Path to shots.json")
@click.option("--brand", required=True)
@click.option("--mode", default="hyperframes", type=click.Choice(["hyperframes"]))
@click.option("--html-model", default=None)
def render_cmd(shots: str, brand: str, mode: str, html_model: str):
    cfg = load_config()
    if html_model:
        cfg.html_gen_model = html_model
    shots_data = ShotsOutput.model_validate(json.loads(Path(shots).read_text()))
    brand_assets = _load_brand(brand)
    output = render(shots_data, brand_assets, cfg)
    click.echo(f"Done: {output}")


cli.add_command(analyze_cmd, name="analyze")
cli.add_command(run_cmd, name="run")
cli.add_command(render_cmd, name="render")

if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_cli.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run all tests**

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/clip_weave/__main__.py tests/test_cli.py
git commit -m "feat: CLI entry point with analyze / run / render commands"
```

---

### Task 10: E2E Integration Test

**Files:**
- Create: `tests/test_e2e.py`
- Create: `tests/fixtures/make_test_video.py` (helper to generate 5s black test video)

**Interfaces:**
- Consumes: all modules; requires `ffmpeg` on PATH; mocks only external LLM and VideoAgent subprocess
- Produces: `output/final.mp4` exists and is non-empty

- [ ] **Step 1: Write fixture video generator**

`tests/fixtures/make_test_video.py`:
```python
"""Run once to create tests/fixtures/test_5s.mp4 (5-second black video)."""
import subprocess
from pathlib import Path

output = Path(__file__).parent / "test_5s.mp4"
if not output.exists():
    subprocess.run([
        "ffmpeg", "-f", "lavfi", "-i", "color=c=black:s=720x1280:d=5",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "5", "-c:v", "libx264", "-c:a", "aac",
        str(output), "-y"
    ], check=True)
    print(f"Created {output}")
```

- [ ] **Step 2: Generate test fixture**

```bash
python tests/fixtures/make_test_video.py
```

Expected: `tests/fixtures/test_5s.mp4` created.

- [ ] **Step 3: Write E2E test**

`tests/test_e2e.py`:
```python
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from clip_weave.config import Config
from clip_weave.schemas.shots import ShotsOutput
from clip_weave.pipeline import analyze, render
from clip_weave.schemas.brand_assets import BrandAssets

FIXTURE_DIR = Path(__file__).parent / "fixtures"
TEST_VIDEO = FIXTURE_DIR / "test_5s.mp4"
SHOTS_JSON = FIXTURE_DIR / "shots.json"


@pytest.mark.skipif(not TEST_VIDEO.exists(), reason="test_5s.mp4 not generated")
def test_full_pipeline_produces_mp4(tmp_path):
    cfg = Config(
        anthropic_api_key="k", openai_api_key="k",
        gemini_api_key="k", pexels_api_key="k",
        html_gen_model="claude", scene_threshold=0.35,
    )
    brand = BrandAssets(
        brand_name="TestBrand",
        copy_points=["高品质", "限时优惠"],
        color_palette=["#FF5733"],
        target_aspect_ratio="9:16",
    )
    shots_fixture = ShotsOutput.model_validate(json.loads(SHOTS_JSON.read_text()))
    mp4_path = tmp_path / "final.mp4"
    mp4_path.write_bytes(b"fake-mp4-content")

    mock_va = MagicMock(return_value=shots_fixture)
    mock_hf = MagicMock(return_value=mp4_path)
    valid_html = "<html><body><div>Shot 1</div></body></html>"
    mock_llm_msg = MagicMock()
    mock_llm_msg.content = [MagicMock(text=valid_html)]
    mock_claude = MagicMock()
    mock_claude.messages.create.return_value = mock_llm_msg

    with patch("clip_weave.adapters.videoagent.subprocess.run") as mock_sub, \
         patch("clip_weave.adapters.hyperframes.subprocess.run", return_value=MagicMock(returncode=0, stderr="")), \
         patch("clip_weave.core.html_generator._get_claude_client", return_value=mock_claude), \
         patch("clip_weave.adapters.hyperframes._output_path", return_value=mp4_path):
        mock_sub.return_value = MagicMock(
            returncode=0,
            stdout=shots_fixture.model_dump_json(),
            stderr="",
        )
        shots = analyze(str(TEST_VIDEO), cfg, output_dir=tmp_path)
        result = render(shots, brand, cfg, output_dir=tmp_path)

    assert result.exists()
    assert result.stat().st_size > 0
    assert (tmp_path / "shots.json").exists()
```

- [ ] **Step 4: Run E2E test**

```bash
pytest tests/test_e2e.py -v
```

Expected: 1 passed (or skipped if test video not yet generated).

- [ ] **Step 5: Run full test suite**

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Final commit**

```bash
git add tests/test_e2e.py tests/fixtures/make_test_video.py tests/fixtures/test_5s.mp4
git commit -m "test: E2E integration test for Phase 1 + 2a pipeline"
```
