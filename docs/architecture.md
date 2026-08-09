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

`core/t2v_prompt.py` 将 storyboard 转为可编辑的 `T2V-PROMPTS.md`。图形化的 scene 会被改写成可拍摄镜头，无法安全改写的 frame 会标记为 `needs_review`。`core/generation_preflight.py` 是 adapter capability 与 `core/video_pipeline.py` 之间纯本地的 G0 边界：它使用已选 adapter 的静态 capability 校验请求、归一化时长，并审计 reference，不发网络请求、不发现远程能力，也不构成完整质量系统。支持的远程 URI（包括已有 T2I 产物）直接通过；本地 reference 在本地预检阶段由 `core/proof_media.py` 按 provider 支持的 scheme 物化。`core/video_pipeline.py` 仅在选中 batch 全部通过预检和本地 reference 物化后才负责选中镜头的 submit → poll → download，并写入 `renders/ai-clips/<provider>/manifest.json`；必需 reference 不能使用时会阻止整个 batch，optional reference 则按 capability 接受或丢弃。`concat_clips()` 用 FFmpeg 合流。provider 适配器位于 `adapters/video_gen/`，目前包括 doubao、ali 和 vertex。

manifest 是版本化的耐久状态记录。它为每个选中镜头保存规范请求指纹、预检的 requested parameters 与 applied parameters，以及轻量首帧 reference audit 的 accepted/dropped 结果和原因；该审计已写入 manifest。清单在提交前写入 `submitting`、拿到 task id 后写入 `running`、远端成功后先写入 `download_pending`、下载完成后写入 `succeeded`。同一指纹再次运行时，已有完成文件会直接复用，运行中的任务只会轮询，待下载记录只会下载；`submitting`（提交结果不确定）和 provider 明确失败的记录都不会自动重提。清单通过临时文件、`fsync` 和 `os.replace()` 原子更新。

本地 proof media 使用环境变量 `PROOF_MEDIA_<SCHEME>_UPLOAD_URL_TEMPLATE`、`PROOF_MEDIA_<SCHEME>_URI_TEMPLATE` 和可选的 `PROOF_MEDIA_<SCHEME>_UPLOAD_HEADERS_JSON` 配置 HTTP PUT 存储；模板必须含 `{sha256}` 与 `{suffix}`，且 URI template 必须产出对应 scheme。Vertex 选择 `gs`，所以 `PROOF_MEDIA_GS_URI_TEMPLATE` 必须产出 `gs://`；其 upload URL 可以是 `https://`。本地文件以 SHA-256、扩展名、scheme 和 URI 去重，并在 `renders/proof-media.json` 原子记录 provenance。仅“本次新上传、ledger 尚未写入”失败时尝试补偿删除远程对象；绝不因复用记录或 ledger 已替换后的错误删除对象。没有可用 store 时，required 会阻止 batch，optional 继续并在 manifest 审计为 `dropped`。

这仍是 P3 前的 T2V 实现。当前轻量首帧 reference audit 只审计请求是否可按 adapter capability 使用；本地 proof media 不构成 T2I adapter，不生成或管理 T2I 产物，也不验证许可证。完整生产质量的 Reference Audit（产品、人物、场景、风格、proof media 等）尚未实现。目标的 T2I→I2V 关键帧链与完整质量 Gate 见 [production-quality-loop.md](production-quality-loop.md)，在其实现前不能作为当前能力宣称。

### 规则与验证

`adapters/rule_guard.py` 只保留一条高确定性预检：子 composition 中不能直接放 `<video>` 或 `<audio>`。其他 HTML/动画规则由 HyperFrames 原生 lint/check 处理，避免用较弱的正则重复实现。

## 3. 代码边界

| 边界 | 位置 | 责任 |
| --- | --- | --- |
| 项目编排 | `pipeline.py` | 路由、创建、素材候选注入、委托 |
| 结构化输入 | `core/intent_router.py`、`core/project_factory.py` | `BRIEF.md` 与项目目录 |
| 分镜与提示词 | `core/storyboard.py`、`core/t2v_prompt.py` | 解析、生成、人工可编辑提示词 |
| T2V 预检 | `core/generation_preflight.py` | 纯本地 capability 校验、参数归一化、reference 审计；非完整质量 Gate |
| 本地 proof media | `core/proof_media.py` | 按配置的 provider scheme 上传本地 reference，并维护项目级去重 ledger |
| 生产契约账本 | `core/production_contract.py`、`renders/production-contract.json` | 冻结 Creative Contract、Facts Source、Reference Audit、Shot Card、Cue Sheet 和 Review Decision 的完整快照；提供追加 revision、读取当前与历史 revision 的 API；当前未接入 submit 或 manifest |
| T2V 执行 | `core/video_pipeline.py`、`adapters/video_gen/` | 在 batch 预检和本地 reference 物化通过后执行异步任务、下载、合流 |
| 素材理解 | `adapters/asset_matcher.py` | 描述增强与匹配 |
| 确定性渲染 | `adapters/hyperframes.py` | 调用 HyperFrames CLI |

业务层不应直接依赖某一家视频模型；模型差异和能力约束必须留在 `adapters/video_gen/`。

## 4. 可靠性边界

当前实现将每镜头 task id、状态、下载来源（URL 或内联内容的短生命周期 sidecar）、路径、错误、请求指纹，以及 requested/applied parameters 和 reference audit 写入 `manifest.json`，并在状态变化时原子持久化。本地 reference 的独立去重 ledger 为 `renders/proof-media.json`；支持的远程 URI 不会被上传或改写，也不做远程 capability discovery。恢复以相同请求指纹为边界，目标是避免本地重复提交；它不提供 provider 端 exactly-once，也没有自动重试，不会自动重新提交 `submitting` 或 `failed` 记录。

当前实现会在下载落盘后计算视频 artifact 的 SHA-256，并将其写入 `ClipResult` 和 manifest。恢复 `succeeded` 记录时，只有 `video_path` 存在、以 `lstat` 判定为普通文件（不接受 symlink），且其重新计算出的 SHA-256 与 manifest 中格式合法的哈希完全一致，才会复用该本地文件。哈希缺失、格式非法、文件缺失/非普通文件、读取失败或不匹配时，记录不再被信任：有已保存下载来源时只回到下载；只有 task id 时只回到轮询；两者都没有时标记为 `failed`；这些恢复路径绝不重新 submit。

这只是下载字节完整性检查，不是媒体 QC。当前不检查文件大小、容器/编码类型，也不运行 `ffprobe` 验证时长、分辨率、fps 或音轨；候选评分、关键帧/视觉质量判断和 G1--G4 媒体质量 Gate 仍未实现。本地 proof media 的 SHA-256 仍只用于上传去重。上述纯本地 G0 预检不能替代完整的 G0-G4 质量系统，也不等同于提升审美质量。

生产契约账本目前不记录 artifact hash、不实现自动重试或 provider 端 exactly-once；现有 manifest 尚无 contract_revision，且生产契约当前未接入 submit 或 manifest。

## 5. 质量演进原则

高质量不是多接几个 provider 或多加几个 Agent。真正的杠杆是：在生成前固定创作方向和身份参考，在昂贵的批量生成前选择 hero shot，在生成后只重做失败镜头，并把批准过的版本锁住。

这套目标流程及来源研究已经收敛在 [production-quality-loop.md](production-quality-loop.md)。不要将 OpenClaw、Hermes、AdCraft、ViMax、VideoAgent 或 OpenMontage 作为运行时后端整体接入；只选择性吸收其被验证的契约、镜头链和人工审批机制。

## 6. 验证

```bash
uv run pytest -q
uv run python -m clip_weave --help
```

离线测试不调用真实模型；真实 provider 调用应从 `gen-video --prompts-only` 和小范围 `--frames` 开始。
