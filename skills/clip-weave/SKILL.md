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

> **Keep skills current:** `npx hyperframes skills update` before any creation session.
> **clip-weave is a front door to HyperFrames** — it generates `BRIEF.md` then hands off
> to the appropriate `/hyperframes` workflow. It never rebuilds what HF already provides.

# clip-weave — intent interview + workflow router

clip-weave补位 HyperFrames 缺失的三件事：**意图路由、素材匹配、规则守卫**。
HF 原生能力（BRIEF.md、capture、frame.md、compositions、render）直接复用，不重造。

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

## 5. Asset Matcher (if capture/ has assets)

After capture completes, run Asset Matcher before delegating to HF:

```bash
python -m clip_weave match-assets "$PROJECT_DIR"
```

This pre-computes embeddings for `capture/extracted/asset-descriptions.md` and writes
`asset_candidates` into each beat of `STORYBOARD.md` before the HF skill runs.
Provider: configured via `GEMINI_API_KEY` (see `references/setup.md`).
If key is absent, falls back to keyword matching.

## 6. Delegate to HF workflow

Once `BRIEF.md` exists, hand off to HF:

```bash
# Activate the routed workflow skill — HF reads BRIEF.md and runs autonomously
/<workflow-name>
# e.g.: /product-launch-video, /faceless-explainer, /motion-graphics
```

clip-weave does NOT re-implement composition building, storyboard generation,
frame rendering, lint, check, or render — these are entirely owned by HF skills.

## 7. Rule Guard (post-composition)

After each HF sub-agent writes a composition, run the Python pre-flight check:

```bash
python -m clip_weave guard "$PROJECT_DIR/compositions"
```

Rule Guard checks 4 HF-specific rules before `npx check` (saves 10-30s per round):
- `media_in_subcomposition` — grep for `<video>/<audio>` in compositions/*.html
- `gsap_css_transform_conflict` — CSS transform + GSAP x/y on same element
- `gsap_timeline_set_initial_hide` — gsap.set() on clip elements outside timeline
- `preserve-3d + filter` — filter on ancestor of preserve-3d element

Known patterns → Fix Registry (deterministic Python fix, 0 tokens).
Unknown errors → pass through to `npx hyperframes check`.

## Resume table

| State | Continue from |
|-------|--------------|
| No `BRIEF.md`, no project | § 2 (intent interview) |
| Pre-filled `BRIEF.md` uploaded | § 4 (project setup) |
| `hyperframes.json` exists, no `BRIEF.md` | § 4 (project setup, skip init) |
| `BRIEF.md` exists | `/hyperframes` directly |
| Composition written, Rule Guard not run | § 7 (guard) |
| Guard passed, check/render pending | continue in HF workflow |
