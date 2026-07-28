# clip-weave Provider 配置

两组环境变量相互独立，任意一组缺失只影响对应阶段，视频仍可正常生成。

## Vision 增强（Phase 1）— 素材图像理解

Asset Matcher 调用企业 AI 网关的 `/chat/completions` 接口，为每张素材图生成高质量视觉描述。

| 变量 | 说明 |
|------|------|
| `VIDEO_ANALYSIS_BASE_URL` | 网关地址（需支持 `/chat/completions`） |
| `VIDEO_ANALYSIS_API_KEY` | 网关认证 Key |
| `VIDEO_ANALYSIS_MODEL` | 视觉模型名称（默认 `gemini-2.5-flash`） |

未配置：跳过 Vision 增强，使用 capture 原始描述；不影响 Embedding 阶段。

## Embedding 语义检索（Phase 2）— 素材匹配

Asset Matcher 调用 OpenAI 兼容的 `/v1/embeddings` 接口，对 beat 查询和素材描述做语义相似度排序。

| 变量 | 说明 |
|------|------|
| `EMBEDDING_BASE_URL` | Embedding 网关地址（需支持 `/v1/embeddings`，OpenAI 兼容） |
| `EMBEDDING_API_KEY` | 网关认证 Key |
| `EMBEDDING_MODEL` | Embedding 模型名称（默认 `text-embedding-3-small`） |

未配置：自动降级为 BM25 关键词匹配；不影响 Vision 阶段。

## HyperFrames capture（HF 直接读取）

| 变量 | 说明 |
|------|------|
| `GEMINI_API_KEY` | HF capture 生成 asset-descriptions.md（clip-weave 不读取此 Key） |
| `GEMINI_BASE_URL` | HF capture 的 Gemini 网关地址（可选，未设置则直连 Google） |

## 配置方式

```bash
# 本地开发
cp .env.example .env
# 编辑 .env，填入各环境的实际值

# CI / 生产（通过环境变量注入，无需 .env 文件）
export VIDEO_ANALYSIS_BASE_URL="https://your-vision-gateway/v1/"
export VIDEO_ANALYSIS_API_KEY="your-key"
export EMBEDDING_BASE_URL="https://your-embed-gateway/v1/"
export EMBEDDING_API_KEY="your-key"
```

## 降级行为一览

| 缺少配置 | 降级行为 |
|---------|---------|
| `VIDEO_ANALYSIS_*` 未配置 | 跳过 Vision 增强；使用 capture 原始描述 |
| `EMBEDDING_*` 未配置 | 跳过语义排序；使用 BM25 关键词匹配 |
| `GEMINI_API_KEY` 未配置 | HF capture 跳过 asset-descriptions.md 生成 |
| 三组均未配置 | 完全 BM25；视频仍可正常生成 |
