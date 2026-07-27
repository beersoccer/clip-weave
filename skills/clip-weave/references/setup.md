# clip-weave Provider 配置

clip-weave 需要以下 API Key 才能使用所有功能。未配置的功能会优雅降级。

## 必需

| Key | 用途 | 获取地址 |
|-----|------|---------|
| `GEMINI_API_KEY` | Asset Matcher embedding + HF `capture` 素材描述生成 | https://aistudio.google.com/app/apikey |

`GEMINI_API_KEY` 被 HyperFrames `capture` 命令和 clip-weave Asset Matcher **共用**，
只需配置一次即可同时启用两个功能。

## 可选

| Key | 用途 | 获取地址 |
|-----|------|---------|
| `OPENAI_API_KEY` | Asset Matcher 备用 embedding 提供商 | https://platform.openai.com/api-keys |
| `HEYGEN_API_KEY` | HeyGen TTS 语音合成 | https://app.heygen.com/settings |

## 配置方式（优先级从高到低）

### 方式 1：环境变量（推荐）

```bash
export GEMINI_API_KEY="your-key-here"
export OPENAI_API_KEY="your-key-here"   # 可选

# 持久化（加入 ~/.zshrc 或 ~/.bashrc）
echo 'export GEMINI_API_KEY="your-key-here"' >> ~/.zshrc
```

### 方式 2：项目根目录 `config.yaml`

```yaml
# clip-weave/config.yaml
providers:
  embedding: gemini   # gemini | openai | local
  vision: gemini      # gemini | openai
  tts: heygen         # heygen | kokoro
```

`config.yaml` 不含 Key 本身，只指定使用哪个 provider。Key 仍需通过环境变量提供。

### 方式 3：`.env` 文件（本地开发）

复制 `.env.example` 为 `.env`，填入 Key：

```bash
cp .env.example .env
# 编辑 .env，填入真实 Key
```

## 降级行为

| 缺少 Key | 降级行为 |
|---------|---------|
| `GEMINI_API_KEY` 缺失 | Asset Matcher 改用关键词匹配（无向量检索）；HF capture 跳过 asset-descriptions.md 生成 |
| `OPENAI_API_KEY` 缺失（且 Gemini 可用） | 无影响，Gemini 为默认 provider |
| `HEYGEN_API_KEY` 缺失 | TTS 步骤跳过；视频无配音 |
