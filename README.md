# clip-weave

> HyperFrames 前置门面 — 意图路由、素材匹配、装配前规则预检、渲染路径决策
>
> v7.0 | 分支：`feat/rule-guard-soundness-and-t2v-routing`

clip-weave 不重造 HF 已有能力，只补几件事：

| 模块 | 职责 |
|------|------|
| **Intent Router** | 用户对话 / BRIEF.md 模板 / CLI → 选 HF workflow，写 BRIEF.md（语义分类优先，关键词兜底） |
| **Asset Matcher** | `capture/extracted/asset-descriptions.md` → Vision 增强 + Embedding/BM25 匹配 → 为每个 beat 填充打分的 `asset_candidates` |
| **Rule Guard** | 装配前预检 `media_in_subcomposition` —— HF lint 有此规则，但在装配前和单文件入口两个窗口失效 |
| **渲染路径** | HTML（HF 合成）还是 T2V（文生视频模型）由用户在项目之初选定一次，写进 `BRIEF.md` 的 `render:` |

HF 本身负责 storyboard 生成、composition 编写、lint / check / render 全链路。

---

## 前置依赖

| 工具 | 版本 | 安装 |
|------|------|------|
| Node.js | ≥ 18 | `brew install node` |
| HyperFrames CLI | 最新 | `npm install -g hyperframes` |
| Python | 3.11+ | 通过 uv 管理 |
| Claude Code | 最新 | https://claude.ai/code |
| ffmpeg | 任意较新版本 | `--concat` 拼接 T2V 片段时需要 |

---

## 快速开始

### 方式一：Claude Code 技能（推荐）

**第一步：安装 clip-weave 技能**

```bash
git clone https://github.com/beersoccer/clip-weave.git
cd clip-weave
uv sync
cp .env.example .env    # 至少填 GEMINI_API_KEY；T2V 网关 key 按需填
```

**第二步：一次性安装引导**

```bash
bash scripts/install.sh
```

这是全仓库唯一许可调用 `npx hyperframes skills update` 的地方。安装完成后不要再主动
升级技能 —— 除非用户明确要求（如「更新技能」）。

**第三步：验证安装**

```bash
uv run python -m clip_weave --help
# 应看到：run / guard / match-assets / route / gen-video
```

**第四步：在 Claude Code 中使用**

```
/clip-weave
> 帮我做个 30 秒的小米 SU7 品牌视频，用 https://xiaomiev.com/su7 的素材
```

clip-weave 技能完成意图引导 → 生成 BRIEF.md（含渲染路径决策）→ 打印 HF workflow 委托指令。

---

### 方式二：CLI

```bash
# 最简调用（纯文字描述），渲染路径首次会问一次
python -m clip_weave run \
  --message "小米SU7 品牌发布视频" \
  --project su7-launch

# 指定网站 URL（自动 capture）+ 显式指定渲染路径，跳过询问
python -m clip_weave run \
  --url "https://xiaomiev.com/su7" \
  --message "好看·好开·舒适·安全" \
  --project su7-launch \
  --length 30s \
  --render html

# Rule Guard 扫描（在 HF check 之前运行）
python -m clip_weave guard videos/su7-launch

# Asset Matcher 单独调用
python -m clip_weave match-assets videos/su7-launch \
  --query "驾驶舱内饰特写"

# 渲染路径为 t2v 或 mixed 时：先生成可编辑的提示词文件，不花钱
python -m clip_weave gen-video videos/su7-launch/STORYBOARD.md \
  --provider doubao --prompts-only
```

---

## 配置

```bash
cp .env.example .env
```

完整变量表见 `.env.example` 与 `skills/clip-weave/references/setup.md`（Vision/Embedding
网关）、`skills/clip-weave/references/t2v-guide.md`（三家文生视频 provider + GCP project）。

关键分组：

| 分组 | 变量 | 说明 |
|------|------|------|
| Asset Matcher Vision | `VIDEO_ANALYSIS_BASE_URL/API_KEY/MODEL` | 未配置则跳过增强，用 capture 原始描述 |
| Asset Matcher Embedding | `EMBEDDING_BASE_URL/API_KEY/MODEL` | 未配置则降级 BM25；与 Vision 完全独立 |
| Intent 语义路由 | `ROUTER_*`（缺失回退 `HTML_GEN_*` → `VIDEO_ANALYSIS_*`）| 网关不可用时自动降级为关键词匹配 |
| T2V provider | `DOUBAO_VIDEO_*` / `ALI_VIDEO_*` / `VERTEX_VIDEO_*` | 各自可配 `*_API_KEY`；未配则回退共享的 `AI_GATEWAY_API_KEY` |
| HF capture | `GEMINI_API_KEY` / `GEMINI_BASE_URL` | HF 自己读取，非 clip-weave |

---

## 项目结构

```
clip-weave/
├── .env.example                    # 环境变量示例
├── src/clip_weave/
│   ├── pipeline.py                 # 顶层编排：Intent → Factory → Delegate → Guard
│   ├── config.py                   # 配置加载
│   ├── adapters/
│   │   ├── hyperframes.py          # HF CLI 封装（init/capture/lint/check/check_full/render）
│   │   ├── rule_guard.py           # 单规则装配前预检（media_in_subcomposition）
│   │   ├── asset_matcher.py        # Vision + Embedding/BM25 素材匹配
│   │   └── video_gen/              # 文生视频 provider（doubao/ali/vertex + gcp_project）
│   └── core/
│       ├── intent_router.py        # 用户输入 → workflow + BRIEF.md
│       ├── workflow_router.py      # LLM 语义 workflow 分类（关键词兜底）
│       ├── project_factory.py      # HF 项目初始化（init / capture / 文件暂存）
│       ├── delegator.py            # 委托指令生成
│       ├── storyboard.py           # STORYBOARD.md 解析 + 基础提示词回落
│       ├── render_path.py          # 项目级 render: html|t2v（默认 html）+ 逐帧 render: 覆盖
│       ├── llm_gateway.py          # 共享的 chat-completion 网关调用（含 OpenAI/Anthropic 双协议重试）
│       ├── t2v_prompt.py           # 生成用户可编辑的 T2V-PROMPTS.md，图文帧经 LLM 改写为可拍摄镜头
│       └── video_pipeline.py       # 逐帧生成 + manifest + FFmpeg 合流
├── skills/
│   └── clip-weave/
│       ├── SKILL.md                # 入口技能（意图引导 + HF 委托）
│       └── references/
│           ├── brief-template.md   # BRIEF.md 可离线填写模板
│           ├── setup.md            # API Key 配置指南
│           ├── input-guide.md      # 4 种输入方式详解
│           └── t2v-guide.md        # T2V 渲染路径详解
├── videos/                         # 每个项目工作目录（HF 标准结构）
│   └── <project-name>/
│       ├── BRIEF.md                # HF 标准 frontmatter + render:
│       ├── capture/                # HF capture 产出
│       ├── compositions/           # HF compositions（Rule Guard 在此目录扫描）
│       ├── STORYBOARD.md           # HF 标准分镜
│       ├── T2V-PROMPTS.md          # render: t2v/mixed 时生成，用户可编辑
│       └── renders/
├── tests/                          # 见「开发与测试」
└── docs/
    ├── architecture.md             # 架构方案（权威文档）
    ├── hyperframes-analysis.md     # HF 能力分析
    ├── tech-selection.md           # 技术选型历史
    └── report-tech-leads.md        # 技术汇报材料
```

---

## 开发与测试

```bash
uv run pytest              # 全部离线，不触真实网关/npx/ffmpeg/gcloud
uv run pytest tests/test_rule_guard.py -v
uv run pytest -q
```

按模块拆分的测试文件：`test_config.py`、`test_hyperframes_adapter.py`、`test_rule_guard.py`、
`test_pipeline.py`、`test_cli.py`、`test_project_factory.py`、`test_asset_matcher.py`、
`test_storyboard.py`、`test_render_path.py`、`test_video_gen_providers.py`、
`test_video_pipeline.py`、`test_gcp_project.py`、`test_workflow_router.py`、
`test_t2v_prompt.py`。当前 257 个测试全部通过（`uv run pytest -q` 的输出为准，不要抄这里
的数字）。

`tests/test_rule_guard.py` 里的 HF 官方正确写法零误报测试是关键防回归资产：它把三条已删除
规则的误报证据固化成断言，防止后续重新引入。

**E2E 烟测（不需要任何 API key）：**

```bash
# 1. 验证意图路由：纯文字 → BRIEF.md
uv run python -m clip_weave run --message "小米SU7 品牌视频" --project smoke-test --render html
cat videos/smoke-test/BRIEF.md
# 预期：workflow: product-launch-video 或 faceless-explainer；render: html

# 2. 验证 Rule Guard：检测 media_in_subcomposition
mkdir -p videos/smoke-test/compositions
printf '<template><video src="x.mp4" muted playsinline></video></template>' \
  > videos/smoke-test/compositions/01.html
uv run python -m clip_weave guard videos/smoke-test
# 预期：exit code 1，输出 "violations need attention"

# 3. 验证 BRIEF.md resume 路径（已有 BRIEF.md 时跳过意图路由）
uv run python -m clip_weave run --message "任意输入" --project smoke-test
# 预期：直接打印委托指令，不重写 BRIEF.md
```

---

## CLI 命令参考

### `run` — 路由意图并生成 HF 项目

```bash
python -m clip_weave run \
  [--url URL]             # 网站 URL（自动 capture）
  --message TEXT          # 核心消息（必须）
  [--project NAME]        # 项目名（默认从 URL/消息推导）
  [--videos-dir PATH]     # 项目根目录（默认 videos/）
  [--length DURATION]     # 视频时长，如 15s 30s 60s（默认 30s）
  [--workflow NAME]       # 强制指定 HF workflow
  [--render {html,t2v,mixed,ask}]  # 渲染路径（默认 ask：已设置则复用，否则询问）
```

若 `videos/<project>/BRIEF.md` 已存在，跳过意图路由直接委托 HF（§4.1.1 resume 路径）。

### `guard` — Rule Guard 预检

```bash
python -m clip_weave guard <project_dir>
```

装配前扫描 `media_in_subcomposition`（`<video>`/`<audio>` 必须是 `index.html` 根的直接
子元素）。**只有这一条规则** —— 其余检查交给 HF 原生 lint/check，详见
`docs/architecture.md` § 3.1。

### `route` — 查看意图路由结果（语义优先）

```bash
python -m clip_weave route "我们不做产品广告，只想讲清楚什么是向量数据库" --compare
# keyword : product-launch-video      ← 关键字命中「产品」，判错
# semantic: faceless-explainer        ← 语义判对
#   method=semantic confidence=1.00
```

workflow 选择默认走语义分类，网关不可用或返回不可解析时自动退回关键字匹配，
`--no-semantic` 可强制关键字。

### `match-assets` — Asset Matcher 单次调用

```bash
python -m clip_weave match-assets <project_dir> [--query TEXT]

# 逐帧验证：读 STORYBOARD.md 每帧 scene，打印 top-3 候选（不改 STORYBOARD.md）
python -m clip_weave match-assets videos/xiaomi-su7-promo --from-storyboard
```

### `gen-video` — T2V 渲染路径

```bash
python -m clip_weave gen-video <STORYBOARD.md> --provider {doubao,ali,vertex} [OPTIONS]
```

提示词生成到同目录的 `T2V-PROMPTS.md`（首次由 STORYBOARD 生成，之后复用并可手工编辑）。
`--prompts-only` 只写文件不花钱；`--dry-run` 只打印不写文件；`--regenerate-prompts` 丢弃
手工编辑重建；`--concat` 用 ffmpeg 拼接全部片段。完整选项与用法见
`skills/clip-weave/references/t2v-guide.md`。

---

## 实施路线图

| 阶段 | 状态 | 内容 |
|------|------|------|
| **P0** Intent Router + BRIEF.md + skills/clip-weave/ | ✅ 完成 | |
| **P1** Rule Guard | ✅ 完成 | 按 HF 源码核对收缩为单规则装配前预检 |
| **P2** Asset Matcher | ✅ 完成 | Vision 增强 + Embedding/BM25 + 质量下限过滤 |
| **P3** T2V 渲染路径 | ✅ 代码完成，待真实网关实测 | 三家 provider + `T2V-PROMPTS.md` + 项目级 `render:` |
| **P4** 渲染路径混排 | 🔲 P3 实测后 | `render: mixed`，FFmpeg 层合流 |

---

## 文档

- [架构方案](docs/architecture.md) — 权威设计文档
- [HyperFrames 能力分析](docs/hyperframes-analysis.md)
- [技术选型历史](docs/tech-selection.md)
- [T2V 渲染路径指南](skills/clip-weave/references/t2v-guide.md)
