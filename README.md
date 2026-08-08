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
- `gen-video`：仅用于 `t2v_brand_film` 项目；由 `STORYBOARD.md` 生成可手改的 `T2V-PROMPTS.md`，逐镜头提交、轮询、下载并可用 FFmpeg 合流。

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

现有 T2V 路径已支持豆包、阿里和 Vertex 适配器，以及逐镜头 `manifest.json` 输出。生产级质量闭环中的可恢复 Job Ledger、Reference Audit、关键帧候选、镜头质量契约和局部重做仍是下一步工作；完整目标、优先级和借鉴边界见[生产质量流程](docs/production-quality-loop.md)。

## 验证

```bash
uv run pytest -q
```

当前离线回归基线：`274 passed`。
