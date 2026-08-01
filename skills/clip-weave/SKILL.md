---
name: clip-weave
description: >
  Entry point for clip-weave: guided video creation with HyperFrames. Use for any
  request to make a brand video, product promo, explainer, motion graphic, or any
  HyperFrames composition when the user wants intent interview assistance, automated
  workflow routing, or asset matching. clip-weave wraps /hyperframes with a lower-friction
  front door — intent interview, BRIEF.md generation, asset pre-matching, and lint
  rule guard — then delegates execution entirely to HF skills. Install clip-weave
  skills first; then /hyperframes + its workflow skills do the actual building.
---

# clip-weave — intent interview + workflow router

clip-weave 补位 HyperFrames 缺失的几件事：**意图路由、素材匹配、装配前规则预检、
渲染路径决策**。HF 原生能力（BRIEF.md、capture、frame.md、compositions、lint/check/render）
直接复用，不重造。

> **技能版本已固定。安装完成后，任何情况下都不要主动升级技能。**
> `npx hyperframes skills update` 唯一许可的调用点是 `scripts/install.sh` 的一次性引导安装。
> 此后即使察觉技能版本落后、或 HF 打印版本告警，也只能提示用户，等用户明确要求
> （例如「更新技能」/「update skills」）才执行。擅自升级会让已部署的 Agent 在会话中途
> 因上游技能变更而中断。注意：`npx hyperframes init` 自身的内部版本检查由框架控制，
> 无法在此抑制。
>
> **clip-weave 是 HyperFrames 的前门** —— 生成 `BRIEF.md` 后交给对应的
> `/hyperframes` workflow。它从不重造 HF 已有的能力。

## Installation (one command)

从 clip-weave 项目根运行一次，安装全部依赖 —— HF 技能、Python 包
（Rule Guard / Asset Matcher / T2V）：

```bash
bash scripts/install.sh
```

它做两件事：

1. `npx hyperframes skills update` —— 安装/刷新 HF 技能到 `~/.claude/skills/`。
   **这是本项目中该命令唯一许可的调用点**，属于一次性引导，不违反上面的固定版本约定。
2. `uv pip install -e ".[dev]"` —— 安装 Python 包。

安装后确认：

```bash
uv run python -m clip_weave --help   # 应列出 run / guard / match-assets / route / gen-video
npx hyperframes auth status          # signed in = 音频可用；signed out = 静音模式
```

## 1. Start from project state

Apply the first matching row:

| State | Action |
|-------|--------|
| `videos/<project>/BRIEF.md` exists | Read `workflow` and `flow`; run `/hyperframes` directly; ask no intent questions |
| `hyperframes.json` or `STORYBOARD.md` exists, no BRIEF.md | Infer workflow from artifacts; resume from HF project state |
| User provides a pre-filled `BRIEF.md` file | Validate frontmatter; proceed to § 4 (Project Setup) |
| Fresh request | Run intent interview (§ 2) |

## 2. Intent interview

**Check preferences first** (`~/.hyperframes/prefs` if it exists) — use remembered language, style, and presets as defaults without asking again.

Run the interview in this order, one question at a time (no survey forms):

### Step 1 — Identify asset source (determines input path)

Detect from the user's message without asking if obvious:

| Detected input | Input path | clip-weave action |
|---------------|-----------|------------------|
| `http/https` URL (non-figma.com) | website capture | `npx hyperframes capture <URL>` → `capture/` |
| `figma.com` URL | Figma import | run `/figma` skill first → produces `capture/` + `tokens.json` |
| Uploaded file(s) in agent workspace | local assets | copy to `capture/assets/`; generate synthetic `tokens.json` |
| Text description only (no URL, no file) | no-capture | synthesize `tokens.json` from brief; use `faceless-explainer` default |

If ambiguous, ask: **"您有素材来源吗？（网站 URL / Figma 链接 / 上传文件 / 纯文字描述）"**

See `references/input-guide.md` for handling each path in detail.

### Step 2 — Core message

Ask: **"这个视频要传达的核心信息是什么？一句话概括。"**

This maps to `message:` in `BRIEF.md`. Required; do not proceed without it.

### Step 3 — Length and format

Suggest defaults based on workflow:
- product-launch-video / faceless-explainer → 30s, 1920×1080
- motion-graphics → 8s, 1920×1080
- slideshow → any (navigable deck, not MP4)

Confirm or adjust. Maps to `length:` and `aspect:` (derived from `destination:`).

### Step 4 — Autonomous or collaborative

Ask only if not clear from context:
**"您希望全自动生成（无需审批），还是逐步审批每个阶段？"**

| User signal | `flow` | `storyboard` | Mode |
|------------|--------|-------------|------|
| "直接做 / 全自动 / just do it" | `automation` | `no` | **autonomous**（默认）|
| "逐步 / 我想看分镜 / collaborative" | `automation` | `yes` | collaborative |
| "一起做 / companion" | `companion` | — | companion |

**Default: autonomous** (`flow: automation, storyboard: no`). Both modes produce identical artifacts.

### Step 5 — Confirm summary

Show a one-paragraph BRIEF.md preview. Ask: **"确认后开始，或需要调整？"**

## 3. Route to HF workflow

Use the first matching row (mirrors `/hyperframes` routing):

| Intent keywords | Workflow |
|----------------|---------|
| 产品发布 / 品牌视频 / 网站宣传 / URL | `product-launch-video` |
| 解说 / 教程 / 纯文字 / 无 URL | `faceless-explainer` |
| 动效 / 标题卡 / 覆盖层 / <10s | `motion-graphics` |
| 字幕 / 加字幕 | `embedded-captions` |
| 演示 / pitch / 幻灯片 | `slideshow` |
| 音乐同步 / 节拍 | `music-to-video` |
| PR / commit / 代码变更 | `pr-to-video` |
| No match | ask once; fallback `general-video` |

关键词匹配在否定或次要语境里会误判（"我们不做产品广告，只讲讲这个概念"命中"产品"→误路由到
`product-launch-video`，真实意图是 `faceless-explainer`）。不确定或想核对时用语义分类器：

```bash
uv run python -m clip_weave route "用户的原话"
uv run python -m clip_weave route "用户的原话" --compare   # 语义结果与关键词结果并排显示
```

语义分类失败（网关未配置、网络不可用、答案无法解析）会静默降级到关键词匹配，不阻塞流程。

## 4. Project setup

```bash
PROJECT_DIR="videos/<project-name>"
mkdir -p "$PROJECT_DIR"
npx hyperframes init "$PROJECT_DIR" --non-interactive --example=blank

# If URL source:
npx hyperframes capture "<URL>" -o "$PROJECT_DIR/capture"

# If Figma source: run /figma skill, then copy output to capture/
# If local files: already in agent workspace → copy to capture/assets/
```

Write `BRIEF.md` to `$PROJECT_DIR/BRIEF.md` using the confirmed intent interview answers.
Template: `references/brief-template.md`.

**渲染路径也在这一步问一次**（见 § 8），或者通过 CLI 一并决定：

```bash
uv run python -m clip_weave run --message "核心信息" --url "<URL>" --render ask
# --render html | t2v | mixed | ask（默认 ask：已设置过就复用，没设置过则询问）
```

## 5. Asset Matcher (if capture/ has assets)

After capture completes, run Asset Matcher before delegating to HF:

```bash
uv run python -m clip_weave match-assets "$PROJECT_DIR"
```

Three-phase pipeline (phases are independent — each degrades separately):

1. **Vision enrichment** (`VIDEO_ANALYSIS_*`) — calls `/chat/completions` to generate rich visual
   descriptions for each image, replacing DOM-derived stubs. Skipped if not configured.
2. **Semantic embedding** (`EMBEDDING_*`) — calls `/v1/embeddings` (OpenAI-compatible) for
   cosine-similarity ranking; catches synonyms and cross-language matches BM25 misses.
   Skipped if not configured.
3. **BM25 fallback** — always available, no config required.

See `references/setup.md` for environment variable reference and degradation table.

The filter step (project_factory.py) removes noise assets automatically after capture:
favicons, QR codes, WhatsApp icons, hash-named SVG icon sprites, and images > 1.5 MB.

## 6. Delegate to HF workflow

Once `BRIEF.md` exists, hand off to HF:

```bash
# Activate the routed workflow skill — HF reads BRIEF.md and runs autonomously
/<workflow-name>
# e.g.: /product-launch-video, /faceless-explainer, /motion-graphics
```

clip-weave does NOT re-implement composition building, storyboard generation,
frame rendering, lint, check, or render — these are entirely owned by HF skills.

## 7. Rule Guard (pre-assembly pre-flight)

**Prerequisite:** `uv pip install -e .`（`scripts/install.sh` 已包含）。

每个 HF sub-agent 写完 composition 后运行：

```bash
uv run python -m clip_weave guard "$PROJECT_DIR"
```

**Rule Guard 只检查一条规则**，因为只有这一条经核对确认 HF 原生能力覆盖不到：

- `media_in_subcomposition` —— `<video>`/`<audio>` 必须是 `index.html` 根的直接子元素。
  放在 sub-composition 里的媒体永不被 seek/解码，渲染为黑屏/白屏。

HF 自己的 lint 也实现了这条规则（error 级），但在 clip-weave 工作的两个窗口里它是失效的：
装配前 `index.html` 还不存在，整个 lint 跑不起来；传单文件入口时 HF 不设置
`isSubComposition`，该规则直接跳过。所以这条预检是补位，不是重造。

**其余规则一律交给 HF 原生 lint，不要在 clip-weave 侧重造。** 核对过 HF 源码后发现：
CSS/GSAP transform 冲突检测 HF 已用 AST 解析器实现得更好；`gsap.set()` 初始隐藏那条
HF 的真实语义与直觉相反（豁免 timeline 外的 `gsap.set()`，警告的是 timeline 内 position 0
的零时长 `tl.set()`）；preserve-3d + filter 的冲突需要完整 CSS 级联与祖先链解析，
无法在正则层可靠判定。详见 `docs/architecture.md` § 3.1。

**check 的覆盖率注意事项：** `npx hyperframes check <单个文件>` 会同时关闭
`media_in_subcomposition` 与全部项目级检查（缺失/空 sub-composition、重复 composition id、
重复音轨、缺失本地资源）。单文件 check 只用于快速迭代，**渲染前必须跑一次全项目 check**：

```bash
npx hyperframes check          # 全项目，完整覆盖
```

## 8. 渲染路径：HTML 还是 T2V

HTML 路径（HF skill 写 composition → 逐帧渲染）适合图形、文字、UI、图表 —— 确定性、
零推理费用，而且是唯一能把字体、品牌色和数据渲染准确的路径。写实画面、实景、镜头运动
交给文生视频模型更合适。

**这个选择在项目之初由用户做一次**，写进 `BRIEF.md` frontmatter：

```yaml
---
workflow: product-launch-video
render: html      # html（默认）| t2v | mixed
---
```

`run` 命令会处理这个决策（`--render ask` 是默认值）：已设置过就复用并回显来源；没设置过、
且在交互终端里，会打印三个选项的取舍并用 `click.prompt` 问一次；非交互环境直接落到默认值
`html` 并说明如何覆盖。选定后写回 `BRIEF.md`，同一项目不会再问第二次。

只有 `render: mixed` 才需要逐帧标注，指出哪些镜头走 T2V：

```markdown
## Frame 2 — 实拍开场
- scene: 城市夜景中一辆红色轿车驶过湿滑路面
- visual_type: live_action
```

`motion` 走 HTML，`live_action` 走 T2V；未标注或取值无法识别的帧跟随项目默认，
`mixed` 项目里这类帧落到 **HTML**。

T2V 提示词不是即时拼装的，而是先落成 `T2V-PROMPTS.md` —— **那才是用户直接编辑的文件**：

```bash
uv run python -m clip_weave gen-video "$PROJECT_DIR/STORYBOARD.md" --provider doubao --prompts-only
# 生成/刷新 T2V-PROMPTS.md，不调用任何模型，不产生费用。编辑后再跑一次真正生成：
uv run python -m clip_weave gen-video "$PROJECT_DIR/STORYBOARD.md" --provider doubao --concat
```

若 `BRIEF.md` 写的是 `render: html` 却在跑 `gen-video`，命令会提示这个矛盾并要求确认
（`--yes` 跳过确认，非交互环境不询问）。

以图文/数据为主的帧会被 `T2V-PROMPTS.md` 标记 `needs_review` —— 文生视频渲染文字不可靠，
这些帧建议留在 HTML 路径。provider 选型、时长约束、GCP project 配置、混排注意事项见
`references/t2v-guide.md`。

## Resume table

| State | Continue from |
|-------|--------------|
| No `BRIEF.md`, no project | § 2 (intent interview) |
| Pre-filled `BRIEF.md` uploaded | § 4 (project setup) |
| `hyperframes.json` exists, no `BRIEF.md` | § 4 (project setup, skip init) |
| `BRIEF.md` exists | `/hyperframes` directly |
| Composition written, Rule Guard not run | § 7 (guard) |
| Guard passed, check/render pending | continue in HF workflow |
| `BRIEF.md` 的 `render:` 为 `t2v` 或 `mixed` | § 8（渲染路径） |
