# G0 预检与参考审计设计

**状态：** 已批准，待实现。

## 目标

在 `gen-video` 调用任何 provider 的 `submit()` 前，验证请求是否满足该 provider 的静态能力约束，并对每个镜头的参考素材形成可恢复的审计记录。预检失败时不得发生 provider I/O，避免无效提交、静默丢弃必需参考或错误地消耗模型额度。

## 范围

本任务是 P1 的一个小型纵切，仅覆盖 `t2v_brand_film` 的本地确定性预检：

- provider 声明并检查比例、分辨率、时长和远程首帧参考能力；
- 将参考素材区分为 `optional` 与 `required`，记录 accepted、dropped 或 blocked 及原因；
- 将 requested/applied 参数和 `reference_audit` 持久化到现有 `manifest.json`；
- 使影响实际请求或审计结论的字段参与恢复身份，避免错误复用已有任务。

不在范围内：上传或物化本地参考、网络发现 provider 能力、provider 端幂等键、自动重试/退避、artifact hash、媒体 QC、T2I/I2V、完整 Creative Contract/Facts Source/Proof Media/Cue Sheet/Review Decision schema，以及新的 CLI 命令。

## 当前问题

`VideoModel` 目前只以 `duration_range`、`duration_choices` 和个别 adapter 内部条件表达能力。`generate_clips()` 会将远程 HTTP(S) 参考直接送入 `VideoRequest.image_url`，而本地路径只记入 `extra["reference_asset"]`，不会在提交前明确说明该参考是必需还是已被丢弃。不同 adapter 还可能悄悄回退参数，例如 Vertex 对不支持的比例使用 `16:9`，Ali legacy 对未知尺寸使用默认 `1080p/16:9`。

这种行为在昂贵生成前缺少统一的、可审计的失败边界。

## 方案选择

采用独立的 `core/generation_preflight.py`，而非把规则继续散落在各 provider adapter 中。

- adapter 只声明静态能力，保留其协议转换职责；
- preflight 只做无网络的纯函数验证和审计，能够单测且保证 submit 前失败；
- `video_pipeline` 负责把通过后的 applied request 与审计结果写入现有状态账本。

不采用 adapter 内部静默回退，因为调用方无法区分“请求被接受”与“请求被改写”；也不采用仅写流程文档的方案，因为 CLI 仍可直接提交。

## 数据模型与接口

在 `adapters/video_gen/base.py` 中新增冻结的 `ProviderCapabilities`：

```python
@dataclass(frozen=True)
class ProviderCapabilities:
    ratios: frozenset[str]
    resolutions: frozenset[str]
    duration_range: tuple[int, int]
    duration_choices: tuple[int, ...] | None = None
    reference_uri_schemes: frozenset[str] = frozenset()
```

每个 `VideoModel` 通过只读 `capabilities` 属性返回能力声明。`duration_range` 和 `duration_choices` 与现有 `clamp_duration()` 保持一致；没有声明的参数不允许在 preflight 中猜测或回退。

`generation_preflight.py` 导出：

```python
@dataclass(frozen=True)
class ReferenceAudit:
    requested: str | None
    requirement: Literal["optional", "required"] | None
    outcome: Literal["not_requested", "accepted", "dropped", "blocked"]
    applied: str | None
    reason: str | None

@dataclass
class PreflightResult:
    request: VideoRequest
    requested_parameters: dict[str, object]
    applied_parameters: dict[str, object]
    reference_audit: ReferenceAudit

def preflight_request(
    request: VideoRequest,
    capabilities: ProviderCapabilities,
    *,
    reference: str | None,
    reference_requirement: Literal["optional", "required"] | None,
) -> PreflightResult: ...
```

`ReferenceAudit` 是冻结的值对象；`PreflightResult` 则是普通 dataclass，因为它携带后续 pipeline 将提交的规范化、可变 `VideoRequest`，以及序列化友好的可变 dict 审计快照。调用方可以替换这些字段或更新 dict，但在提交前必须保持 `request` 与 `applied_parameters` 的一致性。

`requested_parameters` 表示用户/提示词文件所请求的值；返回的 `request` 与 `applied_parameters` 是唯一允许交给 `submit()` 的值。没有合法的 applied 值就抛出 `VideoGenError`，不返回部分结果。

## 预检规则

1. 比例和分辨率必须属于 `capabilities` 的集合；不静默替换。
2. 时长先沿用当前 `clamp_duration()` 的确定性归一化；审计中同时保存原始 requested duration 和 applied duration。若 capability 声明不完整或归一化结果不在声明集合内，失败。
3. 空参考产生 `not_requested`，`image_url` 保持空。
4. URI scheme 属于 `reference_uri_schemes` 的远程参考产生 `accepted`，将原始 URI 放入 `image_url`。例如豆包声明 `http`/`https`，Vertex 声明 `gs`；本任务不假设所有 provider 使用相同的远程 URI 格式。
5. 远程 URI 的 scheme 不被 provider 支持时：`required` 产生 `blocked` 并失败；`optional` 产生 `dropped`，`image_url` 为空，继续生成。
6. 本地路径不能在本任务中物化为 provider 可读 URI：`required` 产生 `blocked` 并失败；`optional` 产生 `dropped` 并继续。审计 reason 必须明确为“本地参考尚未物化”。
7. `reference_requirement` 由 `T2V-PROMPTS.md` 新增的可选字段 `reference_requirement` 读取，允许值为 `optional` 或 `required`；存在 `reference` 而没有该字段时默认为 `optional`，以保持现有 storyboard 的兼容性。

## 管道和持久化

`generate_clips()` 在构造每镜头原始 `VideoRequest` 后、计算指纹和读取 manifest 前调用 preflight。失败会汇总所有选中镜头的错误，在任何 `submit()` 前抛出单一 `VideoGenError`；因此不得产生新 manifest clip 记录。

通过后，`ClipResult.extra` 新增：

```json
{
  "requested_parameters": {"ratio": "16:9", "resolution": "1080p", "duration": 5},
  "applied_parameters": {"ratio": "16:9", "resolution": "1080p", "duration": 5},
  "reference_audit": {
    "requested": "https://cdn.example/hero.png",
    "requirement": "optional",
    "outcome": "accepted",
    "applied": "https://cdn.example/hero.png",
    "reason": null
  }
}
```

请求指纹改为基于 applied `VideoRequest`、provider/model、镜头序号和完整 `reference_audit`。这样 optional 参考从 accepted 变为 dropped、或 capability 改变导致实际请求不同，都不会错误恢复旧任务。旧 v2 记录没有这些 `extra` 字段时不视为匹配新指纹，安全地创建新记录。

## 错误处理与兼容性

- 所有错误使用 `VideoGenError`，错误文本包含镜头号、字段、requested 值、provider 和明确修正路径。
- 为防止部分批次已提交，预检必须先处理全部 selected frames，只有全部通过才进入现有 submit/resume 循环。
- `--dry-run` 保持当前“不构造 provider、不写 manifest、不调用 provider”的离线预览契约；它只显示待生成请求，并明确标注未做 provider capability 校验。真实提交路径必须在 `submit()` 前完成预检。
- 当前本地参考的“记录但不发送”兼容行为改为显式 optional `dropped` 审计，不再留下误导性的 `reference_asset` 成功语义。

## 验收与测试

离线测试至少覆盖：

1. 不支持的 ratio/resolution 在 `submit()` 前失败，FakeModel 的 submitted 为空。
2. 固定时长 provider 的 requested/applied duration 同时持久化。
3. 支持远程图像的 provider 接收 HTTP(S) optional reference，并将 accepted 审计写入 manifest。
4. 不支持远程图像或提供本地路径时，optional reference 以 dropped 原因继续；required reference 阻止全批次所有提交。
5. 多镜头批次中一个 required reference 失败时，其他镜头也不得提交。
6. manifest 包含 requested/applied/reference audit；审计或 applied 请求变化时，恢复逻辑提交新任务而非复用旧记录。
7. `T2V-PROMPTS.md` 的 `reference_requirement` 解析、序列化和无字段默认 optional 的兼容性。

执行聚焦 pytest、完整 `uv run --extra dev pytest -q`、`uv run python -m clip_weave --help` 与 `git diff --check`。实现完成后，README 和 architecture 只能陈述已经交付的 preflight 行为，不能宣称本地参考上传、provider exactly-once 或完整 P1 schema 已上线。
