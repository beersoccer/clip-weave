# clip-weave

AI 驱动的营销视频自动生成工具。输入样例视频 + 品牌素材，自动分析视频结构并生成风格一致的新营销视频。

## 当前状态

| 阶段 | 状态 | 说明 |
|------|------|------|
| Phase 1：视频理解 | ✅ 完成 | FFmpeg 帧提取 + Gemini Flash 分析 → shots.json |
| Phase 2a：HyperFrames 路径 | ✅ 完成 | shots.json → HTML/CSS/GSAP → MP4 |
| Phase 2b：ViMax 路径 | 🔲 待开发 | AI 真实影像生成 |
| Phase 3：质量提升 | 🔲 待开发 | 模板库、多比例输出 |
| Phase 4：工程化 | 🔲 待开发 | Docker、批量处理 |

## 架构

```
样例视频 + 品牌素材
       │
       ▼
Stage 1: 视频理解（FFmpeg 帧提取 + Gemini Flash 逐帧分析）
       → output/shots.json（镜头结构 + 风格信息）
       │
       ▼
Stage 2a: HTML 生成（Claude Sonnet / GPT-4o）
       → HTML/CSS/GSAP 动效代码
       + Pexels 素材自动检索（可选）
       │
       ▼
Stage 3: HyperFrames 渲染（npx hyperframes render）
       → Headless Chromium 逐帧截图 → FFmpeg 合并 → output/final.mp4
```

---

## 前置依赖

运行前需确认以下工具已安装并可在终端访问：

### 1. Python 3.11+（通过 uv 管理）

```bash
# 安装 uv（若未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 验证
uv --version
```

### 2. FFmpeg

视频帧提取的核心依赖，**必须安装**。

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# 验证
ffmpeg -version
```

### 3. Node.js 18+（含 npm）

HyperFrames 渲染通过 `npx` 调用，需要 Node.js 和 npm。

```bash
# macOS（推荐通过 nvm 或 brew）
brew install node

# 验证
node --version   # 需要 >= 18
npm --version
```

---

## 快速开始

### 第一步：克隆项目

```bash
git clone --recurse-submodules https://github.com/your-org/clip-weave.git
cd clip-weave
```

> `--recurse-submodules` 会同时初始化 `vendors/hyperframes`（渲染参考实现）。

### 第二步：安装 Python 依赖

```bash
uv sync
```

uv 会自动读取 `.python-version`（3.11.12）并创建 `.venv`。

### 第三步：配置 API 密钥

```bash
cp .env.example .env
```

编辑 `.env`，填入密钥：

```dotenv
# 视频帧分析（Stage 1）
VIDEO_ANALYSIS_BASE_URL=               # 公司 AI 网关 /v1 地址；留空则直连厂商
VIDEO_ANALYSIS_API_KEY=your_key        # 必填
VIDEO_ANALYSIS_MODEL=gemini-2.0-flash-exp  # 可选，默认 gemini-2.0-flash-exp

# HTML 生成（Stage 2a）
HTML_GEN_BASE_URL=                     # 同上，可与 Stage 1 使用同一网关
HTML_GEN_API_KEY=your_key             # 必填
HTML_GEN_MODEL=claude-sonnet-4-6      # 可选，默认 claude-sonnet-4-6

PEXELS_API_KEY=                        # 可选：缺失时跳过素材搜索
SCENE_THRESHOLD=0.35                   # 可选：场景切变灵敏度，越小帧越多
```

两处 `*_BASE_URL` 留空时直连厂商 API，填入公司 AI 网关地址时走网关代理，两处可独立配置。配置错误时程序会打印 `[WARNING]` 提示而不会崩溃。

**API 密钥申请（直连时）：**
- Gemini：https://aistudio.google.com/apikey
- Anthropic：https://console.anthropic.com/
- Pexels（可选）：https://www.pexels.com/api/

### 第四步：准备样例视频

将一段 MP4/MOV 视频（建议 30s 以内）放到任意路径，例如 `assets/sample.mp4`。

### 第五步：验证分析阶段（Stage 1）

先单独跑分析，确认 FFmpeg 和 LLM 接口配置正常，再做完整渲染：

```bash
uv run python -m clip_weave analyze \
  --video assets/sample.mp4 \
  --output output/shots.json
```

成功输出示例：
```
Analysis complete: output/shots.json (6 shots)
```

查看 `output/shots.json` 确认结构化镜头数据已生成。

### 第六步：完整流程（分析 + 渲染）

```bash
uv run python -m clip_weave run \
  --video assets/sample.mp4 \
  --brand assets/brand
```

生成结果：`output/final.mp4`

---

## 品牌素材配置

`--brand` 指向品牌目录，目录下可放 `brand_assets.json`（所有字段均可选）：

```json
{
  "brand_name": "MyBrand",
  "primary_color": "#FF6B35",
  "secondary_color": "#2C3E50",
  "logo_path": "assets/brand/logo.png",
  "tagline": "品牌口号",
  "font_family": "Inter"
}
```

若目录下无 `brand_assets.json`，则以目录名作为 `brand_name` 自动创建最简品牌配置。

---

## CLI 命令参考

### `analyze` — 仅分析视频

```bash
uv run python -m clip_weave analyze \
  --video <视频路径> \
  --output <shots.json 输出路径，默认 output/shots.json>
```

### `run` — 完整流程（分析 + 渲染）

```bash
uv run python -m clip_weave run \
  --video <视频路径> \
  --brand <品牌目录> \
  [--mode hyperframes]          # 目前仅支持 hyperframes
  [--html-model <模型名>]        # 覆盖 HTML_GEN_MODEL 环境变量
```

### `render` — 仅渲染（从已有 shots.json）

```bash
uv run python -m clip_weave render \
  --shots output/shots.json \
  --brand assets/brand \
  [--html-model claude|gpt4o]
```

适用场景：已有分析结果，只想调整品牌或重新渲染。

---

## 输出文件

| 文件 | 说明 |
|------|------|
| `output/shots.json` | 结构化镜头分析（shot 列表、风格信息、叙事结构） |
| `output/compositions/index.html` | 生成的 HTML/CSS/GSAP 动效源码 |
| `output/final.mp4` | 最终渲染视频 |
| `output/frames/` | FFmpeg 提取的关键帧（中间产物） |

---

## 开发与测试

```bash
# 运行所有单元测试
uv run pytest

# 生成 E2E 测试用的 5s 测试视频（需要 FFmpeg）
uv run python tests/fixtures/make_test_video.py

# 运行 E2E 集成测试（模拟全链路，mock 外部 API）
uv run pytest tests/test_e2e.py -v
```

---

## 成本参考（单个 30s 视频）

| 路径 | 约成本 | 输出类型 |
|------|--------|---------|
| HyperFrames（当前） | ~$0.05–0.08 | Motion Graphics 动效 |
| ViMax（待开发） | ~$0.50–1.10 | AI 真实影像 |

---

## 常见问题

**Q: `ffmpeg: command not found`**  
A: 参考上方"前置依赖"中的 FFmpeg 安装步骤。

**Q: `Error: Cannot find module 'hyperframes'` 或 npx 超时**  
A: 首次运行 `npx hyperframes render` 时 npm 会自动下载，需要网络访问 registry.npmjs.org。也可预先安装：`npm install -g hyperframes`。

**Q: `VideoAnalysisError: LLM API call failed`**  
A: 检查 `.env` 中 `VIDEO_ANALYSIS_API_KEY` 是否正确；若使用网关，确认 `VIDEO_ANALYSIS_BASE_URL` 可访问且模型名称（`VIDEO_ANALYSIS_MODEL`）被该网关支持。启动时终端会打印 `[WARNING]` 提示具体缺失项。

**Q: shots.json 中 `shot_count: 0` 或帧数很少**  
A: 降低 `SCENE_THRESHOLD`（如 `0.2`）增加检测灵敏度。

**Q: 不填 `PEXELS_API_KEY` 会怎样**  
A: 跳过素材搜索，HTML 中使用占位内容，不影响视频渲染。

---

## 项目结构

```
clip-weave/
├── src/clip_weave/
│   ├── __main__.py          # CLI（analyze / run / render）
│   ├── pipeline.py          # 流程编排
│   ├── config.py            # 环境变量加载
│   ├── adapters/
│   │   ├── video_analyzer.py  # FFmpeg + LLM 视频帧分析
│   │   └── hyperframes.py     # npx hyperframes 渲染封装
│   ├── core/
│   │   ├── html_generator.py  # LLM → HTML/CSS/GSAP
│   │   └── asset_resolver.py  # Pexels 素材检索
│   └── schemas/
│       ├── shots.py         # ShotsOutput / Shot / StyleInfo
│       └── brand_assets.py  # BrandAssets
├── vendors/
│   └── hyperframes/         # git submodule（heygen-com/hyperframes）
├── assets/brand/            # 品牌素材（gitignored）
├── output/                  # 生成结果（gitignored）
├── tests/
├── docs/
├── pyproject.toml
└── .env.example
```

---

## 文档

- [架构方案与实施路径](docs/architecture.md)
- [技术选型分析](docs/tech-selection.md)
