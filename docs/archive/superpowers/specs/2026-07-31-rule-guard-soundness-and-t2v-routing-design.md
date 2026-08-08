# clip-weave — Rule Guard 有效性收缩 + T2V 逐帧路由设计规格（历史，2026-07-31）

> 已实现或已被后续架构取代；当前设计见[架构](../../../architecture.md)。

> 版本：v1.0 | 日期：2026-07-31
> HF 源码核对基线：`/Users/beersoccer/workspace/hyperframes`

---

## 0. 指导原则

**clip-weave 对 HF 的每一处"优化"都必须是核对 HF 源码后确认必要的。**

推论，按优先级：

1. HF 已实现且实现质量更高的检查，clip-weave **不重造**。用正则近似一个基于 AST 的规则，结果只会更差。
2. 机制无法在 HF 源码中证实的规则，**不实现**。文档描述与运行时实现冲突时，以运行时实现为准，且宁可缺失一条检查也不引入误判。
3. 只有在 HF 能力存在**源码可证的空档**、且 clip-weave 的判定**误报空间接近零**时，才补位。
4. 任何新增检查若可能把正确代码判为违规，其净收益为负 —— 因为它会引导 LLM 把正确代码改错。

本规格的主要动作就是把既有实现按这四条重新裁剪。

---

## 1. HF 源码核对结论

### 1.1 四条 Rule Guard 规则逐条核对

| 规则 | HF 源码事实 | 判定 |
|------|-----------|------|
| `media_in_subcomposition` | `packages/lint/src/rules/media.ts:345` 有完整实现，severity `error`。`packages/lint/src/project.ts:182-197` 递归遍历 `compositions/**/*.html`，逐个以 `isSubComposition: true` 送检 | **保留**（理由见 § 1.2） |
| `gsap_css_transform_conflict` | `packages/lint/src/rules/gsap.ts` 有实现，severity `error`。基于 `@hyperframes/parsers/gsap-parser-acorn` 的 AST 解析器，可解析计算式 timeline、标签位置、`+=`/`-=` 偏移；额外用正则补齐 standalone `gsap.*` 调用；selector 匹配为「先精确串匹配，再退化为逗号分组各组最右复合选择器的 `#id`/`.class` token」 | **删除** |
| `gsap_timeline_set_initial_hide` | `packages/lint/src/rules/gsap.ts` 有实现，severity `warning`，**语义与 clip-weave 相反**（见 § 1.3） | **删除** |
| `preserve_3d_filter` | HF lint 全部 97 个 rule code 中**无此项**，`packages/cli/src/commands/check.ts` 中亦无 | **删除**（见 § 1.4） |

### 1.2 `media_in_subcomposition` 的两个源码可证空档

architecture.md v6.1 § 3.1 标注该规则为「⚠️ lint 显式盲点，必须 grep 手动检查」——**此表述错误**，须修正。规则在 lint 中以 `error` 级完整实现。

但 clip-weave 的预检仍有价值，理由是两个可在源码中确证的失效窗口：

**空档 A — 装配前窗口。** `project.ts:141`：

```ts
const indexPath = entryFile ? resolve(entryFile) : resolve(projectDir, "index.html");
...
const rootHtml = readFileSync(indexPath, "utf-8");
```

`index.html` 尚未装配时 `lintProject` 第一步即失败，整个 lint 跑不起来。这正是 `hyperframes-core/references/frame-worker-core.md` 描述的窗口：frame worker 无法自检，「它们作用于已装配的项目，你的帧还没接进去，报的是别的文件，是假绿灯」。

**空档 B — 单文件入口窗口。** `project.ts:165`：

```ts
if (!entryFile && existsSync(compositionsDir)) {   // 传 entryFile 时整段遍历被跳过
```

传 `entryFile` 时，该文件以**根合成**身份送检，`options.isSubComposition` 不被设置。而规则首行是：

```ts
if (!options.isSubComposition) return findings;   // media.ts:349
```

即 `npx hyperframes lint <单个 composition 文件>` 下该规则**静默失效**，同时全部项目级检查（`lintMissingOrEmptySubComposition`、`duplicate_composition_id`、音轨重复、缺失资源）也被跳过。

规则本身是 `variables-and-media.md` 明示的 NON-NEGOTIABLE 约束（媒体必须是 `index.html` 根的直接子元素，否则永不被 seek/解码，渲染为黑屏/白屏），grep `<video|<audio>` 在 `compositions/**` 的判定精确、误报空间接近零。**符合第 3 条原则，保留。**

### 1.3 `gsap_timeline_set_initial_hide` 语义倒置（最关键的核对结果）

HF 真实规则针对的是 **timeline 内部 position 0 上的零时长 `tl.set(...)`**：零时长 set 在 playhead 恰好停在 0 时不生效，第 0 帧显示未隐藏状态，第 1 帧才跳为隐藏，且只影响渲染第 0 帧的那个 worker。

关键豁免条件：

```ts
if (win.global || win.immediateRender) continue;
```

`global` 的类型注释为 `/** True for an off-timeline 'gsap.set(...)' (applied once at load). */` —— **顶层 `gsap.set()` 被明确豁免**。官方 fixHint 方向：

> Use `gsap.set(...)` (immediate, outside the timeline) for initial states, or author the hidden state directly in CSS/attributes.

HF 自身单测（`packages/lint/src/rules/gsap.test.ts:2492`，用例名 "does NOT warn on immediate gsap.set or mid-timeline sets"）断言以下三行均**不产生 finding**：

```js
gsap.set('#a', { opacity: 0 });        // 顶层 —— 断言不报
tl.set('#b', { opacity: 0 }, 3);       // 非 0 位置 —— 断言不报
tl.set('#a', { x: 40 }, 0);            // 位置 0 但不隐藏 —— 断言不报
```

clip-weave 现实现报的正是第一行（HF 断言必须不报的那行），且 `detail` 建议「改用 `tl.set()` 放入 timeline」—— 恰是 HF 这条规则要警告的写法。

交叉印证：HF 的 `gsap_fullscreen_overlay_starts_visible` 的 fixHint 明确开出的药方就是「add an immediate `gsap.set(selector, { opacity: 0 })` (outside the timeline)」，源码注释还专门说明这两条规则的建议不能互相矛盾。clip-weave 报的是 HF 自己开的药方。

**后果不是噪声而是质量倒退**：按其提示修改（顶层 `gsap.set` → `tl.set(…, 0)`）会主动制造 HF 真规则警告的第 0 帧闪跳。`videos/xiaomi-su7-promo/.clip-weave/guard-history.json` 中 16 条 `gsap_timeline_set_initial_hide` / `status: unknown` 由此得到解释。**违反原则 4，删除。**

#### 1.3.1 为何不改实现为 `determinism-rules.md` 的那条规则

`hyperframes-core/references/determinism-rules.md` 另有一条无 lint code 覆盖的约束：

> **Do not** `gsap.set()` clip elements from later scenes — they are not in the DOM at page load.

其陈述的机制与运行时实现不符。`packages/core/src/runtime/init.ts:1755-1842`：clip 从不从 DOM 移除，容器用 `visibility: hidden`，叶子 timed clip 用 `display: none`，并通过 `document.querySelector`/`querySelectorAll("[data-start]")` 枚举与缓存叶子判定 —— 说明它们**始终在 DOM 中**。

机制无法在源码中证实，**按原则 2 不实现**。

### 1.4 为何不实现 `preserve_3d_filter`

机制本身为真且是 CSS 规范层面的确定行为：`filter` 取非 `none` 值会把该元素的 used `transform-style` 强制为 `flat`，塌陷其内部所有 `translateZ`。`hyperframes-animation/rules/3d-camera-flight.md:170` 有对应硬约束（「Keep the world CLEAN」）。

但判定「是否构成缺陷」需要：完整 CSS 级联解析 → 解析每个 selector 实际匹配的元素 → 祖先链上是否存在 filter 承载者 → 该 3D 上下文内是否真的存在依赖 Z 的子元素。Python 正则层无法可靠完成。

现实现为 `if "preserve-3d" in html and "filter:" in html` → 整文件报一条（行号 0）。已实测：按 `3d-camera-flight.md` 官方范例原样构造的**正确** composition（`.world` 承载 `preserve-3d`、`.layer` 承载 HF 规定的叶子 DoF `filter: blur(var(--dof))`）触发误报。

同时该约束已内联进 frame worker 的 packet（`## Selected motion rule` 段落随分镜下发），LLM 侧已有信息。**按原则 2 + 3，不实现。**

### 1.5 连带取消：指纹行号无关化 + `guard-history.json` 消费

architecture.md § 3.2.1 待办 1/2。Rule Guard 收缩到单条机械规则后，这套管道没有承载对象：

- 指纹规范化的目的是识别"同一语义错误复现"，前提是存在多条语义模糊的规则。
- "复现即升级人工介入"用在一条 `error` 级、判定确定的规则上，等于给确定结论加冗余闸门。

**取消这两项。** `save_history()` 保留为日志，只修其两个实际缺陷（见 § 2.1）。

### 1.6 新发现：增量 check 的覆盖率损失

architecture.md § 3.2 第 3 层将「只 check 本次变更的 composition（`npx hyperframes check <file>`）」列为 P1 已完成的优化。由 § 1.2 空档 B，该优化会同时关闭：

- `media_in_subcomposition`（`isSubComposition` 未设置）
- 全部项目级检查（`lintMissingOrEmptySubComposition`、`lintMultipleRootCompositions`、`duplicate_composition_id`、`lintDuplicateAudioTracks`、`lintProjectAudioFiles`、`lintMissingLocalAsset`、`lintAudioSrcNotFound`、`lintTextureMaskAssetNotFound`、`lintHevcPreviewCodec`）

这是用时间换真实覆盖率。需在代码与文档中确立策略：**单文件 check 仅用于迭代，渲染前必须跑一次全项目 check。**

---

## 2. Rule Guard 目标状态

### 2.1 变更清单

保留：

- `media_in_subcomposition` 检测器，实现不变。
- `Violation` / `GuardResult` / `scan()` / `save_history()` 的整体形状不变（下游 `pipeline.guard()`、CLI `guard` 命令、测试依赖它）。

删除：

- `_check_gsap_css_transform_conflict`
- `_check_gsap_timeline_set_initial_hide`
- `_check_preserve_3d_filter`
- `_FIXERS` 空注册表及 `scan()` 内的分流分支（无条目，且四条规则中唯一保留的那条在装配前无法自动修 —— 目标位置 `index.html` 尚不存在）
- `GuardResult.fixed` 字段（恒为空，属于误导性 API）

修正：

- `Violation.__post_init__` 的指纹保持 `rule_id + file.name + line` 不变（单规则场景下行号敏感不构成问题，且它只用于日志去重）
- `save_history()`：`mkdir(parents=True, exist_ok=True)`；`json.loads` 包 `try/except (json.JSONDecodeError, OSError)`，损坏时以空历史重建并 warning
- `_check_media_in_subcomposition` 的 `detail` 去掉无占位符的 f-string；文案改为引用 HF 原文（NON-NEGOTIABLE + 直接子元素 + 渲染黑屏）并指明这是装配前预检

新增：

- 模块 docstring 说明收缩理由与 HF 源码位置，防止后续再次"补齐"被删掉的规则
- `RULE_IDS` 缩为单元素列表

### 2.2 `hyperframes.py` 的 check 策略

`check(project_dir, file=None)` 在 `file` 非空时记录一条 warning，明示本次调用不包含 `media_in_subcomposition` 与项目级检查，并提示渲染前需全项目 check。新增 `check_full(project_dir)` 语义等价于 `check(project_dir)`，仅为在调用点表达意图（避免误以为单文件 check 等价）。

---

## 3. T2V 路径现状与缺口

### 3.1 已实现（architecture.md 记为 P3「待验证 / `adapters/t2v.py` 待建」，实际已落地且形态不同）

| 能力 | 位置 |
|------|------|
| STORYBOARD.md 宽容解析（frontmatter + `Frame`/`Beat`/`Scene` 标题 + 别名归一） | `core/storyboard.py` |
| 分镜 → T2V 提示词（剔除 `blueprint`/`roles`/`sfx`/`src` 等 HTML 动效元数据） | `storyboard.build_prompt()` |
| 三家 provider（豆包 Seedance / 阿里万相 / Vertex Veo）统一 submit→poll→download | `adapters/video_gen/{doubao,ali,vertex}.py` + `base.py` |
| 逐帧生成 + manifest 落盘 | `core/video_pipeline.generate_clips()` |
| FFmpeg 合流 | `core/video_pipeline.concat_clips()` |
| Vertex GCP project 多来源解析 | `adapters/video_gen/gcp_project.py` |
| CLI（`--dry-run` / `--frames` / `--concat`） | `__main__.gen_video_cmd` |

### 3.2 缺口

1. **`visual_type` 逐帧路由** —— P3 明列交付项，全仓库无该标识符（仅 `docs/tech-selection.md` 提及）
2. **零测试覆盖** —— 上述约 1300 行无任何测试
3. **技能层不可见** —— `skills/clip-weave/SKILL.md` 完全未提 `gen-video`
4. **文档失真** —— 目录结构、路线图状态、测试数量均与代码不符

---

## 4. `visual_type` 逐帧路由设计

### 4.1 定位

路由单元是 STORYBOARD.md 中的**单个 `## Frame N`**，同一份分镜内可第 2 帧走 T2V 写实镜头、第 3 帧走 HTML 图表。这落实 architecture.md 的「分镜级决策而非项目级」，并构成 P4 混排的地基。

新增独立模块 `core/visual_route.py`，单一职责：`Storyboard` → 每帧的 `path` + 判定来源。

- 不放进 `storyboard.py`：解析器只负责解析。
- 不放进 `video_pipeline.py`：P4 混排时 HTML 路径与 T2V 路径需消费同一份路由结果。

### 4.2 枚举映射

沿用 `docs/tech-selection.md` 已有词表：

| `visual_type` 值 | 路由 |
|---|---|
| `t2v` / `video` / `ai` / `live_action` / `b_roll` / `product_shot` / `footage` | T2V |
| `html` / `text_card` / `ui` / `chart` / `title` / `data` / `code` | HTML |
| 无法识别的值 | HTML + warning（保守：不因拼写错误产生推理费用） |

### 4.3 优先级（默认 HTML）

1. CLI `--frames 2,4` 显式点名 → 无条件生成，路由不参与
2. `--all-frames` → 全部走 T2V，路由不参与
3. 帧上写了 `- visual_type: <值>` → 按声明
4. storyboard frontmatter 写了 `default_visual_type: <值>` → 按该默认值
5. 以上皆无 → **HTML**，从 T2V 生成中跳过

第 5 条是与既有行为的**破坏性变更**：当前 `gen-video` 生成每一帧。变更后未标注的分镜一帧都不生成。这是刻意的安全默认 —— 避免对未标注分镜误跑整轮推理费用。配套要求：`gen-video` 在 0 帧入选时打印可执行的提示（加 `visual_type: t2v`，或用 `--frames` / `--all-frames`）。

### 4.4 数据结构与输出

```python
@dataclass(frozen=True)
class FrameRoute:
    frame: Frame
    path: Literal["html", "t2v"]
    source: str          # "frame.visual_type" | "storyboard.default_visual_type"
                         # | "default" | "cli.frames" | "cli.all-frames"
    declared: str | None # 原始声明值，未声明为 None

def plan_routes(sb, *, frames=None, all_frames=False) -> list[FrameRoute]
def t2v_frames(routes) -> list[Frame]
def format_route_table(routes) -> str
```

`generate_clips()` 改为消费 `plan_routes()` 的结果；manifest 新增 `routing` 字段记录全部帧的路由决策（含被跳过的），供 P4 混排使用。`clips` 仍只含实际生成的帧。

---

## 5. 测试计划

全部离线，不触达真实网关。按模块建文件，从 `test_pipeline.py` 中拆出混入的其它模块测试。

| 文件 | 覆盖 |
|------|------|
| `test_rule_guard.py` | `media_in_subcomposition` 命中与不命中；**HF 官方正确写法零误报**（取自 `3d-camera-flight.md` 范例 + `gsap.test.ts:2492` 断言用例）；`save_history` 的目录创建与损坏 JSON 容错 |
| `test_storyboard.py` | 无 frontmatter / frontmatter 非映射 / 三种标题形态 / 别名归一 / `duration` 解析 / `aspect_ratio()` 换算 / `slug()` 中文 / `build_prompt()` 剔除动效元数据 / warnings |
| `test_visual_route.py` | § 4.3 五条优先级；未识别值降级；`default_visual_type`；路由表格式 |
| `test_video_gen_providers.py` | 三家的请求体构造（含 ali 的 wan27/legacy 双方言、doubao 的 `DURATIONS` 解析、vertex 的 model_path 两种形态）；状态映射；task_id 缺失报错；`clamp_duration` |
| `test_video_pipeline.py` | 注入假 `VideoModel`：提交失败 / 轮询失败 / 超时 / 下载失败 / manifest 内容 / `routing` 字段；`concat_clips` 缺 ffmpeg 与拼接失败 |
| `test_gcp_project.py` | env → frontmatter → gcloud 优先级；`looks_like_project_id` 边界 |
| `test_project_factory.py` | 从 `test_pipeline.py` 拆出的素材过滤测试 |
| `test_asset_matcher.py` | 从 `test_pipeline.py` 拆出的降级测试 |

`pyproject.toml` 增加 `[tool.pytest.ini_options]`（`testpaths`、`pythonpath`）。

Rule Guard 的"零误报"测试是本规格的核心防回归资产：它把 § 1 的核对结论固化成可执行断言，使任何"补齐"被删规则的尝试立即失败。

---

## 6. 技能层变更

### 6.1 `SKILL.md`

- **修正自相矛盾的安装指令**：现状是顶部 blockquote 警告「不要自动运行 `npx hyperframes skills update`」，紧接着的安装章节让 Agent 跑 `bash scripts/install.sh`，而该脚本第一步正是该命令。改为明确表述：`scripts/install.sh` 的一次性引导是**唯一**许可的调用点；安装完成后任何情况下都不主动升级，包括察觉版本落后或 HF 报版本告警时，也只能提示用户、等用户明确要求（如「更新技能」）才执行。
- **结构修正**：blockquote 与安装章节移到 H1 之后，使 Agent 读到的第一段是技能定位。
- **Rule Guard 章节改写为单规则**，并说明其价值边界（装配前 + 单文件入口两个窗口），明确其余三条规则交给 HF 原生 lint。
- **新增 T2V 章节** + `references/t2v-guide.md`。

### 6.2 `references/t2v-guide.md`（新增）

provider 选型与时长约束（Veo 4/6/8s 且仅 16:9 / 9:16；Seedance 依模型 5/10 或 4–15；Wan 2–15）、`visual_type` 逐帧标注用法、GCP project 配置、`--dry-run` 先验流程、FFmpeg 合流的必要性（各家单次生成时长都远小于整片）、以及为何混排必须在 FFmpeg 层而非 HTML 内嵌 `<video>`。

---

## 7. 文档同步清单

| 文档 | 修改 |
|------|------|
| `docs/architecture.md` | § 3.1 四条规则表改为单规则 + 修正「lint 显式盲点」错误表述；§ 3.2 三层拦截改为两层（删除 Fix Registry 层）+ 增量 check 覆盖率损失与兜底策略；§ 3.2.1 整节按核对结论重写（含语义倒置的记录，作为反面案例保留）；§ 4.3 模块说明；§ 6 目录结构（`t2v.py` → `video_gen/` + `storyboard.py` + `video_pipeline.py` + `visual_route.py`）；§ 8 路线图 P1/P3 状态与测试数量；§ 9 移除对 Fix Registry 节省的预估 |
| `README.md` | 规则清单、测试数量、T2V 使用说明 |
| `docs/report-tech-leads.md` | Rule Guard 相关结论按核对结果修正 |
| `docs/hyperframes-analysis.md` | 「lint 盲点」相关表述核对修正 |
| `.env.example` | 删除与代码及 architecture.md § 5.4 矛盾的「EMBEDDING 未配置时回退到 VIDEO_ANALYSIS_*」表述 |
| `skills/clip-weave/SKILL.md` + `references/` | 见 § 6 |

---

## 8. 不做的事

明确记录，避免后续重复讨论：

- 不重造 `gsap_css_transform_conflict`（HF 的 AST 实现更优）
- 不实现 `gsap_set_on_later_scene_clip`（机制与运行时源码冲突）
- 不实现 `preserve_3d_filter`（Python 层无法可靠判定）
- 不实现任何自动 fixer（唯一保留的规则在装配前无可写目标）
- 不做指纹规范化与历史消费（单规则场景无承载对象）
- 不做 P4 混排（待 P3 实测通过后单独设计；牵涉 Chrome 多 `<video>` seek 限制）
