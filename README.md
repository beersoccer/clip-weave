# clip-weave

把用户的一句话需求、URL、参考视频和品牌素材，收敛为可审阅、可编辑、可复现的视频生产项目。

clip-weave 不替代 HyperFrames 或视频模型：它负责低门槛入口、素材与参考对齐、渲染路径选择，以及把生成任务交给正确的生产路径。

## 先读什么

| 需要解决的问题 | 只读这一份 |
| --- | --- |
| 想知道系统现在能做什么、怎么开始 | 本 README |
| 想了解代码边界、数据流和当前实现 | [架构](docs/architecture.md) |
| 想做生产级视频，或评估下一步优化 | [生产质量流程](docs/production-quality-loop.md) |

`docs/archive/` 只保留历史选型、已完成计划和案例，默认不需要阅读。

## 当前能力

```text
用户需求 / URL / 本地素材
  → Intent Router + Project Factory + Production Profile
  → BRIEF.md、capture/、素材候选
  → HyperFrames（精确文字、品牌、UI、图形）
    或 T2V（写实镜头、人物、运动）
  → FFmpeg 合成
```

- `run`：创建项目、选择 Production Profile、写入 `BRIEF.md`，有 URL 时抓取素材。
- `match-assets`：用视觉描述与语义检索给分镜提供打分的素材候选。
- `guard`：在 HyperFrames 装配前检查媒体不能放进子合成，并拒绝 `STORYBOARD.md` 中废弃的帧级 `render:` / `render_path:`。
- `gen-video`：仅用于 `t2v_brand_film` 项目；由 `STORYBOARD.md` 生成可手改的 `T2V-PROMPTS.md`，在提交前按已选 provider 的静态 capability 做批量预检，再逐镜头提交、轮询、下载并可用 FFmpeg 合流。

## 快速开始

```bash
uv sync
cp .env.example .env
uv run python -m clip_weave --help
```

创建一个项目：

```bash
uv run python -m clip_weave run \
  --message "30 秒新能源汽车发布视频，突出夜间驾驶与智能座舱" \
  --project ev-launch \
  --profile html_launch
```

每个项目只有一个 Production Profile，保存在 `BRIEF.md` 的 `production_profile:`：

- `html_launch`：HyperFrames 负责整条视频，适合精确文字、logo、价格、UI、图表和数据叙事。
- `t2v_brand_film`：当前生成式视频路径，适合写实人物、产品运动和实景镜头。

不支持按镜头切换 Production Profile，也不支持 HTML/T2V 自由混排。T2I→I2V 关键帧链、确定性 overlay 与五层质量 Gate 是 [生产质量流程](docs/production-quality-loop.md) 中的后续阶段，当前 `t2v_brand_film` 仍使用既有的逐镜头视频生成路径。

先生成并审阅提示词，不产生模型费用：

```bash
uv run python -m clip_weave gen-video videos/ev-launch/STORYBOARD.md \
  --provider doubao --prompts-only
```

确认后再生成：

```bash
uv run python -m clip_weave gen-video videos/ev-launch/STORYBOARD.md \
  --provider doubao --concat
```

`T2V-PROMPTS.md` 是用户可编辑的最终提示词来源；重新生成它会覆盖手工修改，命令会明确提示。

## 当前实现与下一步

现有 T2V 路径已支持豆包、阿里和 Vertex 适配器，以及逐镜头的可恢复 `manifest.json`。非 dry-run 的 `gen-video` 会在任何提交前，针对选中 batch 的每个镜头，以已选 adapter 声明的静态 capability 检查比例、分辨率、时长和 reference；必需（`required`）reference 不能使用时，整个 batch 被阻止，不会提交任何镜头。可选（`optional`）reference 会按 capability 接受或丢弃，并将 accepted/dropped 结果、原因、requested parameters 与 applied parameters 写入 manifest。每次提交前、远端任务完成待下载时、下载完成或出现本地等待/下载错误时，清单都会原子更新。相同请求再次执行时会复用已完成文件，或仅继续轮询、下载既有任务；对于提交结果不确定的 `submitting` 记录，不会自动重提，以避免重复消耗模型额度。

支持的远程 reference URI（包括已有 T2I 产物 URI）会直接传给 provider；本地 reference 则会在提交前物化为 provider 支持的 proof media URI。下载成功后，视频产物的 SHA-256 会写入 manifest；恢复时仅复用哈希复验相同的普通文件（不接受 symlink）。哈希缺失、非法或不匹配的记录只会按已有下载来源重新下载、按 task id 继续轮询，或标记为失败，绝不重新 submit。对已有 `running`/`download_pending` 记录，连接/超时、429 与 5xx 最多可排期三次短退避；429 会遵守 `Retry-After`。命令不会等待退避，而会提示下次恢复时间、继续处理其他可执行记录并快速返回。`submitting`、认证/权限、参数/capability、必需 reference、本地 I/O 和 provider 明确终态失败均不自动重试；每个 poll/download、等待、退避与预算耗尽都会通过进度输出提示，且明确本次未重新提交。它不是 provider 端的 exactly-once 保证，且没有 `ffprobe` 或媒体 QC，也没有完整的 G0-G4 质量系统；清单不会自动重新提交任务。关键帧候选、镜头质量契约和局部重做仍是后续范围；完整目标、优先级和借鉴边界见[生产质量流程](docs/production-quality-loop.md)。

### 本地 proof media

为使用本地 reference，配置一个 provider 支持的对象存储 scheme。模板必须同时含有 `{sha256}` 和 `{suffix}`；以下只是变量形状示例，不含真实凭据：

```bash
# 适用于支持 https reference URI 的 provider
PROOF_MEDIA_HTTPS_UPLOAD_URL_TEMPLATE=https://upload.example.invalid/proof/{sha256}{suffix}
PROOF_MEDIA_HTTPS_URI_TEMPLATE=https://cdn.example.invalid/proof/{sha256}{suffix}
# 可选，值必须是 string:string JSON；不要把真实 token 提交到仓库
PROOF_MEDIA_HTTPS_UPLOAD_HEADERS_JSON='{"Authorization":"Bearer <upload-token>"}'

# Vertex 使用 gs scheme；上传端点仍可为 https，但最终 URI 必须为 gs://
PROOF_MEDIA_GS_UPLOAD_URL_TEMPLATE=https://storage-upload.example.invalid/proof/{sha256}{suffix}
PROOF_MEDIA_GS_URI_TEMPLATE=gs://example-proof-media/proof/{sha256}{suffix}
# PROOF_MEDIA_GS_UPLOAD_HEADERS_JSON='{"Authorization":"Bearer <upload-token>"}'
```

本地文件按内容 SHA-256、扩展名、scheme 和 URI 去重；首次上传后将记录原始路径、来源/许可证注记和 URI 到项目的 `renders/proof-media.json`。仅当本次新上传而该 ledger 写入失败时，系统会尝试删除刚上传的对象作补偿；复用已有记录或 ledger 已替换后失败时不会删除。未配置可用 store 时，`required` 本地 reference 会阻止整个 batch，`optional` 会继续生成并在 manifest 记为 `dropped`。

这不是 T2I adapter：系统不生成、管理或验证 T2I 产物，也不验证许可证；已有且受 provider 支持的 T2I URI 只会原样传递。proof media 的 SHA-256 仅用于本地上传去重；视频下载产物另有用于恢复复验的 SHA-256，但仍不包含 `ffprobe` 或媒体 QC。

## 验证

```bash
uv run pytest -q
```

离线回归基线以当前 `uv run pytest -q` 输出为准。
