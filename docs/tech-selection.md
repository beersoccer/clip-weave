# clip-weave 技术选型分析

> 文档版本：v2.0 | 更新日期：2026-07-20
> 本文档记录技术选型的分析过程与决策依据，最终架构方案见 `architecture.md`。

---

## 目录

1. [应用场景分析](#1-应用场景分析)
2. [四阶段 Pipeline 总览](#2-四阶段-pipeline-总览)
3. [样例视频分析方法论](#3-样例视频分析方法论)
4. [无版权素材来源](#4-无版权素材来源)
5. [开源项目选型分析](#5-开源项目选型分析)

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
    "pacing": "fast",
    "color_tone": "warm",
    "typography": "bold-sans",
    "transition": "cut",
    "aspect_ratio": "9:16"
  },
  "shots": [
    {
      "index": 1,
      "start": 0.0,
      "end": 2.5,
      "duration": 2.5,
      "type": "hook",
      "composition": "centered",
      "text_overlay": "痛点文案",
      "visual_element": "人物特写",
      "audio_cue": "节奏感强的背景音乐起"
    }
  ],
  "narrative_structure": "AIDA",
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

### 4.2 AI 生成素材（完全无版权风险）

| 用途 | 推荐工具 | 成本 |
|---|---|---|
| 产品场景图 | Flux Pro / SDXL（本地） | ~$0.01/张 或免费 |
| 背景视频 | Wan2.2（开源）/ Kling | $0（本地）/ $0.05/段 |
| 旁白音频 | Kokoro TTS（本地开源） | $0 |
| 背景音乐 | MusicGen（Meta，本地） | $0 |

---

## 5. 开源项目选型分析

### 5.1 视频理解层选型

共考察 6 个项目：

| 项目 | Stars | 许可 | 任务匹配 | 工程成本 | 运行成本 | 维护 | 总分 | 推荐 |
|---|---|---|---|---|---|---|---|---|
| mmaction2 | ~14k | Apache-2.0 | ★☆ | ★★ | ★★ | ★☆ | 6/20 | ❌ |
| SlowFast | 7.4k | Apache-2.0 | ★☆ | ★☆ | ★★ | ★☆ | 5/20 | ❌ |
| InternVideo3 | ~3k | MIT | ★★★ | ★★ | ★★ | ★★★★ | 11/20 | ⚠️ 有 GPU 时 |
| BroderQi/Storyboard | ~50 | - | ★★★★ | ★★★★ | ★★★★★ | ★★★ | 16/20 | ✅ 备选 |
| **DeepScene** | ~80 | MIT | ★★★★★ | ★★★★★ | ★★★★★ | ★★★ | **18/20** | ✅ **Stage 1 首选** |
| **VideoAgent** | 1.5k | MIT | ★★★★★ | ★★★★ | ★★★★ | ★★★★★ | **18/20** | ⚠️ **接口不匹配（见注）** |

**高 stars 项目（mmaction2 / SlowFast）不选的原因：** 输出是预定义动作分类标签（400 类），不能描述广告叙事结构；2022 年后停止维护；必须 GPU。

**最终决策：** 按 DeepScene 方式自行实现（FFmpeg 帧提取 + LLM 多模态分析），内置于 `adapters/video_analyzer.py`，无需引入外部库。

> ⚠️ **VideoAgent 注：** VideoAgent 采用的技术路径（FFmpeg + Gemini 分析）与本项目一致，因此功能评分高。但其架构是交互式多 Agent 系统（入口为 `input("User Requirement:")`），无法以函数调用方式直接输出 shots.json，不适合作为 Python 库集成。Stage 2b（ViMax 路径）同样采用 HKUDS 生态，但 ViMax 是独立的生成框架，接口完全不同。

#### 源码对比后的借鉴点

对 DeepScene（shell 脚本）和 Storyboard（.NET 桌面 GUI）做了源码级分析，`video_analyzer.py` 在任务匹配度（内容感知场景检测 vs 均匀采样、营销专项 schema）和可嵌入性上均已超越两者。以下字段值得在后续阶段引入：

**Phase 2b（ViMax 接入）时扩充到 `Shot` schema：**

| 字段 | 来源 | 用途 |
|---|---|---|
| `reconstruction_prompt` | DeepScene | 每镜头的自然语言重创意描述，直接作为 ViMax/Kling prompt |
| `uncertainties` | DeepScene | LLM 对该镜头分析不确定的项，用于人工审核和质量评估 |
| `first_frame_prompt` | Storyboard | 首帧图像生成 prompt，供 Kling/Seedance 的 image2video 模式 |
| `last_frame_prompt` | Storyboard | 末帧图像生成 prompt，控制镜头出点 |
| `video_prompt` | Storyboard | 该镜头的视频生成 prompt（动作/摄影机运动综合描述） |
| `camera_movement` | Storyboard | 摄影机运动方式（push in / pull out / pan / static 等） |

**备用分析策略（复杂场景准确度提升）：** DeepScene 的两步法——先让 LLM 自由叙述每帧内容，再对叙述结果做结构化提取——对镜头内容复杂的视频比 clip-weave 当前的单步结构化调用更准确。可作为 `video_analyzer.py` 的 `--two-pass` 模式备选。

### 5.2 生成层 Pipeline：ViMax vs agentcut

Stage 1 输出 `ShotsOutput`（结构化富内容：shots + style + narrative_structure）。Stage 2b 选哪个生成框架接收它？

- **agentcut** 接口只接收单一 prompt，ShotsOutput 大部分信息被丢弃，Director Agent 会从头重新规划
- **ViMax `Script2Video`** 直接消费 screenplay 格式，ShotsOutput 可通过约 20 行胶水代码转换为 ViMax 入参，信息无损传递

| 维度 | ShotsOutput + ViMax | ShotsOutput + agentcut |
|---|---|---|
| 接口匹配度 | ★★★★★ | ★★☆☆☆ |
| 信息保留率 | 高 | 低（被重新覆盖） |
| 角色/场景一致性 | ★★★★★ | ★★☆☆☆ |
| MVP 速度 | 较慢 | **较快** |

**结论：** 核心诉求是"参考样例 → 结构一致新视频"，ShotsOutput + ViMax 是原生匹配。agentcut 适合允许 AI 自由发挥、2 天内跑通 MVP 的场景。

### 5.3 HTML→视频渲染引擎

| 项目 | Stars | 许可 | Agent 友好度 | 渲染方式 | 商用 |
|---|---|---|---|---|---|
| **HyperFrames** | 36k | Apache-2.0 | ★★★★★ | Chromium+FFmpeg，确定性 | ✅ 免费 |
| Remotion | 53.2k | 需公司许可 | ★★★★ | Chromium+FFmpeg+Lambda | ⚠️ $50/月起 |

**结论：** AI Agent 生成场景首选 HyperFrames（专为 Agent 设计，免费）；团队有 React 基础且预算充足时可选 Remotion。
