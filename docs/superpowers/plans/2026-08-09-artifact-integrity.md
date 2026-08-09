# 下载产物 SHA-256 完整性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 只复用恢复时重新计算且匹配 manifest SHA-256 的下载视频。

**架构：** `ClipResult` 和既有 manifest clip record 增加可选 `artifact_sha256`；下载原子改名后 hash，恢复时不可信记录只降级到已有下载或轮询路径，绝不提交新任务。无新账本、无 schema version 变更、无媒体 QC。

**技术栈：** Python 3.11、`hashlib`、pytest、现有原子 manifest 写入。

---

### Task 1: 下载成功时记录 SHA-256

**Files:**
- Modify: `src/clip_weave/core/video_pipeline.py:76-88,201-286`
- Modify: `tests/test_video_pipeline.py:150-190`

- [ ] 写失败测试：

```python
def test_downloaded_clip_records_artifact_sha256(tmp_path):
    results = _run(tmp_path, model=FakeModel(), frames=[1])
    expected = hashlib.sha256(b"fake mp4 bytes").hexdigest()
    assert results[0].artifact_sha256 == expected
    assert _manifest(tmp_path)["clips"][0]["artifact_sha256"] == expected
```

- [ ] 运行 `UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest tests/test_video_pipeline.py::test_downloaded_clip_records_artifact_sha256 -q`，预期因字段缺失而失败。
- [ ] 在 `ClipResult` 加 `artifact_sha256: str | None = None`；`_clip_from_record()` 读取该字段。新增分块 `_sha256_file(path)`，使用 `hashlib.sha256()` 与 1 MiB 读取块。
- [ ] 在 `_download_clip()` 的 `os.replace(temp, dest)` 成功后、设置 `succeeded` 前计算 hash 并赋给 result，再持久化。hash 读取 `OSError` 走既有下载失败路径：清理 `.part`、保持 `download_pending`、不写成功 hash。
- [ ] 运行相同聚焦测试，预期 PASS。
- [ ] 写失败测试：将 `_sha256_file` monkeypatch 为 `OSError("read failed")`，断言结果和 manifest 都是 `download_pending` 且 hash 为 `None`；实现后运行 `UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest tests/test_video_pipeline.py -q`，预期 PASS。
- [ ] 提交：`git add src/clip_weave/core/video_pipeline.py tests/test_video_pipeline.py`，随后 `git commit -m "feat: record downloaded artifact hashes"`。

### Task 2: 恢复时重新验证并 fail closed

**Files:**
- Modify: `src/clip_weave/core/video_pipeline.py:470-490`
- Modify: `tests/test_video_pipeline.py:220-300`

- [ ] 写失败测试：首次运行后把 manifest 的 `artifact_sha256` 改为 `"0" * 64`；第二次运行必须无 `submit` 且发生 `download`，而不是直接复用。
- [ ] 运行该测试，预期旧逻辑失败于 `resumed.downloaded == []`。
- [ ] 新增 `_artifact_hash_matches(result)`：hash 必须全匹配 `[0-9a-f]{64}`、`video_path` 是常规文件、重新计算结果相同；文件读取 `OSError` 返回 `False`。
- [ ] 用 helper 替换 `existing.state == "succeeded"` 的仅存在性复用判断。失败时清空 `video_path`/`artifact_sha256`，记录 `artifact integrity check failed` 并持久化；有 `video_url` 或 inline payload 则 `download_pending`，否则有 `task_id` 则 `running`，无来源则 `failed`。每种情况持久化或更新既有记录且绝不进入 submit 分支。
- [ ] 运行 hash mismatch 测试，预期 PASS。
- [ ] 添加参数化测试 `None`、`"not-a-sha"`、`"A" * 64`；均须只下载、不 submit。添加读取 `OSError`、仅 task id（只 poll）、无来源（failed 且含 integrity error）测试。
- [ ] 添加回归测试：首次下载后将标准 `.mp4` 改为用户内容并篡改 manifest hash；恢复运行必须无 submit 且发生 download，标准路径字节不变，新成功记录使用存在且 hash 匹配的 recovered 路径。
- [ ] 在 `_download_clip()` 前提取安全目标选择 helper：标准 `{index:02d}-{slug}.mp4` 不存在时仍使用它；如标准或任一 `{stem}.recovered-{n}{suffix}` 候选已存在（包含悬空符号链接），选择同目录第一个未占用的 `recovered-{n}`。临时文件以所选目标为准，绝不覆盖、移动或删除任何已有候选。
- [ ] 运行 `UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest tests/test_video_pipeline.py -q`，预期 PASS；提交 `git add src/clip_weave/core/video_pipeline.py tests/test_video_pipeline.py`，随后 `git commit -m "fix: verify artifact hashes before reuse"`。

### Task 3: 文档与全量验证

**Files:**
- Modify: `docs/architecture.md:75-79`
- Modify: `docs/production-quality-loop.md:121-126`

- [ ] `architecture.md` 说明下载成功记录 SHA-256，恢复重新验证，缺失/非法/不匹配只按下载 URL、inline payload 或 task id 恢复且不重新 submit；明确没有媒体 QC。
- [ ] `production-quality-loop.md` 的 G1 只称已实现下载 SHA-256，明确 `ffprobe`、候选评分和媒体 QC 仍未实现。
- [ ] 运行 `UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run --extra dev pytest -q`、`UV_CACHE_DIR=/private/tmp/clip-weave-uv-cache uv run python -m clip_weave --help`、`git diff --check`、`git status --short --branch`；预期 pytest 全绿、CLI 返回 0、diff 无输出、状态只含本任务变更。
- [ ] 提交：`git add docs/architecture.md docs/production-quality-loop.md`，随后 `git commit -m "docs: describe artifact integrity checks"`。
