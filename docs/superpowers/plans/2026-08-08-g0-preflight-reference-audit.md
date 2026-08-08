# G0 预检与参考审计实施计划

> **给执行型 agent：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐项执行；步骤使用复选框追踪。

**目标：** 在任何视频生成提交前完成静态能力与参考 URI 预检，并将 requested/applied 参数和参考审计持久化到耐久 manifest。

**架构：** provider adapter 以 `ProviderCapabilities` 声明静态参数与首帧 URI scheme；新的纯函数 `generation_preflight` 返回唯一可提交的 `VideoRequest` 和审计结果。`video_pipeline.generate_clips()` 在加载/写入 manifest 和调用 `submit()` 前批量预检全部镜头，只有全部通过才进入原有恢复状态机。

**技术栈：** Python 3.11 标准库（`dataclasses`、`urllib.parse`）、既有 `VideoModel`/`VideoRequest` 协议、PyYAML、pytest。

---

## 文件范围

- 修改：`src/clip_weave/adapters/video_gen/base.py` — `ProviderCapabilities` 与 `VideoModel.capabilities`。
- 修改：`src/clip_weave/adapters/video_gen/doubao.py`、`ali.py`、`vertex.py` — 明确 capability 声明，删除会掩盖非法预检结果的参数回退。
- 新增：`src/clip_weave/core/generation_preflight.py` — 请求参数/参考 URI 预检和审计数据模型。
- 修改：`src/clip_weave/core/t2v_prompt.py` — `reference_requirement` round-trip。
- 修改：`src/clip_weave/core/video_pipeline.py` — 批量预检、manifest 审计和恢复指纹。
- 修改：`tests/test_video_gen_providers.py`、`tests/test_t2v_prompt.py`、`tests/test_video_pipeline.py` — adapter 声明、文档 round-trip 与无 I/O 的管道回归。
- 修改：`README.md`、`docs/architecture.md` — 仅说明已经交付的 G0 预检边界。

### 任务 1：为 provider 固化静态能力声明

**文件：**

- 修改：`src/clip_weave/adapters/video_gen/base.py:87-128`
- 修改：`src/clip_weave/adapters/video_gen/doubao.py:50-78`
- 修改：`src/clip_weave/adapters/video_gen/ali.py:65-94`
- 修改：`src/clip_weave/adapters/video_gen/vertex.py:50-88`
- 修改：`tests/test_video_gen_providers.py:75-125`

- [ ] **步骤 1：先写 provider capability 失败测试**

```python
from clip_weave.adapters.video_gen.base import ProviderCapabilities

def test_vertex_declares_veo_request_and_reference_limits():
    vm = VertexVideoModel(_cfg("vertex", "http://gw/v", "veo-3.1"))
    assert vm.capabilities.ratios == frozenset({"16:9", "9:16"})
    assert vm.capabilities.duration_choices == (4, 6, 8)
    assert vm.capabilities.reference_uri_schemes == frozenset({"gs"})

def test_ali_declares_no_first_frame_reference_support():
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.7-t2v"))
    assert vm.capabilities.reference_uri_schemes == frozenset()
```

- [ ] **步骤 2：运行测试确认失败**

运行：`uv run --extra dev pytest -q tests/test_video_gen_providers.py::test_vertex_declares_veo_request_and_reference_limits tests/test_video_gen_providers.py::test_ali_declares_no_first_frame_reference_support`

预期：失败，原因是 `capabilities` 尚不存在。

- [ ] **步骤 3：添加最小 capability 数据模型和 adapter 声明**

在 `base.py` 的 `VideoRequest` 后新增：

```python
@dataclass(frozen=True)
class ProviderCapabilities:
    ratios: frozenset[str]
    resolutions: frozenset[str]
    duration_range: tuple[int, int]
    duration_choices: tuple[int, ...] | None = None
    reference_uri_schemes: frozenset[str] = frozenset()
```

在 `VideoModel` 中增加只读属性，返回基于现有 `duration_range` 与 `duration_choices` 的默认能力。各 adapter 覆盖它：豆包使用其目前支持的比例/分辨率与 `frozenset({"http", "https"})`；Ali 用 `frozenset()`；Vertex 用 `frozenset({"gs"})`、`("16:9", "9:16")` 和既有 `duration_choices`。Ali legacy 的 `size` 组合必须从 `_SIZE_TABLE` 计算其 ratio/resolution 集合，避免未知组合再回退为 `1080p/16:9`；Vertex 的 `submit()` 删除 `ratio = ... else "16:9"` 回退，改为直接使用已预检的 `req.ratio`。

在 `adapters/video_gen/__init__.py` 导出 `ProviderCapabilities`。

- [ ] **步骤 4：运行 capability 测试确认通过**

运行：`uv run --extra dev pytest -q tests/test_video_gen_providers.py`

预期：通过；既有请求 payload 测试仍保持 provider 协议不变。

- [ ] **步骤 5：提交**

```bash
git add src/clip_weave/adapters/video_gen/base.py src/clip_weave/adapters/video_gen/__init__.py src/clip_weave/adapters/video_gen/doubao.py src/clip_weave/adapters/video_gen/ali.py src/clip_weave/adapters/video_gen/vertex.py tests/test_video_gen_providers.py
git commit -m "feat(video): declare provider generation capabilities"
```

### 任务 2：实现无网络的请求和参考审计预检

**文件：**

- 新增：`src/clip_weave/core/generation_preflight.py`
- 新增：`tests/test_generation_preflight.py`

- [ ] **步骤 1：写入预检的失败测试**

```python
from clip_weave.adapters.video_gen import VideoGenError, VideoRequest
from clip_weave.adapters.video_gen.base import ProviderCapabilities
from clip_weave.core.generation_preflight import preflight_request

CAPS = ProviderCapabilities(
    ratios=frozenset({"16:9"}), resolutions=frozenset({"1080p"}),
    duration_range=(4, 8), reference_uri_schemes=frozenset({"https"}),
)

def test_required_unsupported_reference_blocks_request():
    with pytest.raises(VideoGenError, match="required reference.*gs://bucket/key.png"):
        preflight_request(VideoRequest(prompt="p"), CAPS,
                          reference="gs://bucket/key.png", reference_requirement="required")

def test_optional_local_reference_is_dropped_with_a_reason():
    result = preflight_request(VideoRequest(prompt="p"), CAPS,
                               reference="assets/hero.png", reference_requirement="optional")
    assert result.request.image_url is None
    assert result.reference_audit.outcome == "dropped"
    assert result.reference_audit.reason == "local reference is not materialized"

def test_requested_duration_is_normalized_and_audited():
    result = preflight_request(VideoRequest(prompt="p", duration=99), CAPS,
                               reference=None, reference_requirement=None)
    assert result.request.duration == 8
    assert result.requested_parameters["duration"] == 99
    assert result.applied_parameters["duration"] == 8
```

- [ ] **步骤 2：运行测试确认失败**

运行：`uv run --extra dev pytest -q tests/test_generation_preflight.py`

预期：失败，原因是模块和函数尚不存在。

- [ ] **步骤 3：实现纯函数 preflight**

实现冻结的 `ReferenceAudit` 和 `PreflightResult`。使用 `urllib.parse.urlparse(reference).scheme.lower()` 区分 URI 与本地路径；允许的 provider URI 只能来自 `capabilities.reference_uri_schemes`。验证 ratio/resolution 不在 capability 集合时立即抛出 `VideoGenError`，错误中包含 `requested`、字段名和可选值。将 duration 限制到 `duration_range`，若 `duration_choices` 非空则选择距离最小且同分时靠前的值，保持 `VideoModel.clamp_duration()` 的现有语义。

对于 accepted 参考，以 `dataclasses.replace(request, duration=applied_duration, image_url=reference)` 返回；optional dropped 以 `image_url=None` 返回；required blocked 抛出异常。`requested_parameters` 必须含 `ratio`、`resolution`、`duration`、`negative_prompt`、`seed`、`generate_audio`、`watermark`；`applied_parameters` 使用同一字段及归一化后的值。空参考的审计为 `not_requested`，其 requirement/applied/reason 都为 `None`。

- [ ] **步骤 4：运行预检测试确认通过**

运行：`uv run --extra dev pytest -q tests/test_generation_preflight.py`

预期：通过，且测试中不存在 session、HTTP 或文件上传调用。

- [ ] **步骤 5：提交**

```bash
git add src/clip_weave/core/generation_preflight.py tests/test_generation_preflight.py
git commit -m "feat(video): preflight generation requests"
```

### 任务 3：让 T2V 提示词声明参考是否必需

**文件：**

- 修改：`src/clip_weave/core/t2v_prompt.py:88-120,405-500`
- 修改：`tests/test_t2v_prompt.py:200-245`

- [ ] **步骤 1：添加提示词文档 round-trip 失败测试**

```python
def test_reference_requirement_round_trips(tmp_path):
    doc = build_doc(parse_storyboard(_project(tmp_path)))
    doc.specs[0].reference_requirement = "required"
    path = tmp_path / "T2V-PROMPTS.md"
    path.write_text(render_markdown(doc), encoding="utf-8")
    assert parse_markdown(path).specs[0].reference_requirement == "required"

def test_reference_defaults_to_optional_for_existing_prompt_documents(tmp_path):
    path = tmp_path / "T2V-PROMPTS.md"
    path.write_text("## Frame 1\\n- reference: assets/hero.png\\n", encoding="utf-8")
    assert parse_markdown(path).specs[0].reference_requirement == "optional"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`uv run --extra dev pytest -q tests/test_t2v_prompt.py::test_reference_requirement_round_trips tests/test_t2v_prompt.py::test_reference_defaults_to_optional_for_existing_prompt_documents`

预期：失败，原因是 `PromptSpec` 没有该字段。

- [ ] **步骤 3：实现字段和兼容默认值**

在 `PromptSpec` 增加 `reference_requirement: Literal["optional", "required"] = "optional"`。当 `reference` 非空时 `render_markdown()` 写入 `- reference_requirement: <value>`；解析时只接受 `required`，其余（缺失、空值或 `optional`）归一化为 `optional`。`build_doc()` 不改变其现有选择参考逻辑，因而所有自动生成的参考默认 optional。

- [ ] **步骤 4：运行 T2V 提示词测试确认通过**

运行：`uv run --extra dev pytest -q tests/test_t2v_prompt.py`

预期：通过，既有手工 `T2V-PROMPTS.md` 不因新增字段失效。

- [ ] **步骤 5：提交**

```bash
git add src/clip_weave/core/t2v_prompt.py tests/test_t2v_prompt.py
git commit -m "feat(video): audit reference requirements"
```

### 任务 4：在管道中批量预检并持久化审计

**文件：**

- 修改：`src/clip_weave/core/video_pipeline.py:87-111,340-420`
- 修改：`tests/test_video_pipeline.py:29-83,130-210,550-590`

- [ ] **步骤 1：写入管道失败测试**

```python
def test_required_reference_blocks_the_whole_batch_before_submit(tmp_path):
    model = FakeModel(reference_uri_schemes=frozenset({"https"}))
    with pytest.raises(VideoGenError, match="frame 2.*required reference"):
        _run(tmp_path, model=model, reference_overrides={2: "assets/hero.png"},
             reference_requirements={2: "required"})
    assert model.submitted == []
    assert not (tmp_path / "renders").exists()

def test_optional_local_reference_is_audited_in_the_manifest(tmp_path):
    model = FakeModel(reference_uri_schemes=frozenset({"https"}))
    _run(tmp_path, model=model, reference_overrides={1: "assets/hero.png"})
    audit = _manifest(tmp_path)["clips"][0]["extra"]["reference_audit"]
    assert audit["outcome"] == "dropped"
    assert audit["reason"] == "local reference is not materialized"
    assert model.submitted[0].image_url is None

def test_audit_change_does_not_reuse_an_old_request(tmp_path):
    _run(tmp_path, model=FakeModel(reference_uri_schemes=frozenset({"https"})),
         reference_overrides={1: "https://cdn/hero.png"}, frames=[1])
    resumed = FakeModel(reference_uri_schemes=frozenset())
    _run(tmp_path, model=resumed, reference_overrides={1: "https://cdn/hero.png"}, frames=[1])
    assert len(resumed.submitted) == 1
```

- [ ] **步骤 2：运行测试确认失败**

运行：`uv run --extra dev pytest -q tests/test_video_pipeline.py::test_required_reference_blocks_the_whole_batch_before_submit tests/test_video_pipeline.py::test_optional_local_reference_is_audited_in_the_manifest tests/test_video_pipeline.py::test_audit_change_does_not_reuse_an_old_request`

预期：失败，原因是 pipeline 尚未接收 `reference_requirements`，也未在 manifest 记录审计。

- [ ] **步骤 3：先完成全部 selected frame 的预检，再进入恢复状态机**

扩展 `generate_clips()` 新增可选 `reference_requirements: dict[int, Literal["optional", "required"]] | None = None`。在现有 submit/resume 循环前构造每个 frame 的原始 `VideoRequest`、调用 `preflight_request()` 并收集成功结果；不要在此阶段创建 `out`、加载/写入 manifest 或调用 `submit()`。若有任一异常，将每个镜头错误按编号合成为一个 `VideoGenError` 后抛出。

全部成功后进入既有循环，使用 `PreflightResult.request` 调用 `submit()`，并将 `requested_parameters`、`applied_parameters` 和 `asdict(reference_audit)` 放入 `ClipResult.extra`。改造 `_request_fingerprint()`，将 applied request 和 `reference_audit` JSON 作为规范化 payload 的字段；调用点传入审计 dict。删去仅记录 `reference_asset` 的分支。

将 `FakeModel` 增加 `capabilities` 属性（从其测试构造参数生成），使全部既有测试的默认能力包含当前常用 ratio/resolution 与 HTTP(S) scheme。保留 `dry_run` 的现有离线契约：它不构造 `VideoModel`、不做 provider capability 预检、不创建输出目录也不写 manifest；report 文本增加“未验证 provider capability”。因为它永远不会调用 `submit()`，这不削弱真实提交路径的预检要求。

- [ ] **步骤 4：接通 CLI prompt 字段**

在 `src/clip_weave/__main__.py` 创建：

```python
reference_requirements = {s.index: s.reference_requirement for s in doc.specs}
```

并在 `generate_clips()` 调用中传入 `reference_requirements=reference_requirements`。为 CLI 增加测试：`T2V-PROMPTS.md` 中 required 本地参考导致命令退出 1 且 stdout/stderr 不显示 `submitted frame`。

- [ ] **步骤 5：运行管道与 CLI 测试确认通过**

运行：

```bash
uv run --extra dev pytest -q tests/test_video_pipeline.py tests/test_cli.py
uv run python -m clip_weave --help
```

预期：通过；失败预检的 FakeModel/CLI 不发生 submit，成功 optional 降级具有 manifest 审计记录。

- [ ] **步骤 6：提交**

```bash
git add src/clip_weave/__main__.py src/clip_weave/core/video_pipeline.py tests/test_video_pipeline.py tests/test_cli.py
git commit -m "feat(video): block unpreflighted generation"
```

### 任务 5：同步当前能力说明并完成回归

**文件：**

- 修改：`README.md:73-77`
- 修改：`docs/architecture.md:45-49,68-72`
- 测试：完整项目测试与静态检查。

- [ ] **步骤 1：更新面向用户和架构的边界说明**

在 README 说明：`gen-video` 在提交前验证静态 provider 能力；必需参考无法使用时阻止整批提交；可选参考的接受/丢弃原因写入 manifest。明确不提供本地参考上传、远程 capability discovery、provider exactly-once、自动重试、artifact hash 或媒体 QC。

在 architecture 中说明 `generation_preflight.py` 是 adapter capability 与 `video_pipeline` 之间的纯本地 G0 边界，并说明 manifest 保存 requested/applied 参数和 reference audit。不得将它称为完整 G0-G4 质量系统。

- [ ] **步骤 2：运行完整验证**

运行：

```bash
uv run --extra dev pytest -q
uv run python -m clip_weave --help
git diff --check
git status --short --branch
```

预期：完整离线测试通过，CLI help 成功，无空白错误，且只存在本计划列出的变更。

- [ ] **步骤 3：提交**

```bash
git add README.md docs/architecture.md
git commit -m "docs: describe generation preflight limits"
```
