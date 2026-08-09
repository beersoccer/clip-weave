# 下载产物 SHA-256 完整性设计

**状态：** 已实现。

## 目标

让 `gen-video` 只在本地下载产物内容经 SHA-256 验证后复用既有 `succeeded` 记录。每个 clip 在现有 `manifest.json` 中保存唯一的 `artifact_sha256`；恢复时重新计算文件 hash，不匹配、缺失或无法计算时绝不静默复用。

## 范围与非目标

本任务仅修改 `t2v_brand_film` 当前的本地下载与恢复状态机。

- 下载完成后以无覆盖的原子发布写入最终路径，计算 SHA-256，并和 `succeeded` 状态一起写入现有 manifest。
- 再次执行时，只有 `video_path` 存在且重新计算 hash 等于 `artifact_sha256` 的记录才可直接复用。
- 旧 manifest、缺少 hash、hash 不匹配或读取失败的文件都视为不可信，根据已有恢复来源转入受控恢复状态。
- 使用现有 `video_path` 作为文件定位，不重复保存路径、字节数、`ffprobe` 结果或第二个 artifact 账本。

不在范围内：文件大小、媒体编码/时长/分辨率探测、媒体 QC、artifact 跨项目去重、远程对象 hash、自动重试/退避、provider 请求幂等键、T2I/I2V、完整生产契约接入。

## 方案

采用在已有 `renders/ai-clips/<provider>/manifest.json` clip 记录中新增可选 `artifact_sha256` 字段的方案，而不创建独立账本。

SHA-256 是产物内容身份；`video_path` 仍是本地定位信息。恢复必须重新 hash 文件，不能只相信曾经写入的 hash。这样可检测下载截断、人工替换与磁盘损坏，而不把当前 P1 扩展为媒体质量检查。

## 数据与状态机

`ClipResult` 增加：

```python
artifact_sha256: str | None = None
```

新建下载路径的状态转换为：

```text
download_pending
  -> 下载到 .part
  -> os.link(.part, .mp4) 原子创建（目标存在则另选路径）
  -> 计算 SHA-256
  -> succeeded + video_path + artifact_sha256
```

`succeeded` 的定义变为：`video_path` 指向常规文件，且 manifest 中有 64 位小写十六进制 `artifact_sha256`，重新计算结果完全一致。hash 计算或 manifest 写入失败时不得写入 `succeeded`。

恢复时，对于匹配请求指纹的既有记录：

1. `succeeded`、文件存在且 hash 匹配：直接复用，不调用 provider I/O。
2. `succeeded` 但缺少/非法 hash、文件不存在、文件不是常规文件、hash 不匹配或读取失败：清空 `video_path` 与 `artifact_sha256`，再按已有恢复来源降级。
3. 有 `video_url` 或 `inline_payload_path`：转为 `download_pending`，仅重试本地下载。
4. 没有下载来源但有 `task_id`：转为 `running`，仅轮询既有任务。
5. 没有恢复来源：保留 `succeeded` 以外的受控失败状态并记录完整性错误；不得重新 `submit()`。

既有 `download_pending`、`running`、`submitting` 与 `failed` 的语义不变。完整性失败不是 provider 失败，也不属于本任务的自动重试分类。

## 错误处理与兼容性

- `_sha256_file(path)` 分块读取文件；`OSError` 转换为带镜头和路径的 `VideoGenError`，不暴露 traceback。
- manifest 中的 hash 必须为 64 个小写十六进制字符；任何其他值等同于缺失，不做宽松兼容。
- 写入到 `.part` 或无覆盖原子发布失败沿用现有 `download_pending` 恢复语义；发布成功后 hash 计算失败同样不能将该 clip 标记为 `succeeded`。
- 不删除 hash 不匹配的既有 `.mp4`，以免删除用户文件；只清除本次内存/manifest 记录中的可复用声明。
- 完整性失败后若可重新下载，标准路径或任一已尝试的恢复候选路径已存在（包括悬空符号链接）时，下载写入同目录第一个未占用的 `{stem}.recovered-{n}{suffix}`，`n` 从 1 递增；绝不覆盖、移动或删除既有文件。仅当标准 `{index:02d}-{slug}.mp4` 不存在时才继续使用它。最终发布使用同目录临时文件的 `os.link(temp, dest)` 原子创建；若竞争中目标出现，清理本次临时文件并改选下一个候选重新下载。
- 旧 schema v2 manifest 不升级 schema version；`artifact_sha256` 是向后兼容的可选字段。缺失字段使旧成功记录在下次运行时重新下载或轮询，而不是被当作可信。

## 测试与验收

离线 pytest 覆盖：

1. 新下载的文件在 `succeeded` manifest 记录中有正确 SHA-256。
2. hash 匹配的 `succeeded` 记录不调用 `submit`、`poll` 或 `download`。
3. 缺失、非法或不匹配 hash 的成功文件不被复用；有下载来源时仅重新下载，不再次 submit。
4. 文件缺失、目录路径、读取错误和无恢复来源均不产生新的 provider submit；状态与错误可恢复且可解释。
5. hash 计算失败或 hash 写入前 manifest 持久化失败不会产生包含 `artifact_sha256` 的 `succeeded` 记录。
6. 完整 `uv run --extra dev pytest -q`、`uv run python -m clip_weave --help`、`git diff --check` 均通过。
7. 完整性失败的恢复下载不得覆盖标准路径的既有用户文件；新产物必须记录到未占用的 recovered 路径并重新 hash。
8. 即使目标在存在性检查后才被其他写入者创建，原子发布也不得替换它；必须改用下一个 recovered 路径。
