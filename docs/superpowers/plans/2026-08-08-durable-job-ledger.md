# 耐久任务账本实现计划

> **给执行型 agent：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐项执行；步骤使用复选框追踪。

**目标：** 将视频生成任务状态持久化，使相同 storyboard 的重复执行恢复已有 provider 工作，而不是重复提交并消耗模型额度。

**架构：** 继续使用 `core/video_pipeline.py` 中的 `manifest.json`，将其升级为版本化、原子写入的恢复记录。每个 `ClipResult` 具有规范请求指纹；匹配记录分别复用已完成文件、轮询 task、下载既有结果，且绝不重提 `submitting` 或 `failed` 记录。

**技术栈：** Python 3.11 标准库（`hashlib`、`json`、`os`、`tempfile`）、既有 `VideoModel` 协议、pytest。

---

## 文件范围

- 修改：`src/clip_weave/core/video_pipeline.py` — 指纹、原子持久化和恢复状态转换。
- 修改：`tests/test_video_pipeline.py` — FakeModel 控制项与离线状态机测试。
- 修改：`README.md` — 已实现的恢复语义和限制。
- 修改：`docs/architecture.md` — durable manifest 生命周期。

### 任务 1：先用失败测试固定恢复行为

**文件：**
- 修改：`tests/test_video_pipeline.py:29-83,117-195`
- 测试：`tests/test_video_pipeline.py`

- [x] **步骤 1：让 FakeModel 能在指定提交处中断**

扩展构造器与 `submit()`，保留现有 poll/download 行为：

```python
def __init__(self, *, submit_error=None, crash_on_submit_number=None, polls=None, download_error=None):
    self.submit_error = submit_error
    self.crash_on_submit_number = crash_on_submit_number
    self.polls = polls or {}
    self.download_error = download_error
    self.submitted, self.downloaded, self._poll_counts = [], [], {}

def submit(self, req):
    self.submitted.append(req)
    if self.crash_on_submit_number == len(self.submitted):
        raise RuntimeError("simulated process stop")
    if self.submit_error:
        raise VideoGenError(self.submit_error)
    return f"task-{len(self.submitted)}"
```

- [x] **步骤 2：写入早期持久化和恢复的红灯测试**

```python
def _manifest(tmp_path):
    path = tmp_path / "renders" / "ai-clips" / "doubao" / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))

def test_manifest_is_written_before_a_later_submit_crashes(tmp_path):
    with pytest.raises(RuntimeError, match="simulated process stop"):
        _run(tmp_path, model=FakeModel(crash_on_submit_number=2))
    data = _manifest(tmp_path)
    assert data["schema_version"] == 2
    assert data["clips"][0]["state"] == "running"
    assert data["clips"][0]["task_id"] == "task-1"
    assert data["clips"][1]["state"] == "submitting"

def test_running_task_is_polled_on_repeat_without_resubmission(tmp_path):
    _run(tmp_path, model=FakeModel(polls={"task-1": TaskStatus(state="running", raw={})}),
         frames=[1], max_wait=0)
    resumed = FakeModel(polls={"task-1": TaskStatus(
        state="succeeded", raw={}, video_url="https://cdn/task-1.mp4"
    )})
    assert _run(tmp_path, model=resumed, frames=[1])[0].state == "succeeded"
    assert resumed.submitted == []

def test_completed_file_is_reused_without_provider_io(tmp_path):
    _run(tmp_path, model=FakeModel(), frames=[1])
    resumed = FakeModel()
    assert _run(tmp_path, model=resumed, frames=[1])[0].state == "succeeded"
    assert resumed.submitted == []
    assert resumed.downloaded == []
```

- [x] **步骤 3：确认红灯**

运行：`uv run pytest -q tests/test_video_pipeline.py::test_manifest_is_written_before_a_later_submit_crashes tests/test_video_pipeline.py::test_running_task_is_polled_on_repeat_without_resubmission tests/test_video_pipeline.py::test_completed_file_is_reused_without_provider_io`

预期：失败；当前代码只在全部工作结束后写 manifest，且每次都会调用 `submit()`。

### 任务 2：实现版本化原子 manifest 基础能力

**文件：**
- 修改：`src/clip_weave/core/video_pipeline.py:13-18,69-81`
- 测试：`tests/test_video_pipeline.py`

- [x] **步骤 1：添加请求身份字段和 imports**

```python
import hashlib
import os
import tempfile

@dataclass
class ClipResult:
    index: int
    title: str
    prompt: str
    duration: int
    request_fingerprint: str | None = None
    # existing fields remain below
```

- [x] **步骤 2：写入指纹与失败关闭的红灯测试**

```python
def test_changed_request_fingerprint_submits_one_new_task(tmp_path):
    _run(tmp_path, model=FakeModel(polls={"task-1": TaskStatus(state="running", raw={})}),
         frames=[1], max_wait=0, seed=1)
    changed = FakeModel()
    _run(tmp_path, model=changed, frames=[1], seed=2)
    assert len(changed.submitted) == 1
    records = [clip for clip in _manifest(tmp_path)["clips"] if clip["index"] == 1]
    assert len({clip["request_fingerprint"] for clip in records}) == 2

def test_manifest_write_failure_prevents_submit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "clip_weave.core.video_pipeline._atomic_write_manifest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    model = FakeModel()
    with pytest.raises(OSError, match="disk full"):
        _run(tmp_path, model=model, frames=[1])
    assert model.submitted == []
```

- [x] **步骤 3：实现私有 helper**

在 `ClipResult` 后添加 `_MANIFEST_SCHEMA_VERSION = 2`、`_request_fingerprint()`、`_atomic_write_manifest()`、`_load_manifest()`、`_find_clip()` 和 `_persist_clip()`。

```python
def _request_fingerprint(*, provider, model, index, request, reference):
    payload = {
        "provider": provider, "model": model, "index": index,
        "prompt": request.prompt, "duration": request.duration,
        "ratio": request.ratio, "resolution": request.resolution,
        "negative_prompt": request.negative_prompt, "seed": request.seed,
        "generate_audio": request.generate_audio, "watermark": request.watermark,
        "reference": reference,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
```

`_atomic_write_manifest()` 用同目录 `NamedTemporaryFile`、`json.dump`、`flush`、`os.fsync` 和 `os.replace`；`_load_manifest()` 对缺失文件返回 v2 空列表，对损坏 JSON、非 object 根节点或非 list 的 `clips` 抛出带 manifest 路径的 `VideoGenError`；`_persist_clip()` 只替换相同 index/fingerprint，否则 append `asdict(clip)` 并调用原子 writer。

- [x] **步骤 4：确认基础能力绿灯**

运行：`uv run pytest -q tests/test_video_pipeline.py::test_changed_request_fingerprint_submits_one_new_task tests/test_video_pipeline.py::test_manifest_write_failure_prevents_submit`

预期：通过。恢复测试将在下一任务重构主循环后转绿。

- [x] **步骤 5：提交**

```bash
git add src/clip_weave/core/video_pipeline.py tests/test_video_pipeline.py
git commit -m "feat(video): add atomic durable manifest primitives"
```

### 任务 3：在 submit、poll、download 前恢复状态

**文件：**
- 修改：`src/clip_weave/core/video_pipeline.py:151-255`
- 修改：`tests/test_video_pipeline.py:154-195`
- 测试：`tests/test_video_pipeline.py`

- [x] **步骤 1：替换本地错误即终态的旧测试**

```python
def test_download_failure_stays_download_pending_and_resumes_without_submit(tmp_path):
    assert _run(tmp_path, model=FakeModel(download_error="disk full"), frames=[1])[0].state == "download_pending"
    resumed = FakeModel()
    assert _run(tmp_path, model=resumed, frames=[1])[0].state == "succeeded"
    assert resumed.submitted == []

def test_timeout_keeps_task_running_for_a_later_resume(tmp_path):
    results = _run(tmp_path, model=FakeModel(
        polls={"task-1": TaskStatus(state="running", raw={})}
    ), frames=[1], max_wait=0)
    assert [result.state for result in results] == ["running"]
    assert _manifest(tmp_path)["clips"][0]["state"] == "running"

def test_submitting_record_is_never_resubmitted(tmp_path):
    _run(tmp_path, model=FakeModel(submit_error="connection reset"), frames=[1])
    resumed = FakeModel()
    assert _run(tmp_path, model=resumed, frames=[1])[0].state == "submitting"
    assert resumed.submitted == []
```

- [x] **步骤 2：确认恢复测试红灯**

运行：`uv run pytest -q tests/test_video_pipeline.py::test_download_failure_stays_download_pending_and_resumes_without_submit tests/test_video_pipeline.py::test_timeout_keeps_task_running_for_a_later_resume tests/test_video_pipeline.py::test_submitting_record_is_never_resubmitted`

预期：失败；当前实现会将下载错误和超时改为 `failed`，也没有持久化 `submitting`。

- [x] **步骤 3：最小重构 generate_clips()**

在 `vm` 与 `out` 创建后加载 manifest：

```python
manifest_path = out / "manifest.json"
manifest = _load_manifest(manifest_path, {
    "storyboard": str(Path(storyboard_path).resolve()),
    "provider": provider, "model": vm.model,
    "resolution": resolution, "ratio": target_ratio,
})
```

每个 selected frame 仍按当前代码构造 `VideoRequest`，设置指纹后按以下分发：

```python
existing = _find_clip(manifest, frame.index, result.request_fingerprint)
if existing and existing.state == "succeeded" and existing.video_path and Path(existing.video_path).exists():
    results.append(existing)
    continue
if existing and existing.state in {"running", "download_pending", "submitting", "failed"}:
    results.append(existing)
    continue

result.state = "submitting"
_persist_clip(manifest_path, manifest, result)
try:
    result.task_id = vm.submit(request)
except VideoGenError as exc:
    result.error = str(exc)
    _persist_clip(manifest_path, manifest, result)
    results.append(result)
    continue
result.state, result.error = "running", None
_persist_clip(manifest_path, manifest, result)
results.append(result)
```

只轮询有 task ID 的 `running`。轮询异常或 `max_wait` 时保持 `running`、保存说明性 error 并结束本次观察；provider 明确失败才保存 `failed`。provider 成功时先保存 `download_pending` 与 URL；新任务和恢复任务均下载到 `*.part`，`os.replace` 到最终路径后才保存 `succeeded`。下载错误保持 `download_pending`，不再提交或轮询。

- [x] **步骤 4：确认完整 pipeline 绿灯**

运行：`uv run pytest -q tests/test_video_pipeline.py`

预期：通过，包括既有 happy path、frames、提示词覆盖、concat 与 reporter 测试。

- [x] **步骤 5：提交**

```bash
git add src/clip_weave/core/video_pipeline.py tests/test_video_pipeline.py
git commit -m "feat(video): resume durable clip tasks"
```

### 任务 4：同步文档并完成回归

**文件：**
- 修改：`README.md:75`
- 修改：`docs/architecture.md:45-68`
- 测试：完整项目测试

- [x] **步骤 1：更新能力边界**

两份文档说明：`manifest.json` 在提交、远端完成、待下载与最终状态时原子更新；匹配记录会恢复且不自动重提。保持重试分类、artifact hash、媒体 QC、Reference Audit 和关键帧为后续范围；不得宣称 provider 端 exactly-once。

- [x] **步骤 2：验证文档和全量行为**

```bash
rg -n -i 'manifest.*end|manifest.*本轮结束|durable job ledger.*next|尚不是.*ledger' README.md docs/architecture.md
uv run pytest
uv run python -m clip_weave --help
git diff --check
git status --short
```

预期：没有旧的“仅在本轮结束写 manifest”表述；测试和 CLI help 通过；无空白错误；最终仅修改计划内四个实现文件。

- [x] **步骤 3：提交**

```bash
git add README.md docs/architecture.md src/clip_weave/core/video_pipeline.py tests/test_video_pipeline.py
git commit -m "docs: describe durable video task recovery"
```
