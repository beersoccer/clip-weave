# clip-weave 架构方案

> 文档版本：v6.0 | 更新日期：2026-07-24
> HF 能力分析见 `hyperframes-analysis.md`；技术选型见 `tech-selection.md`

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
| Fix Registry | 已知错误模板化修复，避免 lint 循环反复烧 token |
| Kling Bridge | 写实镜头混合（P3） |

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
   读 capture/extracted/asset-descriptions.md → 生成 embedding
   为 STORYBOARD 每个 beat 检索 top-K 候选素材
   写入 STORYBOARD.md 的 asset_candidates 字段
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
⑦（可选，P3）Kling 写实镜头 + FFmpeg 合流
```

**关键：** 步骤 ①②③⑤ 是 clip-weave 独有价值，④⑥完全委托 HF。

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

**第 2 层：Fix Registry 确定性修复（无 LLM 参与）**

| 错误模式 | 确定性修复 |
|--------|---------|
| GSAP `x:` + CSS `translateX()` 共存 | 自动改 GSAP 为 `xPercent:` |
| `<video>` 出现在 compositions/*.html（非 index.html 直接子元素）| 自动上提到 index.html 的根节点直接子元素 |
| 页面加载时 `gsap.set(clipEl, ...)` 作用于后面场景的 clip（该 clip 不在 DOM）| 自动改为 `tl.set(clipEl, vars, data-time-in-value)` 放入 timeline |
| `preserve-3d` 祖先带 `filter` | 自动把 filter 下移到叶子元素 |

命中已知模式 → Python 直接改 HTML → 跳过 LLM 修复回合。仅未知错误才回落到 HF skill。

**第 3 层：修复历史 + 增量 check**
- 每个 composition 记录已修复错误签名（错误类型 + 位置指纹），Rule Guard 检测到"同签名再次出现"→ 强制走 Fix Registry 兜底，不再交给 LLM
- 只 check 本次变更的 composition（`npx hyperframes check <file>`），未变更的跳过

**预期效果：** 已知错误 100% 拦截在 Python 层（0 token 消耗），LLM 只处理真正新出现的问题；长视频 lint 循环总时长和 token 消耗预计降 30-50%。

### 3.3 素材利用率低

**问题：** `npx capture` 抓 100+ 张图，v1 版本只用 2 张。原因：agent 在长上下文里没系统读完 `asset-descriptions.md`，且 HF 无自动匹配。

**方案：Asset Matcher 强制填充候选**

1. clip-weave 读 `capture/extracted/asset-descriptions.md`
2. 一次性调 Gemini/OpenAI 为每张素材生成 embedding，缓存到 `capture/extracted/embeddings.json`
3. STORYBOARD 生成前，clip-weave 为每个 beat 的意图文本算 embedding，检索 top-K 素材，写入 STORYBOARD.md 的 `asset_candidates` 字段
4. HF skill 拿到的 STORYBOARD 里 `asset_candidates` 已经是筛选好的短列表（3-5 张），把"在 100+ 张图中自由发挥"变成"在候选中选"

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

### 5.4 Provider 配置（Asset Matcher 等 AI 模型选择）

Provider 配置通过环境变量或项目根目录的 `config.yaml` 指定，两者均可，env var 优先级更高：

```yaml
# config.yaml（放在 clip-weave 项目根目录，可选）
providers:
  embedding: gemini          # gemini | openai | local（asset matcher 用）
  vision: gemini             # gemini | openai（asset-descriptions 补全用）
  tts: heygen                # heygen | kokoro（本地，需 HF auth）
```

对应 env var：`GEMINI_API_KEY`、`OPENAI_API_KEY`。

**HF `capture` 命令本身已使用 `GEMINI_API_KEY`**（生成 asset-descriptions.md），
clip-weave 的 Asset Matcher 复用同一个 key，无需额外配置。若 key 不存在，
asset-descriptions.md 为空时 Asset Matcher 退化为无 embedding 的关键词匹配。

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
│   │   └── kling.py                    # image-to-video（P3）
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

**安装为 agent skills：**

```bash
# 方式一：通过 skills CLI 安装（推荐）
npx skills add <your-org>/clip-weave --full-depth

# 方式二：直接复制 skills/ 目录到 agent workspace
cp -r skills/clip-weave ~/.hyperframes/skills/
```

安装后，在 Claude 对话中输入 `/clip-weave` 即可激活意图引导流程。

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
| **P0** | 打通链路：意图 → HF autonomous 执行 | Intent Router；BRIEF.md 生成器；Project Factory（`init` + `capture` 封装）；Delegator；`skills/clip-weave/` 入口 skill（可 `npx skills add` 安装） | 🔲 实施中 |
| **P1** | **解决 lint 痛点（当前最高优）** | 4 条 HF 高频规则的 Python AST 检测器；4 条规则的 Fix Registry 确定性 fixer；修复历史签名追踪；增量 check 集成 | 🔲 待启动 |
| **P2** | 提升素材利用率 | Asset Matcher（embedding + top-K 检索）；STORYBOARD `asset_candidates` 填充；embedding 缓存 | 🔲 待启动 |
| **P3** | 写实镜头混合路径 | Kling image-to-video 封装；FFmpeg 合流；STORYBOARD `visual_type` 路由 | 🔲 待验证 |
| **P4** | ViMax 全 AI 真实影像（可选） | `adapters/vimax.py`；screenplay 转换 | 🔲 P3 验证后 |

**P1 是最高优先级**：lint 循环是用户体验最大痛点，Rule Guard + Fix Registry 是能立刻见效的杠杆，且不依赖 P0 全量完成即可独立验证。

---

## 9. 成本参考

以 30s 视频、写实镜头占比 40%（12s）为例：

| 路径 | 成本 | 适用场景 |
|------|------|---------|
| 纯 HyperFrames | ~$0.05 | 全动效/文字视频（品牌发布、数据可视化） |
| HF + Kling 混合 | ~$1.7（Kling 12s × $0.14） | 含写实镜头的品牌视频 |
| HF + ViMax | ~$5–15 | 全 AI 真实影像 |

**Rule Guard 预计带来的节省**：拦截已知模式在 Python 层零 token 处理，长视频（10+ compositions）lint 环节 token 消耗预计降 30-50%。
