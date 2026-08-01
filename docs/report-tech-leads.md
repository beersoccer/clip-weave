---
marp: true
theme: default
paginate: true
title: clip-weave 项目汇报
---

# clip-weave

## 让 AI 稳定产出可交付视频

面向科技团队主管 · 项目进展汇报

2026-07-30 · 汇报时长 10 分钟

<!--
开场一句话：clip-weave 是让非视频专业人员也能用 agent + skills
稳定产出可交付视频的工具。
-->

---

# 应用场景：谁在用、做什么样的视频

**目标用户** —— 不是视频剪辑师，是**每天要产出视频素材但不会做视频的人**：
产品经理、市场、运营、技术写作、开发者本人。

**要做什么样的视频** —— 以**文字、图形、图表、动效**为主的类型：

- 品牌宣传、产品发布、功能演示
- 数据可视化、changelog、更新公告
- 教程讲解、SaaS 推广、社交媒体切片

**关键诉求**：一句自然语言输入 → 视频产出，全程**高效、稳定、可交付**，
不用学 After Effects、不用写代码、不用一次次和 AI 反复对齐。

> 核心命题：**把"AI 能做视频"变成"非专业人员能稳定用 AI 做出可交付视频"。**

<!-- 1:00 —— 先把用户和内容边界讲清楚，主管会拿这个衡量后面所有的取舍。 -->

---

# 卡点：现有底座还差什么

底座 HyperFrames（HF）已经解决了"**怎么渲染**"这件事 ——
HTML + CSS + GSAP 写动画 → Chrome 逐帧捕获 → FFmpeg 合成 MP4，
AI 最擅长写 HTML，路径完全对。

但从"能跑出 demo"到"能稳定交付"，中间有三个反复出现的卡点：

| # | 卡点 | 表现 |
|---|------|------|
| 1 | **一条 HF 特有约束在装配前查不出来** | `media_in_subcomposition`（媒体元素必须在 index.html 根）在 HF 的 lint 里有实现，但装配前和单文件入口两个窗口下会失效；早期以为有 4 条这类约束需要预检，核对 HF 源码后确认只有这一条站得住，另外三条要么 HF 已实现得更好、要么直觉判断本身是错的（见附录 E）|
| 2 | **lint 循环烧时间烧 token** | 单次 `check` 需启动 headless Chrome，10–30s；每个合成平均 2–3 轮；长视频累计上百秒 |
| 3 | **素材利用率低** | `capture` 抓到 134 张图，v1 版本只用了 2 张，非专业用户看不出哪张该配哪镜 |

**共同后果**：AI 能出 demo，但**稳定性和一次通过率不够**，非专业用户被迫回到"和 AI 反复扯皮"的低效模式。

<!-- 1:00 —— 三个卡点是后面所有设计的动机；这里是"应用场景"到"解决方案"的桥梁。 -->

---

# 一句话结论：clip-weave 是做什么的

> **clip-weave = HyperFrames 前置门面 + 稳定性补丁**

**不重造渲染引擎**，只在 HF 缺位处补两件事：

**① 前置入口 —— 意图路由**
一句自然语言 → 自动选定 workflow + 生成 BRIEF.md → 触发无人值守执行。
非专业用户无需理解 HF 的 workflow 概念。

**② 三个稳定性解法 —— 分别对应上页三个卡点**

| 卡点 | 解法 | 效果 |
|---|---|---|
| 装配前查不出黑屏级缺陷 | **规则守卫**（单规则）| 确定性 Python 拦截，装配前发现，不依赖 LLM 记忆 |
| lint 循环慢 | **增量 check** | 只 check 变更文件；渲染前仍需跑一次全项目 check（见附录 F 的覆盖率代价）|
| 素材利用率低 | **Asset Matcher** | 100+ 素材语义预排序 + 打分，缩小到 3–5 张候选 |

**当前状态：P0–P3 代码全部交付，257 个测试通过。P3（T2V 渲染路径）待真实网关实测。**

<!-- 0:40 —— 结论一页，把"是什么、解决什么、进展如何"讲完。 -->

---

# 第二部分 · 目前可以做到什么

---

# 三种使用入口 —— 覆盖不同熟练度

| 使用方式 | 交互形式 | 适合场景 |
|---|---|---|
| **对话式 intent interview** | Claude Code 里一句话开始，AI 逐字段问 | 首次使用、字段还没想清楚 |
| **BRIEF.md 模板离线填写** | 复制模板 → 填空 → 一键跑 | 批量、复用同一套参数 |
| **CLI 单行** | `python -m clip_weave run --url ... --message ... --length 30s` | 集成到脚本、CI、自动化流程 |

**共同点**：一旦 BRIEF.md 生成，后续流程**无人值守**，
LLM 不再向用户提问，直接跑到出片。

<!-- 0:30 —— 强调"入口友好度"是给非专业用户看的。 -->

---

# 两条渲染路径 —— 覆盖不同画面性质

**HTML 路径（当前主力）**：AI 写 HTML/CSS/GSAP → HF 逐帧渲染
—— 图形、文字、UI、图表，**代码级精度、可复现、可批量变量化**。

**T2V 旁路（P3 待验证）**：STORYBOARD.md 分镜 → 文生视频模型直出
—— 写实画面、真实场景、镜头运动，**绕开 check 循环**。

| | HTML 路径 | T2V 旁路 |
|---|---|---|
| 画面性质 | 图形、文字、UI、图表 | 写实、氛围、镜头运动 |
| 可控性 | 每一帧可复现，改一个字改一行代码 | 生成结果有随机性，靠改提示词迭代 |
| 主要开销 | LLM 写 + check 循环的**时间** | 模型推理的**费用与排队** |
| 适合 | 品牌发布、数据可视化、功能展示 | 空镜、氛围镜头、实景铺垫 |

**关键点**：两条路径**共用同一份 STORYBOARD.md**，选择哪条是**分镜级别**的决策。

<!-- 0:40 —— 提前铺垫 T2V 是能力扩展，不是重复造轮子。 -->

---

# 目前能覆盖的视频类型

三种入口 × HTML 路径已经跑通的场景：

| 场景 | 典型输入 | 产出 |
|---|---|---|
| **产品/品牌宣传** | 官网 URL + 一句描述 | 15–30s 带 logo/主色的 promo |
| **功能展示** | 功能描述 + 截图 | UI 高亮 + 说明文字的功能演示 |
| **数据可视化** | 数据表 + 想表达的重点 | 图表 + 关键数字动画 |
| **Changelog / 更新公告** | commit / PR 列表 | 逐条动效呈现的更新视频 |
| **教程 / 讲解** | 分步骤脚本 | 分镜化的教学动画 |

**非专业用户视角**：只要能用一句话描述"做什么、给谁看、多长",
剩下的 workflow 选择、设计系统提取、素材匹配、规则守卫**都由 clip-weave 自动完成**。

<!-- 0:30 —— 用具体场景让主管有画面感。 -->

---

# 交付状态一览

| 阶段 | 目标 | 状态 |
|---|---|---|
| **P0** | 打通链路：意图 → HF autonomous 执行 | ✅ 完成 |
| **P1** | 装配前规则预检 | ✅ 完成（按 HF 源码核对收缩为单规则，见附录 E）|
| **P2** | 提升素材利用率（Asset Matcher 排序 + STORYBOARD 集成 + 噪声过滤 + 质量下限）| ✅ 完成 |
| **P3** | T2V 渲染路径：STORYBOARD.md → 三家 provider → FFmpeg 合流；用户可编辑的 T2V-PROMPTS.md；渲染路径由项目级 `render:` 决定 | ✅ 代码完成，待真实网关实测 |
| **P4** | 两条路径混排（`render: mixed`，同一支视频内动效镜头 + 写实镜头并存）| 🔲 P3 后 |

**工程质量指标**

- 257 个单元测试全部通过，全部离线（不触真实网关/npx/ffmpeg/gcloud）
- 有一条回归测试专门固化"HF 官方正确写法零误报"，防止已删除的规则被重新加回
- Vision / Embedding 三级降级，无单点故障（没配 API key 也能跑）

<!-- 0:30 —— 数字页，主管想要的确定性都在这里。 -->

---

# 第三部分 · 未来规划

---

# 规划一 · 音频落地

**现状：视频目前是静音的。**

- `api.heygen.com` 内网屏蔽问题**已解决**
- 用 HeyGen **个人账号**跑通验证：TTS 配音 + 版权 BGM 均可用，中文声线质量满足要求

**下一步**

- 切换到**公司已采购的云厂商**账号 / 额度，走合规通道
- 完成后视频从"静音"变成"**带配音 + BGM**",这是可交付性的一个明确台阶
- 与三种入口无缝衔接：BRIEF.md 里加一个 `voice/bgm` 字段即可

**用户价值**：非专业用户不再需要在剪映里补音轨。

<!-- 0:40 —— HeyGen 屏蔽已解决,不再当风险讲。 -->

---

# 规划二 · T2V 渲染路径（P3，代码已完成，待真实网关实测）

**动机**：HTML 路径画不出真实场景 —— 电影级写实、真人出镜、复杂物理效果超出 CSS/GSAP 表达范围。

**方案**：渲染路径由用户在项目之初选定一次（`BRIEF.md` 的 `render: html | t2v | mixed`），
`t2v`/`mixed` 会把分镜描述先生成一份用户可编辑的 `T2V-PROMPTS.md`，再交给文生视频模型，
**跳过写 HTML 这一步**。已接入三家 provider（豆包 Seedance / 阿里通义万相 / Google Veo）。

**要验证三件事**

1. **信息量** —— `T2V-PROMPTS.md` 的分镜描述够不够模型生成
2. **风格连贯** —— 镜头间视觉风格是否统一
3. **时长可控** —— 模型输出能否精确对齐分镜时长（各家 provider 单次时长上限都远小于整片，
   已用 FFmpeg 拼接多个片段）

**验证结果的两种走向**

- ✅ 通过 → 写实镜头场景**打开**，覆盖面显著扩大
- ❌ 不通过 → 明确是**分镜格式要补字段**,还是**模型能力还不够**,都是可执行的下一步

<!-- 0:40 -->

---

# 规划三 · 两条路径混排（P4）

**目标**：同一支视频里,动效镜头 + 写实镜头**并存**。

- 品牌 logo / 数据图表 → HTML 路径出（精度）
- 环境铺垫 / 氛围空镜 → T2V 路径出（写实）
- 二者按分镜顺序在 **FFmpeg 层合流**

**关键工程约束**

- **不在 HTML 内嵌 `<video>` 做混排** —— Chrome 视频密集渲染会解码器耗尽
- 混排必须在 FFmpeg 层做,时间轴上按段拼接

**用户价值**：一份 BRIEF.md,一次执行,拿到**既有精度又有质感**的成片。

<!-- 0:30 —— 讲清 P4 的边界:不做 HTML-in-video,是刻意规避一个已知硬约束。 -->

---

# 一句话回顾

**clip-weave 做的事**

用一个低摩擦入口（意图路由）+ 稳定性解法（装配前规则预检 / 素材匹配）+ 渲染路径决策,
把 HyperFrames 从"能渲染视频的框架"变成**非专业人员也能稳定交付视频的流水线**。

**当前进展**

P0–P3 代码全部交付,三种入口可用,257 个测试通过。P3 待真实网关实测。

**下一步**

1. 音频切云厂商账号 → 视频从静音到有声
2. 验证 STORYBOARD.md 复用于文生视频 → 打开写实画面场景

Q & A

<!-- 0:20 -->

---

# 附录

以下为技术实现细节,如有具体问题再展开。

- **附录 A**：定位取舍 —— 做门面,不重造引擎
- **附录 B**：架构 7 步流程与补位边界
- **附录 C**：三个产出物 —— BRIEF / frame / STORYBOARD
- **附录 D**：意图路由实现
- **附录 E**：Rule Guard —— 核对 HF 源码后收缩为单条规则
- **附录 F**：Pre-flight 预检 —— lint vs check
- **附录 G**：Asset Matcher —— 三阶段语义排序
- **附录 H**：HF 渲染原理（Seek not Play）
- **附录 I**：⚠️ 渲染环境的平台约束
- **附录 J**：最容易 silent bug 的规则
- **附录 K**：lint / check 的补充细节
- **附录 L**：并行子 agent 机制

---

# 附录 A：定位取舍 —— 做门面,不重造引擎

HF 各阶段产出物已经很完备,**直接复用**：

| HF 原生能力 | clip-weave |
|---|---|
| `BRIEF.md` / `frame.md` / `STORYBOARD.md` 格式 | 复用格式,不另立标准 |
| `capture/` 素材抓取 | 调 `npx hyperframes capture` |
| 10 workflow + 8 domain skills | 直接激活 |
| lint / check / render 渲染管线 | 直接调用 |

**只在 HF 缺位处补充**：意图路由、规则守卫、lint 预检、素材匹配

> 关键取舍:`project.yaml`、自定义 `STORYBOARD.json`、
> `html_generator` 全部移除 —— 每一个自造标准都是后续的维护债。

---

# 附录 B：架构 7 步流程与补位边界

```
用户输入（对话 / CLI / BRIEF.md 模板）
   │
   ├─① Intent Router      ← clip-weave  意图 → workflow + BRIEF.md
   ├─② Project Factory    ← clip-weave  init + capture + frame.md
   ├─③ Asset Matcher      ← clip-weave  语义匹配 → asset_candidates
   │
   ├─④ 委托 Claude Code + HF Skill      → compositions/*.html
   │
   ├─⑤ Rule Guard 拦截    ← clip-weave  Python 层预检 <1s
   │
   ├─⑥ HF check → render                → renders/output.mp4
   │
   └─⑦ T2V 旁路（P3）:STORYBOARD.md → 文生视频模型 → FFmpeg 合流
```

**①②③⑤ 是 clip-weave 的独有价值,④⑥ 完全委托 HF。**

解耦边界只依赖 7 个稳定接口(init / capture / build-frame / BRIEF schema / check / render / Skill 协议),不碰 HF 内部实现。

---

# 附录 C：三个产出物 —— 整条流水线的骨架

三份 Markdown 依次收窄决策空间,每一份都是下一份的输入约束。

| 产出物 | 定位 | 回答什么问题 | 谁写 |
|---|---|---|---|
| **BRIEF.md** | 意图契约 | 做什么、给谁看、多长、什么画幅、要不要人工审批 | clip-weave Intent Router |
| **frame.md** | 设计系统 | 用什么颜色、字体、间距、动效基调 | `build-frame.mjs` 从 capture 的 tokens 生成 |
| **STORYBOARD.md** | 分镜脚本 | 分几个镜头、每镜多长、讲什么、配哪张素材 | HF skill 写;clip-weave 回填 `asset_candidates` |

**为什么顺序不能颠倒**

- BRIEF.md 存在 → workflow **不再问任何问题**,直接进 autonomous 执行
- frame.md 先定 → 所有分镜共享同一套 tokens,不会各自发明配色
- STORYBOARD.md 定稿 → 才能拆成并行子 agent 的 frame packet 去写 HTML

> **STORYBOARD.md 是最有复用价值的一份** —— 与渲染方式无关的纯语义分镜,
> T2V 旁路(P3)就建立在这一点上。

---

# 附录 D：意图路由实现

用户一句话(中/英文) → 确定性关键词路由 → 选定 HF workflow + 写出 BRIEF.md

**三步完成,无 LLM 调用:**

1. **source 检测** —— 识别输入类型:URL / Figma 链接 / 本地文件 / 纯文字
2. **workflow 路由** —— 双语关键词匹配,映射到 9 个 HF workflow 之一
3. **BRIEF.md 生成** —— 填充 workflow、flow mode、message、默认值(30s / 1920×1080)

**BRIEF.md 存在即触发 autonomous 执行,不再问任何问题** —— 整条无人值守流水线的开关。

路由本身**无状态、可测试**,BRIEF.md 是后续三个解法的唯一输入约定。

---

# 附录 E：Rule Guard —— 核对 HF 源码后收缩为单条规则

**原思路**：4 条规则编码为确定性 Python 函数，隔离于 LLM 会话上下文。核对
`/Users/beersoccer/workspace/hyperframes` 源码后，这个思路对其中 3 条不成立：

| 规则 | HF `lint` 事实 | 结论 |
|---|---|---|
| `media_in_subcomposition` | error 级实现，但装配前和单文件入口两个窗口下失效 | **保留** —— 是 clip-weave 真正补上的空档 |
| `gsap_css_transform_conflict` | 用 acorn AST 解析器实现，能处理计算式 timeline、`from`/`fromTo` 豁免等 | **删除** —— HF 原生实现更好，Python 正则版重造只会更差 |
| `gsap_timeline_set_initial_hide` | **真实语义与直觉相反**：HF 警告的是 timeline 内部 position 0 的零时长 `tl.set()`，且明确豁免 timeline 外的 `gsap.set()`。旧实现报的恰好是 HF 认为正确的写法，还建议改成 HF 会警告的写法 | **删除** —— 按这条规则改代码等于主动引入 HF 会告警的缺陷 |
| `preserve-3d + filter` | HF lint 中无此规则 | **删除** —— 判定需要完整 CSS 级联解析，Python 正则层做不到，实测在 HF 官方 3D 镜头范例上误报 |

**时机不变**：HF skill 每写完一个 composition → 立即扫描 → 命中则回传违规位置，不等
`check` 启动 Chrome。测试套件里有一条专门用 HF 官方文档记载的正确写法做回归检查，
确保这三条被删除的规则不会因为"感觉应该多检查一点"被重新加回来。

每个违规仍计算指纹记录到 `.clip-weave/guard-history.json`，但只作日志，不再有"复现即
升级"这类控制逻辑 —— 只剩一条判定确定的规则时，这种冗余闸门没有意义。

---

# 附录 F：Pre-flight 预检 —— lint vs check

**先分清 HF 的两道门**

| | `lint` | `check` |
|---|---|---|
| 原理 | **纯静态分析**,不开浏览器 | 真的启 headless Chrome 跑一遍 |
| 耗时 | 亚秒级 | **10–30s / 次** |
| 能查 | HTML 结构、`data-*`、轨道重叠、GSAP/CSS 冲突、timeline 未注册 | **lint 的全部** + JS 运行时错误 + 布局溢出/遮挡 + motion 断言 + 对比度 |

**`lint` 是 `check` 的真子集** —— 实际只有 `check` 这道门有意义,但它慢到成为瓶颈。
`lint` 对 `media_in_subcomposition` 的检测本身是完整的（error 级），只是在装配前、以及
传单文件入口时会失效（详见附录 E）。

**Rule Guard 在两道门之前补一层 Python 预检(<1s)**

- 逐行 regex,只检查 `media_in_subcomposition` 这一条,无需启动浏览器
- 命中则回传违规位置,交给 HF skill 修（这条规则的修法是把媒体节点搬到 index.html
  根，装配前该文件还不存在，所以没有自动 fixer）
- **每次节省 10–30s 的 Chrome 启动**，且能在装配前发现，比等 lint/check 跑起来更早

**增量 check 的覆盖率代价**：`npx hyperframes check <单个文件>` 会让 HF 把该文件当根合成，
跳过 `compositions/` 遍历、不设 `isSubComposition`，于是 `media_in_subcomposition` 与全部
项目级检查（重复 composition id、重复音轨、缺失资源等）一并失效。策略是单文件 check 只用于
迭代，**渲染前必须跑一次全项目 check**。

---

# 附录 G：Asset Matcher —— 三阶段语义排序

三阶段流水线,把"从 100+ 张自由挑"变成"从 3–5 张候选中选",降低 HF skill 的认知负担。

**三级降级,无单点故障:**

1. **Vision 描述增强** —— 企业网关生成高质量视觉描述,替换 capture 的 DOM 粗描述
2. **Embedding 语义检索** —— cosine 排序,捕获跨语言语义("专业团队" ↔ "professional advisory team")
3. **BM25 关键词兜底** —— Embedding 不可用时自动降级,零配置

| 阶段不可用 | 降级行为 |
|---|---|
| Vision 不可用 | 用 capture 原始描述继续,不影响 Embedding |
| Embedding 不可用 | 直接降级 BM25 |

配套 **capture 噪声过滤**:logo 白名单优先 → 剔除 favicon/QR/hash sprite → SVG 不限大小 → 栅格图 >1.5MB 剔除

HF skill 生成 STORYBOARD.md 后,clip-weave 自动解析每帧 `scene:` 字段、重新调用 Asset Matcher、回填 `asset_candidates`。

---

# 附录 H：HF 渲染原理

**唯一的核心抽象:Seek,不是 Play。** 渲染器从不调 `play()`,
只反复调 `window.__hf.seek(t)` 然后截图。时间不自己走,浏览器的工作是"把画面冻住"。

价值:**Studio 预览和无头渲染跑同一份 runtime bundle**(渲染前校验 sha256),
预览一致性是强制的而不是希望如此。

**拆掉不确定性的四层**

1. `HeadlessExperimental.beginFrame` —— 一次 CDP 调用原子完成 layout→paint→composite→截图,消除截图竞态
2. 9 个 Chrome flag 关掉所有异步调度(线程化动画/滚动、增量图片解码、vsync 时序)
3. `<video>` 不让 Chrome 解码 —— FFmpeg 提前抽成 JPEG,捕获时注入 `<img>` 并拷贝 computed style
4. Google Fonts 编译期改写为本地 base64;每次 seek 过时间量化器

**作者侧契约**:禁止 `Date.now()` / 非 seed `Math.random()` / 渲染时发网络请求 /
`repeat: -1` / `setTimeout` / rAF。

---

# 附录 I：⚠️ 渲染环境的平台约束

> 这一条影响我们的交付方式,值得单独说。

**BeginFrame 确定性捕获只在 Linux + `chrome-headless-shell` 上可靠。**
macOS / Windows 上 Chrome 会崩或 flag 组合失效,引擎自动剥离 flag、
退回 `Page.captureScreenshot` + 启发式等待。

| 影响 | 应对 |
|---|---|
| 本地 mac 渲染是低保真,可能出现"重跑一次就对"的 flaky 帧 | 本地只做开发预览;交付渲染走 Docker(Linux) 或云端 render |
| mac 上 `check` 的报错可能是捕获竞态而非真错 | Rule Guard 对不可复现的失败先在 Linux 复核,再交 LLM |
| **视频密集合成无法并行渲染** —— Chrome 不能同时 seek 多个 `<video>`,解码器耗尽会超时 | 把 T2V 生成的片段当 `<video>` 塞进 HTML 合成会踩这一条;P4 混排应在 **FFmpeg 层合流**,而不是在 HTML 里嵌视频 |

---

# 附录 J：最容易 silent bug 的规则

预览正常但渲染出错,自动化门控也可能漏掉:

1. **Root 必须有明确 px 尺寸** —— 否则内容塌陷到左上角
2. **全屏背景不能设在 `#root` 上** —— 渲染器会丢掉 root background,
   Preview 看着好、渲染出来黑屏;必须放在 `position:absolute; inset:0` 的子 clip 里
3. **assembled page 内 `id` 不能重复** —— 跨文件 `<video id="xxx">` 重复会渲染成空白
4. **clip 必须是 composition root 的直接子元素** —— 套在 wrapper `<div>` 里的 clip
   不会被注册;wrapper 里的 `<video>` 从不被 seek,渲染全黑
5. **可见定时元素必须带 `class="clip"`** —— 缺失则元素全程可见,
   `data-start` / `data-duration` 被完全忽略

配套工具:`*.motion.json` sidecar 断言(appearsBy / before / staysInFrame / keepsMoving),
是检测"渲染 vs Preview 不一致"的唯一自动化手段。

---

# 附录 K：lint / check 的补充细节

**盲点各不相同**

- `lint`:`media_in_subcomposition` 查不出来(官方文档明确标注),必须手动
  `grep -nE '<(video|audio)\b' compositions/*.html`
- `check`:3s 以上的静态合成会误报 `sweep_static`(画面没动 ≠ 出错)

**都支持增量,但只有 check 值得增量**

`lint ./path` 和 `check <file>` 都能限定范围。lint 本来就快,
增量的收益全在 `check` 上 —— 一次全量 = N 次 Chrome 启动。

**JSON 输出便于程序化消费**

`check --json` 返回 `{ok, lint, runtime, layout, motion, contrast}`,
Rule Guard 按字段分流,判断哪些属于已知模式、哪些要回落给 LLM。

> 结论:`lint` 是 `check` 的真子集且有盲点,`check` 是唯一有效但慢的门 ——
> 中间那层 <1s 的确定性检查(Rule Guard)就是为此存在。

---

# 附录 L：并行子 agent 机制

HF Step 5(写合成)是最耗时环节,通过 `frame-packets.mjs` 并行化:

1. 每个 storyboard frame 生成一个**自包含 packet**
2. packet 内联该 frame 需要的全部内容:storyboard block + blueprint 完整代码 + rule recipes
3. 子 agent 只看自己的 packet + `frame.md`,**从不打开** `STORYBOARD.md` 或 skill 文档
4. 只能写 `compositions/frames/NN-*.html`

**意义:每个子 agent 上下文完整但窗口极小,并行执行,遗忘风险最低。**

这正是 Rule Guard 的设计参考 —— 与其依赖记忆,不如每次重新加载。

