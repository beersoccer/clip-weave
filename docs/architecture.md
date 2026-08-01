# clip-weave 架构方案

> 文档版本：v6.1 | 更新日期：2026-07-29
> HF 能力分析见 `hyperframes-analysis.md`；技术选型见 `tech-selection.md`
>
> **v6.1 变更**：新增 § 3.2.1 Rule Guard 实现状态与待办（源码核对）；
> Kling Bridge → T2V Bridge（复用 STORYBOARD.md 走文生视频，跳过写 HTML）；
> § 9 移除误导性成本表；§ 10 HeyGen 内网屏蔽已解决，待切云厂商账号。

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
| Rule Guard | 生成前后确定性规则守卫，绕开 LLM 上下文压缩导致的规则遗忘 |
| Fix Registry | 已知错误定位 + 模板化修复，避免 lint 循环反复烧 token |
| T2V Bridge | 复用 `STORYBOARD.md` 交文生视频模型直出写实镜头，跳过写 HTML（P3）|

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
   Python 层预检 4 条 HF 特有规则（<1s）
   命中已知模式 → Fix Registry 确定性改
   仅未知错误 → 反馈给 HF skill 修
       │
       ▼
⑥ npx hyperframes check [变更文件] → render
   → renders/output.mp4
       │
       ▼
⑦（P3）T2V 旁路：STORYBOARD.md → 文生视频模型 → FFmpeg 合流
   与 ④⑤⑥ 并列的第二条渲染路径，跳过写 HTML
```

**关键：** 步骤 ①②③⑤ 是 clip-weave 独有价值，④⑥完全委托 HF。

**两条渲染路径共用同一份 `STORYBOARD.md`：**

| | HTML 路径（④⑤⑥）| T2V 旁路（⑦，P3）|
|---|---|---|
| 做法 | LLM 写 HTML/CSS/GSAP → HF 逐帧渲染 | 分镜描述直接交文生视频模型 |
| 画面性质 | 图形/文字/UI/图表，代码级精度 | 写实画面、实景、镜头运动 |
| 可控性 | 每帧可复现 | 有随机性，靠改提示词迭代 |
| 主要开销 | LLM 写 + `check` 循环的时间 | 模型推理费用与排队 |
| 不适合 | 电影级写实、真人出镜、复杂物理 | 精确文字排版、品牌色严格一致、数据准确性 |

因为共用 STORYBOARD.md，选哪条路径是**分镜级别**的决策而非项目级别 —— 这是 P4 混排的基础。

> ⚠️ 混排必须在 **FFmpeg 层合流**，不要把 T2V 生成的片段当 `<video>` 塞进 HTML 合成。
> 原因：Chrome 无法同时 seek 多个 `<video>`（解码器耗尽），视频密集合成会退化为单 worker
> 甚至超时。详见 `hyperframes-analysis.md` § 2.6 / § 9.6。

---

## 3. 解决 HF 三大痛点

### 3.1 规则遗忘

**问题：** `media_in_subcomposition`、`gsap_css_transform_conflict`、`gsap_timeline_set_initial_hide`、`preserve-3d + filter` 这 4 条 HF 特有约束不在通用 Web 文档里。长会话上下文压缩后 LLM 易遗忘，导致已修复错误重现。

**方案：Rule Guard 反复重放**

Python 层确定性规则检查器，**不依赖 LLM 记忆**：

| 规则 | 检测方式 | 备注 |
|------|--------|------|
| `media_in_subcomposition` | **grep**：`grep -nE '<(video\|audio)\b' compositions/*.html` | ⚠️ lint 显式盲点，必须 grep 手动检查 |
| `gsap_css_transform_conflict` | 交叉检查：同一 selector 是否 CSS `transform: translateX/Y()` + GSAP `x/y` 冲突 | lint 可检测 |
| `gsap_timeline_set_initial_hide` | 扫描：是否在 timeline 外（页面加载时）对后面场景的 clip 元素调用 `gsap.set()` | 这些 clip 在加载时不在 DOM 里，应改用 `tl.set(sel, vars, time)` |
| `preserve-3d + filter` | AST：`transform-style:preserve-3d` 元素的祖先链上是否有 `filter` | check 可检测 |

**执行时机：** 每次 HF skill 写完 composition → Rule Guard 立即扫描 → 命中规则时生成结构化错误报告 + 修复模板 → 回传 HF skill。规则清单每次都从磁盘重新加载，不受 LLM 上下文压缩影响。

### 3.2 Lint 循环耗时耗 token（当前最高优先级）

**问题：** `npx check` 单次 10-30s（需启动 headless Chrome），一个 composition 平均 2-3 轮，长视频总耗时上百秒。LLM 每轮重写整个 composition，可能重新引入已修复错误，形成 lint → 改 → 再 lint 死循环。

**方案：三层拦截**

**第 1 层：Pre-flight 本地拦截（<1s）**
Rule Guard 在 Python 层跑，能拦截的错误绝不进入 `npx check`。

**第 2 层：Fix Registry（`rule_guard.py` 的 `_FIXERS` 注册表）**

设计上按 `rule_id` 查表，分两条出路：修复机械且语义等价 → Python 直接改写 HTML 落盘、
标记 `fixed`、跳过 LLM 回合；修复涉及语义判断 → 输出违规位置 + 修复模板，回落给 HF skill。

| 错误模式 | 处理方式 | 有自动 fixer？ |
|--------|---------|--------------|
| GSAP `x/y:` + CSS `translateX/Y()` 共存 | 报告违规行 + 模板：`left: calc(50% - <half-width>px)` 替换 `transform: translateX(-50%)` | ❌ **刻意不做** —— pixel→percent 语义不等价，机械替换会让元素位移错误 |
| `<video>` 出现在 compositions/*.html | 报告位置；需上提到 index.html root 直接子元素 | ❌ 未实现（见 § 3.2.1）|
| 页面加载时 `gsap.set()` 作用于后续场景的 clip | 报告；改用 `tl.set(sel, vars, time)` 放入 timeline | ❌ 未实现 —— 需推断目标 clip 的 `data-start` |
| `preserve-3d` 祖先带 `filter` | 报告；把 filter 下移到叶子元素 | ❌ 未实现 —— 需判断哪个叶子该承载 filter |

**第 3 层：违规指纹 + 增量 check**
- 每个违规算 `sha1(rule_id + 文件名 + 行号)[:12]` 指纹，落盘到
  `<project>/.clip-weave/guard-history.json`，用于识别"同一错误第二次出现"
- 只 check 本次变更的 composition（`npx hyperframes check <file>`），未变更的跳过

**预期效果：** 拦截在 Python 层的错误 0 token 消耗，LLM 只处理真正新出现的问题；
长视频 lint 循环总时长和 token 消耗预计降 30-50%（预估口径，尚待长视频实测）。

### 3.2.1 实现状态与待办（2026-07-29 核对源码）

> 汇报材料（`report-tech-leads.md`）只讲设计与已跑通部分，本节是准确底账。

**已实现并有测试覆盖：**

| 能力 | 位置 | 说明 |
|------|------|------|
| 4 条规则检测器 | `rule_guard.py` 的 4 个 `_check_*` 函数 | 输出 `rule_id` + 文件 + 行号 + 说明 |
| 误报抑制 | `_check_gsap_timeline_set_initial_hide` | 缩进 > 4 空格视为在回调内（ScrollTrigger / onComplete）→ 跳过 |
| 违规指纹计算与持久化 | `Violation.__post_init__` + `save_history()` | 写入 `.clip-weave/guard-history.json`，追加不覆盖 |
| 增量 check | `hyperframes.py` 的 `check(project_dir, file=None)` | 支持单文件 |
| Fix Registry 分流骨架 | `scan()` 内 `_FIXERS.get(rule_id)` 分支 | fixer 存在则改写落盘并记 `fixed`，否则记 `unknown` |

**两处尚未接入：**

**① `_FIXERS` 注册表为空 → 无任何自动修复**

```python
_FIXERS: dict = {}   # rule_guard.py:111，当前无条目
```

后果：`_FIXERS.get(rule_id)` 恒为 `None`，4 条规则的违规全部走 `else` 分支进入
`result.unknown`，`result.fixed` 在实际运行中始终为空。
**第 2 层当前的实际价值是精确定位（文件 + 行号 + 修复模板），不是自动修。**

**② 指纹只写不读 → "复现即换策略"未生效**

`save_history()` 内部虽然读取旧文件，但那只是为了追加合并后写回；
代码库中没有任何位置消费 `guard-history.json` 做决策。
因此"同签名再次出现 → 强制走 Fix Registry 兜底，不再交给 LLM"这条控制逻辑不存在，
指纹目前是一份日志而非控制信号。

**附带问题：指纹对行号敏感。** 当前指纹含行号，而 LLM 重写整个 composition 后行号极易漂移，
同一语义错误换行号即变成新指纹，识别不出复现。这是实现强制分流前必须先解决的前置问题。

**待办清单（按性价比排序）：**

| # | 待办 | 工作量 | 判断 |
|---|------|--------|------|
| 1 | 指纹改为行号无关（`rule_id` + 违规代码片段规范化哈希） | 小 | **优先做** —— 强制分流的前置条件，当前指纹形同失效 |
| 2 | 消费 `guard-history.json`：同指纹复现 → 不再交 LLM，直接报告并升级为人工介入 | 小 | **优先做** —— 直接解 `check → 改 → 再 check` 死循环 |
| 3 | `media_in_subcomposition` 自动 fixer：把 `<video>`/`<audio>` 节点搬到 `index.html` root 直接子元素 | 中 —— 需保持 `id`、样式引用、GSAP 选择器不断 | 值得做 —— 这条是 lint 显式盲点，且修法最接近机械 |
| 4 | `gsap.set()` → `tl.set()` 自动 fixer | 中 —— 需解析目标 clip 的 `data-start` 作为插入时间 | 可做，风险中等 |
| 5 | `preserve-3d + filter` 自动 fixer | 大 —— 需判断 filter 该落到哪个叶子元素 | 暂不做，保持报告 |
| 6 | GSAP transform 冲突自动 fixer | 大且有风险 | **明确不做** —— 语义不等价，见上表 |

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

### 4.3 Rule Guard + Fix Registry

见 § 3.1 § 3.2。位于 `src/clip_weave/adapters/rule_guard.py`。

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
│   │   ├── hyperframes.py              # HF CLI 封装（init/capture/check/render）
│   │   ├── rule_guard.py               # 规则守卫 + Fix Registry
│   │   ├── asset_matcher.py            # 素材语义匹配
│   │   └── t2v.py                      # 文生视频旁路：STORYBOARD.md → 视频片段（P3，待建）
│   └── core/
│       ├── intent_router.py            # 用户输入 → workflow + BRIEF.md
│       ├── project_factory.py          # BRIEF.md + capture/ + frame.md 组装
│       └── delegator.py                # 调 Claude Code + skill
├── skills/
│   └── clip-weave/
│       ├── SKILL.md                    # 入口 skill（clip-weave 使用说明 + 意图引导）
│       └── references/
│           ├── brief-template.md       # BRIEF.md 可离线填写模板（含注释）
│           ├── setup.md                # Provider 配置指南（API Key / config.yaml）
│           └── input-guide.md          # 4 种素材输入方式详解
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
| **P1** | 解决 lint 痛点 | 4 条 HF 高频规则检测器；Fix Registry 分流骨架；违规指纹持久化；增量 check | ✅ 完成（2 项未接入，见 § 3.2.1）|
| **P2** | 提升素材利用率 | Asset Matcher（Vision 描述增强 + Embedding/BM25 top-K 检索）；capture 噪声过滤 | ✅ 完成 |
| **P3** | **T2V 旁路** | 复用 `STORYBOARD.md` 交文生视频模型直出，跳过写 HTML；FFmpeg 合流；`visual_type` 路由 | 🔲 待验证 |
| **P4** | 两条路径混排 | 同一支视频内动效镜头（HTML 路径）与写实镜头（T2V 路径）并存，FFmpeg 层合流 | 🔲 P3 验证后 |

**当前状态**：P0–P2 全部交付，33 个测试通过。P3 是下一个里程碑。

> **P1 的两处未接入**（`_FIXERS` 空、指纹只写不读）不影响 P0–P2 的可用性 ——
> 第 1 层 Pre-flight 拦截和增量 check 都已生效。详见 § 3.2.1 待办清单。

---

## 9. 开销参考

> 原 v6.0 的美元成本对照表已移除 —— 只覆盖模型调用费，漏掉了最大的成本项（生成时间与迭代轮数），
> 容易给出误导性结论。改为按主要开销类型区分。

| 路径 | 主要开销 | 说明 |
|------|---------|------|
| HTML 路径 | **时间** —— LLM 写 composition + `check` 循环 | 模型调用费极低（30s 视频量级 ~$0.05）；瓶颈是每次 `check` 10-30s × 每合成 2-3 轮 |
| T2V 旁路（P3）| **推理费用 + 排队** | 按秒计费，且长视频需排队；时间不可控性来自服务端 |

**Rule Guard 预计带来的节省**：拦截在 Python 层的错误零 token 处理，
长视频（10+ compositions）lint 环节耗时与 token 消耗预计降 30-50%。
该数字为预估口径，尚待长视频实测；且当前 `_FIXERS` 为空（§ 3.2.1），
节省主要来自第 1 层 Pre-flight 拦截与增量 check，而非自动修复。

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
