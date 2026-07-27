# HyperFrames 深度分析

> 2026-07-24 | 基于 vendors/hyperframes/ 源码（packages/ + skills/）全量阅读

---

## 1. 系统定位

**一句话：把 HTML 文件渲染成 MP4 视频的框架，专门为 AI agent 设计。**

制作视频的传统工具（AE、Premiere）要人拖时间轴，AI 没法直接操作。
HyperFrames 换了一种思路：用 HTML + CSS + GSAP 写动画，AI 最擅长写 HTML，
再用 Chrome 的帧捕获接口（BeginFrame API）把每一帧截成图，最后 FFmpeg 合成 MP4。

---

## 2. 渲染引擎原理

### 2.1 可寻址帧协议

渲染引擎（`packages/engine/`）的核心是"可寻址 Web 页面到视频"模型：

```
Chrome CDP (headless-experimental BeginFrame API)
    │  接管时钟，想渲染哪帧就渲染哪帧
    ▼
window.__hf.seek(timeSeconds)         # 框架向页面注入时间
    │
    ▼
window.__timelines["<id>"].seek(t)    # GSAP timeline 被 seek 到任意时间点
    │
    ▼
FrameCapture → FFmpeg                 # 截图序列 → MP4
```

关键约束：**每帧必须从时间值独立复现（Deterministic）**。
- 禁止 `Date.now()`、`performance.now()`、`Math.random()`（非 seed）
- 禁止 `repeat: -1`（无限循环）—— 渲染器无法推算帧数
- 禁止 `setTimeout`、`requestAnimationFrame`、`Promise` 内建 timeline
- 禁止在页面加载时 `gsap.set()` 后面场景的 clip 元素（那些 clip 在页面加载时不在 DOM 里）

### 2.2 GSAP Timeline 注册协议

```javascript
// 每个合成必须有且仅有一个 paused timeline，synchronously 注册
window.__timelines["<composition-id>"] = gsap.timeline({ paused: true });
// key 必须等于 root 元素的 data-composition-id
// data-duration 设置渲染总时长，timeline 长度不控制渲染
```

非 GSAP 运行时（CSS animations、WAAPI、Lottie、Three.js）也支持，
但 Three.js 无法自动推断时长 —— **必须**手动设置 `data-duration`。

### 2.3 合成模型

```html
<!-- 独立合成：root 直接在 <body>，禁止 <template> 包裹 -->
<div data-composition-id="hero" data-duration="5">
  <div class="clip" data-track-index="0" data-time-in="0" data-time-out="5">
    <!-- 场景内容 -->
  </div>
</div>

<!-- 子合成：root 必须在 <template> 内 -->
<template>
  <div data-composition-id="cta-overlay" data-duration="3">...</div>
</template>
```

**最容易触发 silent bug 的三条规则（自动化检查可能漏掉）：**
1. Root 必须有明确 px 尺寸（`width`/`height`），否则内容塌陷到左上角
2. 全屏背景必须放在 `position:absolute; inset:0` 的子 clip 里，**不能**设在 `#root` 上（渲染器会丢掉 root 的 background，Preview 看起来正常但渲染出来是黑色）
3. 整个 assembled page 内 `id` 不能重复（跨文件的 `<video id="xxx">` 重复会渲染成空白）

---

## 3. CLI 命令全览

```bash
# 脚手架
npx hyperframes init <dir> [--non-interactive --example=blank]  # 初始化项目
npx hyperframes capture <URL> [-o ./capture]                    # 抓素材/token/描述
npx hyperframes add <block-name>                                # 安装 registry 组件
npx hyperframes skills update [workflow-name]                   # 更新 skills

# 验证（重要：lint 是 check 的子集）
npx hyperframes lint                                            # 静态检查，快（无 Chrome）
npx hyperframes check [file] [--json] [--snapshots] [--samples N] [--at t1,t2]  # 完整门控
npx hyperframes snapshot --at t1,t2,t3                          # 截关键帧

# 预览与渲染
npx hyperframes preview [--port N]                              # Studio 热重载
npx hyperframes render [--quality high] [--output out.mp4]      # 本地渲染
npx hyperframes render --batch rows.json                        # 批量变量渲染
npx hyperframes cloud render                                    # HeyGen 云端渲染
npx hyperframes lambda render <project>                         # AWS Lambda 渲染
npx hyperframes cloudrun render <project>                       # GCP Cloud Run

# 音频
npx hyperframes tts --script SCRIPT.md                          # TTS 语音生成
npx hyperframes transcribe --audio track.mp3                    # 语音转写（Whisper）

# 其他
npx hyperframes auth status                                     # 查看登录状态
npx hyperframes doctor [--json]                                 # 环境诊断
npx hyperframes remove-background <image>                       # 背景移除（云 API）
npx hyperframes upgrade --project . --check                     # 检查 CLI pin 版本
```

### 3.1 lint vs check 的关键差异

| | `lint` | `check` |
|--|--------|---------|
| 速度 | 快（纯静态分析）| 慢（10-30s，需启动 headless Chrome）|
| 检查内容 | HTML 结构、data-* 属性、track 重叠、GSAP/CSS 冲突、未注册 timeline | lint 的全部 + JS 运行时错误 + 布局溢出/遮挡 + motion.json 断言 + WCAG 对比度 |
| 盲点 | **media_in_subcomposition**（显式盲点，文档标注）| 3s+ 静态合成会报 `sweep_static` 错误 |
| 增量支持 | ✓ `lint ./path` | ✓ **`check <file>`**（只检查变更文件，未变更跳过）|
| JSON 输出 | ✓ `--json` | ✓ `--json` → `{ok, lint, runtime, layout, motion, contrast}` |

**lint 的已知盲点（官方文档明确标注，需要手动 grep）：**
```bash
# media_in_subcomposition 规则 lint 检测不到，必须手动检查
grep -nE '<(video|audio)\b' compositions/*.html
# 期望：无匹配（media 应在 index.html 的 root 直接子元素）
```

---

## 4. 完整创作流程（以 product-launch-video 为基准）

> 各 workflow 的步骤基本一致，只有 Step 1（素材来源）和 Step 4（视觉设计细节）有差异。

| 步骤 | 负责方 | 产出物 | 关键 CLI / 脚本 |
|------|--------|--------|-----------------|
| **Step 0 Setup** | 工作流 | `hyperframes.json`, `BRIEF.md` | `npx hyperframes init` |
| **Step 1 Capture** | 工作流 | `capture/` | `npx hyperframes capture <URL>` |
| **Step 2 Design System** | 工作流 | `frame.md`, `.hyperframes/caption-skin.html` | `node scripts/build-frame.mjs --preset <name> --hyperframes .` |
| **Step 3 Storyboard** | 工作流（orchestrator）| `STORYBOARD.md`, `SCRIPT.md` | （LLM 写文件）|
| **Step 3.1 Audio** | 工作流（后台）| `audio_meta.json` | `node scripts/audio.mjs --provider heygen` |
| **Step 4 Visual Design** | 工作流（orchestrator）| enriched `STORYBOARD.md`, `assets/` | `node scripts/stage-assets.mjs` |
| **Step 5 Build Frames** | **并行子 agent**（每帧一个）| `compositions/frames/NN-*.html`, `index.html` | `node scripts/frame-packets.mjs` |
| **Step 5b Captions** | 工作流（后台）| `caption_groups.json` | `node scripts/captions.mjs build` |
| **Step 6 Finalize** | 工作流 | `renders/video.mp4` | `lint` → `check` → `snapshot` → `render` |

### 4.1 capture/ 目录结构（精确）

```
capture/
├── assets/                          ← 图片、视频、字体（原始素材）
└── extracted/
    ├── tokens.json                  ← { title, description, colors[], fonts[] }
    ├── visible-text.txt             ← 页面文字内容
    ├── animations.json              ← 原网站动画信息
    └── asset-descriptions.md        ← 每张图的 AI 文字描述（需 Gemini/OpenRouter key）
```

### 4.2 并行子 agent 机制（关键架构细节）

Step 5 是整个 pipeline 最耗时的步骤。HF 通过 `frame-packets.mjs` 实现并行：

1. 为每个 storyboard frame 生成一个**自包含 packet**（`.hyperframes/frame-packets/` 目录）
2. 每个 packet 只包含该 frame 需要的内容：storyboard block + blueprint 完整代码 + 引用的 rule recipes（全部内联）
3. 同时生成 `_role.md`（`frame-worker-core.md` + 工作流特定的 `sub-agents/frame-worker.md`）
4. 每个子 agent 只看自己的 packet + `frame.md`，**从不打开** `STORYBOARD.md` 或 skill 文档
5. 各子 agent 只能写 `compositions/frames/NN-*.html`，写完后 orchestrator 标记该 frame 为 `animated`

这个机制的意义：**每个子 agent 有完整上下文但 context 窗口极小**，并行执行，减少遗忘风险。

### 4.3 motion.json sidecar（质量保证工具）

在 composition 旁边放一个 `*.motion.json` 文件，`check` 会自动发现并验证：

```json
{
  "duration": 6,
  "assertions": [
    { "kind": "appearsBy", "selector": "#headline", "bySec": 0.5 },
    { "kind": "before", "a": "#headline", "b": "#cta" },
    { "kind": "staysInFrame", "selector": ".card" },
    { "kind": "keepsMoving", "withinSelector": ".scene" }
  ]
}
```

这是检测"渲染 vs Preview 不一致"bug 的唯一自动化代理（渲染器抓帧的时机和 Preview 播放不同）。

---

## 5. BRIEF.md：无对话执行的关键

`BRIEF.md` 是 intent interview 的产出物，存在时工作流**不再问任何问题**。

### 5.1 mode 推导规则

| `flow` | `storyboard` | 推导的 `mode` |
|--------|-------------|-------------|
| `companion` | 任意 | `collaborative`（在 `/general-video` 执行）|
| `automation` | `yes` | `collaborative` |
| `automation` | `no` | **`autonomous`**（clip-weave 目标模式）|

### 5.2 BRIEF.md 完整格式

```yaml
---
workflow: product-launch-video    # 10 个 workflow 之一
flow: automation                  # automation | companion
storyboard: no                    # yes | no
message: "小米 SU7 好看·好开·舒适·安全"
destination: social-feed          # 决定 aspect
aspect: 1920x1080                 # 从 destination 推导
language: zh
length: 30s
---

## Intent
面向潜在买家的品牌宣传视频。主打颜值和驾驶体验，节奏明快。

## Assets
capture/assets/0-1-1.jpg — 主视觉图，用作首帧和关键场景背景

## Customizations
- 使用品牌色 #0A0C10 作为背景，#238AFF 作为强调色

## Notes
不要真人出镜。所有文字使用白色或品牌蓝。
```

### 5.3 checkpoint gate 行为

| Gate 类型 | Collaborative（storyboard:yes）| Autonomous（storyboard:no）|
|-----------|-------------------------------|-----------------------------|
| 偏好选择（preset/voice）| 询问 | 自行决定并说明理由 |
| 检查点（plan/sketch/render）| 暂停等待 | 发送 heads-up 后继续 |
| Quality gate（lint/check）| 遇错停止 | 遇错停止（一样严格）|
| **渲染** | 询问 | 询问（两种模式都要用户确认）|

---

## 6. Skills 系统架构

Skills 是纯 Markdown 指令文件（不是代码），安装后放在 agent 的知识库里，
告诉 Claude 「遇到这类需求，按这个流程做」。**实际执行的是 Claude 本身**，CLI 是工具，Skills 是操作手册。

```bash
npx hyperframes skills update                           # 默认更新 core set（workflow 按需安装）
npx hyperframes skills update <workflow-name>           # 更新单个 workflow
npx skills add heygen-com/hyperframes --full-depth      # 手动安装（必须加 --full-depth）
```

**三层结构：**

```
/hyperframes（入口路由，mandatory first read）
    │  state 表 → 决定走 intent interview 还是直接执行
    │  routing 表 → 映射请求到具体 workflow
    ▼
10 个 Workflow Skills（端到端编排器）
    │  每个 workflow 独立执行，互不干扰
    │  需要某种能力时加载对应的 domain skill
    ▼
8 个 Domain Skills（原子能力，按需加载）
```

**关键规则：`/hyperframes` 是强制入口**，任何"制作视频"请求都必须先读它，
才能判断当前 state（是否已有 BRIEF.md、是否已有 project、是否需要 intent interview）。

### 6.1 10 个 Workflow Skills

| Workflow | 输入 | 适合什么 | 时长甜区 | 特点 |
|----------|------|---------|---------|------|
| `product-launch-video` | URL 或文字 brief | 产品/品牌宣传视频、网站展示 | 30–90s | 最完整的 7 步流程；支持 no-capture 模式 |
| `faceless-explainer` | 文字/文章/笔记 | 解说视频，无真人，视觉完全 AI 发明 | 30–90s | 无 capture 步骤；创意完全由 LLM 生成 |
| `motion-graphics` | 用户供内容或搜索 | 短动效（kinetic type/stat/chart/logo/lower-third/地图）| <10s（最多~30s）| 自主模式 by design；无配音；可输出透明 WebM |
| `general-video` | 任意 | 所有其他视频；companion 模式 co-creation | 任意 | fallback；flow:companion 必走此路 |
| `slideshow` | 演示内容 | 可导航交互式 deck（**非 MP4**）| — | 用 `present` 命令；不输出视频 |
| `music-to-video` | 音频文件 | 节拍同步视频，音乐驱动节奏 | — | 节拍网格决定剪辑点 |
| `pr-to-video` | GitHub PR URL | 代码变更解说视频 | 30–90s | changelog/feature reveal |
| `embedded-captions` | 现有视频 MP4 | 加字幕（footage 不动）| — | 输出同一段视频+字幕层 |
| `talking-head-recut` | 现有采访/播客 MP4 | 加设计覆盖层（lower-thirds/数据卡）| — | footage 不动，只加图形层 |
| `remotion-to-hyperframes` | Remotion React 源码 | 迁移 React 组件到 HF | — | 单向迁移 |

**motion-graphics 的子分类（决定 asset 策略）：**

| 分类 | 触发时机 | 是否需要搜索 |
|------|---------|-------------|
| `kinetic-type` | 打字/引言/标题 | ❌ 用户提供内容 |
| `stat` | 单数字 count-up | ❌ |
| `charts` | 柱/线/饼图 | ❌ |
| `logo-reveal` | logo sting | ❌ 用户提供 logo |
| `lower-thirds` | 名称条/callout | ❌ |
| `maps` | 地图动效 | ❌ |
| `webpage` | 网页/UI 动画 | ✓ 搜索网页 |
| `news` | 新闻标题动效 | ✓ 搜索新闻 |
| `tweet` | 推文动效 | ✓ 搜索推文 |
| `asset-fusion` | 真实图片融入图表 | ✓ 搜索图片 |

### 6.2 8 个 Domain Skills

| Domain Skill | 提供什么能力 | 何时加载 |
|-------------|------------|---------|
| `hyperframes-core` | 合成 HTML 规范：data-* 属性、class="clip"、tracks、sub-compositions、determinism 规则、STORYBOARD/SCRIPT 格式、brief contract | 写任何合成 HTML 之前 |
| `hyperframes-animation` | 动效知识库：atomic motion rules（可组合）、multi-phase blueprints（场景模板）、transitions、7 种运行时适配器（GSAP/Lottie/Three.js/Anime.js/CSS/WAAPI/TypeGPU）| 涉及动效时 |
| `hyperframes-keyframes` | seek-safe 关键帧写法：GSAP timeline、CSS keyframes、SVG 变形/描边、3D 深度；`hyperframes keyframes` 诊断工具 | 复杂关键帧 |
| `hyperframes-creative` | 非动效创意方向：frame.md/design.md 处理、调色板、字体、叙事、beat 节奏规划、音频响应 | 设计决策 |
| `hyperframes-cli` | CLI 所有命令完整用法（init/capture/check/render 等）| 任何 CLI 操作 |
| `hyperframes-registry` | 50+ 预制组件的安装（`npx hyperframes add <block>`）和用法 | 复用现有组件 |
| `media-use` | 媒体 OS：BGM/SFX/图片/logo/TTS/转写/背景移除；`audio.mjs` 统一音频引擎；`.media/manifest.jsonl` 追踪溯源 | 任何媒体资产 |
| `figma` | 从 Figma 导入素材、design tokens、组件、storyboard 帧（REST + MCP）| Figma 来源 |

---

## 7. HF 特有规则（**含纠错**）

> 这些规则不在通用 Web 文档里，LLM 长会话后容易遗忘。
> ⚠️ 标注处为旧版文档的错误描述，以下为基于源码的正确版本。

| 规则 ID | 正确描述 | lint 能检测？ | 错误描述（旧版）|
|---------|---------|------------|---------------|
| `media_in_subcomposition` | `<video>`/`<audio>` 必须是 `index.html` 根节点的**直接子元素**（不能在 sub-composition 的 `<template>` 或任何包装 div 里）| ❌ **lint 盲点**，需手动 grep | — |
| `gsap_css_transform_conflict` | 同一元素的 CSS `transform: translateX/Y()` 和 GSAP `x/y` 属性不能共存，改用 `xPercent`/`yPercent` | ✓ lint 能检测 | — |
| `gsap_timeline_set_initial_hide` | ⚠️ **旧描述有误**。正确规则：**禁止**在页面加载时 `gsap.set()` 后面场景的 clip 元素（这些 clip 在页面加载时根本不在 DOM 里）。**应使用** `tl.set(selector, vars, time)` 放在 timeline 内、clip 的 `data-start` 时间点之后 | 部分检测 | 旧文档错误地说"初始隐藏用 gsap.set() 在 timeline 外"——这正好是错误做法 |
| `preserve-3d + filter` | `transform-style: preserve-3d` 元素的**祖先链**上不能有 `filter`，filter 只能加在叶子元素上 | ✓ check 能检测 | — |
| `full_bleed_background_on_root` | 全屏背景必须放在 `position:absolute; inset:0` 的子 clip 里，**不能**直接设在 composition root 的 `background` 上（渲染器会丢掉 root background）| ❌ silent bug，预览正常但渲染黑屏 | — |
| `root_must_be_sized` | Root `data-composition-id` 元素必须有明确 px 尺寸，所有祖先到 `height:100%` 元素都要有 resolved height | ❌ 自动门控可能漏掉 | — |
| `gsap_repeat_ceil_overshoot` | 有限循环的 repeat 计算用 `Math.floor` 不能用 `Math.ceil`（ceil 会超出 data-duration，触发 lint 错误） | ✓ lint 检测 | — |

### 7.1 media_in_subcomposition 的正确检测方式

```bash
# lint 无法检测，必须手动 grep
grep -nE '<(video|audio)\b' compositions/*.html
# 期望：无匹配
# 非空结果 = render-blocking defect，media 必须移到 index.html 的 root 直接子元素
```

### 7.2 gsap_timeline_set_initial_hide 的正确写法

```javascript
// ❌ 错误：在页面加载时 gsap.set() 后面场景的 clip（那个 clip 可能不在 DOM）
gsap.set("#scene2-element", { opacity: 0 });

// ❌ 错误（旧文档描述的做法）：tl.set(..., 0) 用于初始隐藏 → 实际上这对非-clip 元素是 OK 的
// tl.set("#element", { autoAlpha: 0 }, 0);  // 这对 non-clip 元素是可以的

// ✓ 正确：在 timeline 内、clip 的 data-start 时间点之后设置
tl.set("#scene2-element", { opacity: 0 }, 2.0); // clip 的 data-time-in 时间
```

---

## 8. 适用场景

### 适合

| 场景 | 原因 |
|------|------|
| **品牌/产品发布视频** | Kinetic type + 产品截图，代码级精度 100% 可控 |
| **数据可视化动效** | 数字动画、图表、stats hit，deterministic 渲染 |
| **网站/产品功能展示** | `capture` 直接抓取 token + 素材 |
| **短动效覆盖层** | `/motion-graphics`，可输出透明 WebM |
| **演示文稿/Pitch Deck** | `/slideshow`，可导航交互 |
| **批量变量化视频** | `--batch rows.json`，一套模板多版本 |
| **字幕叠加** | `/embedded-captions` |
| **采访/播客图形包装** | `/talking-head-recut` |

### 不适合

| 场景 | 原因 |
|------|------|
| 电影级写实画面 | 人物运动/真实场景需要 Kling/Sora 等生成，HF 无此能力 |
| 真人出镜内容 | 应使用 HeyGen 主平台 avatar |
| 复杂自然场景/物理效果 | 超出 CSS/GSAP 表达范围 |

---

## 9. 实测经验与 clip-weave 补位

### 9.1 lint 循环不可避免，但可预防

每个 composition 平均需要 2-3 轮 lint/check 才能清零：
- `lint` 是静态检查，速度快；`check` 需启动 headless Chrome，每次 10-30s
- layout 塌陷、JS 运行时错误**只有** `check` 才能发现
- 已知错误模式（§7 的规则）如果有确定性 fixer，可以**完全绕过** LLM 修复轮

**clip-weave Rule Guard 的价值**：在 Python 层（<1s）拦截 §7 中的已知错误，
命中则用 Fix Registry 直接改 HTML，未命中才进入 `npx check`（10-30s）。

### 9.2 增量检查降低循环成本

`npx hyperframes check <file>` 支持指定文件，只检查变更的 composition。
clip-weave 在 Step 5 每个子 agent 返回后立即 check 其文件，而不是批量 check。

### 9.3 素材选择缺乏自动匹配

`capture` 命令能提取大量素材（小米项目抓到 134 张图），但 HF 没有自动素材匹配引擎：
- `asset-descriptions.md` 存储每张图的文字描述（AI 生成，需要 Gemini/OpenRouter key）
- agent 需要读这个文件并手动判断哪张图适合哪个场景
- 没有向量检索，完全依赖 agent 在当前上下文中读取描述文件

**后果**：如果 agent 没有系统性读完描述文件，大量素材被忽略（v1 版本 134 张只用 2 张）。
**clip-weave Asset Matcher 的价值**：Pre-compute embedding + top-K 检索，
Step 3（Storyboard）之前强制填充 `asset_candidates` 字段，把"自由挑 100+"变成"从 3-5 张候选中选"。

### 9.4 sub-agent frame-packets 模式的重要意义

HF 的 Step 5 并行子 agent 之所以能减少遗忘，是因为 `frame-packets.mjs` 为每个 frame
生成了**自包含 context**（storyboard block + 完整 blueprint 代码 + inlined rule recipes），
子 agent 只需读自己的 packet，不需要依赖 LLM 的长期记忆。

这也是 clip-weave Rule Guard 的设计参考：
规则清单每次从磁盘重新加载，而不是期望 LLM 记住它们。

### 9.5 参考样例 > 从零设计

实测结论：找到一个与目标风格接近的已验证官方样例（`vendors/hyperframes-launches/`），
分析其叙事结构、动效语法、设计 tokens，再适配品牌素材，
远比让 agent 从零创作更快、质量更稳定。

