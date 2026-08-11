# P1 受控重试与退避设计

**状态：** 已批准，待实现。

## 目标

对已持久化的 `running` 轮询任务与 `download_pending` 下载任务，保存可解释的可恢复错误和下次重试时间。暂时性故障应快速结束本次命令，后续运行只在到期后恢复已有 provider task 或已有下载来源；整个机制不得产生新的 `submit()`，不得增加模型扣费。

## 范围与非目标

本轮只修改现有 `manifest.json`、`VideoGenError` 的错误元数据、`generate_clips()` 的恢复控制和 CLI 已使用的 `report` 进度通道。

不新增队列、后台进程、数据库、人工重试 CLI、provider 端 exactly-once、媒体 QC 或 P2/P3 功能。不重试 `submitting`，也不把已耗尽重试的记录伪造为 provider 终态 `failed`。

## 方案选择

推荐“持久化排期、快速返回”。相比在同一命令内 sleep 后重试，它不会让用户面对长时间无响应；相比把任意 `VideoGenError` 都重试，它不把凭据、参数与能力问题误当成网络抖动。每次后续 `gen-video` 调用读取同一条记录，只有时间到期才调用既有的 `poll(task_id)` 或 `download()`。

## 数据模型与错误分类

`ClipResult` 及其 manifest record 新增兼容字段：

- `error_class`：`network`、`rate_limited`、`server` 或 `None`。
- `attempts`：当前状态中连续的、已经排期的可恢复失败次数；旧记录默认 `0`。
- `next_retry_at`：UTC RFC 3339 时间字符串或 `None`。

`VideoGenError` 增加可选的机器可读 `error_class`、`status_code` 与 `retry_after_seconds`，同时保留既有安全错误文本。adapter 的 HTTP 层只将 HTTP 429 分类为 `rate_limited`、HTTP 500–599 分类为 `server`；`requests` 的连接与超时类异常分类为 `network`。下载路径按同一严格规则分类。其他 HTTP 4xx、认证/权限、配置、参数、capability、base64/内联负载、本地文件和磁盘错误都保持非可恢复。

provider 返回 `TaskStatus(state="failed")` 一律是明确终态失败，直接保持现有 `failed` 行为，不进入该分类。

## 退避与状态机

一次可恢复失败将 `attempts` 加一。第 1、2 次分别使用 full jitter 的指数窗口 1、2 秒；即随机延迟位于 `[0, window]`。429 的 `Retry-After` 若比该随机延迟更长，以该服务端值为准。`next_retry_at` 必须是从注入的当前 UTC 时间计算出的时间戳。

第 3 次失败后，记录保持 `running` 或 `download_pending`，保存最后错误和分类，清空 `next_retry_at`，且该记录不再自动调用 provider。一次成功的轮询观察（`pending` 或 `running`）会清除错误分类、清空 `next_retry_at` 并将连续 `attempts` 归零；状态转换到 `download_pending` 也归零。

恢复时：

1. `submitting`、明确 `failed`、已耗尽 attempts 的记录均不做 provider I/O。
2. 有未来 `next_retry_at` 的 `running` 或 `download_pending` 不做 provider I/O。
3. 到期的 `running` 只调用保存的 task id 的 `poll()`；到期的 `download_pending` 只使用保存的 URL 或 inline sidecar 调用下载。
4. 没有排期错误的已有记录遵循既有恢复路径；新 fingerprint 才可进入 submit 路径。

命令不因可恢复错误等待下一轮退避。它继续处理同批其他可立即执行的已有任务，然后返回结果，因此故障反馈时间由单次请求超时决定，而不是叠加多轮 sleep。

## 用户可见进度

不引入第二个 UI 通道；复用 CLI 传给 `generate_clips()` 的 `report`。每个既有 task/download 在实际 poll/download 前报告当前动作；遇到可恢复错误后报告状态、分类、尝试次数和 UTC 的 `next_retry_at`，并明确“本次未重新提交”。若重试尚未到期，报告“等待下一次运行恢复”及时间，不静默跳过。达到预算时报告自动重试已停止、任务仍保留，且同样明确未重新提交。

`_safe_reporter` 继续隔离输出通道异常：通知失败绝不能改变 manifest 或把成功任务标为失败。

## 测试与验收

离线 FakeModel 和受控时钟/随机源应覆盖：网络、429（含 `Retry-After`）和 5xx 的持久化排期；未到期时 poll/download 均未调用；到期时只调用相应的已有 task/download；三次预算后不再调用；成功轮询清除连续失败元数据；所有非可恢复分类不排期；`submitting` 永不重提；provider 终态失败保持 `failed`。

测试还应断言 `report` 包含处理、退避、未到期及预算耗尽提示，并在 reporter 抛错时证明状态和调用边界不变。全量测试、CLI help、`git diff --check` 通过后，README 与 architecture 只陈述已经实现的短失败重试边界。
