# clip-weave 架构方案与实施路径

> 文档版本：v2.1 | 更新日期：2026-07-21 | Phase 1 + 2a 已完成
> 技术选型分析见 `tech-selection.md`，开发规格见 `superpowers/specs/2026-07-20-clip-weave-design.md`

---

## 目录

1. [推荐技术架构](#1-推荐技术架构)
2. [实施路径](#2-实施路径)
3. [成本估算](#3-成本估算)

---

## 1. 推荐技术架构

### 1.1 整体架构图

Stage 1 共用 VideoAgent；Stage 2-4 由 `render_mode` 参数控制走哪条路径。

```
┌──────────────────────────────────────────────────────────────────┐
│                    clip-weave 系统架构（双路径）                    │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  输入：样例视频 (MP4/MOV) + 品牌素材包                            │
│        + render_mode: "vimax" | "hyperframes"                    │
│                                                                   │
│  Stage 1: 视频帧分析层                              （共用）        │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │  ffprobe：探测视频时长                                      │   │
│  │  FFmpeg：自适应多标准帧提取                                 │   │
│  │    策略：首帧 + 场景切变 + 时间间隔三重保证                 │   │
│  │    自动补充最后一帧（CTA/品牌结尾）；帧数范围 3–40         │   │
│  │  LLM（可配置）：多模态逐帧分析（场景/构图/色调/叙事）       │   │
│  │  输出: shots.json（ShotsOutput schema）                    │   │
│  └──────────────────────────┬────────────────────────────────┘   │
│                             │                                     │
│               ┌─────────────┴──────────────┐                     │
│               ▼                            ▼                     │
│  render_mode="vimax"          render_mode="hyperframes"          │
│  ┌──────────────────────┐    ┌──────────────────────────────┐    │
│  │ HKUDS/ViMax          │    │ LLM HTML 生成                 │    │
│  │ JSON→screenplay 转换 │    │ shots.json → HTML/CSS/GSAP   │    │
│  │ Director Agent       │    │ 素材资产内嵌（图片/视频/字体） │    │
│  │ Screenwriter Agent   │    └──────────────┬───────────────┘    │
│  │ Producer Agent       │                   ▼                    │
│  │ Generator Agent      │    ┌──────────────────────────────┐    │
│  │ （Kling/Seedance/    │    │ HyperFrames 渲染              │    │
│  │   MiniMax）          │    │ Headless Chromium 逐帧截图    │    │
│  └──────────┬───────────┘    │ FFmpeg 合并帧序列 + 音频      │    │
│             │                └──────────────┬───────────────┘    │
│             └──────────────┬───────────────┘                     │
│                            ▼                                     │
│                       output.mp4                                 │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 技术栈汇总

| 层级 | 组件 | 来源 | 路径 | 用途 |
|---|---|---|---|---|
| **视频帧分析** | video_analyzer | clip-weave 内置 | 共用 | ffprobe + FFmpeg 自适应帧提取 + LLM 多模态分析 → shots.json |
| **素材搜索** | Pexels / Pixabay API | 免费 | 共用 | B-Roll 视频 + 图片素材 |
| **语音合成** | Kokoro TTS | hexgrad/kokoro | 共用 | 旁白音频生成（本地，免费） |
| **视频处理** | FFmpeg | 系统级 | 共用 | 关键帧提取、多比例转码、音频合并 |
| **AI 视频生成** | ViMax | HKUDS/ViMax | vimax | screenplay → 多镜头 AI 真实视频 |
| **底层生成模型** | Kling / Seedance / MiniMax | API | vimax | ViMax 调用的视频生成后端 |
| **HTML 渲染** | HyperFrames | heygen-com/hyperframes | hyperframes | HTML/CSS → MP4，Chromium 渲染 |

### 1.3 目录结构

```
clip-weave/
├── src/clip_weave/
│   ├── __main__.py
│   ├── pipeline.py
│   ├── config.py
│   ├── adapters/
│   │   ├── video_analyzer.py
│   │   └── hyperframes.py
│   ├── core/
│   │   ├── html_generator.py
│   │   └── asset_resolver.py
│   └── schemas/
│       ├── shots.py
│       └── brand_assets.py
├── vendors/
│   └── hyperframes/             # git submodule (heygen-com/hyperframes)
├── assets/brand/
├── output/
├── docs/
├── tests/
├── pyproject.toml
└── .env.example
```

---

## 2. 实施路径

### Phase 1：视频理解 MVP ✅ 已完成

目标：给定样例视频，自动输出结构化 shots.json。

- [x] 实现 `adapters/video_analyzer.py`（FFmpeg 帧提取 + LLM 多模态分析）
- [x] 验证 FFmpeg 关键帧提取 + Gemini Flash 分析 pipeline
- [x] 确认 shots.json 输出格式与 narrative_structure 识别准确率
- [x] 实现 `python -m clip_weave analyze` CLI 命令
- [x] 升级为自适应多标准帧提取算法（ffprobe 时长 + 场景切变 + 时间间隔三重保证 + 首尾帧强制包含）

**交付物：** `stage1_analyze` 可用 + 单元测试 + E2E 集成测试覆盖

### Phase 2a：HyperFrames 路径打通 ✅ 已完成

目标：低成本验证叙事结构和文案，成本接近零，可高频迭代。

- [x] 实现 `core/html_generator.py`：shots.json + BrandAssets → LLM → HTML/CSS/GSAP
- [x] 实现 `adapters/hyperframes.py`：HTML → HyperFrames CLI → frames → FFmpeg → mp4
- [x] 集成 Pexels API（`core/asset_resolver.py`）
- [x] 实现 `python -m clip_weave run --mode hyperframes` 完整路径
- [x] 实现 `python -m clip_weave render` 命令（从已有 shots.json 渲染）

**交付物：** `render_mode="hyperframes"` 端到端可用，成本 ~$0.08/视频

### Phase 2b：ViMax 路径打通（预计 1.5 周）

目标：叙事结构验证满意后，接入 ViMax 生成高质量 AI 视频。

- [ ] 集成 ViMax submodule，实现 `adapters/vimax.py`
- [ ] 实现 `videoagent_to_vimax_script()` 格式转换（约 20 行）
- [ ] 集成 ViMax Script2Video 模式，完成首个端到端生成
- [ ] 对齐两条路径输出接口（统一 output.mp4 规格）

**交付物：** `render_mode="vimax"` 端到端可用

### Phase 3：质量提升（预计 2 周）

- [ ] 建立镜头模板库（hook/product/testimonial/cta 四类）
- [ ] 增加视频质量评估 Agent（自动评分循环）
- [ ] 实现多比例输出（9:16/16:9/1:1）
- [ ] 增加 AI 生成 B-Roll（Wan2.2 或 fal.ai）

### Phase 4：工程化（预计 1 周）

- [ ] 容器化（Docker）
- [ ] 批量处理 CLI（多品牌/多 SKU 并行）
- [ ] 人工审核 + 微调反馈循环

---

## 3. 成本估算

### 3.1 单视频生成成本（30s 营销视频）

| 环节 | 工具 | vimax 路径 | hyperframes 路径 |
|---|---|---|---|
| 样例视频分析（5min） | Gemini Flash + Claude Vision | ~$0.02 | ~$0.02 |
| 分镜重构 / HTML 生成 | Claude Sonnet | ~$0.01 | ~$0.03 |
| 视频生成（4-8 镜头） | Kling / Seedance / MiniMax | ~$0.45–1.00 | $0 |
| HTML 渲染 | HyperFrames（本地） | $0 | $0 |
| 素材获取 | Pexels/Pixabay（免费 API） | $0 | $0 |
| TTS 旁白 | Kokoro（本地） | $0 | $0 |
| **单视频合计** | | **~$0.50–1.10** | **~$0.05–0.08** |

两者相差约 **10–15×**。vimax 路径输出 AI 真实影像；hyperframes 路径输出 Motion Graphics 动效。

### 3.2 月基础设施成本（3000 视频/月）

| 资源 | vimax 路径 | hyperframes 路径 |
|---|---|---|
| LLM API（分析+生成） | ~$90 | ~$150 |
| 视频生成 API（Kling/Seedance） | ~$1350–3000 | $0 |
| HyperFrames 渲染（本地） | $0 | $0 |
| 存储（100GB） | ~$2 | ~$2 |
| **月合计** | **~$1440–3090** | **~$152** |

---

## 参考链接

| 资源 | 链接 |
|---|---|
| ViMax | https://github.com/HKUDS/ViMax |
| HyperFrames | https://github.com/heygen-com/hyperframes |
| DeepScene | https://github.com/PhanTrongGiap/deepscene |
| Kokoro TTS | https://github.com/hexgrad/kokoro |
| Pexels API | https://www.pexels.com/api/documentation/ |
| Pixabay API | https://pixabay.com/api/docs/ |
