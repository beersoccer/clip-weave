# P1 受控重试与退避实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 为既有 `running` 与 `download_pending` 记录实现可持久化、快速返回且绝不重新 submit 的短失败重试，并给用户明确进度提示。

**架构：** `adapters/video_gen/base.py` 将严格识别的网络、429 和 5xx 变为带元数据的 `VideoGenError`；`video_pipeline.py` 将该元数据持久化到既有 clip record，并以 RFC 3339 `next_retry_at` 作为恢复 I/O 的闸门。重试不在一次命令中 sleep；到期后的下一次调用仅 poll 已有 task 或下载已有来源。

**技术栈：** Python 3.11、requests、dataclasses、pytest、Click CLI 的既有 `report` 回调。

---

## 文件结构

- 修改 `src/clip_weave/adapters/video_gen/base.py`：提供安全的结构化错误分类、HTTP `Retry-After` 解析与下载错误分类。
- 修改 `src/clip_weave/core/video_pipeline.py`：持久化 retry 字段、计算退避、阻止未到期/耗尽/非可恢复记录的 I/O，并经 `report` 发出状态提示。
- 修改 `tests/test_video_gen_providers.py`：验证 HTTP 层分类与 `Retry-After`。
- 修改 `tests/test_video_pipeline.py`：验证 manifest、时间闸门、无重提、预算与进度提示。
- 修改 `README.md`、`docs/architecture.md`：仅描述本次已实现的边界。

### Task 1：结构化且严格的可恢复错误分类

**文件：**
- 修改：`src/clip_weave/adapters/video_gen/base.py:32-35,159-230`
- 测试：`tests/test_video_gen_providers.py`

- [ ] **步骤 1：写 HTTP 分类的失败测试**

在 `tests/test_video_gen_providers.py` 添加可控制 `status_code` 与 `headers` 的 response fake，并覆盖如下断言：

```python
def test_request_marks_429_with_retry_after():
    model = _model_with_response(status_code=429, headers={"Retry-After": "9"})
    with pytest.raises(VideoGenError) as raised:
        model._request("GET", "https://gateway.example/tasks/task-1")
    assert raised.value.error_class == "rate_limited"
    assert raised.value.status_code == 429
    assert raised.value.retry_after_seconds == 9.0

@pytest.mark.parametrize("status_code", [500, 502, 599])
def test_request_marks_5xx_as_server(status_code):
    model = _model_with_response(status_code=status_code)
    with pytest.raises(VideoGenError) as raised:
        model._request("GET", "https://gateway.example/tasks/task-1")
    assert raised.value.error_class == "server"
    assert raised.value.status_code == status_code

def test_request_leaves_401_non_retryable():
    model = _model_with_response(status_code=401)
    with pytest.raises(VideoGenError) as raised:
        model._request("GET", "https://gateway.example/tasks/task-1")
    assert raised.value.error_class is None
    assert raised.value.retry_after_seconds is None
```

另加 `requests.Timeout` 与 `requests.ConnectionError` 均为 `network` 的参数化测试，以及下载 HTTP 503、下载超时和下载本地写入 `OSError` 的分类测试。

- [ ] **步骤 2：运行分类测试，确认当前实现失败**

运行：`UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest tests/test_video_gen_providers.py -q`

预期：新增测试失败，因为 `VideoGenError` 尚无 `error_class` 属性。

- [ ] **步骤 3：实现元数据和 HTTP/download 分类**

将 `VideoGenError` 改为保留 RuntimeError 文本并接收可选元数据；只允许下列三种可重试类别：

```python
class VideoGenError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_class: Literal["network", "rate_limited", "server"] | None = None,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
```

在 `VideoModel` 中新增私有辅助函数：仅对 `requests.Timeout` 与 `requests.ConnectionError` 产生 `network`；仅对 429 产生 `rate_limited`；仅对 500–599 产生 `server`。`Retry-After` 先解析非负秒数，再解析 HTTP-date；无效、过去或缺失值返回 `None`。`_request()` 和 `download()` 都通过该辅助函数抛出 `VideoGenError`；其余 `RequestException`、HTTP 4xx、解码错误和本地写入错误不带可恢复分类。不得在错误文本中写入 Authorization header。

- [ ] **步骤 4：运行分类测试，确认通过**

运行：`UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest tests/test_video_gen_providers.py -q`

预期：通过；429、5xx、连接/超时与其他错误的元数据边界均被覆盖。

- [ ] **步骤 5：提交本任务**

```bash
git add src/clip_weave/adapters/video_gen/base.py tests/test_video_gen_providers.py
git commit -m "feat: classify retryable video errors"
```

### Task 2：先以离线测试锁定 retry manifest 与无 I/O 恢复边界

**文件：**
- 修改：`tests/test_video_pipeline.py:37-101,921-1051`
- 修改：`src/clip_weave/core/video_pipeline.py:77-95,260-335,600-670`

- [ ] **步骤 1：扩展 FakeModel 和受控时间测试工具**

让 `FakeModel.poll_error` 与 `download_error` 接受 `VideoGenError`，并在测试中固定 `video_pipeline._utc_now` 为 `2026-08-11T00:00:00+00:00`、固定 `video_pipeline.random.uniform` 为窗口上界。添加以下测试：

```python
def test_retryable_poll_error_is_persisted_and_returns_without_submit(tmp_path, monkeypatch):
    _freeze_retry_clock(monkeypatch)
    results = _run(tmp_path, model=FakeModel(poll_error=VideoGenError("offline", error_class="network")), frames=[1])
    record = _manifest(tmp_path)["clips"][0]
    assert results[0].state == "running"
    assert (record["error_class"], record["attempts"]) == ("network", 1)
    assert record["next_retry_at"] == "2026-08-11T00:00:01+00:00"

def test_future_poll_retry_does_no_provider_io_or_submit(tmp_path, monkeypatch):
    _persist_retryable_running_record(tmp_path, monkeypatch)
    resumed = FakeModel()
    _run(tmp_path, model=resumed, frames=[1])
    assert resumed.submitted == []
    assert resumed.polled == []

def test_due_poll_retry_only_polls_existing_task_and_clears_retry(tmp_path, monkeypatch):
    _persist_retryable_running_record(tmp_path, monkeypatch)
    _advance_retry_clock(monkeypatch, seconds=1)
    resumed = FakeModel(polls={"task-1": TaskStatus(state="running", raw={})})
    _run(tmp_path, model=resumed, frames=[1])
    record = _manifest(tmp_path)["clips"][0]
    assert resumed.submitted == []
    assert resumed.polled == ["task-1"]
    assert (record["error_class"], record["attempts"], record["next_retry_at"]) == (None, 0, None)
```

对 `download_pending` 复制相同三项断言，但只能调用 `download()`，不得调用 `poll()` 或 `submit()`。再分别覆盖：429 的 9 秒 `Retry-After` 胜过 1 秒 jitter；5xx 的首轮 1 秒；三次后 `next_retry_at is None` 且后续运行无 provider I/O；401、磁盘 `OSError`、required reference 失败、`submitting`、provider `TaskStatus(state="failed")` 都不排期也不自动恢复。测试 report 应包含“正在轮询/下载”、“下次可重试”、“本次未重新提交”、“等待下一次运行恢复”和“自动重试已停止”。

- [ ] **步骤 2：运行新增 pipeline 测试，确认失败**

运行：`UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest tests/test_video_pipeline.py -q`

预期：新增断言失败，因为 ClipResult 和 manifest 尚无 retry 字段，且未来记录仍会执行 I/O。

- [ ] **步骤 3：实现 retry 数据、时间闸门和快速返回**

在 `ClipResult` 的 `error` 后添加兼容默认字段：

```python
error_class: str | None = None
attempts: int = 0
next_retry_at: str | None = None
```

在 `_clip_from_record()` 为缺失字段使用上述默认值；不提高 `_MANIFEST_SCHEMA_VERSION`。在 `video_pipeline.py` 定义 `MAX_RETRY_ATTEMPTS = 3`、`_utc_now()`、`_parse_retry_at()`、`_retry_is_due()`、`_schedule_retry()` 与 `_clear_retry()`。`_schedule_retry()` 只接受 `VideoGenError.error_class` 为 `network`、`rate_limited`、`server` 的错误，计算 1、2、4 秒 full-jitter 窗口，并以较长的正 `retry_after_seconds` 覆盖；三次后保持状态、清空 `next_retry_at`。非可恢复错误设置 `error_class="non_retryable"`、清空排期，防止后续自动 I/O。

在恢复分支、download 恢复循环和 `pending` 轮询集合构造前统一调用 `_retry_is_due()`：未来排期、非可恢复与耗尽记录只 report 并保留结果；到期记录才进入既有 `poll()`/`_download_clip()` 路径。poll/download 捕获 `VideoGenError` 时调用 `_schedule_retry()` 后立刻持久化并从本次待处理集合移除，不调用 `time.sleep()`；成功的 pending/running poll 和 `running -> download_pending` 转换调用 `_clear_retry()`。不得改变 `submitting` 的既有保护，也不得在任何 retry 分支调用 `vm.submit()`。

- [ ] **步骤 4：运行 pipeline 测试，确认通过**

运行：`UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest tests/test_video_pipeline.py -q`

预期：全部通过；每个可恢复场景都只访问已有 task/download，非可恢复场景无自动 I/O。

- [ ] **步骤 5：提交本任务**

```bash
git add src/clip_weave/core/video_pipeline.py tests/test_video_pipeline.py
git commit -m "feat: persist controlled retry schedules"
```

### Task 3：同步用户文档并完成回归验证

**文件：**
- 修改：`README.md:73-77`
- 修改：`docs/architecture.md:45-47,73-81`
- 测试：全量 pytest、CLI help、diff 检查

- [ ] **步骤 1：更新 README 与 architecture 的失败边界说明**

将“没有自动重试”改为：仅已存在的 `running`/`download_pending` 记录会对网络、429、5xx 持久化最多三次的短退避；`Retry-After` 被遵守；命令不会等待退避而会显示下次恢复时间；`submitting`、非可恢复错误与 provider 终态失败绝不自动重试或提交。明确 `report` 会显示轮询、下载、退避、等待和预算耗尽状态，且不承诺 provider exactly-once。

- [ ] **步骤 2：运行完整验证**

运行：

```bash
UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest -q
UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run python -m clip_weave --help
git diff --check
git status --short --branch
```

预期：pytest 全绿、CLI 返回 0、diff 无输出；状态只包含本任务的文档变更。

- [ ] **步骤 3：提交文档与验证后的工作树**

```bash
git add README.md docs/architecture.md
git commit -m "docs: describe controlled retry recovery"
```

## 计划自审

- 设计中的结构化分类、三次 full-jitter、429 `Retry-After`、快速返回、无 submit、非可恢复阻断和进度提示，分别由 Task 1、Task 2、Task 3 覆盖。
- 计划不引入队列、后台任务、CLI 重试开关、数据库、QC 或 P2/P3 范围。
- 类型名与字段名在各任务中统一为 `VideoGenError.error_class`、`retry_after_seconds`、`ClipResult.attempts`、`ClipResult.next_retry_at`。
