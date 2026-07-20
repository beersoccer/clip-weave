# clip-weave — 设计规格

> 版本：v1.0 | 日期：2026-07-20
> 范围：Phase 1（视频理解 MVP）+ Phase 2a（HyperFrames 路径）

---

## 1. 项目概述

clip-weave 是一个 AI 自动化营销视频生成系统。给定一个样例视频和品牌素材包，自动分析样例视频的叙事结构与视觉风格，并生成风格一致的新营销视频。

**本 spec 覆盖范围：**
- Phase 1：VideoAgent（HKUDS）→ shots.json（约 1 周）
- Phase 2a：shots.json → HTML/CSS/GSAP → HyperFrames 渲染 → final.mp4（约 3 天）

---

## 2. 架构方案：适配器模式（Adapter Pattern）

选型依据：VideoAgent 作为 git submodule 接口较重，适配层将外部工具与业务逻辑解耦，使各阶段可独立测试和替换，同时保持结构轻量。

### 2.1 目录结构

```
clip-weave/
├── src/clip_weave/
│   ├── __main__.py              # CLI 入口
│   ├── pipeline.py              # 编排：analyze() → render()
│   ├── config.py                # LLM 选择、API keys、阈值配置
│   ├── adapters/
│   │   ├── videoagent.py        # VideoAgent submodule 封装
│   │   └── hyperframes.py       # HyperFrames submodule 封装
│   ├── core/
│   │   ├── html_generator.py    # shots.json → HTML/CSS/GSAP
│   │   └── asset_resolver.py    # Pexels/Pixabay 素材搜索下载
│   └── schemas/
│       ├── shots.py             # ShotsOutput Pydantic model
│       └── brand_assets.py      # BrandAssets Pydantic model
├── vendors/
│   ├── VideoAgent/              # git submodule (HKUDS/VideoAgent) — Phase 1
│   └── hyperframes/             # git submodule (heygen-com/hyperframes) — Phase 2a
├── assets/brand/                # 用户品牌素材（logo/产品图/文案）
├── output/                      # 运行产物
├── docs/
│   ├── tech-selection.md        # 技术选型分析
│   ├── architecture.md          # 架构方案与实施路径
│   └── superpowers/specs/       # 本文件所在目录
├── tests/
│   └── fixtures/                # 测试用 fixture 视频和 mock JSON
├── pyproject.toml
└── .env.example
```

### 2.2 模块边界规则

- `adapters/` 只知道外部工具 API，不包含业务逻辑
- `core/` 只操作 Pydantic schema，不直接调用 vendors
- `pipeline.py` 是连接两层的唯一入口

---

## 3. 数据契约

### 3.1 Stage 1 输出 — ShotsOutput

```python
class Shot(BaseModel):
    index: int
    start: float
    end: float
    duration: float
    type: Literal["hook", "product", "testimonial", "cta"]
    composition: str
    text_overlay: Optional[str]
    visual_element: str
    audio_cue: Optional[str]

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

### 3.2 输入契约 — BrandAssets

```python
class BrandAssets(BaseModel):
    brand_name: str
    tagline: Optional[str]
    logo_path: Optional[Path]
    product_images: list[Path] = []
    color_palette: list[str] = []   # hex codes
    copy_points: list[str] = []     # 文案要点
    target_aspect_ratio: str = "9:16"
```

---

## 4. CLI 接口

```bash
# 仅分析（Stage 1）
python -m clip_weave analyze --video sample.mp4 --output output/shots.json

# 完整运行（Stage 1 + 2a）
python -m clip_weave run \
  --video sample.mp4 \
  --brand assets/brand/ \
  --mode hyperframes \
  --html-model claude    # 可选 claude | gpt4o，默认 claude

# 复用已有 shots.json 仅渲染
python -m clip_weave render \
  --shots output/shots.json \
  --brand assets/brand/ \
  --mode hyperframes
```

**配置（`.env` + `config.py`）：**

```
GEMINI_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
PEXELS_API_KEY=
HTML_GEN_MODEL=claude      # claude | gpt4o
SCENE_THRESHOLD=0.35
```

---

## 5. Pipeline 数据流

```
sample.mp4
    │
    ▼  adapters/videoagent.py
    │  FFmpeg 关键帧提取 → Gemini/GPT-4o/Claude 多模态分析
    │  → ShotsOutput（持久化为 output/shots.json）
    │
    ▼  core/html_generator.py
    │  shots + BrandAssets → prompt → 可配置 LLM（默认 Claude）
    │  → HTML/CSS/GSAP 字符串
    │
    ▼  adapters/hyperframes.py
    │  写 HTML → output/compositions/
    │  HyperFrames CLI（Headless Chromium 逐帧截图）
    │  FFmpeg 合并帧序列 + 音频
    │
    ▼  output/final.mp4
```

---

## 6. 错误处理

| 阶段 | 失败场景 | 处理方式 |
|---|---|---|
| VideoAgent 调用 | FFmpeg 或 LLM API 错误 | 抛出 `VideoAnalysisError`，附带 stderr 和 LLM 原始响应 |
| HTML 生成 | LLM 返回非合法 HTML | 最多重试 2 次；仍失败则保存 raw 输出至 `output/debug/` |
| HyperFrames 渲染 | Chromium 或 FFmpeg 失败 | 保留帧序列 `output/frames/`，不自动删除 |

`analyze` 输出写入 `output/shots.json` 后即持久化，`render` 命令可独立重跑，无需重新分析。

---

## 7. 测试策略

| 层级 | 测试对象 | 方式 |
|---|---|---|
| Schema | `ShotsOutput` / `BrandAssets` 解析与验证 | pytest + 静态 fixture JSON |
| Adapters | `videoagent.py` / `hyperframes.py` | Mock submodule CLI 调用，验证入参和输出解析 |
| Core | `html_generator.py` | Mock LLM 返回，验证 prompt 构造和 HTML 合法性检查 |
| E2E | 完整 `run` 命令 | 5s 测试视频 + 最小 brand_assets，验证 `final.mp4` 存在且非空 |

测试 fixture 放 `tests/fixtures/`。

---

## 8. 超出本 spec 的范围（Phase 2b / 3 / 4）

- ViMax 路径（AI 真实影像视频生成）
- 多比例输出（9:16 / 16:9 / 1:1）
- 视频质量评估 Agent
- Docker 容器化与批量 CLI
