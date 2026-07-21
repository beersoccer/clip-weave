# clip-weave

AI 驱动的营销视频自动生成工具。输入样例视频 + 品牌素材，自动分析视频结构并生成风格一致的新营销视频。

## 当前状态

| 阶段 | 状态 | 说明 |
|------|------|------|
| Phase 1：视频理解 | ✅ 完成 | VideoAgent 分析 → shots.json |
| Phase 2a：HyperFrames 路径 | ✅ 完成 | shots.json → HTML/CSS → MP4 |
| Phase 2b：ViMax 路径 | 🔲 待开发 | AI 真实影像生成 |
| Phase 3：质量提升 | 🔲 待开发 | 模板库、多比例输出 |
| Phase 4：工程化 | 🔲 待开发 | Docker、批量处理 |

## 架构

```
样例视频 + 品牌素材
       │
       ▼
Stage 1: VideoAgent（Gemini Flash 逐帧分析）
       → shots.json（镜头结构 + 风格信息）
       │
       ▼
Stage 2a: HTML 生成（Claude / GPT-4o）
       → HTML/CSS/GSAP 动效代码
       + Pexels 素材自动检索
       │
       ▼
Stage 3: HyperFrames 渲染
       → 帧序列（Headless Chromium）
       → FFmpeg 合并 → output.mp4
```

## 安装

依赖 Python 3.11+ 和 [uv](https://github.com/astral-sh/uv)。

```bash
git clone --recurse-submodules https://github.com/your-org/clip-weave.git
cd clip-weave
uv sync
```

HyperFrames 渲染需要 Node.js（供 `vendors/hyperframes` 使用）。

## 配置

复制 `.env.example` 为 `.env` 并填入密钥：

```bash
cp .env.example .env
```

| 变量 | 必填 | 说明 |
|------|------|------|
| `GEMINI_API_KEY` | ✅ | Stage 1 视频帧分析 |
| `ANTHROPIC_API_KEY` | 条件必填 | HTML_GEN_MODEL=claude 时 |
| `OPENAI_API_KEY` | 条件必填 | HTML_GEN_MODEL=gpt4o 时 |
| `PEXELS_API_KEY` | 可选 | B-Roll 素材自动搜索 |
| `HTML_GEN_MODEL` | 可选 | `claude`（默认）或 `gpt4o` |
| `SCENE_THRESHOLD` | 可选 | 场景切变检测阈值，默认 `0.35` |

## 使用

### 完整流程（分析 + 渲染）

```bash
python -m clip_weave run \
  --video path/to/sample.mp4 \
  --brand path/to/brand_dir \
  --mode hyperframes
```

`brand_dir` 下放置 `brand_assets.json`（可选）：

```json
{
  "brand_name": "MyBrand",
  "primary_color": "#FF6B35",
  "logo_path": "assets/brand/logo.png",
  "tagline": "品牌口号"
}
```

### 仅分析（生成 shots.json）

```bash
python -m clip_weave analyze \
  --video path/to/sample.mp4 \
  --output output/shots.json
```

### 仅渲染（从已有 shots.json）

```bash
python -m clip_weave render \
  --shots output/shots.json \
  --brand path/to/brand_dir
```

### 切换 HTML 生成模型

```bash
# 使用 GPT-4o 生成 HTML
python -m clip_weave run --video sample.mp4 --brand brand/ --html-model gpt4o
```

## 输出

- `output/shots.json`：结构化镜头分析结果
- `output/final.mp4`：生成的营销视频

## 项目结构

```
clip-weave/
├── src/clip_weave/
│   ├── __main__.py          # CLI 入口（analyze / run / render）
│   ├── pipeline.py          # 流程编排
│   ├── config.py            # 环境变量加载与验证
│   ├── adapters/
│   │   ├── videoagent.py    # VideoAgent 封装（Stage 1）
│   │   └── hyperframes.py   # HyperFrames 封装（Stage 2a）
│   ├── core/
│   │   ├── html_generator.py  # LLM → HTML/CSS/GSAP
│   │   └── asset_resolver.py  # Pexels 素材检索与下载
│   └── schemas/
│       ├── shots.py         # ShotsOutput / Shot / StyleInfo
│       └── brand_assets.py  # BrandAssets
├── vendors/
│   ├── VideoAgent/          # git submodule (HKUDS/VideoAgent)
│   └── hyperframes/         # git submodule (heygen-com/hyperframes)
├── assets/brand/            # 品牌素材（本地，不纳入版本控制）
├── output/                  # 生成结果（gitignored）
├── tests/                   # 单元测试 + E2E 集成测试
├── docs/                    # 技术方案与架构文档
├── pyproject.toml
└── .env.example
```

## 开发

```bash
# 运行测试
uv run pytest

# 运行 E2E 测试（需先生成测试视频）
uv run python tests/fixtures/make_test_video.py
uv run pytest tests/test_e2e.py -v
```

## 成本参考（单个 30s 视频）

| 路径 | 成本 | 输出类型 |
|------|------|------|
| HyperFrames（当前） | ~$0.05–0.08 | Motion Graphics 动效 |
| ViMax（待开发） | ~$0.50–1.10 | AI 真实影像 |

## 文档

- [架构方案与实施路径](docs/architecture.md)
- [技术选型分析](docs/tech-selection.md)
- [AI 营销视频解决方案](docs/ai-marketing-video-solution.md)
