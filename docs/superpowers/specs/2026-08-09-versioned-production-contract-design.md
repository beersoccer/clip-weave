# 轻量版本化生产契约设计

**状态：** 已实现（账本基础）。

本轮已交付完整 schema、读取/追加 API 与原子项目级账本。`submit` 接入、在 `manifest.json` 写入 `contract_revision`，以及将契约接入实际生产链仍是后续任务。

## 目标

为每个视频项目提供一个由 Agent 自动维护的、项目级且可追溯的生产契约账本。它在不引入数据库、事件回放、多文件事务或人工版本管理的前提下，保存 Creative Contract、Facts Source、完整 Reference Audit、Shot Card、Cue Sheet 与 Review Decision 的已确认版本。

日常执行只读取当前版本；只有需要解释生成依据、恢复任务或审计发布结论时才读取历史版本。用户不需要编辑 JSON、选择版本或处理镜头制作参数。

## 已确认的设计边界

- 项目只使用一个文件：`renders/production-contract.json`。
- 每次正式变更写入一个完整、已校验的不可变快照；不会生成多个文档，也不保存 JSON patch 或事件流。
- Agent 在推理、草拟或局部生成候选时只保留内存态；仅在首次可提交的生产准备、会影响事实/参考/镜头/时间轴/审片结论的确认、提交前固定依据、或写入审片决定时创建新版本。
- 默认读取当前版本。历史版本永不被调用方覆盖，也不要求调用方手工管理。
- 使用现有临时文件、`fsync`、`os.replace()` 原子替换模式。一次写入失败时，旧文件继续可读；不得留下半份契约。
- P1 只支持单机顺序 Agent 执行；不增加数据库锁、多人协作冲突解决、分布式事务、压缩、生命周期清理或事件重放。
- 本轮不实现 artifact hash、下载完整性记录、错误分类重试与退避、T2I/I2V、媒体 QC 或 P2/P3 用户流程。

这是“同一对象保留当前版本与历史版本”的轻量应用，而不是事件溯源系统。AWS S3 Versioning 的对象版本模型说明了覆盖保留历史和默认读取当前版本的可恢复性；其完整对象版本也说明本项目应仅在明确生产决策点快照，而不为每个中间字段改动持久化。SQLite 的原子提交原则支持将整个小型账本作为一次逻辑写入处理。

## 文件格式与读取模型

账本格式为：

```json
{
  "schema_version": 1,
  "current_revision": 2,
  "revisions": [
    {
      "revision": 1,
      "created_at": "2026-08-09T08:00:00Z",
      "reason": "initial production preparation",
      "contract": {
        "creative_contract": {
          "production_profile": "t2v_brand_film",
          "audience": "new customers",
          "platform": "social",
          "target_duration_seconds": 15,
          "narrative_promise": "show the product benefit",
          "must_keep": ["approved logo"],
          "must_not": ["unapproved pricing"]
        },
        "facts_sources": [],
        "reference_audits": [],
        "shot_cards": [],
        "cue_sheet": [],
        "review_decisions": []
      }
    },
    {
      "revision": 2,
      "created_at": "2026-08-09T08:05:00Z",
      "reason": "approved shot-card change",
      "contract": {
        "creative_contract": {
          "production_profile": "t2v_brand_film",
          "audience": "new customers",
          "platform": "social",
          "target_duration_seconds": 15,
          "narrative_promise": "show the product benefit",
          "must_keep": ["approved logo"],
          "must_not": ["unapproved pricing"]
        },
        "facts_sources": [],
        "reference_audits": [],
        "shot_cards": [
          {
            "shot_id": "shot-01",
            "purpose": "open with the product",
            "subject": "approved product",
            "action": "rotate once",
            "scene": "studio",
            "camera": "medium orbit",
            "lighting": "soft key",
            "duration_seconds": 3,
            "must_keep": ["product silhouette"],
            "must_not": ["generated text"],
            "reference_audit_refs": []
          }
        ],
        "cue_sheet": [],
        "review_decisions": []
      }
    }
  ]
}
```

`current_revision` 必须等于最后一项的 `revision`，且 revision 从 1 连续递增。读取 API 直接返回最后一项的 `contract`，不做差异合并、索引重建或跨文件查询。追加 API 先验证完整候选契约，再复制为下一版本并原子替换整个文件；它不接受“原地更新已有 revision”的操作。

P1 不添加内容 hash：当前账本很小，顺序 revision 和原子写入已经提供可恢复身份；在没有远端同步、篡改检测或大文件存储需求前，hash 只会增加复杂度。未来 artifact hash 仍只属于下载产物完整性工作，不能和契约版本混用。

## 生产契约的最小对象

每个快照的 `contract` 使用以下稳定顶层字段；`schema_version` 演进时才允许改变其含义。

| 对象 | 最小字段 | 目的 |
| --- | --- | --- |
| `creative_contract` | `production_profile`、`audience`、`platform`、`target_duration_seconds`、`narrative_promise`、`must_keep`、`must_not` | 固定全片制作方向与禁止项；不是自由 prompt。 |
| `facts_sources` | `id`、`claim`、`source`、`approved` | 使价格、规格、CTA、法律声明等事实可追溯；未批准事实不能被下游当作可发布事实。 |
| `reference_audits` | `audit_id`、`shot_id`、`subject_type`、`requirement`、`requested`、`submitted`、`applied`、`outcome`、`reason`、`proof_media_ref` | 记录产品、人物、场景、风格或首末帧参考从请求到实际提交/丢弃的结果。 |
| `shot_cards` | `shot_id`、`purpose`、`subject`、`action`、`scene`、`camera`、`lighting`、`duration_seconds`、`must_keep`、`must_not`、`reference_audit_refs` | 把每个生成镜头限制为可审计的结构化制作意图。 |
| `cue_sheet` | `cue_id`、`start_seconds`、`end_seconds`、`kind`、`content`、`shot_id` | 用绝对时间描述 VO、SFX、字幕、CTA、转场和 hold。 |
| `review_decisions` | `target_type`、`target_id`、`target_revision`、`decision`、`reasons`、`score`、`confidence`、`reviewer`、`reviewed_at` | 固定 accepted、revise 或 rejected 的依据，不覆盖既有决定。 |

除 Reference Audit 的明确可空字段外，所有文本字段均为非空字符串，数组元素也是非空字符串。`requirement`、`requested`、`submitted`、`applied`、`reason` 与 `proof_media_ref` 可为 `null`；其中 `requirement` 仅在 `outcome=not_requested` 时可为 `null`，非空时只能为 `optional` 或 `required`。`dropped` 或 `blocked` 的 audit 必须有非空 `reason`；`accepted` 的 audit 必须有非空 `requested` 与 `applied`。列表中的 `facts_sources.id`、`reference_audits.audit_id`、`shot_cards.shot_id`、`cue_sheet.cue_id` 必须在各自命名空间唯一；`shot_cards.reference_audit_refs` 必须引用同一快照中的 `audit_id`，`cue_sheet.shot_id` 必须引用同一快照中的 `shot_cards.shot_id`。`production_profile` 只能为 `html_launch` 或 `t2v_brand_film`。`reference_audits.subject_type` 只能为 `product`、`person`、`scene`、`style`、`first_frame`、`last_frame` 或 `proof_media`；`outcome` 为 `not_requested`、`accepted`、`dropped` 或 `blocked`。`cue_sheet.kind` 为 `vo`、`sfx`、`caption`、`cta`、`transition` 或 `hold`。`decision` 只能为 `accepted`、`revise` 或 `rejected`。`score` 与 `confidence` 均为 0 到 1 的数值。时间区间必须是非负且 `end_seconds >= start_seconds`。

空列表允许用于尚不适用的对象；空值不得伪装成已批准事实或已接受审片。由现有 G0 生成的轻量 `reference_audit` 在接入阶段将被转换为本对象，而不是改写旧 `manifest.json` 历史。

## API 与执行接入

新增窄模块 `src/clip_weave/core/production_contract.py`，只提供：

```python
def load_current_contract(project_dir: Path) -> ProductionContract | None: ...

def load_contract_revision(project_dir: Path, revision: int) -> ProductionContract: ...

def append_contract_revision(
    project_dir: Path,
    contract: ProductionContract,
    *,
    reason: str,
) -> ContractRevision: ...
```

`ProductionContract` 与其六类对象使用冻结 dataclass；构造和加载时执行格式、枚举、引用与时间范围校验。缺失账本返回 `None`，损坏或不满足当前 schema 的账本抛出带项目路径和修正方向的 `VideoGenError`，绝不覆盖原文件。

本轮先交付账本 API、完整 schema 和测试，不添加 CLI。调用方（包括 Agent）通过内部 API 产生和读取版本，避免让用户填写制作术语或维护 JSON。

后续接入必须按以下顺序进行，且每步单独测试：

1. 将 Creative Contract 与 Facts Source 的已批准输入写入首个可提交版本。
2. 将现有 G0/Proof Media 的 applied reference 扩展为完整 Reference Audit，并在提交前固定版本。
3. 让 `T2V-PROMPTS.md` 生成或消费 Shot Card；不猜测缺失业务事实。
4. 在音频/总装配流程出现前接入 Cue Sheet。
5. 将候选与发布结论接入 Review Decision。
6. 在每个 `manifest.json` 任务记录中写入已提交的 `contract_revision`；恢复只能使用该版本，后续契约修订不得改变已提交任务依据。

在步骤 1--6 分别完成前，既有项目维持当前行为；不得从 `BRIEF.md` 或 prompt 猜测未给出的事实并伪造一份“已批准”契约。接入某个需要契约的 submit 边界时，缺少所需的已批准输入必须在 provider I/O 前 fail closed。

## 错误处理与兼容性

- 账本不存在时，API 返回 `None`；这让基础库可在旧项目中安全部署。
- 账本 JSON 损坏、schema 不支持、revision 不连续、当前指针不一致、引用悬空或必填字段无效时失败并保留文件。
- 同一 revision 永远不可修改或删除。新增版本必须包含完整有效快照和非空 `reason`。
- 失败的 Agent 草稿不写入账本。没有正式生产决策，就没有新 revision。
- `renders/proof-media.json` 仍只记录本地对象物化与 provenance；`renders/ai-clips/<provider>/manifest.json` 仍只记录 provider 任务状态。生产契约尚未通过 revision 与它们关联；后续接入时也不得合并三者职责。

## 验收与测试

离线 pytest 至少覆盖：

1. 首次追加创建 schema v1 账本并可直接读取当前完整契约。
2. 第二次追加保留第一版内容、递增 revision，并只将最新快照作为当前版本返回。
3. 任意已存 revision 可按号读取；不存在 revision 明确失败。
4. 原子替换失败后，旧账本字节保持不变。
5. 损坏 JSON、未知 schema、不连续 revision、错误 current 指针、重复 ID、悬空引用、非法枚举和反向 cue 时间均在写入或加载时失败。
6. 空的尚不适用对象列表合法；事实的 `approved` 值可被无损保存，后续提交接入不得把 `false` 的事实作为可发布输入。
7. 完整 `uv run --extra dev pytest -q`、`uv run python -m clip_weave --help` 与 `git diff --check` 通过。

## 非目标

- 不实现人工编辑 CLI、Web UI、审批工作流或多用户合并。
- 不实现差异存储、事件回放、数据库、远程同步、版本清理或压缩。
- 不宣称已经接通 T2I/I2V、完整 G0--G4、下载 artifact hash、自动重试/退避或媒体 QC。
- 不把 Creative Contract 自动翻译为模型 prompt，也不让未批准 Facts Source 绕过业务确认。
