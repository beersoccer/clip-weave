# Rule Guard 有效性收缩 + T2V 逐帧路由 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Rule Guard 从 4 条规则收缩到 1 条经 HF 源码证实必要的规则，为已落地但零覆盖的 T2V 路径补齐测试，实现 `visual_type` 逐帧路由，并让全部项目文档与代码一致。

**Architecture:** 三段独立推进。① Rule Guard 删除 3 条与 HF 原生能力重复或语义错误的检测器，只保留 `media_in_subcomposition`，并把"HF 官方正确写法零误报"固化为回归测试。② 为 `core/storyboard.py`、`core/video_pipeline.py`、`adapters/video_gen/*`、`adapters/video_gen/gcp_project.py` 补离线测试。③ 渲染路径为项目级决策（`BRIEF.md` 的 `render:`，默认 HTML），已由 `core/render_path.py` 实现，本计划为其补齐测试并覆盖 `T2V-PROMPTS.md` 的 override 管道。

**Tech Stack:** Python 3.11+、pytest 8、click 8、requests、pyyaml、hatchling。测试全部离线，不触达真实网关。

## Global Constraints

- 指导原则：clip-weave 对 HF 的每一处优化都必须经 HF 源码核对确认必要；HF 已实现且实现更优的检查不重造；机制无法在 HF 源码中证实的规则不实现；不确定时宁可使用 HF 原生能力。
- HF 源码核对基线路径：`/Users/beersoccer/workspace/hyperframes`。
- 不新增任何运行时依赖。`pyproject.toml` 的 `dependencies` 保持 `pyyaml>=6.0`、`requests>=2.31`、`python-dotenv>=1.0`、`click>=8.0` 四项不变。
- 所有测试必须离线。禁止在测试中发起真实 HTTP 请求或调用 `npx`/`ffmpeg`/`gcloud` 真实二进制。
- 保留中文注释与中文日志的既有风格；新增代码的 docstring 用英文（与 `src/clip_weave/` 现状一致）。
- 每个任务结束时 `.venv/bin/python -m pytest -q` 必须全绿。
- 提交信息用 Conventional Commits，与仓库既有历史一致（`feat(scope):` / `fix(scope):` / `test(scope):` / `docs:` / `refactor(scope):`）。

## 计划修订（2026-07-31，Task 2 之后）

用户在另一会话中做了一个设计决定，本计划据此修订：**逐帧决定走 HTML 还是 T2V 过于复杂，
渲染路径应在项目之初由用户决定。**

已落地的实现（继承，不重做）：

- `core/render_path.py` —— 项目级 `render: html | t2v | mixed` 写在 BRIEF.md frontmatter，
  首次询问后 `persist()` 持久化；`visual_type: motion | live_action` 仅作为 `mixed` 情形下的
  逐帧覆盖。默认 HTML。
- `core/t2v_prompt.py` —— 生成用户可直接编辑的 `T2V-PROMPTS.md`，槽位顺序按各厂商提示词
  指南收敛的结果排列，复用 Asset Matcher 已打分的素材引用，合并 storyboard 负面提示与常备
  规则，标记图形密集帧为不适合 T2V，并支持 markdown 往返以保住手工编辑。
- `video_pipeline.generate_clips()` 新增 `prompt_overrides` / `duration_overrides` /
  `negative_overrides` / `reference_overrides`，使 `T2V-PROMPTS.md` 优先于生成的提示词。
- `asset_matcher` 为候选打分并按质量下限过滤；`storyboard.Frame` 新增
  `asset_candidates()` / `focal_asset()`，`Storyboard` 新增 `direction`。

对本计划的影响：

| 任务 | 变化 |
|------|------|
| Task 8 | **整体重写** —— 不再新建 `core/visual_route.py`，改为给 `render_path.py` 补齐测试 |
| Task 9 | **整体重写** —— 路由接线已不需要，改为给 override 管道补测试 |
| Task 4 | 需额外覆盖 `storyboard.py` 新增的 `asset_candidates()` / `focal_asset()` / `direction` |
| Task 10–13 | 文档与技能须描述**项目级 `render:` + `T2V-PROMPTS.md`** 工作流，**不得**使用原计划的逐帧 `visual_type: t2v / chart / text_card` 词表 |

Task 1–3、5–7 不受影响。

---

## File Structure

新建：

| 文件 | 责任 |
|------|------|
| `tests/test_rule_guard.py` | Rule Guard 全部测试，含"HF 官方正确写法零误报"回归资产 |
| `tests/test_storyboard.py` | STORYBOARD.md 解析器与提示词构造 |
| `tests/test_render_path.py` | 项目级 `render:` 决策：resolve / persist / frame_path |
| `tests/test_video_gen_providers.py` | 三家 provider 的请求体构造与状态映射 |
| `tests/test_video_pipeline.py` | 生成流水线（注入假 `VideoModel`）与 FFmpeg 合流 |
| `tests/test_gcp_project.py` | GCP project 解析优先级 |
| `tests/test_project_factory.py` | 从 `test_pipeline.py` 拆出的素材过滤测试 |
| `tests/test_asset_matcher.py` | 从 `test_pipeline.py` 拆出的匹配降级测试 |
| `skills/clip-weave/references/t2v-guide.md` | T2V 旁路使用指南 |

修改：

| 文件 | 修改 |
|------|------|
| `pyproject.toml` | 新增 `[tool.pytest.ini_options]` |
| `src/clip_weave/adapters/rule_guard.py` | 删 3 个检测器、`_FIXERS`、`GuardResult.fixed`；修 `save_history` 两个缺陷；重写 docstring |
| `src/clip_weave/pipeline.py` | `guard()` 去掉对 `result.fixed` 的引用 |
| `src/clip_weave/adapters/hyperframes.py` | `check()` 单文件模式加覆盖率警示；新增 `check_full()` |
| `tests/test_pipeline.py` | 移除已拆出的测试，只保留 pipeline 编排测试 |
| `skills/clip-weave/SKILL.md` | 安装矛盾、结构、Rule Guard 单规则、T2V 章节 |
| `docs/architecture.md` | § 3.1 / § 3.2 / § 3.2.1 / § 4.3 / § 6 / § 8 / § 9 |
| `README.md`、`docs/report-tech-leads.md`、`docs/hyperframes-analysis.md`、`.env.example` | 表述与代码对齐 |

---

## Task 1: pytest 配置与测试文件拆分

把 `test_pipeline.py` 里混入的 project_factory / asset_matcher / rule_guard 测试拆出去，为后续任务腾出干净的模块边界。本任务不改任何生产代码。

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/test_project_factory.py`
- Create: `tests/test_asset_matcher.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: 无
- Produces: `pytest` 可在仓库根直接运行（`testpaths = ["tests"]`、`pythonpath = ["src"]`）；`tests/test_pipeline.py` 之后只含 pipeline 编排测试

- [ ] **Step 1: 记录当前测试基线**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest -q`
Expected: `33 passed`。把这个数字记下来，拆分后总数必须仍是 33（只是分布到更多文件）。

- [ ] **Step 2: 给 `pyproject.toml` 加 pytest 配置**

在文件末尾追加：

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-ra"
```

- [ ] **Step 3: 验证配置生效**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest -q`
Expected: `33 passed`，且不再需要任何 `PYTHONPATH` 环境变量。

- [ ] **Step 4: 新建 `tests/test_project_factory.py`**

内容（从 `tests/test_pipeline.py` 的 `test_filter_removes_noise_but_keeps_logos` 与 `test_filter_keeps_small_svgs_unconditionally` 整体搬移，并把函数内 import 提到模块顶层）：

```python
"""Tests for Project Factory capture-asset filtering."""

from clip_weave.core.project_factory import _filter_capture_assets


def test_filter_removes_noise_but_keeps_logos(tmp_path):
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()

    # Noise — should be removed
    noise = [
        "favicon.ico",
        "wechat_qrcode.png",
        "whatsapp.svg",
        "svg-a1b2c3d4.svg",
        "social-icons.png",
        "loader.gif",
    ]
    # Logos — must be preserved even though some have short/simple names
    logos = [
        "logo.svg",
        "brand-logo.png",
        "noah-wordmark.svg",
        "company_emblem.png",
    ]
    # Normal assets — not noise, not logo-flagged
    normal = ["hero-banner.png", "team-photo.jpg"]

    for name in noise + logos + normal:
        (assets_dir / name).write_bytes(b"x" * 100)

    _filter_capture_assets(assets_dir)

    remaining = {f.name for f in assets_dir.iterdir()}
    for name in logos + normal:
        assert name in remaining, f"Expected {name} to be kept"
    for name in noise:
        assert name not in remaining, f"Expected {name} to be removed"


def test_filter_keeps_small_svgs_unconditionally(tmp_path):
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    # An SVG with a plain name (not hash-named, no logo keyword) — keep it
    (assets_dir / "arrow-right.svg").write_bytes(b"<svg/>" * 10)
    # A hash-named SVG — remove
    (assets_dir / "svg-deadbeef.svg").write_bytes(b"<svg/>")

    _filter_capture_assets(assets_dir)

    assert (assets_dir / "arrow-right.svg").exists()
    assert not (assets_dir / "svg-deadbeef.svg").exists()
```

- [ ] **Step 5: 新建 `tests/test_asset_matcher.py`**

```python
"""Tests for Asset Matcher ranking and degradation."""

from clip_weave.adapters import asset_matcher
from clip_weave.adapters.asset_matcher import match_assets
from clip_weave.config import Config


def _write_descriptions(tmp_path, body: str):
    desc_file = tmp_path / "capture" / "extracted" / "asset-descriptions.md"
    desc_file.parent.mkdir(parents=True)
    desc_file.write_text(body, encoding="utf-8")
    return desc_file


def test_asset_matcher_bm25_fallback(tmp_path):
    """Without gateway config, should fall back to BM25 and return ranked results."""
    _write_descriptions(
        tmp_path,
        "- team.jpg — professional executives in formal meeting room\n"
        "- chart.png — bar chart showing revenue growth data\n"
        "- office.jpg — modern corporate office interior\n",
    )

    cfg = Config()  # no gateway configured
    results = match_assets(tmp_path, ["executive team meeting", "financial data"], top_k=2, cfg=cfg)

    assert len(results) == 2
    assert len(results[0]) > 0
    assert results[0][0]["filename"] == "team.jpg"


def test_asset_matcher_embedding_fallback_to_bm25(tmp_path, monkeypatch):
    """When embedding endpoint fails, should silently fall back to BM25."""
    _write_descriptions(tmp_path, "- logo.svg — gold and blue company logo\n")

    monkeypatch.setattr(asset_matcher, "_call_embedding_gateway", lambda *a, **k: None)

    cfg = Config(
        embedding_base_url="https://embed.example.com/v1/",
        embedding_api_key="test-key",
    )
    results = match_assets(tmp_path, ["brand identity"], top_k=1, cfg=cfg)
    assert len(results) == 1
    assert results[0][0]["filename"] == "logo.svg"
```

- [ ] **Step 6: 从 `tests/test_pipeline.py` 删除已搬移的测试**

删除这四个函数及其上方的 `# ── Image filtering ───` / `# ── Asset Matcher ───` 分节注释：
- `test_filter_removes_noise_but_keeps_logos`
- `test_filter_keeps_small_svgs_unconditionally`
- `test_asset_matcher_bm25_fallback`
- `test_asset_matcher_embedding_fallback_to_bm25`

同时删除 `test_guard_gsap_css_conflict_reported_without_auto_fix`（该测试断言的规则将在 Task 2 删除；Task 2 的新测试文件会覆盖 Rule Guard）。

并把文件顶部无用的 import 清掉，改为：

```python
"""Tests for the pipeline: Intent → Factory → Asset Match → Delegate."""

from unittest.mock import patch

from clip_weave.pipeline import run, guard
```

- [ ] **Step 7: 运行测试确认总数下降到 28**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest -q`
Expected: `28 passed`（33 − 5 个删除/搬移的：4 个搬到新文件后仍在，1 个 gsap 冲突测试被删）。

实际应为 `32 passed`：4 个搬移的测试在新文件里仍然运行，只有 1 个被删除。若数字不是 32，先排查再继续。

- [ ] **Step 8: 提交**

```bash
cd /Users/beersoccer/workspace/clip-weave
git add pyproject.toml tests/test_pipeline.py tests/test_project_factory.py tests/test_asset_matcher.py
git commit -m "test: add pytest config and split test_pipeline into per-module files"
```

---

## Task 2: Rule Guard 收缩到单条规则

删除 3 条与 HF 原生能力重复或语义错误的检测器，并把"HF 官方正确写法零误报"固化为回归测试。这是本计划中防止后续重复犯错的核心资产。

**Files:**
- Create: `tests/test_rule_guard.py`
- Modify: `src/clip_weave/adapters/rule_guard.py`
- Modify: `src/clip_weave/pipeline.py:130-145`

**Interfaces:**
- Consumes: 无
- Produces:
  - `RULE_IDS: list[str]` 只含 `"media_in_subcomposition"`
  - `Violation(rule_id, file, line, detail)`，`fingerprint` 仍由 `__post_init__` 计算
  - `GuardResult(violations, unknown)`，**不再有 `fixed` 字段**，`ok` 属性语义不变
  - `scan(compositions_dir) -> GuardResult`
  - `save_history(project_dir, result) -> None`

- [ ] **Step 1: 写失败测试 —— HF 官方正确写法必须零误报**

创建 `tests/test_rule_guard.py`：

```python
"""Tests for Rule Guard.

Scope note: Rule Guard deliberately implements ONE rule. The other three rules
it used to carry were removed after checking the HyperFrames source — see
docs/superpowers/specs/2026-07-31-rule-guard-soundness-and-t2v-routing-design.md
section 1. The zero-false-positive test below is the regression asset that keeps
them from being reintroduced.
"""

import json

from clip_weave.adapters.rule_guard import RULE_IDS, GuardResult, save_history, scan


# A composition built to HyperFrames' own canonical recipes:
#   - `.world` carries transform-style: preserve-3d and `.layer` carries the
#     leaf DoF filter — the placement 3d-camera-flight.md MANDATES.
#   - a top-level gsap.set() on a non-clip element — the pattern
#     packages/lint/src/rules/gsap.test.ts:2492 asserts must NOT be flagged,
#     and the fix gsap_fullscreen_overlay_starts_visible prescribes.
#   - a static transform: translateX(-50%) on an element animated only via
#     fromTo — both `from` and `fromTo` are exempt in HF's own rule.
# None of this is a violation. Rule Guard must stay silent.
HF_CANONICAL_COMPOSITION = """<template>
<div data-composition-id="03-flight" id="root">
  <div class="stage">
    <div class="world" id="world" data-layout-allow-overflow>
      <div class="card layer" id="card-a"></div>
    </div>
  </div>
  <div class="badge clip" data-start="0" data-duration="5" data-track-index="0"></div>
</div>
<style>
  .stage { position: absolute; inset: 0; perspective: 1200px; }
  .world { transform-style: preserve-3d; transform-origin: 50% 50%; }
  .layer { --dof: 0px; filter: blur(var(--dof)); }
  .badge { position: absolute; left: 50%; transform: translateX(-50%); }
</style>
<script>
  const tl = gsap.timeline({ paused: true });
  gsap.set(".layer", { opacity: 0 });
  tl.fromTo(".badge", { opacity: 0 }, { opacity: 1, duration: 0.4 }, 0);
  window.__timelines["03-flight"] = tl;
</script>
</template>"""


def test_only_one_rule_is_implemented():
    """Guards the scope decision: three rules were removed on purpose."""
    assert RULE_IDS == ["media_in_subcomposition"]


def test_hf_canonical_composition_produces_zero_violations(tmp_path):
    """HF's own documented-correct patterns must never be flagged."""
    (tmp_path / "hf-canonical.html").write_text(HF_CANONICAL_COMPOSITION, encoding="utf-8")

    result = scan(tmp_path)

    assert result.violations == [], [
        (v.rule_id, v.line, v.detail) for v in result.violations
    ]
    assert result.ok is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest tests/test_rule_guard.py -v`
Expected: 两个测试都 FAIL。`test_only_one_rule_is_implemented` 因 `RULE_IDS` 有 4 个元素；`test_hf_canonical_composition_produces_zero_violations` 报出 3 条违规（`gsap_css_transform_conflict`、`gsap_timeline_set_initial_hide`、`preserve_3d_filter`）。

- [ ] **Step 3: 重写 `src/clip_weave/adapters/rule_guard.py`**

整文件替换为：

```python
"""Rule Guard — pre-assembly pre-flight for the one HF rule that needs it.

Scope is deliberately narrow. Rule Guard used to carry four detectors; three
were removed after checking the HyperFrames source directly. Do not reintroduce
them — `tests/test_rule_guard.py` asserts the scope, and the design record is
`docs/superpowers/specs/2026-07-31-rule-guard-soundness-and-t2v-routing-design.md`.

Why the other three are gone:

* `gsap_css_transform_conflict` — HF implements it in
  `packages/lint/src/rules/gsap.ts` at error severity, on top of an acorn AST
  parser that resolves computed timelines, label positions and standalone
  `gsap.*` calls, and exempts both `from` and `fromTo`. A regex approximation is
  strictly worse and produces false positives on correct code.
* `gsap_timeline_set_initial_hide` — HF's rule of that name means the OPPOSITE.
  It warns about a zero-duration `tl.set(...)` at position 0 INSIDE the paused
  timeline (frame 0 renders un-hidden), and explicitly exempts off-timeline
  `gsap.set()`. `packages/lint/src/rules/gsap.test.ts:2492` asserts a top-level
  `gsap.set('#a', { opacity: 0 })` must NOT be flagged. The previous
  implementation flagged exactly that, and advised moving it into the timeline —
  which is what HF warns about.
* `preserve_3d_filter` — no HF lint code exists for it, but deciding whether a
  `filter` actually breaks a 3D context needs full CSS cascade resolution plus
  the ancestor chain. Not decidable at the regex layer, and the constraint is
  already inlined into each frame worker's packet.

What remains earns its place: `media_in_subcomposition` is a NON-NEGOTIABLE
constraint (`hyperframes-core/references/variables-and-media.md`) whose failure
mode is a black/blank render, and HF's own lint rule for it is inactive in two
windows that clip-weave operates in:

1. Pre-assembly — `packages/lint/src/project.ts:141` reads `index.html` first,
   so the whole lint cannot run before the project is assembled.
2. Single-file entry — `project.ts:165` skips the `compositions/` walk when an
   entry file is given and never sets `isSubComposition`, while the rule starts
   with `if (!options.isSubComposition) return findings;` (`media.ts:349`).
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

RULE_IDS = ["media_in_subcomposition"]

_MEDIA_TAG = re.compile(r"<(video|audio)\b")

_MEDIA_DETAIL = (
    "<video>/<audio> inside a composition file. HF requires media to be a DIRECT "
    "child of the host root (index.html); media inside a sub-composition is never "
    "seeked/decoded and renders BLANK/black. Move it to index.html root and drive "
    "per-scene motion from the MAIN timeline at global time."
)


@dataclass
class Violation:
    rule_id: str
    file: Path
    line: int
    detail: str
    fingerprint: str = field(init=False)

    def __post_init__(self):
        self.fingerprint = hashlib.sha1(
            f"{self.rule_id}:{self.file.name}:{self.line}".encode()
        ).hexdigest()[:12]


@dataclass
class GuardResult:
    violations: list[Violation] = field(default_factory=list)
    unknown: list[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.unknown) == 0


def _check_media_in_subcomposition(html: str, path: Path) -> list[Violation]:
    """<video>/<audio> must be a direct child of the index.html root."""
    violations = []
    for i, line in enumerate(html.splitlines(), 1):
        if _MEDIA_TAG.search(line):
            violations.append(
                Violation(
                    rule_id="media_in_subcomposition",
                    file=path,
                    line=i,
                    detail=_MEDIA_DETAIL,
                )
            )
    return violations


def scan(compositions_dir: Path) -> GuardResult:
    """Scan every HTML file under compositions_dir. No auto-fix by design.

    An auto-fixer would have to move the media node into `index.html`, which
    does not exist yet in the pre-assembly window this check exists for.
    """
    result = GuardResult()
    # **/*.html matches at all depths including the root of compositions_dir.
    for path in compositions_dir.glob("**/*.html"):
        html = path.read_text(encoding="utf-8", errors="replace")
        for v in _check_media_in_subcomposition(html, path):
            result.violations.append(v)
            result.unknown.append(v)
            logger.warning(
                "Rule violation: %s in %s:%d — %s", v.rule_id, path.name, v.line, v.detail
            )
    return result


def save_history(project_dir: Path, result: GuardResult) -> None:
    """Append violation fingerprints to a per-project log.

    This is a log, not a control signal: nothing reads it back to make
    decisions. With a single deterministic error-severity rule there is nothing
    for a "recurring violation" escalation to add.
    """
    history_path = project_dir / ".clip-weave" / "guard-history.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if history_path.exists():
        try:
            loaded = json.loads(history_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
            else:
                logger.warning("guard-history.json is not an object — rebuilding it")
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("guard-history.json unreadable (%s) — rebuilding it", exc)
    for v in result.unknown:
        existing.setdefault(v.fingerprint, {"rule_id": v.rule_id, "status": "unknown"})
    history_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
```

- [ ] **Step 4: 更新 `pipeline.guard()` 去掉 `result.fixed` 引用**

`src/clip_weave/pipeline.py` 中把 `guard()` 函数体替换为：

```python
def guard(compositions_dir: Path, project_dir: Path | None = None) -> bool:
    """Run Rule Guard on compositions_dir. Returns True if no violations."""
    result = guard_scan(compositions_dir)
    if result.unknown:
        logger.warning("Rule Guard: %d violation(s) need manual fix:", len(result.unknown))
        for v in result.unknown:
            logger.warning("  [%s] %s:%d — %s", v.rule_id, v.file.name, v.line, v.detail)
    if project_dir:
        save_history(project_dir, result)
    return result.ok
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest tests/test_rule_guard.py -v`
Expected: 两个测试 PASS。

- [ ] **Step 6: 补齐 Rule Guard 的其余测试**

追加到 `tests/test_rule_guard.py` 末尾：

```python
def test_media_in_composition_is_flagged(tmp_path):
    (tmp_path / "01-hero.html").write_text(
        "<template>\n<video src='hero.mp4' muted playsinline></video>\n</template>",
        encoding="utf-8",
    )

    result = scan(tmp_path)

    assert len(result.violations) == 1
    assert result.violations[0].rule_id == "media_in_subcomposition"
    assert result.violations[0].line == 2
    assert result.ok is False


def test_audio_in_composition_is_flagged(tmp_path):
    (tmp_path / "01-hero.html").write_text(
        "<template>\n<audio src='bgm.mp3'></audio>\n</template>", encoding="utf-8"
    )

    result = scan(tmp_path)

    assert [v.rule_id for v in result.violations] == ["media_in_subcomposition"]


def test_scan_walks_nested_frame_directories(tmp_path):
    nested = tmp_path / "frames"
    nested.mkdir()
    (nested / "02-demo.html").write_text("<video src='x.mp4'></video>", encoding="utf-8")

    result = scan(tmp_path)

    assert len(result.violations) == 1
    assert result.violations[0].file.name == "02-demo.html"


def test_clean_composition_produces_no_violations(tmp_path):
    (tmp_path / "01-hero.html").write_text(
        "<template><div id='root'><h1>Hello</h1></div></template>", encoding="utf-8"
    )

    result = scan(tmp_path)

    assert result.violations == []
    assert result.ok is True


def test_save_history_creates_missing_parent_directories(tmp_path):
    project_dir = tmp_path / "videos" / "proj"  # does not exist yet
    (tmp_path / "01.html").write_text("<video src='x.mp4'></video>", encoding="utf-8")
    result = scan(tmp_path)

    save_history(project_dir, result)

    history = project_dir / ".clip-weave" / "guard-history.json"
    assert history.exists()
    assert list(json.loads(history.read_text()).values())[0]["rule_id"] == (
        "media_in_subcomposition"
    )


def test_save_history_rebuilds_corrupt_file(tmp_path):
    project_dir = tmp_path / "proj"
    history = project_dir / ".clip-weave" / "guard-history.json"
    history.parent.mkdir(parents=True)
    history.write_text("{not json at all", encoding="utf-8")

    (tmp_path / "01.html").write_text("<video src='x.mp4'></video>", encoding="utf-8")
    save_history(project_dir, scan(tmp_path))

    assert len(json.loads(history.read_text())) == 1


def test_save_history_is_additive(tmp_path):
    project_dir = tmp_path / "proj"
    (tmp_path / "01.html").write_text("<video src='a.mp4'></video>", encoding="utf-8")
    save_history(project_dir, scan(tmp_path))

    (tmp_path / "02.html").write_text("<audio src='b.mp3'></audio>", encoding="utf-8")
    save_history(project_dir, scan(tmp_path))

    history = project_dir / ".clip-weave" / "guard-history.json"
    assert len(json.loads(history.read_text())) == 2


def test_guard_result_has_no_fixed_field():
    """`fixed` was removed: it was always empty and misled callers."""
    assert not hasattr(GuardResult(), "fixed")
```

- [ ] **Step 7: 运行全部测试**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest -q`
Expected: 全绿。`tests/test_rule_guard.py` 10 个测试通过；`tests/test_cli.py` 和 `tests/test_pipeline.py` 里现有的 guard 测试（用 `<video>` 触发违规）仍然通过，因为保留的正是那条规则。

- [ ] **Step 8: 用真实项目验证零误报**

Run:
```bash
cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m clip_weave guard videos/noah-group && .venv/bin/python -m clip_weave guard videos/xiaomi-su7-promo
```
Expected: 两个项目都输出 `Rule Guard: all clear`，退出码 0。

- [ ] **Step 9: 提交**

```bash
cd /Users/beersoccer/workspace/clip-weave
git add src/clip_weave/adapters/rule_guard.py src/clip_weave/pipeline.py tests/test_rule_guard.py
git commit -m "refactor(rule-guard): keep only media_in_subcomposition after HF source review

Three detectors were removed:
- gsap_css_transform_conflict: HF implements it via an acorn AST parser at
  error severity; a regex approximation is strictly worse.
- gsap_timeline_set_initial_hide: HF's rule of that name means the opposite.
  Its own test asserts top-level gsap.set() must NOT be flagged, while our
  detector flagged exactly that and advised the pattern HF warns about.
- preserve_3d_filter: no HF lint code exists, but a sound decision needs full
  CSS cascade plus ancestor resolution. Verified false-positive on HF's own
  3d-camera-flight recipe.

media_in_subcomposition stays because HF's lint rule for it is inactive
pre-assembly (project.ts reads index.html first) and under single-file entry
(isSubComposition is never set)."
```

---

## Task 3: 增量 check 的覆盖率损失处置

`npx hyperframes check <file>` 会静默关闭 `media_in_subcomposition` 与全部项目级检查。让代码在调用点把这件事说清楚，并提供一个表达"全项目"意图的入口。

**Files:**
- Modify: `src/clip_weave/adapters/hyperframes.py`
- Modify: `tests/test_hyperframes_adapter.py`

**Interfaces:**
- Consumes: 无
- Produces: `check(project_dir, file=None) -> tuple[bool, str]`（签名不变）；新增 `check_full(project_dir) -> tuple[bool, str]`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_hyperframes_adapter.py` 末尾（并在文件顶部的 import 里加上 `check_full`）：

```python
def test_check_single_file_warns_about_reduced_coverage(tmp_path, caplog):
    import logging

    comp = tmp_path / "compositions" / "01-hero.html"
    comp.parent.mkdir(parents=True)
    comp.write_text("<template></template>")
    with patch("clip_weave.adapters.hyperframes.subprocess.run",
               return_value=MagicMock(returncode=0, stdout="pass", stderr="")):
        with caplog.at_level(logging.WARNING, logger="clip_weave.adapters.hyperframes"):
            check(tmp_path, file=comp)
    assert "project-level" in caplog.text
    assert "media_in_subcomposition" in caplog.text


def test_check_full_does_not_warn(tmp_path, caplog):
    import logging

    with patch("clip_weave.adapters.hyperframes.subprocess.run",
               return_value=MagicMock(returncode=0, stdout="pass", stderr="")):
        with caplog.at_level(logging.WARNING, logger="clip_weave.adapters.hyperframes"):
            ok, _ = check_full(tmp_path)
    assert ok is True
    assert "project-level" not in caplog.text


def test_check_full_passes_no_file_argument(tmp_path):
    with patch("clip_weave.adapters.hyperframes.subprocess.run",
               return_value=MagicMock(returncode=0, stdout="", stderr="")) as mock_run:
        check_full(tmp_path)
    cmd = mock_run.call_args[0][0]
    assert cmd == ["npx", "hyperframes", "check"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest tests/test_hyperframes_adapter.py -v`
Expected: 三个新测试 FAIL（`check_full` 未定义 / 无 warning）。

- [ ] **Step 3: 修改 `src/clip_weave/adapters/hyperframes.py`**

把 `check` 函数替换为下面两个函数（其余内容不动）：

```python
# `npx hyperframes check <file>` passes an explicit lint entry. HF then treats
# that file as the ROOT composition: packages/lint/src/project.ts:165 skips the
# compositions/ walk and never sets `isSubComposition`, which silently disables
# `media_in_subcomposition` (media.ts:349 returns early without it) along with
# every project-level check (missing/empty sub-composition, duplicate
# composition ids, duplicate audio tracks, missing local assets, HEVC notes).
# Fast to iterate with, but not a substitute for a full pass.
_SINGLE_FILE_COVERAGE_WARNING = (
    "check(file=…) runs HF lint with an explicit entry: media_in_subcomposition "
    "and all project-level checks are skipped. Use it for iteration only — run "
    "check_full() before render."
)


def check(project_dir: Path, file: Path | None = None) -> tuple[bool, str]:
    """npx hyperframes check [file] — returns (ok, output). 10-30s per call.

    Passing `file` narrows the run and loses coverage; see
    `_SINGLE_FILE_COVERAGE_WARNING`. Prefer `check_full()` before rendering.
    """
    cmd = ["npx", "hyperframes", "check"]
    if file:
        logger.warning("%s", _SINGLE_FILE_COVERAGE_WARNING)
        cmd.append(str(file.relative_to(project_dir)))
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(project_dir),
            timeout=_TIMEOUT_CHECK,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, f"check timed out after {_TIMEOUT_CHECK}s"


def check_full(project_dir: Path) -> tuple[bool, str]:
    """Full-project `npx hyperframes check` — the only pass with full coverage.

    Exists so callers can state the intent explicitly; a bare `check(dir)` is
    equivalent but reads as if a narrowed run would do.
    """
    return check(project_dir)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest tests/test_hyperframes_adapter.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
cd /Users/beersoccer/workspace/clip-weave
git add src/clip_weave/adapters/hyperframes.py tests/test_hyperframes_adapter.py
git commit -m "fix(hyperframes): surface the coverage loss of single-file check

An explicit lint entry makes HF skip the compositions/ walk and never set
isSubComposition, disabling media_in_subcomposition and every project-level
check. Warn at the call site and add check_full() for intent."
```

---

## Task 4: STORYBOARD.md 解析器测试

`core/storyboard.py` 是宽容解析器，零测试。宽容解析正是最需要测试固定行为的东西。本任务只加测试，不改生产代码。

**Files:**
- Create: `tests/test_storyboard.py`

**Interfaces:**
- Consumes: `clip_weave.core.storyboard` 的 `parse_storyboard`、`build_prompt`、`frame_negative_prompt`、`Frame`、`Storyboard`
- Produces: 无（纯测试）

> **修订补充（2026-07-31）：** 本任务书写时 `storyboard.py` 为 298 行，之后新增了三项能力，
> 一并覆盖（先读实现确认签名，不要凭本文假设）：
>
> - `Frame.asset_candidates() -> list[dict]` —— 解析 `- asset_candidates: a.png (0.62) — desc；b.png — desc`，
>   返回 `{filename, score, description}`。要覆盖：带分数与不带分数两种写法；中文分号 `；` 与
>   英文 `;` 两种分隔符；**文件名本身含连字符**（如 `20-1.png`，只有带空格的 `-` 或 `—`/`–` 才
>   是分隔符，这是该正则最容易写错的地方）；无法匹配时降级为 `{filename: 整块, score: None,
>   description: ""}`；字段缺失时返回空列表。
> - `Frame.focal_asset() -> str | None` —— 优先取 HF 的 `focal:`，否则取首个候选。要覆盖：
>   `focal:` 存在时取其首个词并剥掉尾随 `,;`；`focal:` 缺失时回落到 `asset_candidates()[0]`；
>   两者皆无时返回 `None`。
> - `Storyboard.direction` 与 `Frame.direction_field(label)` —— frontmatter 与首帧之间的
>   自由文本「Video direction」块。要覆盖：该块存在与不存在两种情形。
>
> 另外确认一处即可，不必改代码：`_MOTION_KEYS` 在 `build_prompt` 里实际未被使用（该函数只读
> 白名单键），所以 `visual_type` 不会泄漏进提示词。若你确认 `_MOTION_KEYS` 确为死代码，作为
> Minor 写进报告，不要在本任务里删除它。

- [ ] **Step 1: 写测试文件**

创建 `tests/test_storyboard.py`：

```python
"""Tests for the STORYBOARD.md parser and the text-to-video prompt builder."""

import pytest

from clip_weave.core.storyboard import (
    build_prompt,
    frame_negative_prompt,
    parse_storyboard,
)

FULL_STORYBOARD = """---
format: 1920x1080
duration: 47s
message: "小米 SU7 好看·好开·舒适·安全"
---

## Frame 1 — 爆点数据
- scene: 城市夜景中一辆红色轿车驶过湿滑路面
- voiceover: "2.78 秒破百"
- duration: 5.851s
- beat: hook
- blueprint: counting-dynamic-scale
- roles: hero=counter, support=grid
- sfx: whoosh

narrativeRole: 开场钩子
自由叙述段落，解析器应收进 narrative。

## Frame 2 — 底盘
- scene: 底盘爆炸图缓慢旋转
- duration: 6s
- negative_prompt: 文字, 水印
"""


def _write(tmp_path, body: str, name: str = "STORYBOARD.md"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_parses_frontmatter_and_frames(tmp_path):
    sb = parse_storyboard(_write(tmp_path, FULL_STORYBOARD))

    assert sb.format == "1920x1080"
    assert sb.message == "小米 SU7 好看·好开·舒适·安全"
    assert len(sb.frames) == 2
    assert sb.warnings == []


def test_frame_fields_and_indexes(tmp_path):
    sb = parse_storyboard(_write(tmp_path, FULL_STORYBOARD))
    first, second = sb.frames

    assert (first.index, first.number, first.title) == (1, 1, "爆点数据")
    assert first.scene == "城市夜景中一辆红色轿车驶过湿滑路面"
    assert first.voiceover == "2.78 秒破百"  # quotes stripped
    assert first.duration_seconds == pytest.approx(5.851)
    assert "自由叙述段落" in first.narrative
    assert (second.index, second.number) == (2, 2)


def test_bare_key_value_lines_land_in_meta(tmp_path):
    sb = parse_storyboard(_write(tmp_path, FULL_STORYBOARD))
    assert sb.frames[0].meta.get("narrativeRole") == "开场钩子"


def test_negative_prompt_is_exposed(tmp_path):
    sb = parse_storyboard(_write(tmp_path, FULL_STORYBOARD))
    assert frame_negative_prompt(sb.frames[1]) == "文字, 水印"
    assert frame_negative_prompt(sb.frames[0]) is None


def test_missing_frontmatter_is_tolerated(tmp_path):
    sb = parse_storyboard(_write(tmp_path, "## Frame 1 — A\n- scene: 一只猫\n"))
    assert sb.globals == {}
    assert len(sb.frames) == 1
    assert sb.aspect_ratio() == "16:9"  # default when format is absent


def test_non_mapping_frontmatter_records_warning(tmp_path):
    sb = parse_storyboard(_write(tmp_path, "---\n- just\n- a list\n---\n\n## Frame 1\n- scene: x\n"))
    assert any("not a mapping" in w for w in sb.warnings)
    assert len(sb.frames) == 1


def test_no_frames_records_warning(tmp_path):
    sb = parse_storyboard(_write(tmp_path, "---\nformat: 1080x1920\n---\n\nprose only\n"))
    assert sb.frames == []
    assert any("no `## Frame N` sections" in w for w in sb.warnings)


@pytest.mark.parametrize("heading", ["## Frame 1", "### Beat 1: Title", "## Scene 1 — Title"])
def test_frame_beat_and_scene_headings_all_parse(tmp_path, heading):
    sb = parse_storyboard(_write(tmp_path, f"{heading}\n- scene: 一个镜头\n"))
    assert len(sb.frames) == 1
    assert sb.frames[0].scene == "一个镜头"


@pytest.mark.parametrize(
    "alias,expected_key",
    [
        ("description", "scene"),
        ("summary", "scene"),
        ("caption", "scene"),
        ("vo", "voiceover"),
        ("narration", "voiceover"),
    ],
)
def test_metadata_aliases_are_normalised(tmp_path, alias, expected_key):
    sb = parse_storyboard(_write(tmp_path, f"## Frame 1\n- {alias}: 值\n"))
    assert sb.frames[0].meta[expected_key] == "值"


@pytest.mark.parametrize(
    "fmt,expected",
    [
        ("1920x1080", "16:9"),
        ("1080x1920", "9:16"),
        ("1080x1080", "1:1"),
        ("1600x1200", "4:3"),
        ("2520x1080", "21:9"),
        ("", "16:9"),
        ("garbage", "16:9"),
        ("0x0", "16:9"),
    ],
)
def test_aspect_ratio_mapping(tmp_path, fmt, expected):
    body = f"---\nformat: {fmt}\n---\n\n## Frame 1\n- scene: x\n"
    assert parse_storyboard(_write(tmp_path, body)).aspect_ratio() == expected


def test_slug_handles_chinese_and_falls_back(tmp_path):
    sb = parse_storyboard(_write(tmp_path, "## Frame 1 — 爆点数据\n- scene: x\n\n## Frame 2\n- scene: y\n"))
    assert sb.frames[0].slug() == "爆点数据"
    assert sb.frames[1].slug() == "y"  # falls back to scene when there is no title


def test_non_frame_heading_closes_the_current_frame(tmp_path):
    body = "## Frame 1\n- scene: a\n\n## Notes\n- scene: should-not-attach\n"
    sb = parse_storyboard(_write(tmp_path, body))
    assert len(sb.frames) == 1
    assert sb.frames[0].scene == "a"


# ── build_prompt ──────────────────────────────────────────────────────────────

def test_build_prompt_drops_html_motion_metadata(tmp_path):
    sb = parse_storyboard(_write(tmp_path, FULL_STORYBOARD))
    prompt = build_prompt(sb, sb.frames[0])

    assert "城市夜景" in prompt
    # Motion-implementation metadata describes an HTML composition, not a shot.
    for leaked in ("counting-dynamic-scale", "hero=counter", "whoosh"):
        assert leaked not in prompt


def test_build_prompt_includes_narrative_role_and_beat(tmp_path):
    sb = parse_storyboard(_write(tmp_path, FULL_STORYBOARD))
    prompt = build_prompt(sb, sb.frames[0])
    assert "开场钩子" in prompt
    assert "hook" in prompt


def test_build_prompt_voiceover_is_opt_in(tmp_path):
    sb = parse_storyboard(_write(tmp_path, FULL_STORYBOARD))
    assert "2.78" not in build_prompt(sb, sb.frames[0])
    assert "2.78" in build_prompt(sb, sb.frames[0], include_voiceover=True)


def test_build_prompt_style_replaces_global_theme(tmp_path):
    sb = parse_storyboard(_write(tmp_path, FULL_STORYBOARD))
    with_theme = build_prompt(sb, sb.frames[0])
    with_style = build_prompt(sb, sb.frames[0], style="anamorphic 35mm")

    assert "小米 SU7" in with_theme
    assert "anamorphic 35mm" in with_style
    assert "小米 SU7" not in with_style


def test_build_prompt_falls_back_to_narrative_then_title(tmp_path):
    narrative_only = parse_storyboard(
        _write(tmp_path, "## Frame 1 — T\n\n一段叙述。\n", name="a.md")
    )
    assert "一段叙述" in build_prompt(narrative_only, narrative_only.frames[0])

    bare = parse_storyboard(_write(tmp_path, "## Frame 1 — 只有标题\n", name="b.md"))
    assert build_prompt(bare, bare.frames[0]) == "只有标题"
```

- [ ] **Step 2: 运行测试**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest tests/test_storyboard.py -v`
Expected: 全部 PASS。若个别断言与实现不符，**先确认是测试写错还是实现有缺陷**：解析器的既有行为是基线，除非行为明显错误（例如把 `sfx` 泄漏进提示词），否则调整测试而非实现。任何对实现的修改要单独一次提交并在提交信息中说明原因。

- [ ] **Step 3: 提交**

```bash
cd /Users/beersoccer/workspace/clip-weave
git add tests/test_storyboard.py
git commit -m "test(storyboard): cover the lenient parser and prompt builder"
```

---

## Task 5: video_gen provider 测试

三家 provider 各自的请求体构造与状态映射，共约 650 行，零测试。用假 `requests.Session` 拦截，全部离线。

**Files:**
- Create: `tests/test_video_gen_providers.py`

**Interfaces:**
- Consumes: `clip_weave.adapters.video_gen` 的 `get_model`、`VideoGenError`、`VideoRequest`、`ProviderConfig`；`ali.AliVideoModel`、`doubao.DoubaoVideoModel`、`vertex.VertexVideoModel`
- Produces: 测试内部的 `FakeSession` 模式，Task 6 会用同样的思路构造假 `VideoModel`

- [ ] **Step 1: 写测试文件**

创建 `tests/test_video_gen_providers.py`：

```python
"""Offline tests for the three gateway video-generation providers.

No real HTTP: a FakeSession records requests and returns canned JSON.
"""

import pytest

from clip_weave.adapters.video_gen import VideoGenError, VideoRequest, get_model
from clip_weave.adapters.video_gen.ali import AliVideoModel
from clip_weave.adapters.video_gen.base import ProviderConfig
from clip_weave.adapters.video_gen.doubao import DoubaoVideoModel
from clip_weave.adapters.video_gen.vertex import VertexVideoModel


class FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text or str(payload)

    def json(self):
        if self._payload is _NOT_JSON:
            raise ValueError("not json")
        return self._payload


_NOT_JSON = object()


class FakeSession:
    """Records every request and replays queued responses in order."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json, "headers": headers})
        return self.responses.pop(0) if self.responses else FakeResponse({})


def _cfg(name, base_url, model, **extra):
    return ProviderConfig(
        name=name, base_url=base_url, api_key="test-key", model=model, extra=dict(extra)
    )


# ── ProviderConfig ────────────────────────────────────────────────────────────

def test_require_lists_every_missing_field():
    cfg = ProviderConfig(name="ali", base_url="", api_key="", model="")
    with pytest.raises(VideoGenError) as exc:
        cfg.require()
    for field in ("base_url", "api_key", "model"):
        assert field in str(exc.value)


def test_from_env_falls_back_to_the_shared_gateway_key(monkeypatch):
    monkeypatch.delenv("DOUBAO_VIDEO_API_KEY", raising=False)
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "shared-key")
    monkeypatch.setenv("DOUBAO_VIDEO_BASE_URL", "http://gw/doubaovideo/")
    cfg = ProviderConfig.from_env("doubao", "DOUBAO_VIDEO", default_model="m")
    assert cfg.api_key == "shared-key"
    assert cfg.base_url == "http://gw/doubaovideo"  # trailing slash stripped


def test_get_model_rejects_unknown_provider():
    with pytest.raises(VideoGenError, match="unknown provider"):
        get_model("midjourney")


# ── clamp_duration ────────────────────────────────────────────────────────────

def test_doubao_clamps_to_the_nearest_allowed_choice():
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "doubao-seedance-1-0-pro"))
    assert vm.clamp_duration(5.851) == 5
    assert vm.clamp_duration(8) == 10
    assert vm.clamp_duration(None) == 5


def test_doubao_durations_range_override():
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance-2", DURATIONS="4-15"))
    assert vm.duration_range == (4, 15)
    assert vm.duration_choices is None
    assert vm.clamp_duration(12.4) == 12
    assert vm.clamp_duration(99) == 15


def test_doubao_durations_choice_list_override():
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance", DURATIONS="5,10,15"))
    assert vm.clamp_duration(13) == 15


def test_vertex_clamps_to_veo_choices():
    vm = VertexVideoModel(_cfg("vertex", "http://gw/v", "veo-3.1-generate-001"))
    assert vm.clamp_duration(5) == 4
    assert vm.clamp_duration(7) == 6  # ties resolve to the first nearest choice
    assert vm.clamp_duration(30) == 8


def test_ali_clamps_within_range():
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5-t2v-preview"))
    assert vm.clamp_duration(1) == 2
    assert vm.clamp_duration(99) == 15


# ── 豆包 / Seedance ───────────────────────────────────────────────────────────

def test_doubao_submit_builds_ark_payload():
    session = FakeSession(FakeResponse({"id": "cgt-123"}))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/doubaovideo", "seedance"), session=session)

    task_id = vm.submit(
        VideoRequest(prompt="夜景轿车", duration=5, ratio="16:9", resolution="1080p", seed=7,
                     generate_audio=True)
    )

    assert task_id == "cgt-123"
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "http://gw/doubaovideo/api/v3/contents/generations/tasks"
    assert call["headers"]["Authorization"] == "Bearer test-key"
    body = call["json"]
    assert body["content"] == [{"type": "text", "text": "夜景轿车"}]
    assert body["resolution"] == "1080p"
    assert body["ratio"] == "16:9"
    assert body["duration"] == 5
    assert body["seed"] == 7
    assert body["generate_audio"] is True


def test_doubao_submit_appends_reference_image():
    session = FakeSession(FakeResponse({"id": "cgt-1"}))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"), session=session)
    vm.submit(VideoRequest(prompt="p", image_url="https://cdn/first-frame.png"))
    content = session.calls[0]["json"]["content"]
    assert content[1] == {"type": "image_url",
                          "image_url": {"url": "https://cdn/first-frame.png"}}


def test_doubao_submit_honours_tasks_path_override():
    session = FakeSession(FakeResponse({"id": "x"}))
    vm = DoubaoVideoModel(
        _cfg("doubao", "http://gw/d", "seedance", TASKS_PATH="/flat/tasks"), session=session
    )
    vm.submit(VideoRequest(prompt="p"))
    assert session.calls[0]["url"] == "http://gw/d/flat/tasks"


def test_doubao_submit_without_task_id_raises():
    session = FakeSession(FakeResponse({"error": {"message": "quota"}}))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"), session=session)
    with pytest.raises(VideoGenError, match="no task id"):
        vm.submit(VideoRequest(prompt="p"))


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("queued", "pending"), ("running", "running"), ("succeeded", "succeeded"),
        ("completed", "succeeded"), ("failed", "failed"), ("cancelled", "failed"),
        ("expired", "failed"), ("something-new", "running"),
    ],
)
def test_doubao_state_mapping(raw, expected):
    session = FakeSession(FakeResponse({"status": raw, "content": {"video_url": "u"}}))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"), session=session)
    assert vm.poll("cgt-1").state == expected


def test_doubao_poll_surfaces_error_message():
    session = FakeSession(FakeResponse({"status": "failed", "error": {"message": "nsfw"}}))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"), session=session)
    status = vm.poll("cgt-1")
    assert status.state == "failed"
    assert status.error == "nsfw"


# ── 阿里 通义万相 ─────────────────────────────────────────────────────────────

def test_ali_submit_uses_async_header_and_legacy_size():
    session = FakeSession(FakeResponse({"output": {"task_id": "t-1"}}))
    vm = AliVideoModel(_cfg("ali", "http://gw/alivideo", "wan2.5-t2v-preview"), session=session)

    task_id = vm.submit(VideoRequest(prompt="p", ratio="9:16", resolution="720p", duration=5))

    assert task_id == "t-1"
    call = session.calls[0]
    assert call["url"] == (
        "http://gw/alivideo/api/v1/services/aigc/video-generation/video-synthesis"
    )
    assert call["headers"]["X-DashScope-Async"] == "enable"
    params = call["json"]["parameters"]
    assert params["size"] == "720*1280"
    assert "resolution" not in params


def test_ali_wan27_dialect_uses_resolution_and_ratio():
    session = FakeSession(FakeResponse({"output": {"task_id": "t-2"}}))
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.7-t2v"), session=session)
    vm.submit(VideoRequest(prompt="p", ratio="16:9", resolution="1080p"))
    params = session.calls[0]["json"]["parameters"]
    assert params["resolution"] == "1080P"
    assert params["ratio"] == "16:9"
    assert "size" not in params


def test_ali_protocol_can_be_forced_to_legacy():
    session = FakeSession(FakeResponse({"output": {"task_id": "t"}}))
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.7-t2v", PROTOCOL="legacy"), session=session)
    vm.submit(VideoRequest(prompt="p", ratio="16:9", resolution="1080p"))
    assert session.calls[0]["json"]["parameters"]["size"] == "1920*1080"


def test_ali_unknown_size_combination_falls_back_to_1080p_16x9():
    session = FakeSession(FakeResponse({"output": {"task_id": "t"}}))
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5"), session=session)
    vm.submit(VideoRequest(prompt="p", ratio="21:9", resolution="480p"))
    assert session.calls[0]["json"]["parameters"]["size"] == "1920*1080"


def test_ali_negative_prompt_goes_into_input():
    session = FakeSession(FakeResponse({"output": {"task_id": "t"}}))
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5"), session=session)
    vm.submit(VideoRequest(prompt="p", negative_prompt="水印"))
    assert session.calls[0]["json"]["input"]["negative_prompt"] == "水印"


def test_ali_submit_without_task_id_raises():
    session = FakeSession(FakeResponse({"code": "Throttling", "message": "slow down"}))
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5"), session=session)
    with pytest.raises(VideoGenError, match="Throttling"):
        vm.submit(VideoRequest(prompt="p"))


def test_ali_task_url_appends_placeholder_when_missing():
    session = FakeSession(FakeResponse({"output": {"task_status": "RUNNING"}}))
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5", TASK_PATH="/v2/tasks"), session=session)
    vm.poll("abc")
    assert session.calls[0]["url"] == "http://gw/a/v2/tasks/abc"


@pytest.mark.parametrize(
    "raw,expected",
    [("PENDING", "pending"), ("RUNNING", "running"), ("SUCCEEDED", "succeeded"),
     ("FAILED", "failed"), ("CANCELED", "failed"), ("UNKNOWN", "failed"), ("WAT", "running")],
)
def test_ali_state_mapping(raw, expected):
    session = FakeSession(FakeResponse({"output": {"task_status": raw}}))
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5"), session=session)
    assert vm.poll("t").state == expected


def test_ali_poll_returns_video_url_on_success():
    session = FakeSession(
        FakeResponse({"output": {"task_status": "SUCCEEDED", "video_url": "https://cdn/v.mp4"}})
    )
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5"), session=session)
    assert vm.poll("t").video_url == "https://cdn/v.mp4"


# ── Google Veo / Vertex ───────────────────────────────────────────────────────

def test_vertex_gateway_model_path_omits_project():
    session = FakeSession(FakeResponse({"name": "operations/op-1"}))
    vm = VertexVideoModel(_cfg("vertex", "http://gw/vertexvideo", "veo-3.1"), session=session)

    op = vm.submit(VideoRequest(prompt="p", ratio="16:9", resolution="1080p", duration=6))

    assert op == "operations/op-1"
    assert session.calls[0]["url"] == (
        "http://gw/vertexvideo/v1/publishers/google/models/veo-3.1:predictLongRunning"
    )
    params = session.calls[0]["json"]["parameters"]
    assert params["durationSeconds"] == 6
    assert params["aspectRatio"] == "16:9"
    assert params["sampleCount"] == 1


def test_vertex_raw_path_includes_project_and_location():
    session = FakeSession(FakeResponse({"name": "op"}))
    vm = VertexVideoModel(
        _cfg("vertex", "http://gw/v", "veo-3.1", PROJECT="my-proj", LOCATION="us-central1"),
        session=session,
    )
    vm.submit(VideoRequest(prompt="p"))
    assert "projects/my-proj/locations/us-central1/publishers/google/models/veo-3.1" in (
        session.calls[0]["url"]
    )


def test_vertex_model_path_override_wins():
    session = FakeSession(FakeResponse({"name": "op"}))
    vm = VertexVideoModel(
        _cfg("vertex", "http://gw/v", "veo-3.1", MODEL_PATH="custom/path/model"), session=session
    )
    vm.submit(VideoRequest(prompt="p"))
    assert session.calls[0]["url"] == "http://gw/v/v1/custom/path/model:predictLongRunning"


def test_vertex_coerces_unsupported_ratio_to_16x9():
    session = FakeSession(FakeResponse({"name": "op"}))
    vm = VertexVideoModel(_cfg("vertex", "http://gw/v", "veo-3.1"), session=session)
    vm.submit(VideoRequest(prompt="p", ratio="1:1"))
    assert session.calls[0]["json"]["parameters"]["aspectRatio"] == "16:9"


def test_vertex_submit_without_operation_name_raises():
    session = FakeSession(FakeResponse({"error": {"message": "CONSUMER_INVALID"}}))
    vm = VertexVideoModel(_cfg("vertex", "http://gw/v", "veo-3.1"), session=session)
    with pytest.raises(VideoGenError, match="no operation name"):
        vm.submit(VideoRequest(prompt="p"))


def test_vertex_poll_running_until_done():
    session = FakeSession(FakeResponse({"done": False}))
    vm = VertexVideoModel(_cfg("vertex", "http://gw/v", "veo-3.1"), session=session)
    status = vm.poll("operations/op-1")
    assert status.state == "running"
    assert session.calls[0]["url"].endswith(":fetchPredictOperation")
    assert session.calls[0]["json"] == {"operationName": "operations/op-1"}


def test_vertex_poll_success_reads_gcs_uri():
    session = FakeSession(
        FakeResponse({"done": True, "response": {"videos": [{"gcsUri": "gs://b/v.mp4"}]}})
    )
    vm = VertexVideoModel(_cfg("vertex", "http://gw/v", "veo-3.1"), session=session)
    status = vm.poll("op")
    assert status.state == "succeeded"
    assert status.video_url == "gs://b/v.mp4"


def test_vertex_poll_success_reads_inline_base64():
    session = FakeSession(
        FakeResponse({"done": True, "response": {"videos": [{"bytesBase64Encoded": "AAAA"}]}})
    )
    vm = VertexVideoModel(_cfg("vertex", "http://gw/v", "veo-3.1"), session=session)
    assert vm.poll("op").video_b64 == "AAAA"


def test_vertex_poll_reports_rai_filter_reason():
    session = FakeSession(
        FakeResponse({"done": True,
                      "response": {"videos": [], "raiMediaFilteredReasons": ["blocked: violence"]}})
    )
    vm = VertexVideoModel(_cfg("vertex", "http://gw/v", "veo-3.1"), session=session)
    status = vm.poll("op")
    assert status.state == "failed"
    assert "violence" in status.error


def test_vertex_poll_surfaces_operation_error():
    session = FakeSession(FakeResponse({"error": {"message": "PERMISSION_DENIED"}}))
    vm = VertexVideoModel(_cfg("vertex", "http://gw/v", "veo-3.1"), session=session)
    status = vm.poll("op")
    assert status.state == "failed"
    assert status.error == "PERMISSION_DENIED"


# ── shared request plumbing ───────────────────────────────────────────────────

def test_http_error_becomes_video_gen_error():
    session = FakeSession(FakeResponse({}, status_code=503, text="upstream down"))
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5"), session=session)
    with pytest.raises(VideoGenError, match="HTTP 503"):
        vm.submit(VideoRequest(prompt="p"))


def test_non_json_response_becomes_video_gen_error():
    session = FakeSession(FakeResponse(_NOT_JSON, text="<html>gateway</html>"))
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5"), session=session)
    with pytest.raises(VideoGenError, match="non-JSON"):
        vm.submit(VideoRequest(prompt="p"))


def test_request_exception_becomes_video_gen_error():
    import requests

    class ExplodingSession:
        def request(self, *a, **k):
            raise requests.ConnectionError("dns")

    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5"), session=ExplodingSession())
    with pytest.raises(VideoGenError, match="request to .* failed"):
        vm.submit(VideoRequest(prompt="p"))
```

- [ ] **Step 2: 运行测试**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest tests/test_video_gen_providers.py -v`
Expected: 全部 PASS。

两处需要注意的断言，若失败先核对实现而非直接改测试：
- `test_vertex_clamps_to_veo_choices` 里 `clamp_duration(7) == 6`：`min` 在距离相等时返回**先出现**的元素，`duration_choices = (4, 6, 8)` 中 7 距 6 和 8 均为 1，故取 6。
- `test_doubao_clamps_to_the_nearest_allowed_choice` 里 `clamp_duration(8) == 10`：`(5, 10)` 中 8 距 5 为 3、距 10 为 2，取 10。

- [ ] **Step 3: 提交**

```bash
cd /Users/beersoccer/workspace/clip-weave
git add tests/test_video_gen_providers.py
git commit -m "test(video-gen): cover doubao/ali/vertex payloads and state mapping offline"
```

---

## Task 6: GCP project 解析测试

**Files:**
- Create: `tests/test_gcp_project.py`

**Interfaces:**
- Consumes: `clip_weave.adapters.video_gen.gcp_project` 的 `resolve_project`、`looks_like_project_id`
- Produces: 无

- [ ] **Step 1: 写测试文件**

创建 `tests/test_gcp_project.py`：

```python
"""Tests for GCP project resolution (Vertex requires a real project id)."""

import pytest

from clip_weave.adapters.video_gen import gcp_project
from clip_weave.adapters.video_gen.gcp_project import looks_like_project_id, resolve_project

_ENV_VARS = ("VERTEX_VIDEO_PROJECT", "GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """No env leakage, and gcloud is never invoked unless a test opts in."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(gcp_project, "_from_gcloud", lambda: None)


@pytest.mark.parametrize("var", _ENV_VARS)
def test_env_vars_are_honoured(monkeypatch, var):
    monkeypatch.setenv(var, "env-project")
    project, source = resolve_project()
    assert project == "env-project"
    assert source == f"env {var}"


def test_vertex_var_wins_over_google_cloud_project(monkeypatch):
    monkeypatch.setenv("VERTEX_VIDEO_PROJECT", "vertex-one")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "google-one")
    assert resolve_project()[0] == "vertex-one"


def test_env_wins_over_frontmatter(monkeypatch, tmp_path):
    monkeypatch.setenv("VERTEX_VIDEO_PROJECT", "from-env")
    sb = tmp_path / "STORYBOARD.md"
    sb.write_text("---\nvertex_project: from-file\n---\n", encoding="utf-8")
    assert resolve_project(sb)[0] == "from-env"


@pytest.mark.parametrize(
    "key", ["vertex_project", "gcp_project", "google_cloud_project", "project_id"]
)
def test_storyboard_frontmatter_keys(tmp_path, key):
    sb = tmp_path / "STORYBOARD.md"
    sb.write_text(f"---\nformat: 1920x1080\n{key}: sb-proj\n---\n\n## Frame 1\n", encoding="utf-8")
    project, source = resolve_project(sb)
    assert project == "sb-proj"
    assert source == f"STORYBOARD.md:{key}"


def test_falls_back_to_sibling_brief(tmp_path):
    sb = tmp_path / "STORYBOARD.md"
    sb.write_text("---\nformat: 1920x1080\n---\n", encoding="utf-8")
    (tmp_path / "BRIEF.md").write_text("---\nvertex_project: brief-proj\n---\n", encoding="utf-8")
    project, source = resolve_project(sb)
    assert project == "brief-proj"
    assert source == "BRIEF.md:vertex_project"


def test_quotes_are_stripped(tmp_path):
    sb = tmp_path / "STORYBOARD.md"
    sb.write_text("---\nvertex_project: \"quoted-proj\"\n---\n", encoding="utf-8")
    assert resolve_project(sb)[0] == "quoted-proj"


def test_only_the_frontmatter_block_is_scanned(tmp_path):
    sb = tmp_path / "STORYBOARD.md"
    sb.write_text(
        "---\nformat: 1920x1080\n---\n\n## Frame 1\nvertex_project: body-not-frontmatter\n",
        encoding="utf-8",
    )
    assert resolve_project(sb)[0] is None


def test_gcloud_is_the_last_resort(monkeypatch, tmp_path):
    monkeypatch.setattr(gcp_project, "_from_gcloud", lambda: "gcloud-proj")
    project, source = resolve_project(tmp_path / "STORYBOARD.md")
    assert project == "gcloud-proj"
    assert source == "gcloud config"


def test_unresolved_when_nothing_is_configured(tmp_path):
    assert resolve_project(tmp_path / "missing.md") == (None, "unresolved")


def test_missing_storyboard_file_is_not_an_error(tmp_path):
    assert resolve_project(tmp_path / "nope" / "STORYBOARD.md")[0] is None


@pytest.mark.parametrize("value", ["my-project", "abc123", "a-very-long-but-valid-proj-id"])
def test_valid_project_ids(value):
    assert looks_like_project_id(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "abc",            # too short (< 6)
        "1project",       # must start with a letter
        "My-Project",     # uppercase not allowed
        "proj_underscore",  # underscore not allowed
        "trailing-",      # must end alphanumeric
        "小米-su7",        # non-ascii
        "",
    ],
)
def test_invalid_project_ids(value):
    assert looks_like_project_id(value) is False
```

- [ ] **Step 2: 运行测试**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest tests/test_gcp_project.py -v`
Expected: 全部 PASS。

- [ ] **Step 3: 提交**

```bash
cd /Users/beersoccer/workspace/clip-weave
git add tests/test_gcp_project.py
git commit -m "test(video-gen): cover GCP project resolution order"
```

---

## Task 7: video_pipeline 测试（注入假 VideoModel）

`core/video_pipeline.py` 的 `generate_clips()` 已支持 `model=` 注入，测试全部走这条路，不触网。

**Files:**
- Create: `tests/test_video_pipeline.py`

**Interfaces:**
- Consumes: `clip_weave.core.video_pipeline` 的 `generate_clips`、`concat_clips`、`ClipResult`；`adapters.video_gen` 的 `TaskStatus`、`VideoGenError`
- Produces: 测试内的 `FakeModel`，Task 8 会复用它验证路由

- [ ] **Step 1: 写测试骨架与 FakeModel**

创建 `tests/test_video_pipeline.py`：

```python
"""Offline tests for the storyboard → clips pipeline.

generate_clips() accepts `model=`, so every test injects a FakeModel and no
network or ffmpeg binary is touched.
"""

import json

import pytest

from clip_weave.adapters.video_gen import TaskStatus, VideoGenError
from clip_weave.core.video_pipeline import ClipResult, concat_clips, generate_clips

STORYBOARD = """---
format: 1920x1080
message: "test message"
---

## Frame 1 — 开场
- scene: 第一个镜头
- duration: 5s

## Frame 2 — 收尾
- scene: 第二个镜头
- duration: 5s
"""


class FakeModel:
    """Stands in for a VideoModel. Scripted per-task poll results."""

    model = "fake-model-1"
    duration_range = (5, 10)
    duration_choices = None

    def __init__(self, *, submit_error=None, polls=None, download_error=None):
        self.submit_error = submit_error
        self.polls = polls or {}
        self.download_error = download_error
        self.submitted = []
        self.downloaded = []
        self._poll_counts = {}

    def clamp_duration(self, seconds):
        return int(seconds or 5)

    def submit(self, req):
        self.submitted.append(req)
        if self.submit_error:
            raise VideoGenError(self.submit_error)
        return f"task-{len(self.submitted)}"

    def poll(self, task_id):
        n = self._poll_counts.get(task_id, 0)
        self._poll_counts[task_id] = n + 1
        scripted = self.polls.get(task_id)
        if scripted is None:
            return TaskStatus(state="succeeded", raw={}, video_url=f"https://cdn/{task_id}.mp4")
        if isinstance(scripted, list):
            return scripted[min(n, len(scripted) - 1)]
        return scripted

    def download(self, status, dest):
        if self.download_error:
            raise OSError(self.download_error)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake mp4 bytes")
        self.downloaded.append(dest)
        return dest


def _storyboard(tmp_path, body=STORYBOARD):
    path = tmp_path / "STORYBOARD.md"
    path.write_text(body, encoding="utf-8")
    return path
```

- [ ] **Step 2: 追加 dry-run 与成功路径测试**

追加到同一文件：

```python
# ── dry run ───────────────────────────────────────────────────────────────────

def test_dry_run_builds_prompts_without_a_model(tmp_path):
    results = generate_clips(
        _storyboard(tmp_path), provider="doubao", dry_run=True, report=lambda _: None
    )

    assert [r.state for r in results] == ["dry-run", "dry-run"]
    assert "第一个镜头" in results[0].prompt
    assert results[0].extra["ratio"] == "16:9"
    assert results[0].duration == 5
    # nothing written
    assert not (tmp_path / "renders").exists()


def test_no_frames_raises(tmp_path):
    path = tmp_path / "STORYBOARD.md"
    path.write_text("---\nformat: 1920x1080\n---\n\nprose only\n", encoding="utf-8")
    with pytest.raises(VideoGenError, match="no frames parsed"):
        generate_clips(path, provider="doubao", dry_run=True, report=lambda _: None)


# ── happy path ────────────────────────────────────────────────────────────────

def test_all_frames_succeed_and_files_land(tmp_path):
    model = FakeModel()
    results = generate_clips(
        _storyboard(tmp_path),
        provider="doubao",
        model=model,
        poll_interval=0,
        report=lambda _: None,
    )

    assert [r.state for r in results] == ["succeeded", "succeeded"]
    out = tmp_path / "renders" / "ai-clips" / "doubao"
    assert (out / "01-开场.mp4").exists()
    assert (out / "02-收尾.mp4").exists()
    assert len(model.submitted) == 2


def test_manifest_records_run_metadata(tmp_path):
    generate_clips(
        _storyboard(tmp_path),
        provider="doubao",
        model=FakeModel(),
        poll_interval=0,
        report=lambda _: None,
    )

    manifest = json.loads(
        (tmp_path / "renders" / "ai-clips" / "doubao" / "manifest.json").read_text()
    )
    assert manifest["provider"] == "doubao"
    assert manifest["model"] == "fake-model-1"
    assert manifest["ratio"] == "16:9"
    assert len(manifest["clips"]) == 2
    assert manifest["clips"][0]["state"] == "succeeded"


def test_frames_filter_selects_a_subset(tmp_path):
    model = FakeModel()
    results = generate_clips(
        _storyboard(tmp_path),
        provider="doubao",
        model=model,
        frames=[2],
        poll_interval=0,
        report=lambda _: None,
    )

    assert len(results) == 1
    assert results[0].index == 2
    assert len(model.submitted) == 1


def test_out_dir_override(tmp_path):
    custom = tmp_path / "elsewhere"
    generate_clips(
        _storyboard(tmp_path),
        provider="doubao",
        model=FakeModel(),
        out_dir=custom,
        poll_interval=0,
        report=lambda _: None,
    )
    assert (custom / "manifest.json").exists()


def test_include_voiceover_and_style_reach_the_prompt(tmp_path):
    body = STORYBOARD.replace("- duration: 5s", '- voiceover: "旁白内容"\n- duration: 5s', 1)
    model = FakeModel()
    generate_clips(
        _storyboard(tmp_path, body),
        provider="doubao",
        model=model,
        include_voiceover=True,
        style="35mm 胶片",
        poll_interval=0,
        report=lambda _: None,
    )
    assert "旁白内容" in model.submitted[0].prompt
    assert "35mm 胶片" in model.submitted[0].prompt
```

- [ ] **Step 3: 追加失败路径与合流测试**

追加到同一文件：

```python
# ── failure paths ─────────────────────────────────────────────────────────────

def test_submit_failure_is_recorded_per_frame(tmp_path):
    results = generate_clips(
        _storyboard(tmp_path),
        provider="doubao",
        model=FakeModel(submit_error="quota exceeded"),
        poll_interval=0,
        report=lambda _: None,
    )

    assert [r.state for r in results] == ["failed", "failed"]
    assert all("quota exceeded" in r.error for r in results)
    assert all(r.task_id is None for r in results)


def test_poll_failure_marks_only_that_frame(tmp_path):
    polls = {"task-1": TaskStatus(state="failed", raw={}, error="nsfw block")}
    results = generate_clips(
        _storyboard(tmp_path),
        provider="doubao",
        model=FakeModel(polls=polls),
        poll_interval=0,
        report=lambda _: None,
    )

    by_index = {r.index: r for r in results}
    assert by_index[1].state == "failed"
    assert by_index[1].error == "nsfw block"
    assert by_index[2].state == "succeeded"


def test_download_failure_is_reported_as_failed(tmp_path):
    results = generate_clips(
        _storyboard(tmp_path),
        provider="doubao",
        model=FakeModel(download_error="disk full"),
        poll_interval=0,
        report=lambda _: None,
    )

    assert [r.state for r in results] == ["failed", "failed"]
    assert "download failed" in results[0].error
    assert "disk full" in results[0].error


def test_timeout_marks_pending_frames_failed(tmp_path):
    still_running = TaskStatus(state="running", raw={})
    results = generate_clips(
        _storyboard(tmp_path),
        provider="doubao",
        model=FakeModel(polls={"task-1": still_running, "task-2": still_running}),
        poll_interval=0,
        max_wait=0,
        report=lambda _: None,
    )

    assert [r.state for r in results] == ["failed", "failed"]
    assert all("timed out" in r.error for r in results)


def test_elapsed_seconds_is_recorded_on_success(tmp_path):
    results = generate_clips(
        _storyboard(tmp_path),
        provider="doubao",
        model=FakeModel(),
        poll_interval=0,
        report=lambda _: None,
    )
    assert all(r.elapsed_seconds is not None for r in results)


# ── concat ────────────────────────────────────────────────────────────────────

def test_concat_requires_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr("clip_weave.core.video_pipeline.shutil.which", lambda _: None)
    clip = ClipResult(index=1, title="t", prompt="p", duration=5,
                      video_path=str(tmp_path / "01.mp4"))
    with pytest.raises(VideoGenError, match="ffmpeg not found"):
        concat_clips([clip], tmp_path / "full.mp4", report=lambda _: None)


def test_concat_with_nothing_finished_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("clip_weave.core.video_pipeline.shutil.which", lambda _: "/usr/bin/ffmpeg")
    failed = ClipResult(index=1, title="t", prompt="p", duration=5, state="failed")
    with pytest.raises(VideoGenError, match="nothing to concatenate"):
        concat_clips([failed], tmp_path / "full.mp4", report=lambda _: None)


def test_concat_orders_clips_and_cleans_the_list_file(tmp_path, monkeypatch):
    monkeypatch.setattr("clip_weave.core.video_pipeline.shutil.which", lambda _: "/usr/bin/ffmpeg")

    recorded = {}

    class Done:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = cmd
        listing = next(cmd[i + 1] for i, a in enumerate(cmd) if a == "-i")
        recorded["listing"] = open(listing, encoding="utf-8").read()
        return Done()

    monkeypatch.setattr("clip_weave.core.video_pipeline.subprocess.run", fake_run)

    for name in ("01.mp4", "02.mp4"):
        (tmp_path / name).write_bytes(b"x")
    # deliberately out of order
    clips = [
        ClipResult(index=2, title="b", prompt="p", duration=5,
                   video_path=str(tmp_path / "02.mp4")),
        ClipResult(index=1, title="a", prompt="p", duration=5,
                   video_path=str(tmp_path / "01.mp4")),
    ]

    dest = tmp_path / "full.mp4"
    assert concat_clips(clips, dest, report=lambda _: None) == dest
    assert recorded["listing"].index("01.mp4") < recorded["listing"].index("02.mp4")
    assert "libx264" in recorded["cmd"]
    assert not (tmp_path / ".full-concat.txt").exists()  # temp list removed


def test_concat_surfaces_ffmpeg_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("clip_weave.core.video_pipeline.shutil.which", lambda _: "/usr/bin/ffmpeg")

    class Failed:
        returncode = 1
        stderr = "Invalid data found when processing input"

    monkeypatch.setattr("clip_weave.core.video_pipeline.subprocess.run", lambda *a, **k: Failed())
    (tmp_path / "01.mp4").write_bytes(b"x")
    clip = ClipResult(index=1, title="a", prompt="p", duration=5,
                      video_path=str(tmp_path / "01.mp4"))

    with pytest.raises(VideoGenError, match="ffmpeg concat failed"):
        concat_clips([clip], tmp_path / "full.mp4", report=lambda _: None)
```

- [ ] **Step 4: 运行测试**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest tests/test_video_pipeline.py -v`
Expected: 全部 PASS。

注意 `test_all_frames_succeed_and_files_land` 断言的文件名含中文（`01-开场.mp4`），来自 `Frame.slug()` 保留 CJK 的行为，Task 4 已固化该行为。

- [ ] **Step 5: 提交**

```bash
cd /Users/beersoccer/workspace/clip-weave
git add tests/test_video_pipeline.py
git commit -m "test(video-pipeline): cover submit/poll/download/timeout/manifest and ffmpeg concat"
```

---

## Task 8: `render_path.py` 测试补齐

> **本任务已按用户决定重写（2026-07-31）。** 原设计是新建 `core/visual_route.py` 做
> 逐帧路由。用户判定**逐帧决定 HTML/T2V 过于复杂，应在项目之初由用户决定**，并已在
> 另一会话中实现 `core/render_path.py`：项目级 `render: html | t2v | mixed` 写在
> BRIEF.md frontmatter，首次询问后持久化；`visual_type: motion | live_action` 仅作为
> mixed 情形下的逐帧覆盖。**不再新建 `visual_route.py`。** 本任务改为给 `render_path.py`
> 补齐测试 —— 它目前只有 3 个测试嵌在 `tests/test_t2v_prompt.py` 里，边界情形无覆盖。

**Files:**
- Create: `tests/test_render_path.py`
- Modify: `tests/test_t2v_prompt.py`（移出 3 个 render_path 测试）

**Interfaces（读代码确认，不要凭本文假设）:**
- `clip_weave.core.render_path` 导出 `DEFAULT`、`RenderPath`、`VALID`、`frame_path`、`persist`、`resolve`
- `resolve(project_dir) -> tuple[RenderPath | None, str]`，未选择时返回 `(None, "unset")`
- `persist(project_dir, path) -> bool`，无 BRIEF.md 时返回 `False`
- `frame_path(frame_meta: dict[str, str], project_default: RenderPath) -> RenderPath`

- [ ] **Step 1: 读实现，列出未覆盖分支**

Run: `cd /Users/beersoccer/workspace/clip-weave && cat src/clip_weave/core/render_path.py && grep -n "render_path\|rp\." tests/test_t2v_prompt.py`

`tests/test_t2v_prompt.py` 现有三个：`test_render_path_unset_then_persisted`、
`test_render_path_read_from_brief`、`test_frame_level_override_wins`。

未覆盖的分支（逐一确认后写测试）：`render_path:` 别名；非法值走 warning 且返回 `None`；
`persist` 在无 BRIEF.md 时返回 `False`；`persist` 覆盖已存在的 `render:`；`persist` 写入
无 frontmatter 的 BRIEF.md（应新建 frontmatter 块）；`brief.md` 小写文件名；frontmatter
无闭合 `---` 时的降级；`frame_path` 在 `project_default="mixed"` 且帧无 `visual_type` 时；
`frame_path` 的 `visualtype` 无下划线别名；`_FRAME_HTML` / `_FRAME_T2V` 全部取值。

- [ ] **Step 2: 写 `tests/test_render_path.py`**

```python
"""Tests for the project-level render-path decision.

The path is the user's choice, made once per project in BRIEF.md rather than
inferred per frame. `visual_type` stays available as a per-frame override for the
`mixed` case only.
"""

import logging

import pytest

from clip_weave.core import render_path as rp


def _brief(tmp_path, body: str, name: str = "BRIEF.md"):
    (tmp_path / name).write_text(body, encoding="utf-8")
    return tmp_path


# ── resolve ───────────────────────────────────────────────────────────────────

def test_unset_when_there_is_no_brief(tmp_path):
    assert rp.resolve(tmp_path) == (None, "unset")


def test_unset_when_brief_has_no_render_key(tmp_path):
    _brief(tmp_path, "---\nworkflow: product-launch-video\n---\n\n## Intent\n")
    assert rp.resolve(tmp_path) == (None, "unset")


@pytest.mark.parametrize("value", ["html", "t2v", "mixed"])
def test_every_valid_value_resolves(tmp_path, value):
    _brief(tmp_path, f"---\nworkflow: x\nrender: {value}\n---\n")
    path, source = rp.resolve(tmp_path)
    assert path == value
    assert source == "BRIEF.md:render"


def test_render_path_alias_is_accepted(tmp_path):
    _brief(tmp_path, "---\nrender_path: t2v\n---\n")
    path, source = rp.resolve(tmp_path)
    assert path == "t2v"
    assert source == "BRIEF.md:render_path"


def test_value_is_case_insensitive_and_dequoted(tmp_path):
    _brief(tmp_path, '---\nrender: "T2V"\n---\n')
    assert rp.resolve(tmp_path)[0] == "t2v"


def test_lowercase_brief_filename_is_read(tmp_path):
    _brief(tmp_path, "---\nrender: mixed\n---\n", name="brief.md")
    path, source = rp.resolve(tmp_path)
    assert path == "mixed"
    assert source == "brief.md:render"


def test_invalid_value_warns_and_stays_unset(tmp_path, caplog):
    _brief(tmp_path, "---\nrender: veo\n---\n")
    with caplog.at_level(logging.WARNING, logger="clip_weave.core.render_path"):
        path, source = rp.resolve(tmp_path)
    assert path is None
    assert source == "unset"
    assert "veo" in caplog.text


def test_render_outside_frontmatter_is_ignored(tmp_path):
    """Only the frontmatter block counts — prose must not set the render path."""
    _brief(tmp_path, "---\nworkflow: x\n---\n\n## Notes\nrender: t2v\n")
    assert rp.resolve(tmp_path) == (None, "unset")


def test_default_is_html():
    assert rp.DEFAULT == "html"
    assert rp.VALID == ("html", "t2v", "mixed")


# ── persist ───────────────────────────────────────────────────────────────────

def test_persist_returns_false_without_a_brief(tmp_path):
    assert rp.persist(tmp_path, "t2v") is False


def test_persist_then_resolve_round_trips(tmp_path):
    _brief(tmp_path, "---\nworkflow: x\n---\n\n## Intent\n体验\n")
    assert rp.persist(tmp_path, "t2v") is True
    assert rp.resolve(tmp_path)[0] == "t2v"


def test_persist_overwrites_an_existing_value(tmp_path):
    _brief(tmp_path, "---\nrender: html\nworkflow: x\n---\n")
    rp.persist(tmp_path, "mixed")
    assert rp.resolve(tmp_path)[0] == "mixed"
    # exactly one render: line survives
    assert (tmp_path / "BRIEF.md").read_text().count("render:") == 1


def test_persist_preserves_the_rest_of_the_brief(tmp_path):
    _brief(tmp_path, "---\nworkflow: product-launch-video\n---\n\n## Intent\n核心信息\n")
    rp.persist(tmp_path, "t2v")
    text = (tmp_path / "BRIEF.md").read_text()
    assert "workflow: product-launch-video" in text
    assert "核心信息" in text


def test_persist_creates_frontmatter_when_there_is_none(tmp_path):
    _brief(tmp_path, "# Just a heading\n\nsome prose\n")
    assert rp.persist(tmp_path, "t2v") is True
    text = (tmp_path / "BRIEF.md").read_text()
    assert text.startswith("---\nrender: t2v\n---\n")
    assert "some prose" in text
    assert rp.resolve(tmp_path)[0] == "t2v"


# ── frame_path ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["motion", "html", "graphic", "graphics"])
def test_frame_html_vocabulary(value):
    assert rp.frame_path({"visual_type": value}, "t2v") == "html"


@pytest.mark.parametrize(
    "value", ["live_action", "live-action", "t2v", "footage", "realistic"]
)
def test_frame_t2v_vocabulary(value):
    assert rp.frame_path({"visual_type": value}, "html") == "t2v"


def test_frame_value_is_case_insensitive():
    assert rp.frame_path({"visual_type": "Live-Action"}, "html") == "t2v"


def test_visualtype_without_underscore_is_accepted():
    assert rp.frame_path({"visualtype": "live_action"}, "html") == "t2v"


@pytest.mark.parametrize(
    "project_default,expected", [("html", "html"), ("t2v", "t2v"), ("mixed", "html")]
)
def test_unannotated_frame_follows_the_project_default(project_default, expected):
    """`mixed` with no frame annotation falls to HTML — the safe, free path."""
    assert rp.frame_path({}, project_default) == expected


def test_unrecognised_frame_value_falls_back_to_the_project_default():
    assert rp.frame_path({"visual_type": "nonsense"}, "t2v") == "t2v"
    assert rp.frame_path({"visual_type": "nonsense"}, "html") == "html"
```

- [ ] **Step 3: 运行新测试**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest tests/test_render_path.py -v`
Expected: 全部 PASS。若某个断言与实现不符，**先判断是测试写错还是实现有缺陷**。特别注意
`test_render_outside_frontmatter_is_ignored`：`_RENDER_LINE` 用的是 `re.MULTILINE` 且
`resolve` 只把 `_frontmatter()` 的结果喂给它，所以正文里的 `render:` 不该命中。如果它命中了，
那是实现缺陷，修实现并在提交信息里说明。

- [ ] **Step 4: 从 `tests/test_t2v_prompt.py` 移除已被覆盖的 3 个 render_path 测试**

删除 `test_render_path_unset_then_persisted`、`test_render_path_read_from_brief`、
`test_frame_level_override_wins`，以及随之不再被使用的 `from clip_weave.core import
render_path as rp` 导入（先确认文件里没有其它 `rp.` 引用）。

理由：模块边界。`test_t2v_prompt.py` 应只测提示词构造；渲染路径的测试归 `test_render_path.py`。
移除前确认这 3 个的语义已被新文件覆盖（分别对应 `test_persist_then_resolve_round_trips`、
`test_every_valid_value_resolves`、`test_frame_t2v_vocabulary`）。

- [ ] **Step 5: 全量测试**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest -q`
Expected: 全绿。总数 = 71 − 3（移出）+ 新增数量。

- [ ] **Step 6: 提交**

```bash
cd /Users/beersoccer/workspace/clip-weave
git add tests/test_render_path.py tests/test_t2v_prompt.py
git commit -m "test(render-path): cover the project-level render decision

resolve/persist/frame_path had three tests embedded in test_t2v_prompt.py and no
coverage of the branches that actually bite: the render_path: alias, an invalid
value, persisting into a brief with no frontmatter, and what a `mixed` project
does with an unannotated frame. Moves the render-path tests out of the prompt
test file so each covers one module."
```

---

## Task 9: `video_pipeline` 的覆盖补齐（原路由接线任务已作废）

> **本任务已按用户决定重写（2026-07-31）。** 原设计是把 `visual_route.plan_routes()`
> 接进 `generate_clips()`。渲染路径改为项目级决策后，该接线不再需要 —— CLI 的
> `_settle_render_path()` 已在项目层面处理，`generate_clips()` 通过
> `prompt_overrides` / `duration_overrides` / `negative_overrides` /
> `reference_overrides` 接受 `T2V-PROMPTS.md` 的内容。**不新增任何路由代码。**
> 本任务改为给这批新增的 override 管道补测试 —— 它是新逻辑且零覆盖。

**Files:**
- Modify: `tests/test_video_pipeline.py`（Task 7 创建）

**Interfaces:**
- Consumes: Task 7 的 `FakeModel` 与 `_storyboard()` 辅助
- `generate_clips(..., prompt_overrides: dict[int, str] | None = None,
  duration_overrides: dict[int, int] | None = None,
  negative_overrides: dict[int, str] | None = None,
  reference_overrides: dict[int, str] | None = None)`

- [ ] **Step 1: 读实现确认 override 的确切语义**

Run: `cd /Users/beersoccer/workspace/clip-weave && grep -n "overrides" src/clip_weave/core/video_pipeline.py`

注意 `duration_overrides` 的优先级写法是 `duration or duration_overrides.get(frame.index)
or int(frame.duration_seconds or 5)` —— 显式 `duration` 参数**优先于** override。
测试要按实现的真实优先级写，不要按直觉假设。同时确认 `negative_overrides` 与
`reference_overrides` 分别落到 `VideoRequest` 的哪个字段。

- [ ] **Step 2: 追加 override 测试到 `tests/test_video_pipeline.py`**

```python
# ── T2V-PROMPTS.md overrides ──────────────────────────────────────────────────

def test_prompt_override_replaces_the_generated_prompt(tmp_path):
    model = FakeModel()
    generate_clips(
        _storyboard(tmp_path),
        provider="doubao",
        model=model,
        prompt_overrides={1: "用户手写的提示词"},
        poll_interval=0,
        report=lambda _: None,
    )
    assert model.submitted[0].prompt == "用户手写的提示词"
    # frame 2 has no override and keeps the generated prompt
    assert "第二个镜头" in model.submitted[1].prompt


def test_prompt_override_applies_in_dry_run(tmp_path):
    results = generate_clips(
        _storyboard(tmp_path),
        provider="doubao",
        dry_run=True,
        prompt_overrides={1: "手写"},
        report=lambda _: None,
    )
    assert results[0].prompt == "手写"


def test_duration_override_is_used_when_no_explicit_duration(tmp_path):
    model = FakeModel()
    generate_clips(
        _storyboard(tmp_path),
        provider="doubao",
        model=model,
        duration_overrides={1: 10},
        poll_interval=0,
        report=lambda _: None,
    )
    assert model.submitted[0].duration == 10


def test_explicit_duration_beats_the_override(tmp_path):
    """The CLI's --duration is the operator speaking last; it wins."""
    model = FakeModel()
    generate_clips(
        _storyboard(tmp_path),
        provider="doubao",
        model=model,
        duration=7,
        duration_overrides={1: 10},
        poll_interval=0,
        report=lambda _: None,
    )
    assert model.submitted[0].duration == 7


def test_negative_override_reaches_the_request(tmp_path):
    model = FakeModel()
    generate_clips(
        _storyboard(tmp_path),
        provider="doubao",
        model=model,
        negative_overrides={1: "水印, 文字"},
        poll_interval=0,
        report=lambda _: None,
    )
    assert model.submitted[0].negative_prompt == "水印, 文字"


def test_reference_override_reaches_the_request(tmp_path):
    model = FakeModel()
    generate_clips(
        _storyboard(tmp_path),
        provider="doubao",
        model=model,
        reference_overrides={1: "capture/assets/hero.png"},
        poll_interval=0,
        report=lambda _: None,
    )
    assert model.submitted[0].image_url == "capture/assets/hero.png"


def test_overrides_default_to_empty_and_change_nothing(tmp_path):
    model = FakeModel()
    generate_clips(
        _storyboard(tmp_path), provider="doubao", model=model,
        poll_interval=0, report=lambda _: None,
    )
    assert "第一个镜头" in model.submitted[0].prompt
    assert model.submitted[0].negative_prompt is None
    assert model.submitted[0].image_url is None
```

- [ ] **Step 3: 运行测试**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest tests/test_video_pipeline.py -v`
Expected: 全部 PASS。若 `negative_overrides` / `reference_overrides` 实际落到别的字段，
按实现修正断言（Step 1 已要求先确认）。

- [ ] **Step 4: 提交**

```bash
cd /Users/beersoccer/workspace/clip-weave
git add tests/test_video_pipeline.py
git commit -m "test(video-pipeline): cover the T2V-PROMPTS.md override plumbing

prompt/duration/negative/reference overrides are how a user-edited
T2V-PROMPTS.md reaches the provider, and they had no coverage. Pins the
precedence that is easy to get backwards: an explicit --duration beats a
per-frame override."
```

---

## Task 10: 技能层 —— SKILL.md 与 T2V 指南

三件事：解掉安装指令自相矛盾、把 Rule Guard 章节改为单规则、让 T2V 路径对 Agent 可见。

**Files:**
- Modify: `skills/clip-weave/SKILL.md`
- Create: `skills/clip-weave/references/t2v-guide.md`

**Interfaces:**
- Consumes: Task 2 的单规则事实、Task 3 的 `check_full`、`render_path.py` 的项目级 `render:` 与 `t2v_prompt.py` 的 `T2V-PROMPTS.md`
- Produces: 无代码接口

- [ ] **Step 1: 修正 SKILL.md 的结构与安装矛盾**

现状问题：文件顶部的 blockquote 警告「不要自动运行 `npx hyperframes skills update`」排在 H1 之前，而紧随其后的安装章节要求 Agent 运行 `bash scripts/install.sh` —— 该脚本第一步正是那条被禁止的命令。

把 SKILL.md 从 frontmatter 结束处到「# clip-weave — intent interview + workflow router」标题之前的全部内容删除，改为：H1 标题在前，然后是警告与安装章节。替换后的开头（frontmatter 保持原样不动）：

```markdown
# clip-weave — intent interview + workflow router

clip-weave 补位 HyperFrames 缺失的三件事：**意图路由、素材匹配、规则守卫**。
HF 原生能力（BRIEF.md、capture、frame.md、compositions、lint/check/render）直接复用，不重造。

> **技能版本已固定。安装完成后，任何情况下都不要主动升级技能。**
> `npx hyperframes skills update` 唯一许可的调用点是 `scripts/install.sh` 的一次性引导安装。
> 此后即使察觉技能版本落后、或 HF 打印版本告警，也只能提示用户，等用户明确要求
> （例如「更新技能」/「update skills」）才执行。擅自升级会让已部署的 Agent 在会话中途
> 因上游技能变更而中断。注意：`npx hyperframes init` 自身的内部版本检查由框架控制，无法在此抑制。

## Installation (one command)

从 clip-weave 项目根运行一次，安装全部依赖 —— HF 技能、Python 包（Rule Guard / Asset Matcher）：

```bash
bash scripts/install.sh
```

它做两件事：

1. `npx hyperframes skills update` —— 安装/刷新 HF 技能到 `~/.claude/skills/`。
   **这是本项目中该命令唯一许可的调用点**，属于一次性引导，不违反上面的固定版本约定。
2. `uv pip install -e ".[dev]"` —— 安装 Python 包。

安装后确认：

```bash
uv run python -m clip_weave --help   # 应列出 run / guard / match-assets / gen-video
npx hyperframes auth status          # signed in = 音频可用；signed out = 静音模式
```
```

- [ ] **Step 2: 重写 Rule Guard 章节（§ 7）**

把 SKILL.md 中「## 7. Rule Guard (post-composition)」整节替换为：

```markdown
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

**其余三条规则一律交给 HF 原生 lint，不要在 clip-weave 侧重造。** 曾经存在的
`gsap_css_transform_conflict`、`gsap_timeline_set_initial_hide`、`preserve_3d_filter`
三个检测器已被删除：第一条 HF 用 AST 解析器实现得更好；第二条 clip-weave 的语义与
HF 真实规则相反，照它改会引入 HF 真规则要警告的缺陷；第三条无法在正则层可靠判定。
详见 `docs/superpowers/specs/2026-07-31-rule-guard-soundness-and-t2v-routing-design.md`。

**check 的覆盖率注意事项：** `npx hyperframes check <单个文件>` 会同时关闭
`media_in_subcomposition` 与全部项目级检查（缺失/空 sub-composition、重复 composition id、
重复音轨、缺失本地资源）。单文件 check 只用于快速迭代，**渲染前必须跑一次全项目 check**：

```bash
npx hyperframes check          # 全项目，完整覆盖
```
```

- [ ] **Step 3: 新增 T2V 章节（§ 8）**

> **本步骤已按 § 计划修订 重写。** 渲染路径是**项目级**决策，不是逐帧决策。写文档前先读
> `src/clip_weave/core/render_path.py` 与 `src/clip_weave/core/t2v_prompt.py`，以及
> `src/clip_weave/__main__.py` 里 `_settle_render_path()` 和实际的命令名与选项 ——
> 下面的命令行示例必须与真实 CLI 一致，不一致时以代码为准并在报告中说明。

在 SKILL.md 的「## Resume table」之前插入：

```markdown
## 8. 渲染路径：HTML 还是 T2V

HTML 路径（HF skill 写 composition → 逐帧渲染）适合图形、文字、UI、图表 —— 确定性、
零推理费用，而且是唯一能把字体、品牌色和数据渲染准确的路径。写实画面、实景、镜头运动
交给文生视频模型更合适。

**这个选择在项目之初由用户做一次，写进 `BRIEF.md` frontmatter：**

```yaml
---
workflow: product-launch-video
render: html      # html（默认）| t2v | mixed
---
```

`render:` 缺失时问用户一次，然后持久化到 BRIEF.md —— 同一个项目不重复询问。
默认是 `html`。

只有 `render: mixed` 时才需要逐帧标注，用来指出哪些镜头走 T2V：

```markdown
## Frame 2 — 实拍开场
- scene: 城市夜景中一辆红色轿车驶过湿滑路面，霓虹反射
- visual_type: live_action
- duration: 5s
```

`visual_type: motion` 走 HTML，`live_action` 走 T2V；未标注的帧跟随项目默认，而 `mixed`
项目里未标注的帧落到 HTML（安全、免费的那一侧）。

T2V 的提示词不由模型即时拼装，而是先生成 `T2V-PROMPTS.md` —— **那是用户直接编辑的文件**。
它按各厂商提示词指南收敛的槽位顺序组织（主体、动作、场景、镜头、光线、风格、音频、约束），
复用 Asset Matcher 已打分的素材引用，并把 storyboard 的负面提示与常备规则合并。手工编辑
在重新生成时会被保留。

provider 选型、时长约束、GCP project 配置、混排注意事项见 `references/t2v-guide.md`。
```

同时在「## Resume table」的表格末尾追加一行：

```markdown
| `BRIEF.md` 的 `render:` 为 `t2v` 或 `mixed` | § 8（渲染路径） |
```

- [ ] **Step 4: 校验 SKILL.md 无残留矛盾**

Run:
```bash
cd /Users/beersoccer/workspace/clip-weave
grep -n "skills update" skills/clip-weave/SKILL.md
grep -n "gsap_css_transform_conflict\|gsap_timeline_set_initial_hide\|preserve-3d" skills/clip-weave/SKILL.md
```
Expected: 第一条只出现在 § Installation 的许可说明与顶部警告中，二者表述一致（唯一许可调用点）；第二条只出现在「已删除、交给 HF 原生」的说明语境里，没有任何把它们当作 clip-weave 现有能力介绍的句子。

- [ ] **Step 5: 提交**

```bash
cd /Users/beersoccer/workspace/clip-weave
git add skills/clip-weave/SKILL.md
git commit -m "docs(skill): fix install contradiction, single-rule guard, add T2V section"
```

---

## Task 11: `references/t2v-guide.md`

**Files:**
- Create: `skills/clip-weave/references/t2v-guide.md`

**Interfaces:**
- Consumes: Task 8/9 的路由语义；`adapters/video_gen/*` 的时长约束常量
- Produces: 无

- [ ] **Step 1: 创建文件**

```markdown
# T2V 旁路使用指南

`STORYBOARD.md` → 文生视频模型 → FFmpeg 合流。与 HTML 路径并列的第二条渲染路径，
跳过写 composition HTML。

## 何时用哪条路径

| | HTML 路径 | T2V 旁路 |
|---|---|---|
| 适合 | 图形、文字、UI、图表、数据 | 写实画面、实景、真人、镜头运动 |
| 精度 | 代码级，每帧可复现 | 有随机性，靠改提示词迭代 |
| 主要开销 | LLM 写 composition + `check` 循环的时间 | 模型推理费用与排队 |
| 不适合 | 电影级写实、复杂物理 | 精确文字排版、品牌色严格一致、数据准确性 |

品牌色和文字排版必须准确的镜头**不要**交给 T2V —— 模型无法保证十六进制色值与字形。

## 路径在项目之初决定一次

写进 `BRIEF.md` frontmatter，不是逐帧决定：

```yaml
---
workflow: product-launch-video
render: t2v       # html（默认）| t2v | mixed
---
```

缺失时会问一次并持久化，同一项目不重复询问。也接受 `render_path:` 作为别名。
非法值会告警并视为未设置。

只有 `mixed` 才需要逐帧标注，指出哪些镜头走 T2V：

```markdown
## Frame 2 — 实拍开场
- scene: 城市夜景中一辆红色轿车驶过湿滑路面
- visual_type: live_action
```

识别的取值（大小写不敏感）：

- 走 T2V：`live_action` `live-action` `t2v` `footage` `realistic`
- 走 HTML：`motion` `html` `graphic` `graphics`

未标注或取值无法识别的帧跟随项目默认；`mixed` 项目里这类帧落到 **HTML** —— 确定性、
零推理费用的那一侧。

## 提示词是一个可编辑的文件，不是即时拼装

T2V 提示词先落成 `T2V-PROMPTS.md`，**那才是用户直接编辑的文件**。它的槽位顺序取自各厂商
提示词指南收敛的结果（主体 · 动作 · 场景 · 镜头取景与运动 · 光线 · 风格 · 音频 · 约束），
并且：

- 复用 Asset Matcher 已经打过分的素材引用，不重新分析；低于分数下限的引用会被丢弃
- 把 storyboard 帧上的负面提示与常备规则合并
- 把图形密集的帧标记出来 —— 那类镜头交给 T2V 效果差，应留在 HTML 路径
- 支持 markdown 往返：重新生成不会覆盖你的手工编辑

先生成、审阅、按需改写，再交给模型，比反复重跑推理便宜得多。

## provider 与时长约束

单次生成的时长上限远小于整片，所以一份分镜必然返回 N 个片段，需要 FFmpeg 合流。

| provider | 模型 | 单次时长 | 画幅 |
|---|---|---|---|
| `doubao` | Seedance（豆包） | 1.0 pro 仅 5 或 10 秒；1.5/2.0 为 4–15 秒，用 `DOUBAO_VIDEO_DURATIONS` 声明 | 由 `ratio` 传入 |
| `ali` | 通义万相 Wan | 2–15 秒 | wan2.7 用 `resolution`+`ratio`；2.6 及更早用 `size` |
| `vertex` | Google Veo 3.1 | 仅 4 / 6 / 8 秒 | **仅 16:9 与 9:16**，其它比例会被强制为 16:9 |

分镜里写的 `duration` 会被自动 clamp 到 provider 允许的值，不会报错。

## 环境变量

见 `.env.example` 的「AI video models on the company gateway」段落。三家各自一组
`*_BASE_URL` / `*_API_KEY` / `*_MODEL`；未设置 `*_API_KEY` 时会回退到共享的
`AI_GATEWAY_API_KEY`，避免同一把 key 在 `.env` 里抄三遍。

**Vertex 需要真实的 GCP project id**，它是计费身份而非标签 —— 随便编一个名字会返回
`403 PERMISSION_DENIED / CONSUMER_INVALID`。解析顺序：

1. `VERTEX_VIDEO_PROJECT`
2. `GOOGLE_CLOUD_PROJECT` / `GCLOUD_PROJECT`
3. storyboard 或同目录 `BRIEF.md` 的 frontmatter（`vertex_project` / `gcp_project` /
   `google_cloud_project` / `project_id`）
4. `gcloud config get-value project`

设一次即可，之后不需要任何命令行参数。或用 `VERTEX_VIDEO_MODEL_PATH` 直接钉死完整资源路径。

## 推荐流程

```bash
# 1. 干跑：看路由表和最终提示词，不花钱
uv run python -m clip_weave gen-video videos/<proj>/STORYBOARD.md \
  --provider doubao --dry-run

# 2. 先只做一帧，确认风格
uv run python -m clip_weave gen-video videos/<proj>/STORYBOARD.md \
  --provider doubao --frames 2

# 3. 全部标注帧 + 合流
uv run python -m clip_weave gen-video videos/<proj>/STORYBOARD.md \
  --provider doubao --concat
```

常用开关：

- `--frames 2,4` —— 只做指定帧，无条件生成，绕过路由（显式覆盖）
- `--style "35mm 胶片质感"` —— 追加到每条提示词末尾的全局风格
- `--include-voiceover` —— 把旁白也喂进提示词（默认不喂，旁白是时间参考不是画面描述）
- `--seed 42` —— 固定随机种子，便于复现
- `--resolution 720p` —— 降分辨率试样，省时间和费用

产物落在 `<storyboard 目录>/renders/ai-clips/<provider>/`：编号片段、`manifest.json`
（含每一帧的路由决策，被跳过的帧也记录）、`--concat` 时的 `full.mp4`。

## 混排必须在 FFmpeg 层

同一支视频里动效镜头（HTML）与写实镜头（T2V）并存时，**在 FFmpeg 层合流，不要把 T2V
片段当 `<video>` 塞进 HTML 合成。** 原因：Chrome 无法同时 seek 多个 `<video>`（解码器
耗尽），视频密集的合成会退化为单 worker 甚至超时。另外 `<video>` 必须是 `index.html`
根的直接子元素，放进 sub-composition 会渲染黑屏（Rule Guard 检查的正是这条）。

## 提示词的构造方式

`build_prompt()` 从分镜帧里只取画面相关信息：`scene`、`narrativeRole` / `keyMessage`、
`beat`（情绪基调）、全局 `message` 或 `--style`。刻意丢弃 `blueprint`、`roles`、`sfx`、
`src`、`asset_candidates`、`visual_type`、`transition_in` —— 这些描述的是 HTML 合成的
实现方式，对文生视频模型是噪声。

需要排除的元素写在帧上：

```markdown
- negative_prompt: 文字, 水印, 变形的手
```
```

- [ ] **Step 2: 核对与代码一致**

Run:
```bash
cd /Users/beersoccer/workspace/clip-weave
grep -n "duration_choices\|duration_range" src/clip_weave/adapters/video_gen/*.py
grep -n "_MOTION_KEYS" -A 12 src/clip_weave/core/storyboard.py
```
Expected: 指南里的时长表与 `doubao.py`（`(5, 10)` / `DURATIONS`）、`ali.py`（`(2, 15)`）、
`vertex.py`（`(4, 6, 8)` + `supported_ratios`）一致；被丢弃的元数据键清单与 `_MOTION_KEYS`
一致（Task 8 已把 `visual_type` 加入该集合）。

- [ ] **Step 3: 提交**

```bash
cd /Users/beersoccer/workspace/clip-weave
git add skills/clip-weave/references/t2v-guide.md
git commit -m "docs(skill): add T2V bypass guide"
```

---

## Task 12: 同步 `docs/architecture.md`

架构文档是失真最严重的一份：规则数量、盲点判断、目录结构、路线图状态、测试数量全部与代码不符。

**Files:**
- Modify: `docs/architecture.md`

**Interfaces:**
- Consumes: 前 11 个任务的全部结论
- Produces: 无

- [ ] **Step 1: 更新版本头**

把文件顶部的版本块改为：

```markdown
> 文档版本：v7.0 | 更新日期：2026-07-31
> HF 能力分析见 `hyperframes-analysis.md`；技术选型见 `tech-selection.md`
>
> **v7.0 变更**：按 HF 源码逐条核对 Rule Guard 四条规则，删除三条（两条与 HF 原生重复
> 或语义相反，一条无法可靠判定），只保留 `media_in_subcomposition`；记录其真实价值边界
> （装配前 + 单文件入口两个窗口），修正 v6.1 及以前"lint 显式盲点"的错误表述；
> 取消指纹规范化与历史消费；补记增量 check 的覆盖率损失；
> T2V 旁路（P3）实际实现状态与 `visual_type` 逐帧路由落地。
```

- [ ] **Step 2: 改写 § 1.1 分工边界表**

在「clip-weave 补位」表格中，把 Rule Guard 一行改为：

```markdown
| Rule Guard | 装配前预检 `media_in_subcomposition` —— HF lint 有此规则但在装配前与单文件入口两个窗口失效 |
```

删除 Fix Registry 一行（该模块已删除）。T2V Bridge 一行改为：

```markdown
| T2V 旁路 | 复用 `STORYBOARD.md` 交文生视频模型直出写实镜头，跳过写 HTML；`visual_type` 逐帧路由 |
```

- [ ] **Step 3: 改写 § 3.1「规则遗忘」**

整节替换为：

```markdown
### 3.1 规则遗忘（已按源码核对收缩）

**原判断：** 4 条 HF 特有约束不在通用 Web 文档里，长会话上下文压缩后 LLM 易遗忘，
需要 Python 层确定性守卫反复重放。

**核对结论：** 这个判断对其中 3 条不成立。核对 `/Users/beersoccer/workspace/hyperframes`
源码后的实际情况：

| 规则 | HF 源码事实 | clip-weave 决定 |
|------|-----------|----------------|
| `media_in_subcomposition` | `packages/lint/src/rules/media.ts:345` 有实现（error 级）；`project.ts:182-197` 递归遍历 `compositions/**/*.html` 逐个以 `isSubComposition: true` 送检 | **保留** —— 但价值边界不同于原判断，见下 |
| `gsap_css_transform_conflict` | `packages/lint/src/rules/gsap.ts` 有实现（error 级），基于 acorn AST 解析器，可解析计算式 timeline、标签位置、standalone 调用；`from` 与 `fromTo` 均豁免；冲突属性不含 `rotation` | **删除** —— Python 正则版严格劣于 HF 原生 |
| `gsap_timeline_set_initial_hide` | HF 真实语义**相反**：警告 timeline 内 position 0 的零时长 `tl.set(...)`，并明确豁免 timeline 之外的 `gsap.set()`；`gsap.test.ts:2492` 断言顶层 `gsap.set` 必须不报 | **删除** —— 原实现报的正是 HF 断言不该报的写法，且建议改成 HF 真规则要警告的写法 |
| `preserve_3d_filter` | HF 全部 97 个 lint code 中无此项 | **删除** —— 机制为真，但可靠判定需完整 CSS 级联 + 祖先链解析，正则层做不到；实测在 HF 官方 `3d-camera-flight` 范例上误报 |

**保留那一条的真实理由**（不是"lint 盲点"）：HF 的 lint 规则本身是完整的，但在 clip-weave
工作的两个窗口里失效：

1. **装配前** —— `packages/lint/src/project.ts:141` 第一步读 `index.html`，尚未装配时整个
   lint 跑不起来。这正是 `frame-worker-core.md` 描述的"假绿灯"窗口。
2. **单文件入口** —— `project.ts:165` 的 `if (!entryFile && …)` 在传入 entry 时跳过
   `compositions/` 遍历，且不设置 `isSubComposition`，而规则首行是
   `if (!options.isSubComposition) return findings;`（`media.ts:349`）。

规则本身是 `variables-and-media.md` 的 NON-NEGOTIABLE 约束（媒体必须是 `index.html` 根的
直接子元素，否则永不被 seek/解码，渲染黑屏），grep 判定精确、误报空间接近零。

**指导原则（后续新增任何检查前必须先满足）：** HF 已实现且实现更优的检查不重造；机制无法
在 HF 源码中证实的规则不实现；不确定时宁可使用 HF 原生能力。任何可能把正确代码判为违规的
检查，净收益为负 —— 它会引导 LLM 把正确代码改错。

`tests/test_rule_guard.py` 中的「HF 官方正确写法零误报」测试是这条原则的可执行守卫。
```

- [ ] **Step 4: 改写 § 3.2 与 § 3.2.1**

§ 3.2 标题改为「### 3.2 Lint 循环耗时耗 token」，把「三层拦截」改为「两层」：

```markdown
**方案：两层**

**第 1 层：Pre-flight 本地拦截（<1s）**
Rule Guard 在 Python 层跑一条规则（`media_in_subcomposition`），装配前即可发现，
避免装配后才在 lint 里暴露。

**第 2 层：增量 check**
只 check 本次变更的 composition（`npx hyperframes check <file>`），未变更的跳过。

> ⚠️ **增量 check 有覆盖率代价。** 传入显式 entry 会使 HF 把该文件当作根合成：
> `project.ts:165` 跳过 `compositions/` 遍历且不设 `isSubComposition`，于是
> `media_in_subcomposition` 与全部项目级检查（缺失/空 sub-composition、重复 composition
> id、重复音轨、缺失本地资源、HEVC 提示）全部失效。
> **策略：单文件 check 仅用于迭代，渲染前必须跑一次全项目 `npx hyperframes check`。**
> `adapters/hyperframes.py` 在单文件模式下会打印该警示，并提供 `check_full()` 表达意图。

**原第 2 层 Fix Registry 已移除。** 唯一保留的规则在装配前没有可写目标 —— 修法是把媒体
节点搬到 `index.html` 根，而那个文件此时还不存在。

**原第 3 层的违规指纹 + 历史消费已取消。** 指纹规范化的目的是识别"同一语义错误复现"，
前提是存在多条语义模糊的规则；"复现即升级人工介入"用在一条判定确定的 error 级规则上，
等于给确定结论加冗余闸门。`guard-history.json` 保留为日志，不作为控制信号。
```

§ 3.2.1 整节替换为：

```markdown
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
`determinism-radius.md` 的一条窄约束（"不要对后续场景的 clip 调用 `gsap.set()`"）与一个
同名 lint code 混为一谈，然后两者都没实现对。后者的真实语义是相反方向。更进一步，
那条窄约束自身的机制也不成立：`packages/core/src/runtime/init.ts:1755-1842` 显示 clip
从不从 DOM 移除（容器 `visibility: hidden`，叶子 timed clip `display: none`，靠
`querySelectorAll("[data-start]")` 枚举）。**文档与运行时冲突时以运行时为准。**
```

注意：上段中 `determinism-radius.md` 是笔误，正确文件名是 `determinism-rules.md`，写入时用正确名称。

- [ ] **Step 5: 更新 § 4.3、§ 6、§ 8、§ 9**

§ 4.3 标题与正文改为：

```markdown
### 4.3 Rule Guard

见 § 3.1。位于 `src/clip_weave/adapters/rule_guard.py`。单条规则，无 Fix Registry。
```

§ 6 目录结构中 `src/clip_weave/` 部分改为：

```
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
│       ├── project_factory.py          # BRIEF.md + capture/ + frame.md 组装
│       ├── delegator.py                # 调 Claude Code + skill
│       ├── workflow_router.py          # LLM 语义 workflow 分类（关键词为兜底）
│       ├── storyboard.py               # STORYBOARD.md 解析 + 基础提示词构造
│       ├── render_path.py              # 项目级 render: html|t2v|mixed（默认 HTML）
│       ├── t2v_prompt.py               # 生成用户可编辑的 T2V-PROMPTS.md
│       └── video_pipeline.py           # 逐帧生成 + manifest + FFmpeg 合流
```

`skills/clip-weave/references/` 下增加一行 `t2v-guide.md`。

§ 8 路线图的 P1 / P3 两行改为：

```markdown
| **P1** | 解决 lint 痛点 | 按 HF 源码核对后收缩为单规则装配前预检；增量 check 及其覆盖率策略 | ✅ 完成（三条规则经核对删除，见 § 3.1）|
| **P3** | **T2V 旁路** | STORYBOARD.md 解析；三家 provider；逐帧生成 + manifest；FFmpeg 合流；项目级 `render:` 路径选择；用户可编辑的 `T2V-PROMPTS.md` | ✅ 代码完成，待真实网关实测 |
```

§ 8 路线图之后补一段说明渲染路径的定位（替换原计划里"分镜级决策"的表述）：

```markdown
**渲染路径是项目级决策。** 逐帧判断走 HTML 还是 T2V 对用户过于复杂，因此改为在项目之初
问一次、写进 `BRIEF.md` 的 `render:` 并持久化。`mixed` 时才用帧上的
`visual_type: motion | live_action` 指出个别镜头。默认 HTML —— 确定性、零推理费用，
且是唯一能准确渲染字体、品牌色与数据的路径。
```

「当前状态」一行改为（测试数量在 Task 13 用实际数字回填）：

```markdown
**当前状态**：P0–P3 代码全部交付，<N> 个测试通过。P3 待真实网关实测；P4 混排待 P3 实测后设计。
```

§ 9 中「Rule Guard 预计带来的节省」整段替换为：

```markdown
**Rule Guard 的收益已按核对结果下调。** 它现在只拦截一条规则，节省来自"装配前发现
黑屏级缺陷"而非"减少 lint 轮数"。原 v6.x 预估的 30-50% 降幅建立在四条规则与自动修复
之上，那两个前提都已不成立，故移除该数字。
```

- [ ] **Step 6: 核对文档内不再有失效表述**

Run:
```bash
cd /Users/beersoccer/workspace/clip-weave
grep -n "Fix Registry\|_FIXERS\|显式盲点\|4 条\|四条 HF" docs/architecture.md
```
Expected: 只在 § 3.1 / § 3.2 / § 3.2.1 的"已删除/已修正"叙述语境中出现，没有任何把它们当作现存能力介绍的句子。

- [ ] **Step 7: 提交**

```bash
cd /Users/beersoccer/workspace/clip-weave
git add docs/architecture.md
git commit -m "docs(architecture): v7.0 — align with HF source review and T2V reality"
```

---

## Task 13: 同步其余文档并全量验证

**Files:**
- Modify: `README.md`
- Modify: `docs/report-tech-leads.md`
- Modify: `docs/hyperframes-analysis.md`
- Modify: `docs/tech-selection.md`
- Modify: `.env.example`
- Modify: `docs/architecture.md`（回填测试数量）
- Modify: `src/clip_weave/adapters/rule_guard.py`（改一处悬空引用）
- Modify: `tests/test_rule_guard.py`（同上）

> **Task 2 评审带出的两项，一并在本任务处理：**
>
> 1. `docs/tech-selection.md:83-84` 仍保留着 Task 2 要纠正的那处规则语义倒置表述
>    （「页面加载时 `gsap.set()` … 应改用 `tl.set()`」）。这是全仓库最后一处该错误说法，
>    必须改掉，否则它会成为把被删检测器加回来的依据。
> 2. `rule_guard.py:7` 与 `tests/test_rule_guard.py:4` 引用
>    `docs/superpowers/specs/…-design.md`，而 `docs/superpowers` 被 `.gitignore` 忽略 ——
>    对克隆仓库的人是悬空引用。把这两处指向 `docs/architecture.md` § 3.1（Task 12 已让该节
>    承载完整的核对结论与三条规则的删除理由）。docstring 本身的解释是自洽的，只改指引目标。
> 3. **把源码引用里的行号换成不会漂移的代码表达式。** `rule_guard.py` 的 docstring 与
>    `hyperframes.py` 的 `_SINGLE_FILE_COVERAGE_WARNING` 注释都引用了 HF 的具体行号，实测
>    已漂移 2 行（`project.ts` 的守卫在 167 而非 165，`isSubComposition: true` 在 197，
>    `media.ts` 的提前返回在 351 而非 349；`gsap.ts` 与 `gsap.test.ts` 的引用同样漂移
>    2–3 行）。断言全部为真，但行号会继续漂移。改为引用文件名 + 可 grep 的代码片段，例如
>    「`project.ts` 的 `if (!entryFile && existsSync(compositionsDir))` 守卫」、
>    「`media.ts` 的 `if (!options.isSubComposition) return findings;`」。
>    涉及文件：`src/clip_weave/adapters/rule_guard.py`、
>    `src/clip_weave/adapters/hyperframes.py`、`tests/test_rule_guard.py`。

**Interfaces:**
- Consumes: 全部前置任务
- Produces: 无

- [ ] **Step 1: 修正 `.env.example` 与代码矛盾的表述**

当前「Semantic embedding」段落的注释写着 embedding 未配置时回退到 `VIDEO_ANALYSIS_*`，
与 `config.py` 的 `has_embedding`（要求 `embedding_base_url` 与 `embedding_api_key` 同时存在）
以及 architecture.md § 5.4「两组完全独立」都矛盾。把那两行注释替换为：

```
# ── Semantic embedding (Asset Matcher Phase 2) ────────────────────────────────
# OpenAI-compatible /v1/embeddings endpoint. Independent of VIDEO_ANALYSIS_*:
# if these are unset, matching falls back to BM25 keyword ranking.
```

- [ ] **Step 2: 逐个定位其余文档中的失效表述**

Run:
```bash
cd /Users/beersoccer/workspace/clip-weave
grep -n "Fix Registry\|_FIXERS\|显式盲点\|4 条\|四条\|33 个测试\|33 tests\|t2v\.py\|gsap_css_transform_conflict\|gsap_timeline_set_initial_hide\|preserve-3d" README.md docs/report-tech-leads.md docs/hyperframes-analysis.md
```

对每一处命中，按下列原则改写：

- 「4 条 / 四条规则」→「1 条规则」，并补一句为何其余三条交给 HF 原生。
- 「lint 显式盲点」→ 改为准确表述：HF lint 有该规则，但装配前与单文件入口两个窗口失效。
- 「Fix Registry」/「`_FIXERS`」→ 删除，或改为「已移除：唯一保留的规则在装配前无可写目标」。
- 「`adapters/t2v.py`（待建）」→ 改为实际结构 `adapters/video_gen/` + `core/storyboard.py` +
  `core/render_path.py` + `core/t2v_prompt.py` + `core/video_pipeline.py`。
- 「33 个测试」→ 用 Step 4 得到的实际数字。
- 提到那三条被删规则时，必须同时说明删除原因，避免读者以为是遗漏待补。

`docs/hyperframes-analysis.md` 若有把 `media_in_subcomposition` 描述为 lint 不检测的句子，
改为：lint 检测（error 级），但需要 `isSubComposition`，单文件入口下不生效。

- [ ] **Step 3: 运行全量测试**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest -q`
Expected: 全绿，无 warning 级失败。

- [ ] **Step 4: 取实际测试数量并回填文档**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest -q 2>&1 | tail -3`

把输出中的通过数量回填到 `docs/architecture.md` § 8「当前状态」与 `README.md` 中对应位置，
替换掉占位的 `<N>` 与旧的 33。

- [ ] **Step 5: 端到端验证 Rule Guard 在真实项目上零误报**

Run:
```bash
cd /Users/beersoccer/workspace/clip-weave
.venv/bin/python -m clip_weave guard videos/noah-group
.venv/bin/python -m clip_weave guard videos/xiaomi-su7-promo
```
Expected: 两个都输出 `Rule Guard: all clear`，退出码 0。

再验证真违规确实会被拦截：

```bash
cd /Users/beersoccer/workspace/clip-weave
mkdir -p /tmp/cw-verify/compositions/frames
printf '<template><video src="x.mp4" muted playsinline></video></template>' \
  > /tmp/cw-verify/compositions/frames/01.html
.venv/bin/python -m clip_weave guard /tmp/cw-verify; echo "exit=$?"
rm -rf /tmp/cw-verify
```
Expected: 打印 `media_in_subcomposition` 违规，`exit=1`。

- [ ] **Step 6: 验证 CLI 帮助反映全部能力**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m clip_weave --help && .venv/bin/python -m clip_weave gen-video --help`
Expected: 顶层列出 `run` / `guard` / `match-assets` / `gen-video`；`gen-video` 的帮助里含
各命令的选项与 `src/clip_weave/__main__.py` 的实际定义一致（以代码为准）。

- [ ] **Step 7: 文档与代码一致性终检**

Run:
```bash
cd /Users/beersoccer/workspace/clip-weave
# 文档里提到的模块必须真实存在
for f in adapters/rule_guard.py adapters/hyperframes.py adapters/asset_matcher.py \
         adapters/video_gen/base.py adapters/video_gen/doubao.py adapters/video_gen/ali.py \
         adapters/video_gen/vertex.py adapters/video_gen/gcp_project.py \
         core/intent_router.py core/project_factory.py core/delegator.py \
         core/storyboard.py core/render_path.py core/t2v_prompt.py \
         core/video_pipeline.py core/workflow_router.py pipeline.py; do
  test -f "src/clip_weave/$f" || echo "MISSING: $f"
done
# 文档里不应再出现已删除的符号
grep -rn "_FIXERS\|GuardResult.fixed\|adapters/t2v.py" docs/ README.md skills/ 2>/dev/null \
  | grep -v superpowers/specs | grep -v superpowers/plans
```
Expected: 无 `MISSING:` 输出；第二条 grep 无结果（spec 与 plan 目录允许保留历史叙述）。

- [ ] **Step 8: 提交**

```bash
cd /Users/beersoccer/workspace/clip-weave
git add README.md docs/report-tech-leads.md docs/hyperframes-analysis.md .env.example docs/architecture.md
git commit -m "docs: align README, tech-lead report, HF analysis and .env.example with code"
```

- [ ] **Step 9: 最终确认工作区干净**

Run: `cd /Users/beersoccer/workspace/clip-weave && git status --short && .venv/bin/python -m pytest -q 2>&1 | tail -2`
Expected: 除 `videos/`、`.claude/`、`.agents/` 等既有未跟踪项外无遗漏改动；测试全绿。

---

## Self-Review 记录

**规格覆盖检查：** 规格 § 2.1 → Task 2；§ 2.2 → Task 3；§ 3.2 缺口 1 → Task 8/9；
缺口 2 → Task 1/4/5/6/7；缺口 3 → Task 10/11；缺口 4 → Task 12/13；§ 4 → Task 8/9；
§ 5 → Task 1/2/4/5/6/7/8/9；§ 6 → Task 10/11；§ 7 → Task 12/13；§ 8「不做的事」→
体现为 Task 2 的删除动作与 Task 12 的留档。

**类型一致性检查：** Task 8/9 改为测试既有实现，签名以 `render_path.py` 与
`video_pipeline.py` 的真实代码为准（两个任务的 Step 1 都要求先读实现再写断言）；`check_full` 在 Task 3 定义，Task 10 与
Task 12 的文档按同名引用；`GuardResult` 在 Task 2 去掉 `fixed`，Task 2 Step 4 同步更新
`pipeline.guard()`。

**已知需要执行者判断的地方：**
- Task 1 Step 7 的测试数量预期已在正文中自我修正为 32，执行时以实际为准。
- Task 4 Step 2、Task 5 Step 2 提示：断言与实现不符时先判断是测试写错还是实现缺陷，
  解析器既有行为为基线，改实现须单独提交并说明。
- Task 12 Step 4 正文中出现的 `determinism-radius.md` 为笔误，写入时用 `determinism-rules.md`。
