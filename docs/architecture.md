# clip-weave 架构

> 当前架构与实现边界。面向开发者和维护者；面向生产质量与后续演进请读 [production-quality-loop.md](production-quality-loop.md)。

## 1. 定位

clip-weave 是视频生产的前置编排层，不是另一个视频模型或完整剪辑器。

它的职责是把模糊输入变成一个可运行项目，并将每类画面交给最适合的引擎：HyperFrames 负责确定性图形画面，T2V 负责写实运动画面。HyperFrames 继续拥有 storyboard、HTML/CSS/GSAP 编写、lint、check 和 render；clip-weave 不重造这些能力。

## 2. 当前数据流

```text
需求 / URL / 上传素材
  → Intent Router
  → Project Factory
  → BRIEF.md + capture/
  → Asset Matcher
  → STORYBOARD.md
  ├─ HTML：HyperFrames 生成与渲染
  └─ T2V：T2V-PROMPTS.md → provider task → 本地片段 → FFmpeg
```

### 项目初始化

`core/intent_router.py` 把输入映射到 HyperFrames workflow 和 flow；`core/project_factory.py` 初始化项目、抓取 URL 或放入上传素材；`core/delegator.py` 输出下一步 HyperFrames 委托说明。`pipeline.py` 是这条链的唯一编排入口。

### 素材匹配

`adapters/asset_matcher.py` 先用视觉模型丰富图片描述，再用 embedding 排序；embedding 不可用时回退 BM25。它把带分数的 `asset_candidates` 写回 `STORYBOARD.md`，让 HyperFrames 和 T2V 都能消费同一组候选，而非让下游随意挑素材。

### Production Profile

`core/render_path.py` 以 `BRIEF.md` 中唯一的 `production_profile:` 选择项目主生产链：

- `html_launch` → HyperFrames：精确文字、数据、品牌色、UI、录屏和确定性图形。
- `t2v_brand_film` → 生成式视频：写实人物、产品运动、实景和镜头运动。

旧项目的 `render: html|t2v` 只在读取时映射为对应 profile；下一次写入会迁移成 canonical 字段。旧的帧级渲染字段已被拒绝，不支持帧级路径覆盖或 HTML/T2V 自由混排。每个项目选择一次主生产链，`gen-video` 只接受 `t2v_brand_film`。

默认 profile 是 `html_launch`。它对文字、数据、品牌色和 UI 可复现；`t2v_brand_film` 仅用于 HTML 无法提供的写实镜头与运动。

### T2V 路径

`core/t2v_prompt.py` 将 storyboard 转为可编辑的 `T2V-PROMPTS.md`。图形化的 scene 会被改写成可拍摄镜头，无法安全改写的 frame 会标记为 `needs_review`。`core/video_pipeline.py` 负责所有 storyboard frame 的 submit → poll → download，并写入 `renders/ai-clips/<provider>/manifest.json`；`concat_clips()` 用 FFmpeg 合流。provider 适配器位于 `adapters/video_gen/`，目前包括 doubao、ali 和 vertex。

manifest 是版本化的耐久状态记录。它为每个镜头保存规范请求指纹，并在提交前写入 `submitting`、拿到 task id 后写入 `running`、远端成功后先写入 `download_pending`、下载完成后写入 `succeeded`。同一指纹再次运行时，已有完成文件会直接复用，运行中的任务只会轮询，待下载记录只会下载；`submitting`（提交结果不确定）和 provider 明确失败的记录都不会自动重提。清单通过临时文件、`fsync` 和 `os.replace()` 原子更新。

这仍是 P3 前的 T2V 实现。目标的 T2I→I2V 关键帧链、Reference Audit 与质量 Gate 见 [production-quality-loop.md](production-quality-loop.md)，在其实现前不能作为当前能力宣称。

### 规则与验证

`adapters/rule_guard.py` 只保留一条高确定性预检：子 composition 中不能直接放 `<video>` 或 `<audio>`。其他 HTML/动画规则由 HyperFrames 原生 lint/check 处理，避免用较弱的正则重复实现。

## 3. 代码边界

| 边界 | 位置 | 责任 |
| --- | --- | --- |
| 项目编排 | `pipeline.py` | 路由、创建、素材候选注入、委托 |
| 结构化输入 | `core/intent_router.py`、`core/project_factory.py` | `BRIEF.md` 与项目目录 |
| 分镜与提示词 | `core/storyboard.py`、`core/t2v_prompt.py` | 解析、生成、人工可编辑提示词 |
| T2V 执行 | `core/video_pipeline.py`、`adapters/video_gen/` | 异步任务、下载、合流 |
| 素材理解 | `adapters/asset_matcher.py` | 描述增强与匹配 |
| 确定性渲染 | `adapters/hyperframes.py` | 调用 HyperFrames CLI |

业务层不应直接依赖某一家视频模型；模型差异和能力约束必须留在 `adapters/video_gen/`。

## 4. 可靠性边界

当前实现将每镜头 task id、状态、下载来源（URL 或内联内容的短生命周期 sidecar）、路径、错误和请求指纹写入 `manifest.json`，并在状态变化时原子持久化。恢复以相同请求指纹为边界，目标是避免本地重复提交；它不提供 provider 端 exactly-once，也不会自动重新提交 `submitting` 或 `failed` 记录。

下载后仍应执行媒体探测：文件类型、大小、哈希、`ffprobe` 时长/分辨率/fps/音轨。它提高交付可靠性，不等同于提升审美质量。

## 5. 质量演进原则

高质量不是多接几个 provider 或多加几个 Agent。真正的杠杆是：在生成前固定创作方向和身份参考，在昂贵的批量生成前选择 hero shot，在生成后只重做失败镜头，并把批准过的版本锁住。

这套目标流程及来源研究已经收敛在 [production-quality-loop.md](production-quality-loop.md)。不要将 OpenClaw、Hermes、AdCraft、ViMax、VideoAgent 或 OpenMontage 作为运行时后端整体接入；只选择性吸收其被验证的契约、镜头链和人工审批机制。

## 6. 验证

```bash
uv run pytest -q
uv run python -m clip_weave --help
```

离线测试不调用真实模型；真实 provider 调用应从 `gen-video --prompts-only` 和小范围 `--frames` 开始。
