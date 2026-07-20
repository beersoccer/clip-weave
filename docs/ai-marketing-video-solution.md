# AI 自动化营销视频生成系统方案

> 文档版本：v2.0 | 更新日期：2026-07-20

---

## 目录

1. [应用场景分析](#1-应用场景分析)
2. [四阶段 Pipeline 总览](#2-四阶段-pipeline-总览)
3. [样例视频分析方法论](#3-样例视频分析方法论)
4. [无版权素材来源](#4-无版权素材来源)
5. [开源项目选型分析](#5-开源项目选型分析)
   - [5.1 视频理解层选型](#51-视频理解层选型)
   - [5.2 生成层 Pipeline 选型：VideoAgent + ViMax vs agentcut](#52-生成层-pipeline-选型)
   - [5.3 多 Agent 编排框架对比](#53-多-agent-编排框架对比)
   - [5.4 HTML→视频渲染引擎对比](#54-html视频渲染引擎对比)
   - [5.5 参考实现分析](#55-参考实现分析)
6. [推荐技术架构](#6-推荐技术架构)
7. [实施路径](#7-实施路径)
8. [成本估算](#8-成本估算)

---

## 1. 应用场景分析

### 1.1 核心需求拆解

给定一个优质样例视频，结合品牌素材，自动生成风格一致的新营销视频。

| 挑战 | 说明 | 技术难点 |
|---|---|---|
| **风格提取** | 从样例视频中理解节奏、镜头语言、色调、转场风格 | 视频多模态理解，结构化输出 |
| **内容重构** | 用新的品牌素材填充相同的叙事结构，而非简单复制 | LLM 创意改写 + 素材匹配 |
| **精准渲染** | HTML→视频的像素级还原，确保动画、字幕、音频精准同步 | 确定性渲染引擎 |

### 1.2 典型使用场景

- **电商大促**：同一模板视频，替换产品图/价格/文案，批量生成百款 SKU 的短视频
- **品牌系列内容**：参考爆款竞品视频，提取叙事结构，用己方素材重新生成
- **多平台适配**：一次生成，自动输出 16:9（YouTube）、9:16（抖音/Reels）、1:1（朋友圈）三种比例

---

## 2. 四阶段 Pipeline 总览

### 2.1 整体流程图

Stage 1 对两条路径完全共用；Stage 2-4 根据 `render_mode` 参数分叉：

```
┌─────────────────────────────────────────────────────────────────┐
│  输入：样例视频 + 品牌素材包                                      │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│   Stage 1: 视频理解（VideoAgent）          ← 两条路径共用        │
│   场景切变检测 (FFmpeg) → 关键帧提取                              │
│   多模态 LLM 分析（Gemini + Claude + GPT-4o）                    │
│   输出：shots.json + style.json                                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
              render_mode 参数控制分叉
                  ┌────────┴────────┐
                  ▼                 ▼
        "vimax"（默认）       "hyperframes"
   ─────────────────────   ─────────────────────
   Stage 2-4: ViMax          Stage 2: LLM 生成 HTML
   screenplay 格式转换        CSS/GSAP 动效代码
   多 Agent 分镜规划          素材资产内嵌
   AI 视频片段生成             Stage 3: HyperFrames 渲染
   （Kling/Seedance/MiniMax） Headless Chromium 逐帧
   角色/场景一致性保障         FFmpeg 合并帧序列+音频
   ─────────────────────   ─────────────────────
        output.mp4               output.mp4
   AI 真实影像风格          Motion Graphics 动效风格
   成本 ~$0.50-1.10/视频    成本 ~$0.05-0.08/视频
```

### 2.2 关键技术决策

#### Stage 1：为什么先做帧提取再分析？

直接将完整视频发送给视觉 LLM 的成本是先做帧提取再分析的 **10-16×**。

| 方法 | 5min 视频成本 | GPU 需求 |
|---|---|---|
| 场景检测 + 帧提取 + Gemini Flash | ~$0.003 | 无 |
| 原始视频 → Gemini Native | ~$0.05 | 无 |
| 原始视频 → GPT-4V | ~$0.08 | 无 |
| Video-LLaMA（本地） | $0（电费） | A100 必须 |

最佳实践：用 FFmpeg 场景切变检测（`select='gt(scene,0.4)'`）提取关键帧再调用 API。

#### Stage 2-4：两条路径的取舍

| | ViMax 路径 | HyperFrames 路径 |
|---|---|---|
| **输出风格** | AI 真实影像（真人/实景） | Motion Graphics 动效 |
| **单视频成本** | ~$0.50–1.10 | ~$0.05–0.08 |
| **适合内容** | 人物出镜、产品实拍风格 | 纯文字/图片/logo 动效 |
| **推荐用途** | 正式生产 | 快速预览、高频批量 |

HyperFrames 路径用原生 HTML/CSS 而非 React/DSL，原因：LLM 生成 HTML 的质量显著更高（HTML 是训练数据主体），渲染结果确定性高（相同输入 = 相同视频帧）。

---

## 3. 样例视频分析方法论

### 3.1 结构化提取内容

```json
{
  "style": {
    "pacing": "fast",              // 节奏：fast / medium / slow
    "color_tone": "warm",          // 色调：warm / cool / neutral
    "typography": "bold-sans",     // 字体风格
    "transition": "cut",           // 转场：cut / fade / swipe / zoom
    "aspect_ratio": "9:16"         // 画幅比例
  },
  "shots": [
    {
      "index": 1,
      "start": 0.0,
      "end": 2.5,
      "duration": 2.5,
      "type": "hook",              // 镜头类型：hook / product / testimonial / cta
      "composition": "centered",   // 构图：centered / rule-of-thirds / full-bleed
      "text_overlay": "痛点文案",
      "visual_element": "人物特写",
      "audio_cue": "节奏感强的背景音乐起"
    }
  ],
  "narrative_structure": "AIDA",   // 叙事结构：AIDA / PAS / StoryBrand
  "total_duration": 30,
  "shot_count": 12
}
```

### 3.2 营销叙事结构

| 结构 | 全称 | 镜头分配 | 适用场景 |
|---|---|---|---|
| **AIDA** | Attention→Interest→Desire→Action | 2+3+4+1 镜 | 品牌/产品通用 |
| **PAS** | Problem→Agitate→Solution | 3+3+4 镜 | 痛点驱动型 |
| **Hook-Story-Offer** | 钩子→故事→报价 | 1+6+3 镜 | 电商转化型 |
| **Before-After-Bridge** | 前→后→桥接 | 3+4+3 镜 | 效果展示型 |

### 3.3 关键帧提取命令

```bash
# 场景切变检测（适合节奏快的营销视频）
ffmpeg -i sample.mp4 \
  -vf "select='gt(scene,0.35)',scale=1280:720" \
  -vsync vfr \
  frames/frame_%04d.jpg

# 固定间隔提取（适合慢节奏视频）
ffmpeg -i sample.mp4 -vf fps=1 frames/frame_%04d.jpg

# 提取音频（用于节奏分析）
ffmpeg -i sample.mp4 -q:a 0 -map a audio.mp3
```

---

## 4. 无版权素材来源

### 4.1 免费视频素材 API（可商用，无需署名）

| 平台 | 限制 | 最佳用途 |
|---|---|---|
| **Pexels** | 无商用限制 | 人物/场景 B-Roll |
| **Pixabay** | 无商用限制，无需署名 | 背景/自然素材 |
| **Mixkit** | 完全免费，含 4K | 高质量转场/背景 |
| **Coverr** | 商用可用，无需署名 | 商业场景视频 |

```python
# Pexels API 调用示例
import requests

headers = {"Authorization": "YOUR_PEXELS_API_KEY"}
response = requests.get(
    "https://api.pexels.com/videos/search",
    headers=headers,
    params={"query": "product lifestyle", "per_page": 10, "orientation": "portrait"}
)
videos = response.json()["videos"]
```

### 4.2 图片素材 API

| 平台 | 特点 |
|---|---|
| **Unsplash** | 质量最高，商用免费（`api.unsplash.com`） |
| **Pexels Photos** | 同视频 API，统一 key |
| **Pixabay Images** | 量最大（430万+，`pixabay.com/api`） |

### 4.3 AI 生成素材（完全无版权风险）

AI 生成内容在多数司法管辖区不受版权保护，是最安全的素材来源。

| 用途 | 推荐工具 | 成本 |
|---|---|---|
| 产品场景图 | Flux Pro / SDXL（本地） | ~$0.01/张 或免费 |
| 背景视频 | Wan2.2（开源）/ Kling | $0（本地）/ $0.05/段 |
| 旁白音频 | Kokoro TTS（本地开源） | $0 |
| 背景音乐 | MusicGen（Meta，本地） | $0 |

---

## 5. 开源项目选型分析

### 5.1 视频理解层选型

#### 5.1.1 候选项全量对比

共考察 6 个项目：

| 项目 | ⭐ Stars | 贡献者 | 最近维护 | 许可 | 语言 |
|---|---|---|---|---|---|
| [open-mmlab/mmaction2](https://github.com/open-mmlab/mmaction2) | **~14k** | 200+ | **2022**（停止维护） | Apache-2.0 | Python |
| [facebookresearch/SlowFast](https://github.com/facebookresearch/SlowFast) | **7.4k** | 30+ | **2022**（停止维护） | Apache-2.0 | Python |
| [OpenGVLab/InternVideo](https://github.com/OpenGVLab/InternVideo) | **~3k** | 20+ | Jun 2026（活跃） | MIT | Python |
| [HKUDS/VideoAgent](https://github.com/HKUDS/VideoAgent) | 1.5k | 8 | Jul 2026（活跃） | MIT | Python |
| [BroderQi/Storyboard](https://github.com/BroderQi/Storyboard) | ~50 | 2 | 2025 | - | Python |
| [PhanTrongGiap/deepscene](https://github.com/PhanTrongGiap/deepscene) | ~80 | 1 | 2025 | MIT | Python |

> Stars 高 ≠ 适合本场景。以下从任务匹配度做根本分析。

#### 5.1.2 高 Stars 项目为何不选

三个高 stars 项目解答的问题与本应用的问题根本不同：

| | mmaction2 / SlowFast | InternVideo3 | **本应用需要** |
|---|---|---|---|
| **核心问题** | "这段视频里在做什么动作？" | "这段视频讲的是什么？" | **"这个广告的叙事结构和风格是什么？"** |
| **输出形式** | 分类标签（`running`, `jumping`） | 自由文本描述 | **结构化 JSON**（镜头/节奏/色调/叙事） |
| **设计年代** | 2019（深度学习分类时代） | 2022-2026（MLLM 时代） | 2024-2026（Agent 时代） |
| **基础设施** | 必须 GPU，环境配置复杂 | 需 A100/H100 级 GPU | **无 GPU，直接 API 调用** |

**mmaction2 / SlowFast**：训练/评测框架，面向学术动作识别数据集（Kinetics-400 等）。输出是 400 个预定义动作标签之一，无法描述广告叙事结构或视觉风格。2022 年后均已停止维护，mmcv 版本依赖地狱是常见问题。Stars 来自 CV 研究社区引用，与本场景无关。

**InternVideo3**：最接近可用的候选项，视频理解能力是六者中最强的，但对本应用有结构性限制：

| 维度 | InternVideo3 | 本应用需求 | 差距 |
|---|---|---|---|
| 模型大小 | 8B instruct 模型 | 无 GPU 偏好 | 需要 A100/H100 |
| 输出格式 | 自由文本（需再解析） | 直接输出 shots.json | 需额外 prompt 工程 |
| 调用成本 | GPU 时间费用 | API 调用 $0.003/5min | 比 API 方案贵 10-50× |
| storyboard 支持 | 无内置分镜提取 | 需要开箱即用 | 需自行搭建 |

**结论**：若团队有 GPU 基础设施且愿意投入集成成本，InternVideo3 可替换 Stage 1 中的 LLM Vision 调用，理解质量更高。但它不是 pipeline，无法独立满足需求。

#### 5.1.3 低 Stars 项目为何更合适

三个低 stars 项目生于 LLM/Agent 时代，回答的问题与本应用完全一致：

| 项目 | 设计问题 | 输出 | 基础设施 | 场景匹配度 |
|---|---|---|---|---|
| **DeepScene** | "给我这个视频的分镜脚本" | 结构化 JSON（shots/scenes/audio_cues） | 无 GPU，纯 API | ★★★★★ |
| **BroderQi/Storyboard** | "把视频拆解成可编辑的分镜" | 数据库中的分镜记录 | 无 GPU，Python | ★★★★☆ |
| **VideoAgent (HKUDS)** | "理解、编辑并重制这个视频" | 视频分析 + 编辑指令 + 新视频 | 无 GPU，LLM API | ★★★★★ |

**DeepScene** 的内部流程与 Stage 1 需求完全对齐：

```
视频文件
  → FFmpeg 场景切变检测（阈值 0.35）
  → 关键帧提取（base64 编码）
  → 音频块提取（Whisper 转写）
  → Gemini Flash / GPT-4V 多模态分析
  → 输出 shots.json（含 shot type/scene/characters/audio_cues）
```

**VideoAgent** 实现了"视频理解→编辑→重制"的完整闭环，覆盖本应用 Stage 1 + Stage 2：

```
├── 视频内容理解（multimodal，图构化引导）
├── 自动构建编辑工作流（graph-structured）
├── 视频重制输出（remaking）
└── 自反馈质量评估（self-reflection）
```

#### 5.1.4 选型决策矩阵

综合 **任务匹配度、工程成本、运行成本、维护状态** 四维评分（5 分制）：

| 项目 | 任务匹配 | 工程成本 | 运行成本 | 维护状态 | **总分** | **推荐** |
|---|---|---|---|---|---|---|
| mmaction2 | ★☆☆☆☆ | ★★☆☆☆ | ★★☆☆☆ | ★☆☆☆☆ | 6/20 | ❌ |
| SlowFast | ★☆☆☆☆ | ★☆☆☆☆ | ★★☆☆☆ | ★☆☆☆☆ | 5/20 | ❌ |
| InternVideo3 | ★★★☆☆ | ★★☆☆☆ | ★★☆☆☆ | ★★★★☆ | 11/20 | ⚠️ 有 GPU 时可考虑 |
| BroderQi/Storyboard | ★★★★☆ | ★★★★☆ | ★★★★★ | ★★★☆☆ | 16/20 | ✅ 备选 |
| DeepScene | ★★★★★ | ★★★★★ | ★★★★★ | ★★★☆☆ | 18/20 | ✅ **Stage 1 首选** |
| VideoAgent | ★★★★★ | ★★★★☆ | ★★★★☆ | ★★★★★ | 18/20 | ✅ **整体首选** |

**最终推荐：**
- MVP 阶段：DeepScene（最快上手，成本最低）
- 进阶方案：VideoAgent（覆盖理解+重制，论文级质量）
- 有 GPU 时：InternVideo3 可替换 LLM Vision 调用，理解质量更高
- 永不选用：mmaction2、SlowFast（工具类型根本不匹配，且已停止维护）

### 5.2 生成层 Pipeline 选型

以 VideoAgent 作为 Stage 1 的前提下，Stage 2-4 选 ViMax 还是 agentcut？

#### 三个项目的职责边界

| 项目 | 本质 | 输入 | 输出 |
|---|---|---|---|
| **VideoAgent** | 视频"理解→编辑→重制"框架 | 已有视频 + 用户意图 | 结构化分析、编辑指令、重制内容 |
| **ViMax** | 多 Agent 视频"生成"框架 | 文字 Idea / 剧本 / 参考图 | 完整多镜头视频（含角色一致性） |
| **agentcut** | 轻量 6-Agent 视频"生成"管道 | 一句文字 prompt | MP4（via MiniMax） |

#### 核心问题：VideoAgent 的输出，谁能接住？

VideoAgent 分析完样例视频后，输出**结构化富内容**（叙事结构 + shots + 角色 + 风格）。

**agentcut 的接口只接收贫内容**：

```bash
POST /api/create
{"prompt": "A product video for sneakers", "duration": 18, "num_shots": 3}
```

VideoAgent 的全部富信息到 agentcut 只能压缩为一句话 prompt，其 Director Agent 会**从头重新规划**——VideoAgent 的分析实际被丢弃，两个 Stage 的工作产生严重重叠。

**ViMax 的 `Script2Video` 接收富内容**：

```python
# main_script2video.py —— 直接接受 screenplay 格式
script = """
EXT. CITY STREET - DAY
Lisa (25, athletic) runs toward camera. Wide shot, warm tone.
Text overlay: "跑得更快"

INT. STUDIO - DAY
Product close-up: sneaker sole. Macro lens, 3 seconds.
"""
user_requirement = "Fast-paced, no more than 8 shots, energetic style"
```

VideoAgent 输出的结构化脚本可以**直接格式化为 ViMax Script2Video 的入参**，信息无损传递。

**VideoAgent → ViMax 格式转换（约 20 行胶水代码）**：

```python
def videoagent_to_vimax_script(analysis: dict) -> str:
    lines = []
    for shot in analysis["shots"]:
        lines.append(f"SHOT {shot['index']} - {shot['type'].upper()}")
        lines.append(shot["description"])
        if shot.get("text_overlay"):
            lines.append(f'Text: "{shot["text_overlay"]}"')
        lines.append(f"Duration: {shot['duration']}s")
        lines.append("")
    return "\n".join(lines)

user_requirement = f"Style: {analysis['style']['tone']}, pacing: {analysis['style']['pacing']}"
```

#### 多维度对比

| 维度 | VideoAgent + ViMax | VideoAgent + agentcut |
|---|---|---|
| **接口匹配度** | ★★★★★ VideoAgent 输出 → ViMax `Script2Video` 直接消费 | ★★☆☆☆ 必须压缩为单一 prompt |
| **信息保留率** | 高：叙事结构、角色、风格、镜头规划全部传递 | 低：VideoAgent 分析大部分被 agentcut 重新覆盖 |
| **重复工作** | 无：职责分工清晰 | 有：两个组件都在规划叙事 |
| **角色/场景一致性** | ★★★★★ ViMax 内置 consistency 检查 + 参考图追踪 | ★★☆☆☆ agentcut 无一致性机制 |
| **视频生成质量** | 高，支持 MiniMax/Seedance/Kling/Google Omni | 中，仅 MiniMax/Hailuo |
| **同源性** | 同一研究组（HKUDS），设计理念完全一致 | 不同团队，数据格式需手工适配 |
| **集成复杂度** | 中：需要约 20 行格式转换代码 | 低：REST API 直接调用 |
| **项目成熟度** | ViMax 373 commits，Jul 2026 活跃 | agentcut ~30 commits，更新较少 |
| **MVP 速度** | 较慢（ViMax 环境配置较重） | **较快（FastAPI 一键启动）** |

#### 何时选 agentcut

agentcut 不是更差的选择，而是不同场景的选择：

- **适合**：允许 AI 自由发挥风格，VideoAgent 仅作灵感参考
- **适合**：2 天内快速跑通 MVP，先验证技术可行性
- **不适合**：需要严格复刻样例视频的叙事结构和视觉风格

#### 结论

> 本应用核心诉求是"参考样例视频 → 结构一致的新营销视频"。VideoAgent 负责深度理解，ViMax 负责高质量生成，二者是这个场景的**原生匹配**。agentcut 在此 pipeline 中会造成明显的信息断层。

### 5.3 多 Agent 编排框架对比

| 项目 | ⭐ Stars | 贡献者 | 最近更新 | 许可 | 架构 | 适合场景 |
|---|---|---|---|---|---|---|
| [HKUDS/ViMax](https://github.com/HKUDS/ViMax) | **11.2k** | 14 | Jul 2026 | MIT | Director+Screenwriter+<br>Producer+Generator | 完整长视频，叙事一致性强 |
| [calderbuild/agentcut](https://github.com/calderbuild/agentcut) | ~30 | 2 | 2025 | MIT | 6 Agent 串行+并行，SSE 流式进度 | 短营销视频，成本敏感 |
| [tapankumarpatro/openframe-ai](https://github.com/tapankumarpatro/openframe-ai) | 19 | 3 | Jul 2026 | Sustainable Use | 7 Agent，视觉画布，15+ 视频模型 | 时尚/奢侈品广告 |
| [SainathPattipati/ai-video-generation-pipeline](https://github.com/SainathPattipati/ai-video-generation-pipeline) | ~10 | 1 | 2025 | - | 概念→脚本→分镜→角色一致性→组装 | 角色出镜视频 |

**推荐：** ViMax 是当前最成熟的多 Agent 视频生成框架，与 VideoAgent 组合时接口天然匹配（见 5.2 节）。

### 5.4 HTML→视频渲染引擎对比

| 项目 | ⭐ Stars | 贡献者 | 最近更新 | 许可 | Agent 友好度 | 渲染方式 | 商用 |
|---|---|---|---|---|---|---|---|
| [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes) | **36k** | 20+ | Jul 2026 | Apache-2.0 | ★★★★★ 专为 Agent 设计 | Chromium+FFmpeg，确定性 | ✅ 免费 |
| [remotion-dev/remotion](https://github.com/remotion-dev/remotion) | **53.2k** | 150+ | Jul 2026 | 需公司许可 | ★★★★ React 生态 | Chromium+FFmpeg，支持 Lambda | ⚠️ 商用需购买公司许可 |
| [NovusGFX/RenderGarden](https://github.com/NovusGFX/RenderGarden) | 4 | 1 | Jul 2025 | - | ★★★ Python CLI | Puppeteer+MoviePy | ✅ |

| 维度 | HyperFrames | Remotion |
|---|---|---|
| 语言范式 | 原生 HTML/CSS/JS | React 组件 |
| LLM 代码生成质量 | 更高（HTML 是训练数据主体） | 较高（React 熟悉但需 API 知识） |
| 商用许可 | Apache-2.0，完全免费 | 需购买公司许可（$50/月起） |
| 批量渲染 | 本地 CLI，可容器化 | 支持 AWS Lambda 弹性扩容 |

**结论：** 对 AI Agent 生成场景，**HyperFrames 是首选**；若团队已有 React 基础且预算允许，Remotion 在复杂动画上更强。

### 5.5 参考实现分析

#### 以 "video storyboard" 搜索出的高 Star 项目

| 项目 | Stars | 技术栈 | 定位 | 适合本场景 |
|---|---|---|---|---|
| [LingyiChen-AI/AIComicBuilder](https://github.com/LingyiChen-AI/AIComicBuilder) | 高 | Next.js + SQLite + FFmpeg + Seedance 2.0 | 动漫/漫剧短视频生成 | ★★☆☆☆ |
| [waooAI/waoowaoo](https://github.com/waooAI/waoowaoo) | 高 | TypeScript，闭源 SaaS | 可控影视制作 Agent 平台 | ★☆☆☆☆ |
| [Forget-C/Jellyfish](https://github.com/Forget-C/Jellyfish) | 高 | FastAPI + React + MySQL + Redis | 品牌/电商故事性宣传视频 | ★★★☆☆ |

**AIComicBuilder**：流水线结构与本项目高度相似（剧本→角色提取→分镜→首尾帧→视频生成→合成），但输入为**文本剧本**（无参考视频分析），且风格固定为漫剧/动漫。

**waoowaoo**：SaaS 化平台，团队不接受外部 PR，无法程序化接入。

**Jellyfish**：三者中最有价值的发现。完整 FastAPI + OpenAPI/Swagger 文档，Docker Compose 一键部署，把角色/场景一致性作为一等公民，明确面向"品牌和电商团队"。致命短板同 AIComicBuilder：**从文本脚本出发，无参考视频理解入口**。可作为生成层备选替代 ViMax，但需自行实现 VideoAgent JSON → Jellyfish API 的适配层。

#### 端到端参考实现

| 项目 | Stars | 实际能力 | 能否超越 VideoAgent+ViMax |
|---|---|---|---|
| [danielrosehill/Claude-AI-Video-Producer-Plugin](https://github.com/danielrosehill/Claude-AI-Video-Producer-Plugin) | ~20 | Claude Code 交互式插件，每步需人工确认 | ❌ 不可自动化，无视频分析 |
| [coleam00/hyperframes-ai-video-generation](https://github.com/coleam00/hyperframes-ai-video-generation) | ~40 | HTML/CSS GSAP 动画模板，非真实 AI 视频 | ❌ 输出类型根本不同 |
| [aicontentskills/ai-video-storyboard-skill](https://github.com/aicontentskills/ai-video-storyboard-skill) | 24 | 单文件 SKILL.md，输出 markdown 文本计划 | ❌ 仅文本规划工具 |

三者均不构成对 VideoAgent+ViMax 的竞争：danielrosehill 依赖 human-in-the-loop；coleam00 本质是 Web 动画而非 AI 视频生成；aicontentskills 仅 2 commits，无生成能力。

#### 生成层选型汇总

| 方案 | 视频质量 | 部署复杂度 | 适用场景 |
|---|---|---|---|
| **ViMax**（推荐） | 高，AI 真实视频 | 中（需配置多个 LLM API） | 高质量创意营销视频 |
| **Jellyfish**（备选） | 中高，AI 真实视频 | 低（Docker Compose 一键） | 快速上线、品牌电商定制 |
| **HyperFrames**（备选） | 中，Web 动画渲染 | 低（本地 Chromium） | 批量模板化、近零成本 |

---

## 6. 推荐技术架构

### 6.1 整体架构图

Stage 1 共用 VideoAgent；Stage 2-4 由 `render_mode` 参数控制走哪条路径。

```
┌──────────────────────────────────────────────────────────────────┐
│                    clip-weave 系统架构（双路径）                    │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  输入：样例视频 (MP4/MOV) + 品牌素材包                            │
│        + render_mode: "vimax" | "hyperframes"                    │
│                                                                   │
│  Stage 1: 视频理解层  ←── HKUDS/VideoAgent        （共用）        │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │  Gemini：逐帧精细视觉理解（场景/角色/构图/色调）            │   │
│  │  Claude：Agentic Graph Router（意图解析+工作流规划）        │   │
│  │  GPT-4o：内容摘要、脚本重构、叙事结构识别                  │   │
│  │  输出: shots.json + style.json                             │   │
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
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 6.2 技术栈汇总

| 层级 | 组件 | 来源 | 路径 | 用途 |
|---|---|---|---|---|
| **视频理解** | VideoAgent | HKUDS/VideoAgent | 共用 | 样例视频分析 → shots.json |
| **素材搜索** | Pexels / Pixabay API | 免费 | 共用 | B-Roll 视频 + 图片素材 |
| **语音合成** | Kokoro TTS | hexgrad/kokoro | 共用 | 旁白音频生成（本地，免费） |
| **视频处理** | FFmpeg | 系统级 | 共用 | 关键帧提取、多比例转码、音频合并 |
| **AI 视频生成** | ViMax | HKUDS/ViMax | vimax | screenplay → 多镜头 AI 真实视频 |
| **底层生成模型** | Kling / Seedance / MiniMax | API | vimax | ViMax 调用的视频生成后端 |
| **HTML 渲染** | HyperFrames | heygen-com/hyperframes | hyperframes | HTML/CSS → MP4，Chromium 渲染 |

### 6.3 目录结构

```
clip-weave/
├── src/
│   ├── stage1_analyze.py        # VideoAgent 封装 + shots.json 输出（共用）
│   ├── renderers/
│   │   ├── vimax_renderer.py    # shots.json → screenplay → ViMax 生成
│   │   └── hf_renderer.py       # shots.json → HTML/CSS → HyperFrames 渲染
│   └── pipeline.py              # 入口，render_mode 参数分发
├── assets/
│   ├── brand/                   # 品牌素材包（Logo/配色/产品图/文案）
│   └── downloaded/              # Pexels/Pixabay 自动下载的素材
├── output/
│   ├── shots.json               # Stage 1 输出（共用）
│   ├── screenplay.txt           # vimax 路径中间产物
│   ├── compositions/            # hyperframes 路径中间产物
│   └── final.mp4                # 最终视频
├── vendors/
│   ├── VideoAgent/              # git submodule
│   ├── ViMax/                   # git submodule
│   └── hyperframes/             # git submodule
└── docs/
    └── ai-marketing-video-solution.md
```

Pipeline 入口示例：

```python
from src.stage1_analyze import analyze
from src.renderers.vimax_renderer import vimax_render
from src.renderers.hf_renderer import hyperframes_render
from typing import Literal

def run_pipeline(
    sample_video: str,
    brand_assets: dict,
    render_mode: Literal["vimax", "hyperframes"] = "vimax"
) -> str:
    shots = analyze(sample_video)           # 共用 Stage 1
    if render_mode == "vimax":
        return vimax_render(shots, brand_assets)
    else:
        return hyperframes_render(shots, brand_assets)
```

---

## 7. 实施路径

### Phase 1：视频理解 MVP（预计 1 周）

目标：给定样例视频，自动输出结构化 shots.json。

- [ ] 集成 DeepScene 或 VideoAgent，封装 Stage 1 接口
- [ ] 验证 FFmpeg 关键帧提取 + Gemini Flash 分析 pipeline
- [ ] 确认 shots.json 输出格式与 narrative_structure 识别准确率

**交付物：** `stage1_analyze.py` + 3 个样例视频的 shots.json 对比报告

### Phase 2a：HyperFrames 路径打通（预计 3 天）

目标：**先用 HyperFrames 快速验证叙事结构和文案**，成本接近零，可高频迭代。

- [ ] 实现 `hf_renderer.py`：shots.json → LLM 生成 HTML/CSS → HyperFrames 渲染
- [ ] 集成 Pexels/Pixabay API，实现素材自动搜索下载
- [ ] 集成 Kokoro TTS，生成旁白音频
- [ ] 验证 render_mode 参数分发逻辑

**交付物：** `render_mode="hyperframes"` 端到端可用，成本 ~$0.08/视频

### Phase 2b：ViMax 路径打通（预计 1.5 周）

目标：叙事结构验证满意后，接入 ViMax 生成高质量 AI 视频。

- [ ] 实现 `vimax_renderer.py`：实现 `videoagent_to_vimax_script()` 格式转换
- [ ] 集成 ViMax Script2Video 模式，完成首个端到端生成
- [ ] 对齐两条路径的输出接口（统一 output.mp4 规格）

**交付物：** `render_mode="vimax"` 端到端可用，两条路径均通过同一入口调用

### Phase 3：质量提升（预计 2 周）

目标：生成视频质量接近人工制作水准。

- [ ] 建立镜头模板库（hook/product/testimonial/cta 四类）
- [ ] 增加视频质量评估 Agent（自动评分循环）
- [ ] 实现多比例输出（9:16/16:9/1:1）
- [ ] 增加 AI 生成 B-Roll（Wan2.2 或 fal.ai）

### Phase 4：工程化（预计 1 周）

- [ ] 容器化（Docker）
- [ ] 批量处理 CLI（多品牌/多 SKU 并行）
- [ ] 人工审核 + 微调反馈循环

---

## 8. 成本估算

### 8.1 单视频生成成本（30s 营销视频）

| 环节 | 工具 | vimax 路径 | hyperframes 路径 |
|---|---|---|---|
| 样例视频分析（5min） | Gemini Flash + Claude Vision | ~$0.02 | ~$0.02 |
| 分镜重构 / HTML 生成 | Claude claude-sonnet-4-6 | ~$0.01 | ~$0.03 |
| 视频生成（4-8 镜头） | Kling / Seedance / MiniMax | ~$0.45–1.00 | $0 |
| HTML 渲染 | HyperFrames（本地） | $0 | $0 |
| 素材获取（Pexels/Pixabay） | 免费 API | $0 | $0 |
| TTS 旁白（Kokoro 本地） | 免费 | $0 | $0 |
| **单视频合计** | | **~$0.50–1.10** | **~$0.05–0.08** |

两者相差约 **10–15×**。vimax 路径输出 AI 真实影像；hyperframes 路径输出 Motion Graphics 动效。

### 8.2 月基础设施成本（3000 视频/月）

| 资源 | vimax 路径 | hyperframes 路径 |
|---|---|---|
| LLM API（分析+生成） | ~$90 | ~$150 |
| 视频生成 API（Kling/Seedance） | ~$1350–3000 | $0 |
| HyperFrames 渲染（本地） | $0 | $0 |
| Pexels / Pixabay API | $0 | $0 |
| 存储（100GB） | ~$2 | ~$2 |
| **月合计** | **~$1440–3090** | **~$152** |

---

## 参考链接

| 资源 | 链接 |
|---|---|
| VideoAgent 视频理解框架 | https://github.com/HKUDS/VideoAgent |
| ViMax 多 Agent 视频生成 | https://github.com/HKUDS/ViMax |
| DeepScene 分镜提取工具 | https://github.com/PhanTrongGiap/deepscene |
| HyperFrames HTML→MP4 渲染 | https://github.com/heygen-com/hyperframes |
| agentcut 6-Agent 参考实现 | https://github.com/calderbuild/agentcut |
| Jellyfish 品牌电商视频工作台 | https://github.com/Forget-C/Jellyfish |
| AIComicBuilder 动漫短视频生成 | https://github.com/LingyiChen-AI/AIComicBuilder |
| Pexels API 文档 | https://www.pexels.com/api/documentation/ |
| Pixabay API 文档 | https://pixabay.com/api/docs/ |
| Kokoro TTS（本地免费） | https://github.com/hexgrad/kokoro |
| Wan2.2 开源视频生成 | https://github.com/Wan-Video/Wan2.2 |
