# 耐久任务账本设计

**状态：** 已实现；PR #11 已合并（`ff9d2cc`）。

**实现边界：** 已交付本文定义的版本化原子 `manifest.json`、请求指纹、`submitting`/`running`/`download_pending`/`succeeded`/`failed` 恢复状态机和本地重复提交防护。provider 端 exactly-once、自动重试/退避、artifact hash、媒体 QC、Reference Audit 与能力预检仍不属于这次交付。

## 目标

让重复执行 `gen-video` 时恢复已知的视频生成任务，而不是再次提交相同提示词并消耗模型额度。实现复用现有 `manifest.json` 路径与 `generate_clips()` 入口。

## 范围

本 MVP 仅覆盖单个 storyboard/provider 输出目录内的原子本地状态持久化、恢复和重复提交防护。不新增 CLI 命令、数据库、跨机器协调、provider 能力注册、服务端幂等请求头、自动重试/退避、媒体 QC 或 artifact hash。

## 当前问题

`generate_clips()` 仅在内存保存 `ClipResult`，并在全部轮询、下载结束后才写入 `manifest.json`。若进程在 `VideoModel.submit()` 后停止，provider task ID 丢失；下一次执行会再次提交同一镜头。

## 数据模型

`renders/ai-clips/<provider>/manifest.json` 升级为版本化恢复记录，保留现有的 storyboard、provider、model、resolution、ratio 字段，并新增 `schema_version: 2`。每个镜头记录新增：

- `request_fingerprint`：对 provider、model、镜头序号、提示词、时长、比例、分辨率、负提示词、seed、音频、水印和参考素材做规范 JSON 后计算的 SHA-256。
- `state`：`submitting`、`running`、`download_pending`、`succeeded` 或 `failed`。
- 现有 task ID、provider 结果 URL、本地路径、错误、耗时和请求元数据。

指纹只是本地语义身份，不是 provider API 的幂等键。只有指纹完全相同的记录才能恢复；同一镜头经过有意的提示词或参数修改会创建新记录，不覆盖旧 task 记录。

## 原子持久化

所有写入经过一个私有 helper：

1. 在 manifest 同目录写入唯一临时文件。
2. flush 并 `fsync` 临时文件。
3. 用 `os.replace()` 替换 `manifest.json`。

在 provider 提交前和每个持久状态转换后调用它。写入失败时，任务不得调用 provider；不引入新的存储依赖。

## 状态机

| 状态 | 含义 | 下次执行的动作 |
| --- | --- | --- |
| `submitting` | 提交前已保存请求指纹，但尚未保存 task ID。 | 停止该镜头并报告记录的错误，绝不自动重提。 |
| `running` | 已持久化 provider task ID。 | 仅轮询该 task ID。 |
| `download_pending` | provider 已成功并返回视频 URL，本地文件尚未确认。 | 仅下载已有结果。 |
| `succeeded` | 文件已写入且路径已保存。 | 仅当文件存在时直接复用。 |
| `failed` | provider 返回明确终态失败。 | 返回记录的失败，不自动重试。 |

```text
新任务 -> submitting -> running -> download_pending -> succeeded
                         |             |
                         +-> failed    +-> download_pending（下载失败）
```

远端调用前先原子保存 `submitting`。提交成功后，将 task ID 与 `running` 原子保存，再开始轮询。提交抛错或进程正好在此窗口中断时，记录保持 `submitting`；不猜测 provider 是否已接单，以避免重复消耗模型额度。

provider 返回成功后，先保存 URL 与 `download_pending`，再下载。下载失败保持该状态，下一次仅下载。下载写入临时路径后原子重命名，最后保存 `succeeded`。

`max_wait` 和临时轮询错误是本次观察失败，不是 provider 终态失败：任务保持 `running`，记录最后错误并可在之后恢复。只有 provider 明确失败才进入 `failed`。

## 恢复算法

每个被选中的 storyboard frame 都重新构造有效 `VideoRequest` 和指纹，然后读取匹配记录：

1. `succeeded` 且文件存在：不做 provider I/O，直接返回。
2. `running`：加入现有 task ID 的轮询集合。
3. `download_pending`：加入下载集合。
4. `submitting` 或 `failed`：返回记录状态，不提交。
5. 无匹配记录：追加并原子保存 `submitting`，然后提交。

执行仍保持批处理形态：先提交新任务，再一起轮询，再下载完成任务；恢复路径仅把已有任务送入后续阶段，不会再次调用 `submit()`。

## 兼容性

没有 `schema_version` 的旧 manifest 视为旧版最终摘要，不能用来恢复活动任务，因为它无法证明 task ID 与请求指纹的配对。新执行会写入 v2 格式；读取旧文件时仍先校验 JSON，损坏文件报出带路径的可操作错误，绝不静默覆盖。

## 验证

在 `tests/test_video_pipeline.py` 使用 `FakeModel` 覆盖：

1. 后续提交崩溃时，前一个 `running` task ID 已写入 manifest。
2. 第二次相同执行只轮询已保存 task ID，不再提交。
3. 已完成且文件存在的镜头不做 provider 调用。
4. provider 成功后下载失败，下一次只下载。
5. 超时和临时轮询错误保持可恢复，不变成 `failed`。
6. 已保存的 `submitting` 永不自动重提。
7. 修改提示词或请求参数会产生新指纹且只提交一次新任务。
8. 原子写入失败时，model 不会收到请求。

执行聚焦测试、完整 `uv run pytest` 和 `git diff --check`。

## 参考资料

- AWS Builders' Library：[Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)
- Stripe：[Idempotent requests](https://docs.stripe.com/api/idempotent_requests)
- Temporal：[Activities](https://docs.temporal.io/encyclopedia/activities)
- Google AIP-151：[Long-running operations](https://google.aip.dev/151)
