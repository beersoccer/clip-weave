# clip-weave — LLM 网关接入设计规格（历史，2026-07-21）

> 已实现或已被后续架构取代；当前代码与 `.env.example` 为准。

> 版本：v1.0 | 日期：2026-07-21

---

## 1. 背景与目标

clip-weave 当前有两处 LLM 调用：
- `adapters/video_analyzer.py`：使用 `google-generativeai` SDK 调用 Gemini Flash 进行视频帧多模态分析
- `core/html_generator.py`：按 `HTML_GEN_MODEL` 分支使用 `anthropic` 或 `openai` SDK 生成 HTML/CSS/GSAP

目标：统一使用 OpenAI 兼容接口，支持通过公司 AI 网关（`base_url` + `api_key`）接入任意模型，同时保留直连各厂商的能力。

---

## 2. 设计方案

### 2.1 配置结构

按使用用途（而非厂商）组织，每个用途一个三元组（`BASE_URL` + `API_KEY` + `MODEL`）：

```ini
# 视频帧分析（Stage 1）
VIDEO_ANALYSIS_BASE_URL=http://aigateway.example.com/v1
VIDEO_ANALYSIS_API_KEY=your_key
VIDEO_ANALYSIS_MODEL=gemini-2.0-flash-exp

# HTML 生成（Stage 2a）
HTML_GEN_BASE_URL=http://aigateway.example.com/v1
HTML_GEN_API_KEY=your_key
HTML_GEN_MODEL=claude-sonnet-4-6

# 素材搜索（可选）
PEXELS_API_KEY=

# 其他
SCENE_THRESHOLD=0.35
```

`BASE_URL` 留空时使用 SDK 默认值（直连厂商 API）。两个用途可独立配置不同网关或直连不同厂商。

### 2.2 SDK 统一

移除 `anthropic` 和 `google-generativeai` 依赖，全部改用 `openai` SDK：

```python
from openai import OpenAI

client = OpenAI(
    base_url=cfg.video_analysis_base_url,
    api_key=cfg.video_analysis_api_key,
)
```

`openai` SDK 的 `base_url` 参数即为网关入口；`None` 表示使用默认值（`https://api.openai.com/v1`）。Anthropic/Gemini 模型通过网关代理时，网关负责协议转换，客户端侧接口完全相同。

### 2.3 视频帧分析的图片格式

原 `google-generativeai` SDK 使用 `inline_data`（base64 JPEG）；改用 `openai` SDK 后统一使用 OpenAI vision 格式：

```python
{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
```

---

## 3. 受影响模块

| 文件 | 变更内容 |
|---|---|
| `config.py` | 新增 6 个字段；删除 `anthropic_api_key`, `openai_api_key`, `gemini_api_key` |
| `adapters/video_analyzer.py` | 替换 `google.generativeai` → `openai.OpenAI`；图片格式改为 OpenAI vision |
| `core/html_generator.py` | 删除 `anthropic` 分支，统一 `openai.OpenAI` 路径 |
| `pyproject.toml` | 删除 `anthropic>=0.40`, `google-generativeai>=0.8` |
| `.env.example` | 替换为新三元组结构 |
| `tests/conftest.py` | 移除 `google.generativeai` mock，改为 `openai` mock |
| `tests/test_video_analyzer.py` | 更新 patch 路径 |
| `tests/test_html_generator.py` | 更新 patch 路径 |
| `tests/test_e2e.py` | 更新 mock 路径 |

---

## 4. Config 数据契约

```python
@dataclass
class Config:
    # Video analysis (Stage 1)
    video_analysis_base_url: str | None  # None = SDK 默认值（直连厂商）
    video_analysis_api_key: str
    video_analysis_model: str            # 默认 "gemini-2.0-flash-exp"

    # HTML generation (Stage 2a)
    html_gen_base_url: str | None        # None = SDK 默认值（直连厂商）
    html_gen_api_key: str
    html_gen_model: str                  # 默认 "claude-sonnet-4-6"

    # Optional
    pexels_api_key: str
    scene_threshold: float               # 默认 0.35
```

`load_config()` 从环境变量读取，将空字符串的 `*_BASE_URL` 转为 `None`（SDK 识别 `None` 为使用默认端点）。两个 `api_key` 字段缺失时运行时报错，其余字段均有默认值。

---

## 5. 关键实现细节

### video_analyzer.py 调用示例

```python
client = OpenAI(
    base_url=cfg.video_analysis_base_url,
    api_key=cfg.video_analysis_api_key,
)

messages = [
    {"role": "user", "content": [
        {"type": "text", "text": ANALYSIS_PROMPT},
        *[{"type": "image_url",
           "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
          for b64 in frame_b64s],
    ]}
]

response = client.chat.completions.create(
    model=cfg.video_analysis_model,
    messages=messages,
    max_tokens=4096,
)
shots_json = response.choices[0].message.content
```

### html_generator.py 调用示例

```python
client = OpenAI(
    base_url=cfg.html_gen_base_url,
    api_key=cfg.html_gen_api_key,
)

response = client.chat.completions.create(
    model=cfg.html_gen_model,
    messages=[{"role": "user", "content": prompt}],
    max_tokens=8192,
)
html = response.choices[0].message.content or ""
```

---

## 6. 测试策略

- `test_config.py`：验证 `load_config()` 正确读取所有新字段，`base_url` 为空时不传给 SDK
- `test_video_analyzer.py`：mock `openai.OpenAI`，验证 `base_url`/`api_key`/`model` 正确透传
- `test_html_generator.py`：同上，验证单一 SDK 路径（删除 anthropic 分支后无 if/else）
- `test_e2e.py`：更新 mock 路径，验证端到端不回归

---

## 7. 超出本 spec 范围

- 重试/限流策略（openai SDK 自带重试，暂不自定义）
- 流式输出（`stream=True`）
- Kokoro TTS 和 Pexels 搜索的 LLM 配置（当前无 LLM 调用，不涉及）
