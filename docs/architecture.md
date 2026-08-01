# clip-weave 架构方案

> 文档版本：v7.0 | 更新日期：2026-07-31
> HF 能力分析见 `hyperframes-analysis.md`；技术选型见 `tech-selection.md`
>
> **v7.0 变更**：按 HF 源码逐条核对 Rule Guard 四条规则，删除三条（两条与 HF 原生重复
> 或语义相反，一条无法可靠判定），只保留 `media_in_subcomposition`，并记录其真实价值
> 边界（装配前 + 单文件入口两个窗口）；取消指纹规范化与历史消费；补记增量 check 的
> 覆盖率损失；T2V 路径实际实现状态（三家 provider、用户可编辑的 `T2V-PROMPTS.md`、
> 项目级 `render:` 决策，取代此前设想的逐帧路由）。

---

## 1. 系统定位

**clip-weave = HyperFrames 前置门面 + 稳定性补丁。**

不重造 HF 已有能力，只补 HF 缺失的三件事：**意图路由、素材匹配、规则守卫**。

### 1.1 分工边界

HF 各阶段产出物已经十分完备，clip-weave **直接复用**：

| HF 原生产出物 | 作用 | clip-weave 是否重造 |
|-------------|------|------------------|
| `BRIEF.md` | brief + workflow + flow 三合一入口 | ❌ 直接生成 HF 标准格式 |
| `frame.md` | 设计系统（色/字/间距 preset） | ❌ 调 `build-frame.mjs` |
| `capture/` 目录 | 素材 + tokens + asset-descriptions | ❌ 调 `npx hyperframes capture` |
| `STORYBOARD.md` | 分镜脚本 | ❌ 用 HF 标准格式 |
| Skills 系统 | 10 个 workflow + 8 个领域技能 | ❌ 直接激活 |
| lint / check / render | 完整渲染管线 | ❌ 直接调用 |

clip-weave 补位（HF 缺失或用户体验不足）：

| clip-weave 模块 | 解决什么 |
|--------------|--------|
| Intent Router | 用户对话/YAML → HF workflow 选择 + BRIEF.md 自动生成 |
| Asset Matcher | asset-descriptions.md → 语义匹配 → STORYBOARD `asset_candidates` |
| Rule Guard | 装配前预检 `media_in_subcomposition` —— HF lint 有此规则但在装配前与单文件入口两个窗口失效 |
| T2V 路径 | 复用 `STORYBOARD.md` 交文生视频模型直出写实镜头，跳过写 HTML；渲染路径由用户在项目之初选定 |

---

## 2. 执行流程

```
用户输入（对话 或 极简 project.yaml）
       │
       ▼
① Intent Router（clip-weave）
   意图分析 → 选 HF workflow（/product-launch-video 等）
   → BRIEF.md（HF 标准 frontmatter，flow: automation + storyboard: no）
       │
       ▼
② Project Factory（clip-weave）
   npx hyperframes init "videos/<name>"
   npx hyperframes capture "<URL>"（如有源）
   build-frame.mjs → frame.md
       │
       ▼
③ Asset Matcher（clip-weave）
   Vision 增强 asset-descriptions.md（VIDEO_ANALYSIS_* 网关）
   BM25 top-K 检索 → 写入 STORYBOARD.md 的 asset_candidates 字段
       │
       ▼
④ 委托 Claude Code + HF Skill 执行
   激活 workflow skill（BRIEF.md 存在 → autonomous 模式，无对话）
   生成 compositions/*.html
       │
       ▼
⑤ Rule Guard 拦截（clip-weave，在 HF check 之前）
   Python 层预检 media_in_subcomposition（<1s，仅这一条规则，见 § 3.1）
       │
       ▼
⑥ npx hyperframes check [变更文件] → render
   → renders/output.mp4
       │
       ▼
⑦ 渲染路径决策（BRIEF.md 的 render: html | t2v | mixed）
   render: html → 步骤 ④⑤⑥ 就是终点
   render: t2v / mixed → STORYBOARD.md → T2V-PROMPTS.md（用户可编辑）→ 文生视频模型 → FFmpeg 合流
```

**关键：** 步骤 ①②③⑤ 是 clip-weave 独有价值，④⑥完全委托 HF。

**渲染路径是项目级决策，不是分镜级。** 逐帧判断走 HTML 还是 T2V 对用户过于复杂，因此在
项目之初问一次、写进 `BRIEF.md` 的 `render:` 并持久化（`run --render ask` 默认行为）。
只有 `render: mixed` 才需要逐帧标注（`visual_type: motion | live_action`），指出个别镜头。

| | HTML 路径（④⑤⑥）| T2V 路径（⑦）|
|---|---|---|
| 做法 | LLM 写 HTML/CSS/GSAP → HF 逐帧渲染 | `T2V-PROMPTS.md` 提示词交文生视频模型 |
| 画面性质 | 图形/文字/UI/图表，代码级精度 | 写实画面、实景、镜头运动 |
| 可控性 | 每帧可复现 | 有随机性，靠改提示词迭代 |
| 主要开销 | LLM 写 + `check` 循环的时间 | 模型推理费用与排队 |
| 不适合 | 电影级写实、真人出镜、复杂物理 | 精确文字排版、品牌色严格一致、数据准确性 |
| 默认 | ✅ 确定性、零推理费用 | 需显式选择 |

> ⚠️ `render: mixed` 混排必须在 **FFmpeg 层合流**，不要把 T2V 生成的片段当 `<video>`
> 塞进 HTML 合成。原因：Chrome 无法同时 seek 多个 `<video>`（解码器耗尽），视频密集
> 合成会退化为单 worker 甚至超时。详见 `hyperframes-analysis.md` § 2.6 / § 9.6，
> 以及 `skills/clip-weave/references/t2v-guide.md`。

---

## 3. 解决 HF 的实际痛点

### 3.1 规则遗忘（已按源码核对收缩）

**原判断：** 4 条 HF 特有约束不在通用 Web 文档里，长会话上下文压缩后 LLM 易遗忘，
需要 Python 层确定性守卫反复重放。

**核对结论：** 这个判断对其中 3 条不成立。核对 HyperFrames 源码
（`packages/lint/src/rules/gsap.ts`、`media.ts`、`packages/lint/src/project.ts`）后的
实际情况：

| 规则 | HF 源码事实 | clip-weave 决定 |
|------|-----------|----------------|
| `media_in_subcomposition` | `media.ts` 有实现（error 级）；`project.ts` 递归遍历 `compositions/**/*.html` 逐个以 `isSubComposition: true` 送检 | **保留** —— 但价值边界不同于原判断，见下 |
| `gsap_css_transform_conflict` | `gsap.ts` 有实现（error 级），基于 acorn AST 解析器，可解析计算式 timeline、标签位置、standalone 调用；`from` 与 `fromTo` 均豁免；冲突属性不含 `rotation` | **删除** —— Python 正则版严格劣于 HF 原生 |
| `gsap_timeline_set_initial_hide` | HF 真实语义**相反**：警告 timeline 内 position 0 的零时长 `tl.set(...)`，并明确豁免 timeline 之外的 `gsap.set()`；HF 自己的单测断言顶层 `gsap.set` 必须不报 | **删除** —— 原实现报的正是 HF 断言不该报的写法，且建议改成 HF 真规则要警告的写法 |
| `preserve-3d + filter` | HF 全部 lint code 中无此项 | **删除** —— 机制为真，但可靠判定需完整 CSS 级联 + 祖先链解析，正则层做不到；实测在 HF 官方 3D 镜头范例上误报 |

**保留那一条的真实理由**（不是"lint 盲点"）：HF 的 lint 规则本身是完整的，但在
clip-weave 工作的两个窗口里失效：

1. **装配前** —— `project.ts` 的入口逻辑第一步就读 `index.html`，尚未装配时整个 lint
   跑不起来。这正是 `frame-worker-core.md` 描述的"假绿灯"窗口。
2. **单文件入口** —— `project.ts` 传入显式 entry 文件时跳过 `compositions/` 遍历，且不
   设置 `isSubComposition`，而规则首行就是 `if (!options.isSubComposition) return findings;`。

规则本身是 `variables-and-media.md` 的 NON-NEGOTIABLE 约束（媒体必须是 `index.html` 根的
直接子元素，否则永不被 seek/解码，渲染黑屏），grep 判定精确、误报空间接近零。

**指导原则（后续新增任何检查前必须先满足）：** HF 已实现且实现更优的检查不重造；机制无法
在 HF 源码中证实的规则不实现；不确定时宁可使用 HF 原生能力。任何可能把正确代码判为违规的
检查，净收益为负 —— 它会引导 LLM 把正确代码改错。

`tests/test_rule_guard.py` 中的「HF 官方正确写法零误报」测试是这条原则的可执行守卫：
它把 HF 文档记载的正确写法（preserve-3d 叶子 DoF filter、顶层 `gsap.set`、`fromTo`
静态居中）固化成断言，任何试图把三条被删规则加回来的改动会立刻让它失败。

### 3.2 Lint 循环耗时耗 token

**问题：** `npx check` 单次 10-30s（需启动 headless Chrome），一个 composition 平均 2-3 轮，
长视频总耗时上百秒。LLM 每轮重写整个 composition，可能重新引入已修复错误，形成
lint → 改 → 再 lint 死循环。

**方案：两层**

**第 1 层：Pre-flight 本地拦截（<1s）**
Rule Guard 在 Python 层跑一条规则（`media_in_subcomposition`），装配前即可发现，
避免装配后才在 lint 里暴露。

**第 2 层：增量 check**
只 check 本次变更的 composition（`npx hyperframes check <file>`），未变更的跳过。

> ⚠️ **增量 check 有覆盖率代价。** 传入显式 entry 会使 HF 把该文件当作根合成：跳过
> `compositions/` 遍历且不设 `isSubComposition`，于是 `media_in_subcomposition` 与全部
> 项目级检查（缺失/空 sub-composition、重复 composition id、重复音轨、缺失本地资源、
> HEVC 提示）全部失效。**策略：单文件 check 仅用于迭代，渲染前必须跑一次全项目
> `npx hyperframes check`。** `adapters/hyperframes.py` 在单文件模式下会打印该警示，
> 并提供 `check_full()` 表达意图。

**原第 2 层 Fix Registry 已移除。** 唯一保留的规则在装配前没有可写目标 —— 修法是把媒体
节点搬到 `index.html` 根，而那个文件此时还不存在。

**原第 3 层的违规指纹 + 历史消费已取消。** 指纹规范化的目的是识别"同一语义错误复现"，
前提是存在多条语义模糊的规则；"复现即升级人工介入"用在一条判定确定的 error 级规则上，
等于给确定结论加冗余闸门。`guard-history.json` 保留为日志，不作为控制信号。

### 3.2.1 实现状态（2026-07-31 核对 HF 源码后）

**已实现并有测试覆盖：**

| 能力 | 位置 |
|------|------|
| `media_in_subcomposition` 检测器 | `rule_guard.py` 的 `_check_media_in_subcomposition` |
| HF 官方正确写法零误报回归测试 | `tests/test_rule_guard.py` |
| 违规指纹计算与持久化（仅作日志） | `Violation.__post_init__` + `save_history()` |
| 增量 check + 覆盖率警示 | `hyperframes.py` 的 `check(file=…)` / `check_full()` |

**已删除（连同其设计意图）：** 三个检测器、`_FIXERS` 注册表、`GuardResult.fixed` 字段、
指纹规范化待办、历史消费待办。理由见 § 3.1。

**反面案例值得留档：** `gsap_timeline_set_initial_hide` 的语义倒置源于把
`determinism-rules.md` 的一条窄约束（"不要对后续场景的 clip 调用 `gsap.set()`"）与一个
同名 lint code 混为一谈，然后两者都没实现对。后者的真实语义是相反方向。更进一步，
那条窄约束自身的机制也不成立：HyperFrames 运行时（`packages/core/src/runtime/init.ts`）
显示 clip 从不从 DOM 移除（容器 `visibility: hidden`，叶子 timed clip `display: none`，
靠 `querySelectorAll("[data-start]")` 枚举）。**文档与运行时冲突时以运行时为准。**

### 3.3 素材利用率低

**问题：** `npx capture` 抓 100+ 张图，v1 版本只用 2 张。原因：agent 在长上下文里没系统读完 `asset-descriptions.md`，且 HF 无自动匹配。

**方案：Asset Matcher 三阶段流水线（业界最佳实践）**

1. **Vision 描述增强**（依赖 `VIDEO_ANALYSIS_*`）：调企业网关的 `/chat/completions` 接口，对每张素材图生成高质量视觉描述，替换 capture 产出的 DOM 粗描述
2. **Embedding 语义检索**（依赖 `EMBEDDING_*`）：调 OpenAI 兼容的 `/v1/embeddings` 接口，将 beat 查询和所有素材描述批量 embedding，cosine 相似度排序 — 能捕获 BM25 遗漏的同义词和跨语言语义（"专业团队" ↔ "professional advisory team"）
3. **BM25 关键词兜底**：Embedding 不可用时自动降级，无需任何配置

两个阶段**完全独立**，互不依赖：

| 阶段 | 降级行为 |
|------|---------|
| Vision 增强不可用（`VIDEO_ANALYSIS_*` 未配置）| 跳过增强，使用 capture 原始描述；不影响 Embedding |
| Embedding 不可用（`EMBEDDING_*` 未配置或端点故障）| 直接降级到 BM25；与 Vision 配置无关 |

HF skill 拿到的 `asset_candidates` 是已排好序的 3–5 张候选。

**图片过滤规则（优先级从高到低）**：
1. 正向白名单：文件名含 `logo/brand/wordmark/trademark/emblem` → 无条件保留
2. 噪声模式：favicon、QR 码、WhatsApp 图标、webpack hash-named sprite → 删除
3. SVG 无大小限制：品牌 logo 常是 2–20 KB 矢量，不做大小过滤
4. 栅格图片 > 1.5 MB → 删除（照片/横幅通常不适合直接用作品牌元素）

---

## 4. 核心补位模块

### 4.1 Intent Router

**输入：** 用户对话文本、已有 BRIEF.md、或上传的素材文件
**输出：** HF 标准 `BRIEF.md`（如已存在则直接继续，不重新生成）

#### 4.1.1 输入类型检测（优先级从高到低）

| 检测到的输入 | 路由到 | clip-weave 动作 |
|------------|-------|---------------|
| `videos/<project>/BRIEF.md` 已存在 | 直接委托 HF workflow | 跳过 Intent Router，不提任何问题 |
| 网站 URL（http/https，非 figma.com）| `product-launch-video`（默认）| `npx hyperframes capture <URL>` → capture/ |
| `figma.com` URL | 由 brief 决定 | 先调 `/figma` skill → 产出 capture/ + tokens.json |
| 上传的本地文件（图片/音频/视频）| 由 brief 决定 | 文件已在 agent workspace → 复制到 `capture/assets/`，生成 synthetic tokens.json |
| 纯文字描述（无 URL 无文件）| `faceless-explainer`（默认）| no-capture 路径，合成 tokens.json |

#### 4.1.2 Workflow 映射

| 用户意图关键词 | 匹配 workflow |
|-------------|--------------|
| 产品发布 / 品牌视频 / 网站宣传 / URL | `product-launch-video` |
| 解说 / 教程 / 纯文字 / 无 URL | `faceless-explainer` |
| 动效 / 标题卡 / 覆盖层 / <10s | `motion-graphics` |
| 字幕 / 加字幕 | `embedded-captions` |
| 演示文稿 / pitch / 幻灯片 | `slideshow` |
| 音乐同步 / 节拍 / 音乐驱动 | `music-to-video` |
| PR / commit / 代码变更 | `pr-to-video` |
| 无匹配 | 反问一次；fallback `general-video` |

#### 4.1.3 Mode 检测（写入 BRIEF.md frontmatter）

HF 的两种模式产出物**完全相同**（BRIEF.md、STORYBOARD.md、compositions、renders/video.mp4），
区别仅在于 checkpoint gate 行为：autonomous 模式自动通过所有检查点，collaborative 模式在每个检查点暂停等待用户确认。

| 用户信号 | `flow` | `storyboard` | 推导模式 |
|---------|--------|-------------|---------|
| "直接生成 / 不用问我 / just do it / autonomous" | `automation` | `no` | **autonomous**（clip-weave 默认）|
| "帮我一步步做 / 我想参与审批 / collaborative" | `automation` | `yes` | collaborative（有 storyboard 审核）|
| "一起做 / companion" | `companion` | — | companion（在 `/general-video` 执行）|

**clip-weave 默认写 `flow: automation, storyboard: no`（autonomous 模式）**，
适合 pipeline 自动化场景。用户可在填写 BRIEF.md 模板时显式覆盖。

### 4.2 Asset Matcher

见 § 3.3。位于 `src/clip_weave/adapters/asset_matcher.py`。

### 4.3 Rule Guard

见 § 3.1 § 3.2。位于 `src/clip_weave/adapters/rule_guard.py`。单条规则，无 Fix Registry。

---

## 5. 用户输入形式

**`project.yaml` 已废弃，统一用 `BRIEF.md`。** BRIEF.md 是 HF 的单一 source of truth，clip-weave 完全复用其格式，不另立标准。

### 5.1 路径 A：对话式（适合普通用户）

```
> 帮我做个 30 秒的小米 SU7 品牌视频，用 https://xiaomiev.com/su7 的素材
```

clip-weave 的 SKILL.md 运行 intent interview → 引导用户提供必要信息 → 生成 BRIEF.md，缺关键信息则反问（一次一个字段，避免表单式问卷）。interview 结束时展示 BRIEF.md 摘要请用户确认。

**引导流程（对话式 intent interview）：**

1. 检查 `~/.hyperframes/prefs` 记忆的用户偏好（语言/风格/preset），有则作为推荐选项
2. 识别素材来源（URL / Figma URL / 已上传文件 / 纯文字），路由到对应的 input path
3. 提问核心信息：视频要传达的**一句话核心消息**（message）
4. 确认时长和画幅（提供推荐值）
5. 询问审批偏好：是否需要逐步审批（autonomous / collaborative）
6. 可选：是否选用某个风格模板（展示 frame preset 预览链接）

### 5.2 路径 B：BRIEF.md 模板（适合离线填写 / 批量场景）

用户下载模板 `skills/clip-weave/references/brief-template.md`，离线填写后上传到 agent workspace，放在任意位置，clip-weave 检测到后直接用。

模板结构见 `skills/clip-weave/references/brief-template.md`。BRIEF.md 存在时 clip-weave 跳过所有引导问题，直接进入 Project Factory。

### 5.3 路径 C：CLI 单行命令（适合开发者）

```bash
python -m clip_weave run \
  --url "https://xiaomiev.com/su7" \
  --message "小米 SU7 好看·好开·舒适·安全" \
  --length 30s
```

等价于路径 A，只是跳过对话，参数直接映射到 BRIEF.md frontmatter。

### 5.4 Provider 配置

clip-weave 通过以下环境变量配置 AI 模型，均在 `.env` 文件中设置：

两组变量相互独立，任意一组缺失只影响对应阶段，不影响另一阶段。

**Vision 增强（Phase 1）— 素材图像理解**

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `VIDEO_ANALYSIS_BASE_URL` | 企业 AI 网关地址（需支持 `/chat/completions`）| 空（跳过增强）|
| `VIDEO_ANALYSIS_API_KEY` | 网关 Key | 空 |
| `VIDEO_ANALYSIS_MODEL` | 视觉模型名称 | `gemini-2.5-flash` |

**Embedding 语义检索（Phase 2）— 素材匹配**

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `EMBEDDING_BASE_URL` | OpenAI 兼容 Embedding 网关地址（需支持 `/v1/embeddings`）| 空（降级 BM25）|
| `EMBEDDING_API_KEY` | 网关 Key | 空 |
| `EMBEDDING_MODEL` | Embedding 模型名称 | `text-embedding-3-small` |

**其他**

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `GEMINI_API_KEY` | HF capture 素材描述生成（由 HF 读取，非 clip-weave）| 空（降级无描述）|

详见 `skills/clip-weave/references/setup.md`。

---

## 6. 目录结构

```
clip-weave/
├── config.yaml                         # Provider 配置（可选，env var 优先）
├── .env.example                        # 环境变量示例
├── src/clip_weave/
│   ├── pipeline.py                     # 顶层编排：Intent → Factory → Delegate → Guard
│   ├── adapters/
│   │   ├── hyperframes.py              # HF CLI 封装（init/capture/lint/check/check_full/render）
│   │   ├── rule_guard.py               # 单规则装配前预检（media_in_subcomposition）
│   │   ├── asset_matcher.py            # 素材语义匹配
│   │   └── video_gen/                  # 文生视频 provider
│   │       ├── base.py                 # ProviderConfig / VideoModel / submit→poll→download
│   │       ├── doubao.py               # 豆包 Seedance（Volcengine Ark 协议）
│   │       ├── ali.py                  # 通义万相（DashScope 异步协议）
│   │       ├── vertex.py               # Google Veo（predictLongRunning）
│   │       └── gcp_project.py          # Vertex 所需 GCP project id 解析
│   └── core/
│       ├── intent_router.py            # 用户输入 → workflow + BRIEF.md
│       ├── workflow_router.py          # LLM 语义 workflow 分类（关键词为兜底）
│       ├── project_factory.py          # BRIEF.md + capture/ + frame.md 组装
│       ├── delegator.py                # 调 Claude Code + skill
│       ├── storyboard.py               # STORYBOARD.md 解析 + 基础提示词回落
│       ├── render_path.py              # 项目级 render: html|t2v|mixed（默认 HTML）
│       ├── t2v_prompt.py               # 生成用户可编辑的 T2V-PROMPTS.md
│       └── video_pipeline.py           # 逐帧生成 + manifest + FFmpeg 合流
├── skills/
│   └── clip-weave/
│       ├── SKILL.md                    # 入口 skill（clip-weave 使用说明 + 意图引导）
│       └── references/
│           ├── brief-template.md       # BRIEF.md 可离线填写模板（含注释）
│           ├── setup.md                # Provider 配置指南（API Key / config.yaml）
│           ├── input-guide.md          # 4 种素材输入方式详解
│           └── t2v-guide.md            # T2V 渲染路径：provider 选型、时长约束、GCP project 配置
├── videos/                             # 每个项目工作目录（HF 标准结构）
│   └── <project-name>/
│       ├── BRIEF.md                    # HF 标准
│       ├── capture/                    # HF 标准
│       ├── frame.md                    # HF 标准
│       ├── compositions/               # HF 标准
│       └── renders/
└── docs/
```

**安装为 Claude Code skills：**

```bash
# 项目本地安装（仅在该工作目录下可用，推荐）
cp -r skills/clip-weave .claude/skills/clip-weave

# 全局安装（所有项目均可用）
cp -r skills/clip-weave ~/.claude/skills/clip-weave

# 符号链接（开发调试，修改即时生效）
ln -sf "$(pwd)/skills/clip-weave" .claude/skills/clip-weave
```

重启 Claude Code 后，在对话中输入 `/clip-weave` 即可激活意图引导流程。

**相比 v5.0 移除：**
- `templates/` 目录 —— HF registry + skills 已含预制模板
- 自定义 `STORYBOARD.json` —— 改用 HF 标准 `STORYBOARD.md`
- `project.yaml` —— 改用 BRIEF.md（HF 标准格式）
- `core/html_generator.py`、`core/storyboard_generator.py` —— 委托 HF skills，不重造

---

## 7. 与 HF 的解耦边界

clip-weave 只依赖以下稳定接口，与 HF 内部实现完全解耦：

| 接口 | 说明 |
|------|------|
| `npx hyperframes init` | 初始化项目，生成 `hyperframes.json` |
| `npx hyperframes capture <URL>` | 抓取素材 + tokens + asset-descriptions |
| `build-frame.mjs --preset <name>` | 从 tokens.json 生成 frame.md |
| `BRIEF.md` frontmatter schema | 固定字段规范，不依赖 HF 源码 |
| `npx hyperframes check [file]` | 支持指定文件的增量检查，返回码 0/非 0 |
| `npx hyperframes render` | 标准渲染命令 |
| Claude Code Skill 调用协议 | `/<workflow-name>` 激活对应 skill |

---

## 8. 实施路线图

| 阶段 | 目标 | 核心交付 | 状态 |
|------|------|---------|------|
| **P0** | 打通链路：意图 → HF autonomous 执行 | Intent Router；BRIEF.md 生成器；Project Factory（`init` + `capture` 封装）；Delegator；`skills/clip-weave/` 入口 skill | ✅ 完成 |
| **P1** | 解决 lint 痛点 | 按 HF 源码核对后收缩为单规则装配前预检；增量 check 及其覆盖率策略 | ✅ 完成（三条规则经核对删除，见 § 3.1）|
| **P2** | 提升素材利用率 | Asset Matcher（Vision 描述增强 + Embedding/BM25 top-K 检索 + 质量下限过滤）；capture 噪声过滤 | ✅ 完成 |
| **P3** | **T2V 路径** | STORYBOARD.md 解析；三家 provider；逐帧生成 + manifest；FFmpeg 合流；项目级 `render:` 路径选择；用户可编辑的 `T2V-PROMPTS.md` | ✅ 代码完成，待真实网关实测 |
| **P4** | 两条路径混排 | `render: mixed` 项目内动效镜头（HTML 路径）与写实镜头（T2V 路径）并存，FFmpeg 层合流 | 🔲 P3 实测后 |

**当前状态**：P0–P3 代码全部交付，257 个测试通过。P3 待真实网关实测；P4 混排待 P3
实测后设计。

**渲染路径是项目级决策。** 逐帧判断走 HTML 还是 T2V 对用户过于复杂，因此改为在项目之初
问一次、写进 `BRIEF.md` 的 `render:` 并持久化。`mixed` 时才用帧上的
`visual_type: motion | live_action` 指出个别镜头。默认 HTML —— 确定性、零推理费用，
且是唯一能准确渲染字体、品牌色与数据的路径。

---

## 9. 开销参考

> 原 v6.0 的美元成本对照表已移除 —— 只覆盖模型调用费，漏掉了最大的成本项（生成时间与迭代轮数），
> 容易给出误导性结论。改为按主要开销类型区分。

| 路径 | 主要开销 | 说明 |
|------|---------|------|
| HTML 路径 | **时间** —— LLM 写 composition + `check` 循环 | 模型调用费极低（30s 视频量级 ~$0.05）；瓶颈是每次 `check` 10-30s × 每合成 2-3 轮 |
| T2V 路径 | **推理费用 + 排队** | 按秒计费，且长视频需排队；时间不可控性来自服务端 |

**Rule Guard 的收益已按核对结果下调。** 它现在只拦截一条规则，节省来自"装配前发现
黑屏级缺陷"而非"减少 lint 轮数"。原先设想的 30-50% 降幅建立在四条规则与自动修复之上，
那两个前提都已不成立，故移除该数字。

---

## 10. 音频能力（后续增强计划）

HyperFrames 原生支持 TTS 配音和 BGM 背景音乐，通过 `audio.mjs` 脚本统一管理。
clip-weave 通过 `STORYBOARD.md` frontmatter 传递音频参数，不重造音频逻辑。

### 10.1 HeyGen 音频（推荐 — 在线，支持中文）

> **当前状态（2026-07-29 更新）**：`api.heygen.com` 内网屏蔽问题**已解决**。
> 已用 HeyGen **个人账号**验证通过：TTS 配音 + 版权 BGM 均可用，中文声线质量满足要求。
>
> **待办**：切换到公司已采购的云厂商账号/额度，走合规通道。个人账号仅用于能力验证，
> 不作为交付路径。切换后凭证仍在 `~/.heygen`，`STORYBOARD.md` 的 `music` / `voice` 字段无需改动。

HeyGen 提供高质量 TTS（含中文声线）和版权音乐库。需要帐号授权：

```bash
npx hyperframes auth login    # 浏览器 OAuth，凭证存于 ~/.heygen
npx hyperframes auth status   # 显示 "signed in" = 音频已启用
```

> **注意**：`auth status` 未登录时退出码为 1，这是正常状态，不代表命令失败，不要用 `&&` 或 `set -e` 链接。

登录后，`STORYBOARD.md` 中指定音频参数：

```yaml
music: ambient-corporate     # HeyGen 音乐库 mood 查询
voice: Marcia                # 声线 id（列表：npx hyperframes tts --list）
```

- 中文配音建议优先使用 HeyGen 声线（质量显著高于 Kokoro）
- BGM 采用 HeyGen 音乐库检索（非 AI 生成），复用同一 `~/.heygen` 凭证

**验证步骤：**

1. `npx hyperframes auth login` 完成浏览器授权
2. `npx hyperframes auth status` 确认输出 "signed in"
3. 在项目目录运行音频生成脚本（需先有 `SCRIPT.md` 和 `STORYBOARD.md`）：

```bash
SKILL_DIR=$(node -e "console.log(require('path').dirname(require.resolve('hyperframes/package.json')))")
node "$SKILL_DIR/skills/product-launch-video/scripts/audio.mjs" \
  --script ./SCRIPT.md \
  --storyboard ./STORYBOARD.md \
  --hyperframes . \
  --out ./audio_meta.json \
  --provider heygen
```

4. 检查 `audio_meta.json` 含 `bgm` 和 `voice_segments` 字段 → 验证通过

### 10.2 Kokoro TTS（离线，英文为主）

```bash
pip install kokoro soundfile   # 核心依赖
pip install misaki             # 可选：更好的音素化
```

声线命名前缀：`am_`/`bm_` = 男声，`af_`/`bf_` = 女声，`z` = 中文（效果有限）。

### 10.3 静音视频（当前默认）

`STORYBOARD.md` 顶部 YAML 块设置以下两项：

```yaml
music: none
```

同时**不创建 `SCRIPT.md`**。音频管线检测到此组合后完全跳过，不调用任何 TTS/BGM API。

### 10.4 依赖汇总

| 能力 | 依赖 | 配置方式 |
|------|------|---------|
| HeyGen TTS + BGM | `npx hyperframes auth login` | `~/.heygen` 凭证文件 |
| Kokoro TTS | `pip install kokoro soundfile` | 无需额外配置 |
| 语音时间戳同步 | HF `audio.mjs sync-durations` | 需先生成 `audio_meta.json` |

音频能力完全属于 HyperFrames 层，clip-weave 不封装也不重造，仅通过 `STORYBOARD.md` 传递参数。
