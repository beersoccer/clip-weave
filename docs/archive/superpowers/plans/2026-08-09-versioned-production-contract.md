# 轻量版本化生产契约 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 以单一原子 JSON 账本保存完整、不可覆盖的生产契约快照，并提供可校验、可读取、可追加的内部 API。

**架构：** 新增 `production_contract` 核心模块，冻结 dataclass 定义六类生产对象和聚合契约。模块将完整快照序列化到 `renders/production-contract.json`，读取时验证 schema 与所有跨对象引用，追加时以临时文件、`fsync`、`os.replace()` 原子替换。此计划仅交付账本基础，不改动 `gen-video`、`manifest.json` 或 provider 请求。

**技术栈：** Python 3.11、标准库 `dataclasses`/`json`/`pathlib`/`tempfile`/`os`、pytest。

---

## 文件结构

- 新建：`src/clip_weave/core/production_contract.py` — 冻结数据模型、schema v1 序列化/反序列化、跨对象校验、账本读取与原子追加。
- 新建：`tests/test_production_contract.py` — 真实文件系统上的 API、schema 和失败生命周期测试。
- 修改：`docs/architecture.md` — 声明当前已实现的账本职责和未接入生成路径的边界。
- 修改：`docs/production-quality-loop.md` — 将 P1 的“所有契约版本化”落实为一个项目账本、正式决策点快照，避免暗示多文件或事件回放。

### Task 1: 数据对象与契约校验

**Files:**
- Create: `tests/test_production_contract.py`
- Create: `src/clip_weave/core/production_contract.py`

- [ ] **Step 1: 写入失败测试，表达最小有效契约和跨对象引用规则**

```python
from clip_weave.adapters.video_gen import VideoGenError
from clip_weave.core.production_contract import (
    CreativeContract,
    Cue,
    FactSource,
    ProductionContract,
    ReferenceAudit,
    ReviewDecision,
    ShotCard,
)
import pytest


def _contract() -> ProductionContract:
    return ProductionContract(
        creative_contract=CreativeContract(
            production_profile="t2v_brand_film",
            audience="new customers",
            platform="social",
            target_duration_seconds=15,
            narrative_promise="show the product benefit",
            must_keep=("approved logo",),
            must_not=("unapproved pricing",),
        ),
        facts_sources=(FactSource("fact-1", "Price is 99", "pricing.md", True),),
        reference_audits=(
            ReferenceAudit("audit-1", "shot-1", "product", "required", "./hero.png", "gs://bucket/hero.png", "gs://bucket/hero.png", "accepted", None, "proof-1"),
        ),
        shot_cards=(
            ShotCard("shot-1", "open", "product", "rotate once", "studio", "medium orbit", "soft key", 3, ("product silhouette",), ("generated text",), ("audit-1",)),
        ),
        cue_sheet=(Cue("cue-1", 0, 3, "vo", "Meet the product", "shot-1"),),
        review_decisions=(ReviewDecision("shot", "shot-1", 1, "accepted", ("identity matches",), 0.9, 0.8, "agent", "2026-08-09T08:00:00+00:00"),),
    )


def test_contract_accepts_complete_linked_snapshot() -> None:
    assert _contract().shot_cards[0].reference_audit_refs == ("audit-1",)


def test_contract_rejects_unknown_reference_audit() -> None:
    contract = _contract()
    with pytest.raises(VideoGenError, match="reference audit"):
        ProductionContract(
            creative_contract=contract.creative_contract,
            facts_sources=contract.facts_sources,
            reference_audits=(),
            shot_cards=contract.shot_cards,
            cue_sheet=contract.cue_sheet,
            review_decisions=contract.review_decisions,
        )
```

- [ ] **Step 2: 运行测试，确认因模块不存在而失败**

Run: `UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest tests/test_production_contract.py -q`

Expected: FAIL，提示 `ModuleNotFoundError: No module named 'clip_weave.core.production_contract'`。

- [ ] **Step 3: 实现冻结对象和聚合校验的最小代码**

在 `src/clip_weave/core/production_contract.py` 定义下列冻结 dataclass，字段顺序与测试构造一致：

```python
@dataclass(frozen=True)
class CreativeContract:
    production_profile: str
    audience: str
    platform: str
    target_duration_seconds: int
    narrative_promise: str
    must_keep: tuple[str, ...]
    must_not: tuple[str, ...]


@dataclass(frozen=True)
class FactSource:
    id: str
    claim: str
    source: str
    approved: bool


@dataclass(frozen=True)
class ReferenceAudit:
    audit_id: str
    shot_id: str
    subject_type: str
    requirement: str | None
    requested: str | None
    submitted: str | None
    applied: str | None
    outcome: str
    reason: str | None
    proof_media_ref: str | None
```

同一文件继续定义 `ShotCard`、`Cue`、`ReviewDecision` 和 `ProductionContract`。在每个对象的 `__post_init__` 调用私有 `_non_empty()`、`_string_tuple()` 或 `_in()`；非法值抛 `VideoGenError`。`ProductionContract.__post_init__` 必须验证：`facts_sources.id`、`reference_audits.audit_id`、`shot_cards.shot_id` 和 `cue_sheet.cue_id` 分别唯一；每个 `ShotCard.reference_audit_refs` 存在；每个 `Cue.shot_id` 存在；`dropped`/`blocked` audit 有 reason，`accepted` audit 同时有 requested/applied；Cue 时间非负且结束不早于开始；Review score/confidence 均在 `[0, 1]`。

- [ ] **Step 4: 运行聚焦测试，确认通过**

Run: `UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest tests/test_production_contract.py -q`

Expected: PASS。

- [ ] **Step 5: 扩展参数化失败测试并实现枚举边界**

追加以下测试，以真实构造替换 `_contract()` 的单一字段：

```python
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("production_profile", "mixed", "production profile"),
        ("subject_type", "identity", "subject type"),
        ("outcome", "ignored", "outcome"),
        ("kind", "music", "cue kind"),
        ("decision", "pending", "decision"),
    ],
)
def test_contract_rejects_unknown_enums(field: str, value: str, message: str) -> None:
    with pytest.raises(VideoGenError, match=message):
        _replace_contract_field(_contract(), field, value)
```

实现测试中的私有 `_replace_contract_field()`，用 `dataclasses.replace()` 只替换相应子对象。生产模块的允许值必须严格等于设计文档：两个 production profile、七个 subject type、四个 audit outcome、六个 cue kind、三个 review decision。

- [ ] **Step 6: 运行聚焦测试并提交**

Run: `UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest tests/test_production_contract.py -q`

Expected: PASS。

```bash
git add src/clip_weave/core/production_contract.py tests/test_production_contract.py
git commit -m "feat: add production contract schema"
```

### Task 2: 账本序列化、读取和不可覆盖追加

**Files:**
- Modify: `tests/test_production_contract.py`
- Modify: `src/clip_weave/core/production_contract.py`

- [ ] **Step 1: 写入失败测试，表达首版、读取和历史不变性**

```python
from clip_weave.core.production_contract import (
    append_contract_revision,
    load_contract_revision,
    load_current_contract,
)


def test_append_creates_v1_ledger_and_reads_current_contract(tmp_path: Path) -> None:
    revision = append_contract_revision(tmp_path, _contract(), reason="initial production preparation")

    ledger = json.loads((tmp_path / "renders" / "production-contract.json").read_text())
    assert revision.revision == 1
    assert ledger["schema_version"] == 1
    assert ledger["current_revision"] == 1
    assert load_current_contract(tmp_path) == _contract()


def test_append_preserves_old_snapshot_and_returns_latest(tmp_path: Path) -> None:
    first = append_contract_revision(tmp_path, _contract(), reason="initial production preparation")
    changed = replace(_contract(), cue_sheet=(Cue("cue-1", 0, 4, "vo", "Meet the product", "shot-1"),))
    second = append_contract_revision(tmp_path, changed, reason="approved cue change")

    assert first.revision == 1
    assert second.revision == 2
    assert load_contract_revision(tmp_path, 1).cue_sheet[0].end_seconds == 3
    assert load_current_contract(tmp_path).cue_sheet[0].end_seconds == 4
```

- [ ] **Step 2: 运行测试，确认 API 缺失导致失败**

Run: `UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest tests/test_production_contract.py -q`

Expected: FAIL，提示 `append_contract_revision` 无法导入。

- [ ] **Step 3: 实现 schema v1 编解码与追加 API**

增加如下公开值对象与 API：

```python
@dataclass(frozen=True)
class ContractRevision:
    revision: int
    created_at: str
    reason: str
    contract: ProductionContract


def load_current_contract(project_dir: Path) -> ProductionContract | None:
    ledger = _read_ledger(_ledger_path(project_dir))
    return None if ledger is None else ledger[-1].contract


def load_contract_revision(project_dir: Path, revision: int) -> ProductionContract:
    for record in _read_required_ledger(_ledger_path(project_dir)):
        if record.revision == revision:
            return record.contract
    raise VideoGenError(f"production contract revision {revision} does not exist")


def append_contract_revision(project_dir: Path, contract: ProductionContract, *, reason: str) -> ContractRevision:
    if not isinstance(reason, str) or not reason.strip():
        raise VideoGenError("production contract revision reason must be non-empty")
    records = _read_required_ledger(_ledger_path(project_dir), missing_ok=True)
    record = ContractRevision(len(records) + 1, datetime.now(timezone.utc).isoformat(), reason, contract)
    _write_ledger_atomically(_ledger_path(project_dir), _encode_ledger([*records, record]))
    return record
```

`_encode_ledger()` 产生 `schema_version`、`current_revision` 和 `revisions`；使用显式字段转换将 tuple 写成 JSON list，禁止使用 `asdict()` 后不校验地接受任意 JSON。`_decode_ledger()` 必须先验证顶层结构与 schema，再逐项构造 dataclass；只接受 revision 从 1 连续递增、当前指向最后一项的账本。`_ledger_path(project_dir)` 固定返回 `project_dir / "renders" / "production-contract.json"`。为使下一任务的原子写入测试先红，本任务暂用私有 `_write_ledger(path, payload)` 的 `path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")`；它只在本分支的中间提交存在，Task 3 必须替换它，最终版本不得保留直接覆盖写入。

- [ ] **Step 4: 运行聚焦测试，确认通过**

Run: `UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest tests/test_production_contract.py -q`

Expected: PASS。

- [ ] **Step 5: 添加损坏账本与不合法追加的失败测试**

```python
@pytest.mark.parametrize(
    "ledger",
    [
        '{"schema_version": 2, "current_revision": 1, "revisions": []}',
        '{"schema_version": 1, "current_revision": 2, "revisions": []}',
        '{"schema_version": 1, "current_revision": 2, "revisions": [{"revision": 2}]}',
    ],
)
def test_load_rejects_invalid_ledger_without_overwriting(tmp_path: Path, ledger: str) -> None:
    path = tmp_path / "renders" / "production-contract.json"
    path.parent.mkdir()
    path.write_text(ledger)

    with pytest.raises(VideoGenError, match="production contract"):
        load_current_contract(tmp_path)

    assert path.read_text() == ledger


def test_append_rejects_blank_reason_without_creating_ledger(tmp_path: Path) -> None:
    with pytest.raises(VideoGenError, match="reason"):
        append_contract_revision(tmp_path, _contract(), reason=" ")

    assert not (tmp_path / "renders" / "production-contract.json").exists()
```

实现时将 `OSError` 和 `JSONDecodeError` 统一转换为不含内部 traceback 的 `VideoGenError`，错误文本包含 `production-contract.json` 路径；读取失败绝不调用写入函数。

- [ ] **Step 6: 运行聚焦测试并提交**

Run: `UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest tests/test_production_contract.py -q`

Expected: PASS。

```bash
git add src/clip_weave/core/production_contract.py tests/test_production_contract.py
git commit -m "feat: persist versioned production contracts"
```

### Task 3: 原子替换失败生命周期

**Files:**
- Modify: `tests/test_production_contract.py`
- Modify: `src/clip_weave/core/production_contract.py`

- [ ] **Step 1: 写入失败测试，证明替换前失败不伤害旧账本**

```python
def test_failed_atomic_append_keeps_previous_ledger_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    append_contract_revision(tmp_path, _contract(), reason="initial production preparation")
    path = tmp_path / "renders" / "production-contract.json"
    previous = path.read_bytes()
    monkeypatch.setattr(production_contract.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(OSError, match="disk full"):
        append_contract_revision(tmp_path, _contract(), reason="approved cue change")

    assert path.read_bytes() == previous
```

- [ ] **Step 2: 运行测试，确认在缺少原子写入 helper 时失败**

Run: `UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest tests/test_production_contract.py -q`

Expected: FAIL，测试不能通过，因为账本写入尚未具有所需的 replace 失败清理行为。

- [ ] **Step 3: 实现与现有账本一致的原子写入 helper**

实现 `_write_ledger_atomically(path, ledger)`：创建父目录；在同目录用 `NamedTemporaryFile(delete=False)` 写入 `json.dump(..., ensure_ascii=False, indent=2)` 和末尾换行；flush 后 `os.fsync()`；调用 `os.replace()`；再 `fsync` 父目录；finally 中只删除仍存在的临时文件。不要把本 helper 抽到共享模块，避免无关重构；不引入补偿、重试或锁。

保留 `os.replace()` 前的异常原样抛出，使测试和调用方可以区分本地写入失败；目录同步在 replace 后失败时，抛出带“replacement completed”含义的 `VideoGenError`，不得尝试恢复旧版本或删除已提交账本。

- [ ] **Step 4: 运行聚焦测试，确认通过**

Run: `UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest tests/test_production_contract.py -q`

Expected: PASS。

- [ ] **Step 5: 增加临时文件清理与 replace 后目录同步测试**

```python
def test_failed_atomic_append_removes_temporary_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(production_contract.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(OSError, match="disk full"):
        append_contract_revision(tmp_path, _contract(), reason="initial production preparation")

    assert list((tmp_path / "renders").glob(".production-contract-*.tmp")) == []
```

对目录 `fsync` 注入失败，断言账本已经包含新 revision，且异常文本明确说明 replacement 已完成；不要在该情形删除账本或写入额外版本。

- [ ] **Step 6: 运行聚焦测试并提交**

Run: `UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest tests/test_production_contract.py -q`

Expected: PASS。

```bash
git add src/clip_weave/core/production_contract.py tests/test_production_contract.py
git commit -m "test: cover production contract atomic writes"
```

### Task 4: 当前能力文档与全量验证

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/production-quality-loop.md`

- [ ] **Step 1: 更新当前架构边界**

在 `docs/architecture.md` 的“代码边界”表新增 `生产契约` 行，位置在 `本地 proof media` 后：

```markdown
| 生产契约 | `core/production_contract.py` | 在 `renders/production-contract.json` 原子保存完整、不可覆盖的生产契约版本；当前未接入 submit 或 manifest |
```

在“可靠性边界”补充：账本不实现 artifact hash、自动重试或 provider exactly-once；现有任务清单尚未写入 `contract_revision`，该接入属于后续独立步骤。

- [ ] **Step 2: 更新目标质量文档的版本语义**

将 `docs/production-quality-loop.md` 第 4 节“所有契约版本化且不可覆盖”的说明改为：一个项目级账本保存正式生产决策的完整快照，默认读取当前版本，历史只用于追溯与恢复；Agent 草稿不落盘；不使用每对象文件或事件回放。保留该文档对后续 `contract_revision` 任务钉扎的目标描述，但标注其尚未接入当前 `manifest.json`。

- [ ] **Step 3: 运行文档与完整测试验证**

Run:

```bash
UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest -q
UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run python -m clip_weave --help
git diff --check
git status --short --branch
```

Expected: 全部 pytest 通过；CLI 帮助返回 0；diff 检查无输出；状态只包含本任务预期变更。

- [ ] **Step 4: 提交文档**

```bash
git add docs/architecture.md docs/production-quality-loop.md
git commit -m "docs: describe production contract ledger"
```
