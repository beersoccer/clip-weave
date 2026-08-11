# Proof Media v1 实施计划

> **给执行型 agent：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐项执行；步骤使用复选框追踪。

**目标：** 将必需本地首帧参考物化为 provider 可读取的不可变 URI，并在上传账本写入失败时安全补偿删除。

**架构：** `core/proof_media.py` 以窄的 store 协议实现 HTTP PUT 上传、内容 hash 去重和原子项目账本。`video_pipeline.generate_clips()` 在现有批量 G0 preflight 前解析 reference：可接受远程 URI 直传，本地路径先物化；随后将实际 URI 与 proof-media 快照写进现有 manifest/fingerprint。T2V prompt 仅增加可选来源和授权备注字段。

**技术栈：** Python 3.11 标准库、现有 `requests`、PyYAML、pytest。

---

## 文件范围

- 新增：`src/clip_weave/core/proof_media.py` — hash、HTTP PUT store、原子 proof-media 账本与本地 reference 解析。
- 修改：`src/clip_weave/core/video_pipeline.py` — 在 preflight 前物化、把快照加入 manifest/fingerprint。
- 修改：`src/clip_weave/core/t2v_prompt.py` — `reference_source`/`reference_license` 兼容性 round-trip。
- 修改：`src/clip_weave/__main__.py` — 传递两个新增 prompt 字段。
- 修改：`tests/test_proof_media.py` — store、复用、补偿删除和错误分类单元测试。
- 修改：`tests/test_video_pipeline.py` — provider URI、无 submit 批量失败、manifest/fingerprint 集成测试。
- 修改：`tests/test_t2v_prompt.py` — 可选元数据 round-trip。
- 修改：`README.md`、`docs/architecture.md` — 只说明已实现的配置和边界。

### 任务 1：固定 T2V prompt 的可选来源元数据

**文件：**

- 修改：`tests/test_t2v_prompt.py:232-262`
- 修改：`src/clip_weave/core/t2v_prompt.py:99-105, 430-432, 500-516`
- 修改：`src/clip_weave/__main__.py:318-363`

- [ ] **步骤 1：先写失败的 round-trip 测试**

```python
def test_reference_metadata_round_trips(tmp_path):
    doc = parse_markdown_from_text(
        tmp_path,
        "## Frame 1 — Hero\n"
        "- reference: assets/hero.png\n"
        "- reference_source: capture/hero.png\n"
        "- reference_license: customer supplied\n",
    )

    assert doc.specs[0].reference_source == "capture/hero.png"
    assert doc.specs[0].reference_license == "customer supplied"
    assert "- reference_source: capture/hero.png" in render_markdown(doc)
```

- [ ] **步骤 2：运行测试并确认因字段不存在而失败**

运行：`uv run --extra dev pytest -q tests/test_t2v_prompt.py::test_reference_metadata_round_trips`

预期：失败，提示 `T2VPromptSpec` 没有 `reference_source`。

- [ ] **步骤 3：实现最小的兼容字段与 CLI 映射**

```python
@dataclass
class T2VPromptSpec:
    # existing fields
    reference: str = ""
    reference_requirement: Literal["optional", "required"] = "optional"
    reference_source: str | None = None
    reference_license: str | None = None
```

在 `render_markdown()` 中仅在字段为真值时输出 `reference_source` 和 `reference_license`；在 `parse_markdown()` 的 frame-key 分支中读取两个字段。`gen_video_cmd()` 构建并传入：

```python
reference_sources = {s.index: s.reference_source or s.reference for s in doc.specs}
reference_licenses = {s.index: s.reference_license for s in doc.specs if s.reference_license}
```

并为 `generate_clips()` 增加同名可选参数。无字段的旧 prompt 必须保持 `None`/原 reference，且渲染时不产生新行。

- [ ] **步骤 4：运行聚焦测试确认通过**

运行：`uv run --extra dev pytest -q tests/test_t2v_prompt.py -q`

预期：通过。

- [ ] **步骤 5：提交**

```bash
git add src/clip_weave/core/t2v_prompt.py src/clip_weave/__main__.py tests/test_t2v_prompt.py
git commit -m "feat: retain proof media prompt metadata"
```

### 任务 2：以失败测试驱动 Proof Media store 与原子账本

**文件：**

- 新增：`tests/test_proof_media.py`
- 新增：`src/clip_weave/core/proof_media.py`

- [ ] **步骤 1：写 store 成功、复用和账本故障补偿的失败测试**

```python
def test_materialize_local_file_uploads_once_and_reuses_hash_record(tmp_path, monkeypatch):
    image = tmp_path / "hero.png"
    image.write_bytes(b"proof")
    calls = []
    class Response:
        def raise_for_status(self): pass
    def fake_put(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()
    monkeypatch.setattr(requests, "put", fake_put)
    store = HttpPutProofMediaStore.from_environment({
        "PROOF_MEDIA_HTTPS_UPLOAD_URL_TEMPLATE": "https://upload/{sha256}{suffix}",
        "PROOF_MEDIA_HTTPS_URI_TEMPLATE": "https://cdn/{sha256}{suffix}",
    })

    first = materialize_local_reference(image, tmp_path / "renders/proof-media.json", store, "https")
    second = materialize_local_reference(image, tmp_path / "renders/proof-media.json", store, "https")

    assert first.uri == second.uri
    assert len(calls) == 1
    assert json.loads((tmp_path / "renders/proof-media.json").read_text())["records"][0]["sha256"]

def test_ledger_write_failure_deletes_only_new_upload(tmp_path, monkeypatch):
    store = FakeStore(uri="https://cdn/hero.png")
    monkeypatch.setattr("clip_weave.core.proof_media._atomic_write_ledger", raise_os_error)

    with pytest.raises(VideoGenError, match="proof-media ledger"):
        materialize_local_reference(tmp_path / "hero.png", tmp_path / "proof-media.json", store, "https")

    assert store.deleted == ["https://cdn/hero.png"]
```

测试中的 HTTP 响应必须使用 fake object，避免任何实际网络；另加本地路径不存在、非法 headers JSON、缺少匹配 scheme 配置、删除失败仍保留原始账本错误的单独测试。

- [ ] **步骤 2：运行测试并确认导入失败**

运行：`uv run --extra dev pytest -q tests/test_proof_media.py`

预期：失败，原因是 `clip_weave.core.proof_media` 不存在。

- [ ] **步骤 3：实现最小 store、账本与解析 API**

```python
@dataclass(frozen=True)
class MaterializedReference:
    source: str
    sha256: str
    suffix: str
    uri: str
    scheme: str
    created: bool

class ProofMediaStore(Protocol):
    def materialize(self, path: Path, *, scheme: str, sha256: str) -> MaterializedReference: ...
    def delete(self, reference: MaterializedReference) -> None: ...

def materialize_local_reference(
    path: Path, ledger_path: Path, store: ProofMediaStore, scheme: str,
    *, source: str | None = None, source_note: str | None = None,
    license_note: str | None = None,
) -> MaterializedReference: ...
```

实现要求：用分块读取计算 SHA-256；调用既有样式的 `NamedTemporaryFile + fsync + os.replace` 写 `{ "schema_version": 1, "records": [] }`；只在不存在相同 `sha256`、`suffix`、`scheme`、`uri` 的记录时 PUT。PUT 时发送 `data=path.open("rb")` 与 `Content-Type=mimetypes.guess_type(path.name)[0] or "application/octet-stream"`，`raise_for_status()` 后才入账。若入账失败且 `created=True`，调用 `delete()`；将 delete 错误附加给抛出的 `VideoGenError`。

`HttpPutProofMediaStore.from_environment()` 只读取传入 mapping/`os.environ`，验证模板同时存在、包含 `{sha256}` 与 `{suffix}`，解析可选 headers JSON 为字符串字典，且返回 URI 的 scheme 与参数一致。删除使用相同 upload URL 的 HTTP DELETE。不要记录 headers。

- [ ] **步骤 4：运行聚焦测试确认通过**

运行：`uv run --extra dev pytest -q tests/test_proof_media.py`

预期：通过且不触发网络。

- [ ] **步骤 5：提交**

```bash
git add src/clip_weave/core/proof_media.py tests/test_proof_media.py
git commit -m "feat: add proof media materialization"
```

### 任务 3：将物化接入批量 G0 与恢复身份

**文件：**

- 修改：`tests/test_video_pipeline.py:280-430, 688-720`
- 修改：`src/clip_weave/core/video_pipeline.py:94-112, 296-421`

- [ ] **步骤 1：写 pipeline 失败测试**

```python
def test_required_local_reference_is_materialized_before_submit(tmp_path, monkeypatch):
    model = FakeModel(capabilities=capabilities(reference_uri_schemes=frozenset({"https"})))
    calls = []
    def fake_materialize(*args, **kwargs):
        calls.append((args, kwargs))
        return ResolvedReference(
            requested="assets/hero.png", applied="https://cdn/hero.png",
            proof_media={"sha256": "a" * 64, "uri": "https://cdn/hero.png"},
        )
    monkeypatch.setattr("clip_weave.core.video_pipeline.materialize_reference", fake_materialize)

    results = _run(tmp_path, model=model, reference_overrides={1: "assets/hero.png"},
                   reference_requirements={1: "required"})

    assert model.submitted[0].image_url == "https://cdn/hero.png"
    assert results[0].extra["proof_media"]["uri"] == "https://cdn/hero.png"
    assert len(calls) == 1

def test_materialization_failure_blocks_every_submit(tmp_path, monkeypatch):
    monkeypatch.setattr("clip_weave.core.video_pipeline.materialize_reference", fail_materialization)
    with pytest.raises(VideoGenError, match="frame 2.*materialize"):
        _run(tmp_path, reference_overrides={2: "assets/missing.png"},
             reference_requirements={2: "required"})
    assert model.submitted == []
```

另加测试：支持的远程 URI 不调用 materializer；proof-media snapshot 改变使 `_request_fingerprint()` 不复用旧 manifest；无 store 配置时 optional 本地 reference 保持当前 dropped 行为。

- [ ] **步骤 2：运行测试并确认失败**

运行：`uv run --extra dev pytest -q tests/test_video_pipeline.py -k 'materialized or materialization or proof_media'`

预期：失败，因为 `materialize_reference` 尚未接入 pipeline。

- [ ] **步骤 3：实现解析、批量预检与 manifest 快照**

在 `proof_media.py` 导出：

```python
@dataclass(frozen=True)
class ResolvedReference:
    requested: str | None
    applied: str | None
    proof_media: dict[str, object] | None

def materialize_reference(
    reference: str | None, *, project_dir: Path, supported_schemes: frozenset[str],
    source_note: str | None, license_note: str | None,
) -> ResolvedReference: ...
```

它对已有 supported URI 返回 `applied=reference, proof_media=None`；对带不支持 scheme 的远程 URI 不上传，让现有 preflight 决定 dropped/blocked；对项目相对本地路径选择已配置的 capability scheme 并调用 `materialize_local_reference()`，账本固定为 `project_dir / "renders/proof-media.json"`。在 `generate_clips()` 的 preflight 循环中先调用该函数，使用 `resolved.applied` 构造 `VideoRequest` 和调用 `preflight_request()`，但传入原 `reference` 作为 `requested` 语义。将 `proof_media` 同时放入 `ClipResult.extra` 和 `audit`，使 fingerprint 覆盖实际 materialized version/URI。所有解析与物化错误收集进现有 `preflight_errors`，保证没有部分 submit。

- [ ] **步骤 4：运行聚焦与回归测试确认通过**

运行：`uv run --extra dev pytest -q tests/test_video_pipeline.py tests/test_generation_preflight.py tests/test_cli.py`

预期：通过。

- [ ] **步骤 5：提交**

```bash
git add src/clip_weave/core/proof_media.py src/clip_weave/core/video_pipeline.py tests/test_video_pipeline.py
git commit -m "feat: submit materialized proof media references"
```

### 任务 4：补充用户配置说明并执行完整验证

**文件：**

- 修改：`README.md`
- 修改：`docs/architecture.md`

- [ ] **步骤 1：写文档验收检查**

```bash
rg -n 'PROOF_MEDIA_HTTPS_UPLOAD_URL_TEMPLATE|PROOF_MEDIA_GS_URI_TEMPLATE|本地参考' README.md docs/architecture.md
```

预期：说明配置变量、支持 URI 直传、仅账本写入失败时补偿删除，以及未配置 store 时 required reference 仍阻止生成；不声称已具备 T2I、许可证验证、自动重试或 artifact hash。

- [ ] **步骤 2：更新最小使用说明**

文档加入如下示例，且不包含真实凭据：

```bash
export PROOF_MEDIA_HTTPS_UPLOAD_URL_TEMPLATE='https://upload.example/references/{sha256}{suffix}'
export PROOF_MEDIA_HTTPS_URI_TEMPLATE='https://cdn.example/references/{sha256}{suffix}'
export PROOF_MEDIA_HTTPS_UPLOAD_HEADERS_JSON='{"Authorization":"Bearer ..."}'
```

说明 Vertex 使用 `PROOF_MEDIA_GS_*`，其 upload URL 可以仍为 HTTPS，但 URI template 必须产生 `gs://`。

- [ ] **步骤 3：运行完整验证**

运行：`uv run --extra dev pytest -q && uv run python -m clip_weave --help >/dev/null && git diff --check`

预期：退出码为 0，pytest 无失败，CLI 可加载，diff 无空白错误。

- [ ] **步骤 4：提交**

```bash
git add README.md docs/architecture.md
git commit -m "docs: describe proof media materialization"
```

## 计划自检

- 覆盖性：四个任务分别覆盖 prompt 输入、上传/账本、G0/manifest 集成和用户配置；没有延伸到 T2I、重试、artifact hash 或完整授权流程。
- 占位符：已检查没有 `TBD`、`TODO`、模糊的“适当处理”或未定义接口。
- 类型一致性：`MaterializedReference` 是 store 的返回值；`ResolvedReference` 是 pipeline 的解析结果；`proof_media` snapshot 进入 `extra` 和 fingerprint，不替换既有 `ReferenceAudit` 字段。
