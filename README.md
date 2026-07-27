# clip-weave

> HyperFrames 前置门面 — 意图路由、素材匹配、规则守卫
>
> v6.0 | 分支：`feat/v6-hf-frontdoor`

clip-weave 不重造 HF 已有能力，只补三件事：

| 模块 | 职责 |
|------|------|
| **Intent Router** | 用户对话 / BRIEF.md 模板 / CLI → 选 HF workflow，写 BRIEF.md |
| **Asset Matcher** | `capture/extracted/asset-descriptions.md` → Gemini 向量匹配 → 为每个 beat 填充 `asset_candidates` |
| **Rule Guard** | 生成后 `npx check` 前确定性扫描 4 条 HF 特有规则；已知错误 Python 直接修复（0 token） |

HF 本身负责 storyboard 生成、composition 编写、lint / check / render 全链路。

---

## 前置依赖

| 工具 | 版本 | 安装 |
|------|------|------|
| Node.js | ≥ 18 | `brew install node` |
| HyperFrames CLI | 最新 | `npm install -g hyperframes` |
| Python | 3.11+ | 通过 uv 管理 |
| Claude Code | 最新 | https://claude.ai/code |

---

## 快速开始

### 方式一：Claude Code 技能（推荐）

**第一步：安装 clip-weave 技能**

```bash
# 克隆项目
git clone https://github.com/beersoccer/clip-weave.git
cd clip-weave

# 安装 Python 依赖
uv sync

# 配置 API 密钥
cp .env.example .env    # 填入 GEMINI_API_KEY（必须）
```

**第二步：将技能注册到 Claude Code**

```bash
# 将 skills/clip-weave/ 复制到 Claude Code 技能目录
cp -r skills/clip-weave ~/.claude/plugins/
```

或在 claude.ai 中使用 `/skills add` 安装（需要 HF CLI 已全局安装）。

**第三步：在 Claude Code 中使用**

```
/clip-weave
```

clip-weave 技能会引导你完成意图确认、素材来源配置，然后委托 HF workflow 执行。

---

### 方式二：CLI

```bash
# 最简调用（纯文字描述）
python -m clip_weave run \
  --message "小米SU7 品牌发布视频" \
  --project su7-launch

# 指定网站 URL（自动 capture）
python -m clip_weave run \
  --url "https://xiaomiev.com/su7" \
  --message "好看·好开·舒适·安全" \
  --project su7-launch \
  --length 30s

# Rule Guard 扫描（在 HF check 之前运行）
python -m clip_weave guard videos/su7-launch

# Asset Matcher 单独调用
python -m clip_weave match-assets videos/su7-launch \
  --query "驾驶舱内饰特写"
```

---

## 配置

```bash
cp .env.example .env
```

| 环境变量 | 必须 | 说明 |
|---------|------|------|
| `GEMINI_API_KEY` | ✅ | Gemini embedding（Asset Matcher）；HF capture 也使用此 key |
| `OPENAI_API_KEY` | 可选 | 预留，当前未使用 |
| `HEYGEN_API_KEY` | 可选 | TTS 路径（P3） |
| `FIGMA_TOKEN` | 可选 | Figma 输入路径 |

或使用项目根目录的 `config.yaml`（env var 优先）：

```yaml
providers:
  embedding: gemini   # gemini（当前唯一实现）
  vision: gemini
  tts: heygen
```

---

## 项目结构（v6.0）

```
clip-weave/
├── config.yaml                     # Provider 配置（可选，env var 优先）
├── .env.example                    # 环境变量示例
├── src/clip_weave/
│   ├── pipeline.py                 # 顶层编排：Intent → Factory → Delegate → Guard
│   ├── config.py                   # 配置加载（env + config.yaml）
│   ├── adapters/
│   │   ├── hyperframes.py          # HF CLI 封装（init / capture / lint / check / render）
│   │   ├── rule_guard.py           # 规则守卫 + Fix Registry（4 条 HF 高频规则）
│   │   └── asset_matcher.py        # Gemini embedding 素材匹配
│   └── core/
│       ├── intent_router.py        # 用户输入 → workflow + BRIEF.md
│       ├── project_factory.py      # HF 项目初始化（init / capture / 文件暂存）
│       └── delegator.py            # 委托指令生成
├── skills/
│   └── clip-weave/
│       ├── SKILL.md                # 入口技能（意图引导 + HF 委托）
│       └── references/
│           ├── brief-template.md   # BRIEF.md 可离线填写模板
│           ├── setup.md            # API Key 配置指南
│           └── input-guide.md      # 4 种输入方式详解
├── videos/                         # 每个项目工作目录（HF 标准结构）
│   └── <project-name>/
│       ├── BRIEF.md                # HF 标准 frontmatter
│       ├── capture/                # HF capture 产出（素材 + tokens + descriptions）
│       ├── compositions/           # HF compositions（Rule Guard 在此目录扫描）
│       └── renders/
├── tests/                          # 29 个单元测试
└── docs/
    ├── architecture.md             # v6.0 架构方案（权威文档）
    ├── hyperframes-analysis.md     # HF 能力分析
    └── tech-selection.md           # 技术选型历史
```

---

## 开发与测试

```bash
# 运行所有测试（29 个，全部通过）
uv run pytest

# 指定测试模块
uv run pytest tests/test_pipeline.py -v
uv run pytest tests/test_cli.py -v

# 查看覆盖情况
uv run pytest --tb=short
```

**测试覆盖：**

| 测试文件 | 覆盖范围 |
|---------|---------|
| `test_config.py` (8) | Config 加载、env var 优先级、has_embedding |
| `test_hyperframes_adapter.py` (8) | HF CLI 封装（init/capture/lint/check/render）|
| `test_pipeline.py` (8) | 完整 pipeline、BRIEF.md resume、--length 传递、GSAP fixer 回归 |
| `test_cli.py` (5) | CLI 命令（run / guard / match-assets）|

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
```

若 `videos/<project>/BRIEF.md` 已存在，跳过意图路由直接委托 HF（§4.1.1 resume 路径）。

### `guard` — Rule Guard 预检

```bash
python -m clip_weave guard <project_dir>
# 示例：python -m clip_weave guard videos/su7-launch
```

在 `npx hyperframes check` 之前运行，检查 4 条 HF 特有规则；已知模式 Python 直接修复（0 LLM token）。

### `match-assets` — Asset Matcher 单次调用

```bash
python -m clip_weave match-assets <project_dir> [--query TEXT]
```

---

## 实施路线图

| 阶段 | 状态 | 内容 |
|------|------|------|
| **P0** Intent Router + BRIEF.md + skills/clip-weave/ | ✅ 完成 | 已实现并测试 |
| **P1** Rule Guard + Fix Registry | ✅ 完成 | 4 条规则 + 4 条确定性修复 |
| **P2** Asset Matcher | ✅ 完成 | Gemini embedding + top-K + 缓存 |
| **P3** Kling 写实镜头混合 | 🔲 待验证 | `adapters/kling.py`（规划中）|
| **P4** ViMax 全 AI 真实影像 | 🔲 远期 | P3 验证后启动 |

---

## 文档

- [架构方案](docs/architecture.md) — 权威设计文档（v6.0）
- [HyperFrames 能力分析](docs/hyperframes-analysis.md)
- [技术选型历史](docs/tech-selection.md)
