# HyperFrames 深度分析

> 2026-07-24 初版 | 2026-07-29 更新 §2（渲染引擎原理）
> 基于 ~/workspace/hyperframes/ 源码（packages/ + skills/）全量阅读
> §2 已对照官方文档与研究文章交叉验证，来源见文末 §10

---

## 1. 系统定位

**一句话：把 HTML 文件渲染成 MP4 视频的框架，专门为 AI agent 设计。**

制作视频的传统工具（AE、Premiere）要人拖时间轴，AI 没法直接操作。
HyperFrames 换了一种思路：用 HTML + CSS + GSAP 写动画，AI 最擅长写 HTML，
再用 Chrome 的帧捕获接口（BeginFrame API）把每一帧截成图，最后 FFmpeg 合成 MP4。

---

## 2. 渲染引擎原理

> **核心矛盾**：浏览器为了流畅是故意异步的 —— 图片后台解码、视频卡了丢帧、动画跟显示器时钟走。
> 这些全是性能优化，同时全是不确定性来源。视频渲染要的恰恰相反：同样输入必须出同样的像素。
> 下面五层，每层拆掉一个不确定性来源。

### 2.1 唯一的核心抽象：Seek，不是 Play

每个合成只对外暴露一个契约：

```javascript
window.__hf = {
  duration: 10,
  seek: (timeSeconds) => { /* 定位每个 clip、tween 和 video */ }
}
```

渲染器**从不调 `play()`**。渲染 10s / 30fps 的视频就是 `seek(0)` 截图 → `seek(1/30)` 截图 → …
重复 300 次。时间不会自己前进，没有任何东西由 `requestAnimationFrame` 驱动，
浏览器的工作变成"把画面冻在这一帧，等我要下一帧"。

**这一个抽象的价值：预览和渲染是同一条代码路径。**

| 场景 | 驱动方式 | 调用的东西 |
|------|---------|-----------|
| Studio 预览 | iframe + postMessage 桥（play/pause/scrub）| `window.__hf.seek(t)` |
| 无头渲染 | Puppeteer + CDP | `window.__hf.seek(t)` |

用户拖时间轴和渲染器抓第 147 帧，走的是同一段代码，所以输出一致。

**动画库通过三方法 FrameAdapter 接入：**

```typescript
interface FrameAdapter {
  id: string;
  init?: (ctx) => Promise<void> | void;
  getDurationFrames: () => number;
  seekFrame: (frame: number) => Promise<void> | void;
}
```

GSAP 是默认，因为它的 timeline 天生 paused + seekable（`timeline.pause()` +
`timeline.totalTime(t, false)` 就是所需的全部功能）。Lottie、经 WAAPI 的 CSS、Three.js clock
都能套进同一形状。

**套不进来的是"坚持自己掌握时钟"的东西**：无控制器的 CSS keyframes 动画、
`<video>` 元素、自己跑 rAF 的多数 canvas 库。这些要么包一层 adapter 把时钟夺走，
要么离线渲成帧序列再当图片回放（这正是视频的处理方式，见 §2.4）。

### 2.2 帧捕获：用 BeginFrame 接管合成器

capture loop 的第一个版本只有两行 Puppeteer（`seek` + `page.screenshot`），
官方文章记录了随后踩的四个坑：

**坑 1 · `Page.captureScreenshot` 与渲染器竞态**
它在合成器"愿意给图"的时刻返回，那个时刻**不等于**"布局完成 + 字体加载完 +
GSAP 提交了最终样式 + GPU 画完了"。于是会拿到文字还没渲染、SVG 填充还是未动画的默认值、
`<video>` 还是 300x150 默认尺寸的帧 —— 重跑一次就对，这类 bug 最难查。
早期靠启发式（轮询 `fonts.ready`、等 computed style、比像素哈希）兜，能用但不够稳。

**坑 2 · `HeadlessExperimental.beginFrame` 才给得了控制权**
一次 CDP 调用原子地跑完 layout→paint→composite→截图：

```javascript
await cdp.send("HeadlessExperimental.beginFrame", {
  frameTimeTicks, interval,
  screenshot: { format: "jpeg", quality: 80, optimizeForSpeed: true }
});
```

一次调用一帧，合成器在你要下一帧之前保持暂停。返回值带 `hasDamage`，
告诉你画面相比上一帧有没有变化。**没有并发管线在后台收尾，就没有竞态。**

代价是环境要求很硬：二进制必须是 `chrome-headless-shell`（不是普通 Chrome），
外加 9 个关掉异步调度的 flag：

```
--deterministic-mode                        # 时间源固定，performance.now() 由 frameTimeTicks 驱动
--enable-begin-frame-control                # 合成器等 CDP 指令才推进
--run-all-compositor-stages-before-draw
--disable-threaded-animation                # 关线程化动画
--disable-threaded-scrolling
--disable-checker-imaging                   # 关增量图片解码
--disable-image-animation-resync
--enable-surface-synchronization            # 关 vsync 驱动的 surface 时序
```

> ⚠️ **平台限制（对 clip-weave 直接相关）**：这套组合只在 **Linux + chrome-headless-shell** 上可靠。
> macOS / Windows 上 Chrome 会崩或 flag 组合有问题，引擎自动退回
> `Page.captureScreenshot` + 启发式等待（`stripBeginFrameFlags()`，见
> `packages/engine/src/services/browserManager.ts`）。
> **本地 mac 开发是低保真模式，生产渲染需跑 Docker / Linux。**
> 引擎还会主动 probe `beginFrame` 方法是否存在（近期 chrome-headless-shell 147 上
> `HeadlessExperimental.enable` 成功但 `beginFrame` 方法缺失），任何失败都按不支持处理。

**坑 3 · Chrome 停止推进事件循环**
`--enable-begin-frame-control` 生效后主线程不再自己 tick：没有帧回调、没有 `setTimeout`、
任务间不排空微任务。渲染期间是好事，**页面加载期间是灾难** ——
`document.fonts.ready` 是靠 task resolve 的 promise，没有 tick 就永远挂着。
GSAP 脚本加载完、timeline 注册好、`__hf.seek` 接好，然后卡死在 fonts。

修法是 **warmup 循环**：加载期间每 33ms 发一个 `noDisplayUpdates: true` 的 beginFrame，
只推事件循环不出帧；等 `window.__hf` 就绪且字体加载完就杀掉循环，
再从一个超过 warmup 范围的帧时间开始真实捕获（避免合成器看到时间倒流）。

**坑 4 · Puppeteer 的 `waitForFunction` 失效**
它底层在注入世界里用 rAF 轮询，而 rAF 在 beginFrame 模式不触发，
于是和 `fonts.ready` 一样挂住，还丢掉了 Puppeteer 的友好报错。
修法是不用它，自己写 `evaluate` + `setTimeout` 的轮询循环。

**今天实际跑的 capture loop：**

```javascript
for (let i = 0; i < totalFrames; i++) {
  const time = quantizeTimeToFrame(i / fps, fps);
  await page.evaluate(t => window.__hf.seek(t), time);
  const { buffer } = await beginFrameCapture(page, options, frameTicks, interval);
  writeFileSync(`frame_${i}.jpg`, buffer);
}
```

一次 seek、一次 beginFrame、一帧落盘。无重试、无 flaky 帧。
（`hasDamage=false` 时复用上一帧缓存 —— 合成器已暂停，此时再调
`Page.captureScreenshot` 会超时。）

### 2.3 GSAP Timeline 注册协议与合成模型

```javascript
// 框架在任何脚本运行前初始化 window.__timelines = {}
// 每个合成必须有且仅有一个 paused timeline，synchronously 注册
window.__timelines["<composition-id>"] = gsap.timeline({ paused: true });
// key 必须严格等于 root 元素的 data-composition-id
```

规则：所有 timeline 必须 `{ paused: true }`；框架**自动**把子 timeline 嵌进父级
（不要手动 add）；timeline 必须有限（无无限循环/repeat）。

**属性正确写法**（⚠️ 旧版本文档此处写成 `data-time-in`/`data-time-out`，
这两个属性**不存在**；`data-layer` / `data-end` 是已废弃别名）：

```html
<!-- 独立合成：root 直接在 <body>，禁止 <template> 包裹 -->
<div id="root" data-composition-id="hero"
     data-width="1920" data-height="1080" data-duration="5">
  <!-- clip 必须是 composition root 的直接子元素 -->
  <div id="el-1" class="clip"
       data-start="0" data-duration="5" data-track-index="0">
    <!-- 场景内容；要包装/变换就把 wrapper 放在 clip 内部 -->
  </div>
</div>

<!-- 子合成：root 必须在 <template> 内 -->
<template>
  <div data-composition-id="cta-overlay" data-width="1920" data-height="1080">...</div>
</template>
```

| 属性 | 位置 | 说明 |
|------|------|------|
| `data-composition-id` | root | 必填，需匹配 `window.__timelines` 的 key |
| `data-width` / `data-height` | root | **必填**，像素帧尺寸（1920x1080 / 1080x1920 / 1080x1080）|
| `data-duration` | root | 渲染总时长，**非** timeline 长度；编译期读一次（脚本或 `--variables` 改不动）|
| `data-fps` | root | 可选帧率提示，CLI render flag 可覆盖 |
| `class="clip"` | 可见定时元素 | **必填**，缺失则元素全程可见、`data-start`/`data-duration` 被忽略；`<video>`/`<audio>` 省略 |
| `data-start` | clip | 必填，秒数或对另一 clip ID 的相对引用（该 clip 结束时开始）|
| `data-duration` | clip | `div`/`img`/子合成宿主必填；video/audio 可默认取媒体时长 |
| `data-track-index` | clip | 必填，轨道号，决定 z 序（越大越前）；同轨道 clip 不可重叠 |
| `data-media-start` | video/audio | 源文件内的裁切偏移（秒）|

关于 root `data-duration` 的**条件必填**：当运行时能自动推断时长时可省略
（已注册的 GSAP timeline、有限的 CSS animation、有限的 WAAPI `element.animate()`、
已注册的 Lottie）。**Three.js 无法推断，必须手写**；无限/无界 CSS/WAAPI 动画、
以及完全没有动画信号的合成也必须手写。`lint` 用 `root_composition_missing_duration_source` 强制。

> 官方在线文档（`hyperframes.heygen.com/reference/html-schema`）写的是
> "duration 来自 `tl.duration()`，不要在 composition 元素上加 `data-duration`" ——
> 那是面向纯 GSAP 场景的简化表述，与本地 skills 的条件必填规则不冲突。
> **clip-weave 以本地 `hyperframes-core/references/data-attributes.md` 为准。**

**可见窗口两端都是闭区间**：clip 在 `start ≤ t ≤ start + duration` 期间显示，
在 `t = start + duration` 这一帧仍会渲染，所以落在 `data-duration` 上的入场动画
在最后一帧是可见的，不需要提前结束。

**最容易触发 silent bug 的四条规则（自动化检查可能漏掉）：**
1. Root 必须有明确 px 尺寸，否则内容塌陷到左上角
2. 全屏背景必须放在 `position:absolute; inset:0` 的子 clip 里，**不能**设在 `#root` 上
   （渲染器会丢掉 root 的 background，Preview 正常但渲染出来是黑色）
3. 整个 assembled page 内 `id` 不能重复（跨文件的 `<video id="xxx">` 重复会渲染成空白）
4. **clip 必须是 composition root 的直接子元素** —— 套在 wrapper `<div>` 里的 clip
   不会被注册。最明显的症状是 wrapper 里的 `<video>` 从不被 seek/解码，渲染全黑

### 2.4 视频当翻页画册：不让 Chrome 解码

让浏览器在渲染时播 `<video>` 行不通：无头 + BeginFrame 下解码器会丢帧、解码失败、
或 `readyState: 0` 卡到超时；即便不开 BeginFrame，不同机器不同编解码路径
对同一合成也会产出不同结果。**网页上的 `<video>` 丢帧无所谓，视频渲染器不行。**

所以把解码权从 Chrome 拿走：

1. 捕获开始前，FFmpeg 按目标 fps 把合成里每个 `<video>` 预抽成编号 JPEG
   （5 秒 30fps = 150 个文件）
2. 捕获时，为当前帧上每个活跃视频注入一个 `<img>` 兄弟节点（帧字节做 data URI），
   隐藏原 `<video>`

```html
<!-- 之前 -->
<video data-start="2" data-duration="5" src="clip.mp4" />

<!-- 捕获时，150 帧中的第 60 帧 -->
<video style="visibility: hidden" ... />
<img src="data:image/jpeg;base64,..." class="__render_frame__" />
```

关键在于让 `<img>` 长得和它替换掉的 `<video>` 一模一样，这样 GSAP tween、CSS transform、
opacity 淡入、`object-fit` 规则全都照常生效 —— 引擎读原元素的 computed style
（position / transform / opacity / objectFit 等十几个属性）逐个拷到注入的 img 上。
**从动画库的视角看什么都没变**，元素还在原位、样式一样，只是显示一张每帧都换的静态图。

实现位置：`packages/engine/src/services/videoFrameInjector.ts`。
这也解释了 `media_in_subcomposition` 规则（§7）为什么存在 —— 注入逻辑依赖
`<video>` 位于宿主 root 的直接子元素这一结构假设。

**三种路线对比：**

| 框架 | 做法 | 取舍 |
|------|------|------|
| **HyperFrames** | FFmpeg 提前全量解码 → 从磁盘供 JPEG | 管线最短；难处理 blob URL / 流式源 / 动态改 `src` |
| Remotion | 常驻 Rust 合成器按需解码，HTTP 供给 `<OffthreadVideo>` | 更灵活，架构更重 |
| Replit | 浏览器内 mp4box.js demux + WebCodecs 解码 → 画进 canvas | 全前端，复杂度高 |

### 2.5 其余确定性陷阱

**字体网络请求**。多数合成用 `@import url(fonts.googleapis.com/...)`，
渲染时这是抛硬币 —— 网络快慢/是否被墙决定字体在第一帧之前还是之后到。
解法：编译期把所有 Google Fonts `@import` 重写成本地 base64 内嵌的 `@fontsource` 副本
（`packages/producer/src/services/deterministicFonts.ts`）。视觉完全一致，去掉网络往返和抖动。

**时间量化**。30fps 每帧 33.3333ms。若一条路径算出 `seek(0.0333333)`、
另一条边缘路径重算出 `0.0333334`，必须落到同一帧。所以每次 seek（预览和渲染都一样）
都过一遍量化器：

```javascript
function quantizeTimeToFrame(time, fps) {
  return Math.round(time * fps) / fps;
}
```

一行代码，但没有它，两条算出同一标称时间的路径会产出差一个像素的帧
（`packages/core/src/inline-scripts/parityContract.ts`）。

**作者侧契约**（违反则前面所有工程都白做）：
- 禁止 `Date.now()`、`performance.now()`、非 seed 的 `Math.random()`
- 禁止渲染时发网络请求
- 禁止 `repeat: -1`（无限循环）—— 渲染器无法推算帧数
- 禁止 `setTimeout`、`requestAnimationFrame`、`Promise` 内建 timeline
- 禁止在页面加载时 `gsap.set()` 后面场景的 clip 元素（那些 clip 加载时不在 DOM 里，见 §7.2）

### 2.6 预览一致性与并行渲染

**一致性是强制的，不是"希望如此"**：Studio 预览（iframe 内）和无头渲染跑
**同一个** `window.__hf` runtime bundle，渲染器启动前校验 bundle 的 sha256
与 manifest 是否匹配。所以"预览里看到的"字面上就是产出 MP4 的那段代码。

**长视频并行**：帧被切分到 N 个 Chrome 进程，各 worker 渲染自己那份，
最后 FFmpeg 拼接各 worker 的 MP4 chunk。

> ⚠️ **已知问题**：视频密集的合成在并行模式会超时 ——
> Chrome 无法同时 seek 多个 `<video>` 而不耗尽解码器。
> 官方给的修法就是对视频密集渲染退回单 worker。
> 另有 `Another frame is pending` 错误：并行渲染打满 CPU 时出现，
> 引擎指数退避重试 5 次后报错。
> **clip-weave 影响**：写实镜头混合路径（P3）产出的合成属于视频密集类型，
> 渲染耗时无法靠并行降低，排期需按单 worker 估算。

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
| `hyperframes-registry` | 预制组件的安装（`npx hyperframes add <block>`）和用法。本地 registry 实测 **109 blocks + 25 components + 13 examples**（官方文档口径 "150+ blocks and components"）| 复用现有组件 |
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
| `clip_must_be_direct_child` | clip 必须是 composition root 的**直接子元素**。套在 wrapper `<div>` 里的 clip 不会被注册；要包装/变换就把 wrapper 放进 clip 内部，或直接动画 clip 本身 | ❌ silent bug（wrapper 里的 `<video>` 从不被 seek，渲染全黑）| — |
| `clip_class_required` | 可见定时元素必须带 `class="clip"`，缺失则元素**全程可见**、`data-start`/`data-duration` 被完全忽略。`<video>`（框架直管可见性）和 `<audio>`（无视觉）省略 | ❌ silent bug | — |
| `root_composition_missing_duration_source` | root `data-duration` 在运行时无法推断时长时必填（Three.js、无限 CSS/WAAPI 动画、无动画信号）。root 的 `data-duration` 编译期读一次，脚本或 `--variables` 改不动；clip 的 `data-duration` 则从活 DOM 重读，可被脚本驱动 | ✓ lint 检测 | — |
| **已废弃属性别名** | `data-layer` → 用 `data-track-index`；`data-end` → 用 `data-duration`。**`data-time-in` / `data-time-out` 不存在**（旧版本文档误写，源码中无任何引用）| — | 旧文档示例用了 `data-time-in`/`data-time-out` |

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
tl.set("#scene2-element", { opacity: 0 }, 2.0); // 该 clip 的 data-start 时间
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

实测结论：找到一个与目标风格接近的已验证官方样例（`~/workspace/hyperframes-launches/`），
分析其叙事结构、动效语法、设计 tokens，再适配品牌素材，
远比让 agent 从零创作更快、质量更稳定。

### 9.6 渲染环境的平台约束（2026-07-29 补充）

§2.2 的 BeginFrame 确定性捕获**只在 Linux 上可靠**，macOS/Windows 自动退回
截图 + 启发式等待模式。这对 clip-weave 有三个直接影响：

| 影响 | 说明 | 应对 |
|------|------|------|
| 本地 mac 渲染是低保真 | 可能出现"重跑一次就对"的 flaky 帧 | 本地只做开发/预览；交付渲染走 Docker(Linux) 或 `cloud render` / `lambda render` |
| flaky 帧会污染 check 结果 | mac 上 `check` 报的 layout/runtime 错误可能是捕获竞态而非真错 | Rule Guard 遇到 mac 上不可复现的 check 失败，先在 Linux 复核再交给 LLM 修 |
| 视频密集合成不能并行 | Chrome 解码器不足，并行会超时；只能单 worker | P3 写实镜头路径的渲染耗时按单 worker 估算，不要按并行折算 |

---

## 10. 信息来源

本文档 §1、§3–§9 基于 `~/workspace/hyperframes/`（packages/ + skills/）源码阅读。
§2 于 2026-07-29 对照以下官方来源重写并交叉验证：

- [HTML to Video: How HyperFrames Solved AI Video Rendering](https://www.heygen.com/research/html-to-video) —— HeyGen 官方研究文章，§2 的 seek 契约、BeginFrame 四个坑、视频翻页画册、确定性陷阱均出自此文
- [Introduction to Hyperframes](https://developers.heygen.com/hyperframes-overview) —— 官方产品概述（核心概念、渲染方式、组件库口径）
- [HTML Schema Reference](https://hyperframes.heygen.com/reference/html-schema) —— 官方 data-* 属性与 timeline 契约参考
- [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes) —— 开源仓库

**本地源码交叉验证点**（官方描述与本地实现一致）：

| 官方描述 | 本地源码位置 |
|---------|------------|
| BeginFrame 原子捕获 + `hasDamage` 帧缓存 | `packages/engine/src/services/screenshotService.ts` |
| 9 个 flag + 非 Linux 剥离回退 + beginFrame 能力探测 | `packages/engine/src/services/browserManager.ts`（`BEGINFRAME_ONLY_FLAGS` / `stripBeginFrameFlags` / `probeBeginFrameSupport`）|
| 视频帧预抽 + `<img>` 注入 | `packages/engine/src/services/videoFrameInjector.ts`、`frameCapture.ts` |
| Google Fonts → 本地 base64 重写 | `packages/producer/src/services/deterministicFonts.ts` |
| `quantizeTimeToFrame` 时间量化 | `packages/core/src/inline-scripts/parityContract.ts` |
| data-* 属性表（含废弃别名）| `skills/hyperframes-core/references/data-attributes.md` |

> 内容已改写以符合来源的授权限制。
> **存在分歧时以本地 skills 文档为准** —— 在线文档为面向通用场景的简化表述，
> 本地版本是 clip-weave 实际调用的那一份。
