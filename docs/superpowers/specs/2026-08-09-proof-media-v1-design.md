# Proof Media v1 与本地参考物化设计

**状态：** 待用户审阅。

## 目标

让 `t2v_brand_film` 的必需本地首帧参考在 provider 提交前成为该 provider 可读取的不可变 URI；物化结果可复用、可追溯，并在本地记录提交失败时清理刚上传的孤立对象。

## 范围与非目标

本版本只解决 `T2V-PROMPTS.md` 的 `reference` 进入既有 `generate_clips()` 的路径。

- 本地图片按 SHA-256 内容版本去重，上传至配置的对象存储，得到 `https://` 或 `gs://` URI。
- 已是目标 provider 支持 scheme 的远程 URI（包括未来 T2I 返回的 URI）直接传递，不重复上传。
- 保存最小来源/授权备注；二者均为记录字段，不构成许可证判定或阻塞规则。
- 复用既有 G0 preflight：只有物化后的 URI 通过 provider capability 检查，才调用 `submit()`。

不在范围内：T2I adapter、远程 URI 下载并 hash、完整 Creative Contract/Proof Media schema、授权凭据工作流、对象垃圾回收、artifact hash、自动重试、provider 端幂等或 P2/P3 能力。

## 方案选择

比较过三种实现：

1. 为 S3、GCS、OSS 分别接入 SDK：对用户最省配置，但引入三套凭据、依赖和失败语义，超出本纵切。
2. 静态 URI 模板但不上传：实现最小，却不能让本地文件真正可用于生成。
3. **采用通用 HTTP PUT 对象存储协议：** 以两个 URI 模板和可选请求头配置上传端点与 provider 可读端点；无 SDK 依赖，兼容内部对象存储代理、MinIO/GCS 网关等，同时真实完成上传。

选择方案 3。部署者为每个目标 scheme 配置上传 URL 模板、可读 URI 模板和认证头；未配置匹配 store 时，本地 `required` reference 明确失败，`optional` reference 仍沿用 G0 的 dropped 语义。

## 数据与配置

新增 `core/proof_media.py`，包含以下窄接口：

```python
@dataclass(frozen=True)
class MaterializedReference:
    source: str
    version: str | None
    uri: str
    scheme: str
    created: bool

class ProofMediaStore(Protocol):
    def materialize(self, path: Path, *, scheme: str) -> MaterializedReference: ...
    def delete(self, reference: MaterializedReference) -> None: ...
```

`HttpPutProofMediaStore` 用 `requests.put()` 上传，配置如下：

- `PROOF_MEDIA_<SCHEME>_UPLOAD_URL_TEMPLATE`：包含 `{sha256}` 与 `{suffix}` 的 PUT URL；
- `PROOF_MEDIA_<SCHEME>_URI_TEMPLATE`：包含同一占位符、返回给 provider 的 URI；
- `PROOF_MEDIA_<SCHEME>_UPLOAD_HEADERS_JSON`：可选 JSON 请求头，不写入 manifest 或日志。

`SCHEME` 取 `HTTPS` 或 `GS`。只有 URI 模板的 scheme 等于目标 provider capability 中已选 scheme 才可使用。每个本地 reference 优先选择 capability 顺序中的已配置 scheme；若多个可用，按稳定排序选择。上传 URL 可以是 HTTPS，即使返回给 Vertex 的 URI 是 `gs://`。

项目根目录的 `renders/proof-media.json` 是小型原子账本，版本为 `1`。每条本地记录至少包含：`source`（项目相对路径）、`sha256`、`suffix`、`uri`、`scheme`、`source_note`、`license_note` 与 `created_at`。相同内容 hash、suffix、scheme 和 URI 模板下的记录直接复用。远程 URI 不写入该账本，因为其内容和生命周期不由本地管理。

## 执行流程与回滚

1. `T2V-PROMPTS.md` 可选解析和写回 `reference_source`、`reference_license`；缺省时 `reference_source` 等于 `reference`，`reference_license` 为 `null`。
2. `generate_clips()` 创建 provider 后，在现有批量 preflight 前逐镜头解析 reference。
3. provider 已支持的远程 URI 原样进入 preflight；本地文件调用 materializer，替换为返回 URI。
4. 每次新上传成功后，立即把对应记录原子写入 `proof-media.json`。若该写入失败，调用 `delete()` 删除刚创建的对象，然后抛出包含镜头号和路径的 `VideoGenError`；删除失败只追加到错误文本，不掩盖原始账本错误。
5. 对全部镜头使用解析后的 URI 运行既有 preflight。任何必需参考无法解析、上传、入账或通过 capability 时，整批在任何 `submit()` 前失败。
6. `reference_audit` 的 `requested` 保留用户原始 reference；`applied` 为实际提交 URI。额外写入 `proof_media` 快照（version、uri、source、可选 notes），使恢复指纹随实际提交 URI 改变。

对象不会因正常失败、成功、或后续不再引用而自动删除；仅“本次上传成功但本地账本原子写入失败”的新对象需要补偿删除。已有记录或直传 URI 永不触发删除。

## 错误处理与兼容性

- 保持远程 `http`、`https`、`gs` reference 的现有行为。
- 没有 Proof Media 配置时，本地 optional reference 仍以 `dropped` 继续；本地 required reference 仍在 submit 前阻止。
- 本地路径须存在且是常规文件；读取/hash/上传异常均使用 `VideoGenError`，说明镜头、路径、目标 scheme 与配置修正方向。
- 上传请求显式传递 MIME type；无法从 suffix 判断时使用 `application/octet-stream`，不猜测图片格式。
- URI、认证头和授权备注不得写入不必要的日志；manifest 仅保存提交 URI 与用户提供的可选备注。

## 测试与验收

离线 pytest 覆盖：

1. 本地 required reference 经 fake HTTP store 上传后以支持的 URI 提交，并在 manifest/proof-media ledger 中留下版本记录。
2. 相同文件第二次运行复用记录，不再次 PUT 或再次提交已恢复任务。
3. provider 只支持 `gs` 时选择配置的 `gs` store；无匹配 store 时 required 在任何 submit 前失败。
4. 可用远程 URI 直传，materializer 不被调用；不支持的远程 URI 保持既有 required/optional G0 结果。
5. 账本写入失败会删除本次新对象；复用对象不会删除；删除失败保留两个错误原因。
6. `reference_source`/`reference_license` 的 parse/write round-trip 与旧提示词兼容。
7. 完整 `uv run --extra dev pytest -q`、`uv run python -m clip_weave --help`、`git diff --check` 均通过。

