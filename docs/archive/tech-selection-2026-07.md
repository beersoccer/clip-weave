# clip-weave 技术选型分析（历史记录，2026-07）

> 本文包含已失效的阶段划分、模型比较、价格和“远期”判断，不代表当前方案。当前决策见 [架构](../architecture.md) 与 [生产质量流程](../production-quality-loop.md)。

> 文档版本：v6.0 | 更新日期：2026-07-27  
> 最终架构方案见 `architecture.md`

---

## 目录

1. [应用场景与工具分工](#1-应用场景与工具分工)
2. [三阶段方案总览](#2-三阶段方案总览)
3. [渲染引擎：HyperFrames](#3-渲染引擎hyperframes)
4. [模板库：hyperframes-launches](#4-模板库hyperframes-launches)
5. [Phase 2 文生视频层：Kling / Veo](#5-phase-2-文生视频层kling--veo)
6. [Phase 3 生成层：ViMax（远期）](#6-phase-3-生成层vimax远期)
7. [被排除方案](#7-被排除方案)
8. [无版权素材来源](#8-无版权素材来源)

---

## 1. 应用场景与工具分工

给定品牌素材包（logo / 色板 / 产品图 / 文案），自动生成风格一致的营销视频。

| 内容类型 | 工具 | 理由 |
|---------|------|------|
| 品牌文字、数字、数据图表 | HyperFrames | 代码级精度，100% 可控 |
| Kinetic type / 产品动效 | HyperFrames | 成熟动效语法（GSAP），lint 验证 |
| 网站截图 / 产品图叠加层 | HyperFrames | capture 抓取后直接使用 |
| 写实动态画面（汽车行驶/城市/自然）| Kling / Veo（Phase 2）| HF 无法生成真实画面 |
| 真人出镜 | HeyGen 主平台 avatar | 独立产品，不在此路径 |

**核心边界**：HyperFrames 是 HTML 渲染引擎，它能精确还原设计，但不能凭空生成写实画面。
任何期望"LLM 生成电影级视觉"的需求都应通过文生视频模型满足，而非 HF。

---

## 2. 三阶段方案总览

| | Phase 1（v6.0，当前）| Phase 2（验证）| Phase 3（远期）|
|---|---|---|---|
| **输入** | 用户对话 / URL / 本地文件 / BRIEF.md | 品牌素材 + Kling API | 品牌素材 + ViMax |
| **核心技术** | clip-weave 前置门面（Intent Router + Asset Matcher + Rule Guard）+ HF 全链路 | HF 故事线 + 文生视频 + FFmpeg | HF + ViMax screenplay |
| **输出风格** | Motion Graphics（动效图形）| 动效 + 写实混合 | 全 AI 真实影像 |
| **成本/视频** | ~$0.05 | ~$1–5 | ~$5–15 |
| **制作时间** | 30–60 分钟 | 30–60 分钟 | 20–40 分钟 |
| **状态** | ✅ 已完成（P0–P2 全部交付）| 🔲 验证目标 | 🔲 远期规划 |

---

## 3. 渲染引擎：HyperFrames

**最终选定**：heygen-com/hyperframes（Apache-2.0）

### 3.1 选型对比

| | HyperFrames | Remotion |
|---|---|---|
| **Stars** | 36k | 53k |
| **许可** | Apache-2.0 | 公司使用需 $50/月起 |
| **Agent 友好度** | ★★★★★（专为 Agent 设计）| ★★★★ |
| **技术栈** | 原生 HTML/CSS/GSAP | React + TypeScript |
| **LLM 生成质量** | 更高（HTML 是 LLM 训练数据主体）| 中（JSX 复杂度更高）|
| **内置资产** | 109 registry blocks + 19 skills | 无 |

### 3.2 HyperFrames 工作流的实测问题与对策

基于 xiaomi-su7 项目的实践总结（`docs/xiaomi-su7-video-production.md` §三）：

| 问题 | 根因 | 对策（v7.0 实现，按 HF 源码核对后收缩）|
|------|------|------|
| 30min/composition + 多轮 lint | 框架规则密集，LLM 每次需重读 | **Rule Guard** Python 装配前预检（<1s）拦截 `media_in_subcomposition`（HF lint 装配前跑不了的那条）；其余原设想的规则已核对删除，见下 |
| 素材利用率低（134 张用 2 张）| 无结构化素材输入，LLM 随机选 | **Asset Matcher** Vision 增强 + Embedding/BM25 匹配，为每个 beat 填充打分的 top-K 候选 |
| 媒体文件无法在子合成中使用 | `media_in_subcomposition` 规则 | Rule Guard 自动检测并报告；视频/音频只放 index.html |

### 3.3 关于「4 条框架规则」的历史结论已核对纠正

早期版本的本文档在此列出 4 条被认为「HF 特有、需要预注入 prompt」的规则。核对
`/Users/beersoccer/workspace/hyperframes` 源码后，结论改变：

| 规则 | 结论 |
|------|------|
| `media_in_subcomposition` | 真实存在，HF lint 已有 error 级实现，但装配前与单文件入口两个窗口失效 —— clip-weave 的 Rule Guard 因此保留这一条 |
| `gsap_css_transform_conflict` | HF lint 用 acorn AST 解析器实现，比本文档设想的"改用 xPercent/yPercent"简单描述更完整（还处理标签位置、`from`/`fromTo` 豁免等），交给 HF 原生，不重造 |
| `gsap_timeline_set_initial_hide` | **本文档原表述是错的，方向恰好相反。** HF 真实规则警告的是 timeline **内部** position 0 的零时长 `tl.set()`，并明确豁免 timeline **外** 的 `gsap.set()`。旧表述「必须在 timeline 外调用」与 HF 实际告警的写法正好一致，等于把 HF 要警告的模式当成了正确做法 |
| `preserve-3d + filter` | HF lint 中无此规则；判定需要完整 CSS 级联与祖先链解析，Python 正则层做不到可靠判定，交给 HF 3D 镜头文档里内联的约束 |

完整核对记录与源码引用见 `docs/architecture.md` § 3.1。

---

## 4. 模板库：hyperframes-launches

> **v6.0 变更**：`vendors/hyperframes-launches` 已从本 repo 移出（减小 clone 体积）。  
> 参考实现位于 `~/workspace/hyperframes-launches`，也可直接访问 https://github.com/heygen-com/hyperframes-launches。

**heygen-com/hyperframes-launches** 是 HyperFrames 官方生产级模板集合，每套均通过 CI 验证。

### 4.1 可用模板

| 模板 | 适用场景 | 核心特征 |
|------|---------|---------|
| product-launch | 品牌/产品发布（主力模板）| 窗口揭晓→锁定→step cards→收尾 |
| software-demo | SaaS / 工具演示 | UI 截图叠加 + feature 卡片序列 |
| texture-launch | 视觉驱动型 | 表达性文字 + shader 背景 |
| website-to-hf | 网站宣传 | capture 截图 + agent 自动流程 |

### 4.2 模板驱动的价值

| 原有方式 | 模板填充方式 |
|---------|------------|
| 空白 HTML，LLM 自由发挥设计 | 已验证骨架，LLM 只做品牌替换 |
| `visual_element: "沙漠地面"` → CSS 画沙漠 | `design_note: "全屏暗背景 + 白色 hero 字从下入场"` |
| 产品图未注入，凭空创作 | base64 / 绝对路径内嵌每帧 `<img>` |
| 30min/composition，3 轮 lint | 目标 15min/composition，≤2 轮 lint |

**frame.md 设计系统**（每套模板内置）提供视频原生设计 token：
- Typography：hero type 92px / weight 700，subtitle 24px，caption 16px  
- Motion：entrance duration、exit overlap、dwell timing  
- Color：品牌色直接映射为 CSS custom properties  

---

## 5. Phase 2 文生视频层：Kling / Veo

### 5.1 使用场景与定位

Phase 2 中文生视频模型**只负责写实动态镜头**，不替代 HF 的文字/动效层：

```
写实场景（汽车行驶、城市、内饰特写）→ Kling image-to-video
品牌文字 / 数字 / step cards / endcard  → HyperFrames HTML（保持精度）
FFmpeg 合流 → 最终 MP4
```

### 5.2 模型选型

| | Kling 3.0 | Google Veo 3.1 | Sora 2 |
|---|---|---|---|
| **价格** | ~$0.11–0.14/s（Pro）| ~$0.35/s | ~$0.13/s |
| **image-to-video** | ✅ 强（产品一致性高）| ✅ | ✅ |
| **运动/摄影控制** | ★★★★★（高速运动最佳）| ★★★★（物理最准确）| ★★★★ |
| **音频生成** | ✅ 原生 | ✅ 原生 | ❌ 无 |
| **可用性** | ✅ API 稳定 | ✅ Google AI Pro | ⚠️ 通过 ChatGPT |
| **推荐场景** | 汽车/产品动态镜头 | 精准物理/自然场景 | 叙事性画面 |

**Phase 2 首选 Kling**：image-to-video 质量最高，适合用产品图作起始帧，API 稳定。

### 5.3 成本估算（以 30s 视频为例）

设写实镜头占比 40%（12s），其余为 HF 动效层：

| 模型 | 写实层成本 | HF 层成本 | 合计 |
|------|---------|---------|------|
| Kling 3.0 Pro | 12s × $0.14 = $1.68 | $0.03 | **$1.71** |
| Veo 3.1 | 12s × $0.35 = $4.20 | $0.03 | **$4.23** |
| 纯 HF | — | $0.05 | **$0.05** |

**决策阈值**：若 Kling 混合方案主观质量评分 ≥ 纯 HF +2 分（10 分制），$1.71 的增量成本是合理的。

---

## 6. Phase 3 生成层：ViMax（远期）

接入 HKUDS/ViMax（screenplay → Kling/Seedance/MiniMax → AI 真实影像全流程）。

**触发条件**：Phase 2 验证通过 + 有完全写实影像（无动效覆盖层）的需求场景。

- `STORYBOARD.json → ViMax screenplay` 转换约 20 行映射函数，信息无损
- 输出 AI 真人/实景风格，成本 ~$5–15/视频（比 Phase 2 高 3–8×）

---

## 7. 被排除方案

> 保留研究记录，避免将来重复纳入研究目标。

### 7.1 OpenMontage（calesthio/OpenMontage，~40k stars）

**研究结论**：工具链设计优秀，但与 clip-weave 的集成路径不兼容；核心设计理念已被吸收。

**工具链结构（源码验证）：**

| 工具文件 | 实现 | 输出 |
|---------|------|------|
| `video_analyzer.py` | BaseTool，深度：transcript_only / standard / deep | 编排下列工具，输出 VideoAnalysisBrief JSON |
| `scene_detect.py` | PySceneDetect（ContentDetector / AdaptiveDetector）+ FFmpeg 回退 | 场景边界列表，代码层（非 LLM）|
| `frame_sampler.py` | FFmpeg，策略 interval / count / scene_guided | keyframes/ 目录 + 时间戳列表 |
| `transcriber.py` | faster-whisper，字级时间戳 + 语言检测 | {segments, word_timestamps, language} |
| `transcript_fetcher.py` | youtube-transcript-api | YouTube caption 直取 |
| `video-reference-analyst.md` | Agent skill | LLM 5-Aspect 结构化输出 |

**VideoAnalysisBrief 关键字段（`schemas/artifacts/video_analysis_brief.schema.json`）：**

```json
{
  "content_analysis": {
    "tone": "cinematic|dramatic|inspirational|corporate|...",
    "hook_technique": "...",
    "call_to_action": "..."
  },
  "structure_analysis": {
    "pacing_profile": { "cuts_per_minute": 53.3, "pacing_style": "rapid_fire" },
    "scenes": [{ "narration_text": "...", "visual_type": "b_roll|text_card|product_shot|..." }]
  },
  "replication_guidance": "如果要做类似视频的导演级操作指令"
}
```

**4 个有价值的设计，已吸收到 STORYBOARD.json 规范中：**

| # | 特性 | 吸收方式 |
|---|------|---------|
| 1 | 两阶段分析（FFmpeg 结构 + LLM 视觉理解）| clip-weave 中代码层提取 + LLM 语义 |
| 2 | `narration_text` 字级时间戳绑定 | STORYBOARD.json 的 `narration_text` 字段 |
| 3 | `visual_type` enum + `pacing_style` 代码分类 | STORYBOARD.json 的 `visual_type` 字段 |
| 4 | `replication_guidance` 导演指令 | STORYBOARD.json 顶层字段 |

**不直接使用的原因：**
- 工具是 `BaseTool` 子类，由 AI agent 调用驱动，不能作为 Python 库 `import`
- `VideoAnalysisBrief` 格式与 clip-weave pipeline 不兼容，需重写

**被排除的具体原因：** clip-weave 不再以"输入样例视频 → 分析叙事 → 复制"作为主路径，
改为"模板选择 + 品牌素材填充"，消除了对视频分析层的依赖。

---

### 7.2 其他被排除方案

| 方案 | 排除原因 |
|------|---------|
| **VideoAgent**（HKUDS）| 交互式多 Agent 系统（入口为 `input("User Requirement:")`），不能函数调用；ViMax 是其架构下的正确替代 |
| **Remotion 生态** | React/JSX 技术栈，与 HyperFrames HTML 渲染不兼容；HF registry 已覆盖同等能力，且 Apache-2.0 无商用成本 |
| **agentcut** | 接口只接收单一 prompt，VideoAnalysisBrief 大量结构化信息被丢弃 |
| **mmaction2 / SlowFast** | 输出是预定义动作分类标签（400 类），不能描述广告叙事；2022 年后停止维护，强依赖 GPU |
| **InternVideo3** | 能力覆盖，但当前无 GPU 环境；有 GPU 时可重新评估 |
| **DeepScene** | Shell 脚本封装，输出无法直接对接 clip-weave pipeline |
| **Sora（文生视频）** | 无原生 API（通过 ChatGPT 访问），image-to-video 质量弱于 Kling，不适合批量生产调用 |

---

## 8. 无版权素材来源

| 平台/工具 | 限制 | 用途 |
|---------|------|------|
| **Pexels** | 无商用限制 | 人物/场景 B-Roll |
| **Pixabay** | 无商用限制，无需署名 | 背景/自然素材 |
| **Mixkit** | 完全免费，含 4K | 高质量转场/背景 |
| **Coverr** | 商用可用，无需署名 | 商业场景视频 |
| **Kokoro TTS**（本地开源）| $0 | 旁白音频生成 |
| **MusicGen**（Meta，本地）| $0 | 背景音乐生成 |
