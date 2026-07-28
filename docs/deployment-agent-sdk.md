# clip-weave 服务端部署方案 — Agent SDK + 单请求单运行时

> 文档版本：v1.0 | 更新日期：2026-07-28
> 目标读者：负责把 clip-weave 接入服务端 agent 运行时的基础设施/后端工程师
> 前置阅读：`architecture.md`（clip-weave 本身的编排逻辑）

---

## 1. 场景与约束

目标架构：用户请求到达服务端后，**为该请求拉起一个独立的 agent 运行时**（VM / microVM / sandbox 级隔离，一个用户一个实例），在该运行时内用 **Claude Agent SDK（Python，编程式调用）** 驱动 clip-weave + HyperFrames 技能完成视频生成，并向用户暴露一个专属的 Storyboard 编辑页面。

这个场景相比"长驻服务器 + 本机 CLI 安装"，本质约束是：

1. **运行时是一次性、短生命周期的**：每个请求对应新实例，实例销毁后状态不保留（除非你自己持久化）。
2. **任何"安装"动作都不能发生在请求路径上**：`git clone`、`uv sync`、`npx hyperframes skills update`、`pip install` 这类操作必须在镜像构建期完成，运行时只允许"读取已就位的文件 + 启动进程"。
3. **Agent SDK 不提供技能的编程注册 API**：Skills 只能作为文件系统产物（`SKILL.md` + 目录）存在，SDK 通过 `setting_sources` 从磁盘发现它们，这一点决定了部署形态必须是"把技能目录连同代码一起打进镜像"，而不是运行时动态拉取。

---

## 2. 制品划分：三类构建产物

| 制品 | 来源 | 构建方式 | 运行时如何使用 |
|------|------|---------|--------------|
| **clip-weave wheel** | `src/clip_weave` | `uv build` → `.whl` | `pip install` 进镜像，运行时 `import clip_weave` 直接调用 pipeline |
| **技能树（skills bundle）** | `.agents/skills/`、`skills/`、`skills-lock.json` | 原样打入镜像固定路径，构建期用 `skills-lock.json` 做哈希校验 | Agent SDK 通过 `setting_sources=["project"]` + `cwd` 指向这棵目录树发现技能 |
| **HyperFrames CLI + 系统依赖** | `npm install -g hyperframes`、Chromium、ffmpeg | 构建期装好，做一次 `npx hyperframes doctor` 预热 | 技能内部 `npx hyperframes ...` 调用时无需再联网安装 |

三者都在镜像构建期固化，运行时零安装、零联网依赖（除了模型调用、TTS/BGM 等业务网络请求本身）。

---

## 3. 目录布局要求（Agent SDK 技能发现规则）

Agent Skills 文档明确了发现规则（来自官方 SDK 文档）：Skills is discovered from filesystem locations governed by `setting_sources`；Python SDK 用 `setting_sources=["user", "project"]` 才会加载技能，默认（不传该参数时行为等同于 `["user","project","local"]`），显式传 `[]` 则完全不加载任何文件系统配置。技能加载路径是 **`cwd` 以及 `cwd` 往上、直到 repo 根目录的每一层 `.claude/skills/`**。

据此，镜像内必须保证：

```
/opt/clip-weave/                     ← 作为 SDK 的 cwd
├── .claude/
│   └── skills/                      ← 真实目录或到下面 bundle 的软链，SDK 从这里发现技能
│       ├── clip-weave -> /opt/hyperframes-skills/skills/clip-weave
│       ├── hyperframes-cli -> /opt/hyperframes-skills/.agents/skills/hyperframes-cli
│       └── ...（其余 24 个技能同理）
├── pyproject.toml / .venv 等         ← clip-weave 源码或已安装包
└── videos/<project-name>/           ← 运行时按请求动态创建的项目工作目录
```

- `cwd` 必须精确指向包含 `.claude/skills` 的目录，避免依赖"往上找到 repo 根目录"这个隐式行为在容器内没有 `.git` 时的不确定表现。
- 保留仓库现有的 `.claude/skills/*` 软链方式（本机开发时就是这么做的，见 `scripts/install.sh`）：镜像构建期跑一遍等价的软链生成逻辑，落到 `/opt/clip-weave/.claude/skills/`，实际内容仍指向只读挂载的 `/opt/hyperframes-skills/`。
- **`skills` 是上下文过滤器，不是沙箱**：SDK 文档明确指出，未在 `skills` 列表里的技能文件依然躺在磁盘上，可被 `Read`/`Bash` 工具读到，只是模型不会主动调用、`Skill` 工具会拒绝调用未列出的技能。如果你需要真正阻止某些技能内容被读取（比如还在灰度的技能），要在文件系统层面隔离，不能只靠 `skills` 参数。

---

## 4. 镜像构建（Dockerfile 骨架）

```dockerfile
# ---- 阶段 1：装好系统级重依赖，一次性预热 ----
FROM node:22-slim AS base
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg chromium ca-certificates python3.11 python3.11-venv \
    && rm -rf /var/lib/apt/lists/*
RUN npm install -g hyperframes@<PINNED_VERSION>

# ---- 阶段 2：clip-weave Python 包 ----
FROM base AS pyapp
WORKDIR /opt/clip-weave
COPY dist/clip_weave-*.whl /tmp/
RUN python3.11 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir /tmp/clip_weave-*.whl \
    && /opt/venv/bin/pip install --no-cache-dir claude-agent-sdk
ENV PATH="/opt/venv/bin:${PATH}"

# ---- 阶段 3：技能树打包 + 完整性校验 ----
COPY .agents/skills /opt/hyperframes-skills/.agents/skills
COPY skills /opt/hyperframes-skills/skills
COPY skills-lock.json /opt/hyperframes-skills/skills-lock.json
COPY scripts/verify-skills-lock.mjs /opt/hyperframes-skills/verify-skills-lock.mjs
RUN node /opt/hyperframes-skills/verify-skills-lock.mjs \
        /opt/hyperframes-skills/skills-lock.json /opt/hyperframes-skills

# 在 /opt/clip-weave/.claude/skills 下生成软链，指向 bundle 中的每个技能目录
COPY scripts/link-skills.sh /opt/link-skills.sh
RUN bash /opt/link-skills.sh /opt/hyperframes-skills /opt/clip-weave/.claude/skills

# ---- 阶段 4：预热重依赖，把首启开销挪到构建期 ----
RUN npx hyperframes doctor --json | tee /opt/doctor-report.json

WORKDIR /opt/clip-weave
ENTRYPOINT ["python3.11", "-m", "clip_weave.server"]
```

`verify-skills-lock.mjs` 需要新增（`skills-lock.json` 里已有每个技能的 `computedHash`，脚本只是重新计算并比对，构建期哈希不匹配直接 `exit 1`，避免"镜像里的技能内容和你本地开发时看到的不一致"这种漂移在生产才暴露）。`link-skills.sh` 遍历 bundle 目录，为每个技能创建同名软链，等价于本机 `scripts/install.sh` 里做的事，只是发生在构建期而非请求期。

版本锚定建议：镜像 tag 里同时编码 `clip-weave` wheel 版本号 + `skills-lock.json` 的内容哈希（或简单用锁文件自身的 sha256），例如 `clip-weave:0.1.0-skills-3a3a1d9`，发布 = 出新 tag，回滚 = 调度层切回旧 tag，不涉及任何运行中实例的原地变更。

---

## 5. Agent SDK 编程式调用（Python）

运行时进程（每个用户实例内跑一次）大致形态：

```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
from clip_weave.pipeline import run as clipweave_run
from clip_weave.config import load_config

PROJECT_ROOT = "/opt/clip-weave"          # 必须是包含 .claude/skills 的目录
VIDEOS_DIR = f"{PROJECT_ROOT}/videos"     # 该实例专属的工作目录（每实例一个用户，不需要再按 project 隔离租户）

async def handle_request(user_message: str, project_name: str):
    # ① Python 编排层先落地 BRIEF.md / 项目骨架（不经过 agent，本身就是确定性代码）
    cfg = load_config()
    project_dir = clipweave_run(
        user_input=user_message,
        project_name=project_name,
        videos_dir=VIDEOS_DIR,
        cfg=cfg,
    )

    # ② 用 Agent SDK 驱动 Claude 执行委托指令（HF workflow 技能真正生成 storyboard/composition）
    options = ClaudeAgentOptions(
        cwd=PROJECT_ROOT,
        setting_sources=["project"],       # 只加载项目级技能，不读运行时容器里不存在的 ~/.claude
        skills="all",                       # 或显式传入本次请求允许的技能名单
        allowed_tools=["Read", "Write", "Bash", "Skill"],
        permission_mode="acceptEdits",      # 服务端无人值守场景，按你的风控策略调整
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(
            f"项目目录：{project_dir}\n"
            f"BRIEF.md 已生成，请按照 clip-weave 技能中 §6 的委托指令继续执行对应的 HyperFrames workflow。"
        )
        async for msg in client.receive_response():
            # 按需要转发进度到你的请求-响应通道 / WebSocket
            ...
```

几个必须确认的选项含义（直接影响这套架构能否工作，务必对照你的容器环境验证）：

- **`setting_sources=["project"]`**：容器里通常没有真实的 `~/.claude`（用户级配置），显式只启用 `project` 源，避免 SDK 尝试读取一个不存在或者是别的用户遗留的 `~/.claude` 目录导致行为不可预测。如果你确实想让 `~/.claude` 里的组织级默认配置也生效，再加上 `"user"`，但要确保该路径在镜像里是你主动放的内容，不是宿主机穿透进来的脏状态。
- **`cwd`**：必须精确等于第 3 节里那个包含 `.claude/skills` 的目录，SDK 用它做技能发现的起点。
- **`skills`**：省略时行为等同于全部发现到的技能可用（匹配 CLI 行为）；显式传 `"all"` 或具体名单都可以，传 `[]` 会完全关闭技能调用。**建议显式传值而不是省略**，这样镜像里 bundle 内容变化时行为是显式可控的，不依赖"默认值恰好符合预期"。
- **`allowed_tools`** 里必须包含 `"Skill"`，否则设置了 `skills` 选项也无法真正调用到——SDK 文档特别强调了这一点（设置 `skills` 后 SDK 会自动把 `Skill` 加进 `allowedTools`，但如果你自己显式传了 `tools`/`allowed_tools` 列表，需要自己把 `"Skill"` 加进去，否则会被你自己的显式列表覆盖掉自动添加的行为）。

---

## 6. Storyboard 编辑页面在这个架构下的落地

延续之前的结论并针对"一用户一运行时"细化：

1. **HyperFrames `preview`（Studio 编辑器）进程在实例内绑定到该实例的网络接口**（不是 `127.0.0.1`），由你的调度层维护一张"用户请求 → 实例 → 内部端口"的映射，边缘网关按此映射把外部稳定 URL 转发进去。
2. 因为是一用户一实例，**不需要在同一个 studio-server 进程里做多租户 project 隔离**，这比之前设想的"长驻服务器多用户共享"场景简单得多。
3. 仍然建议给对外暴露的 URL 加一个短时效签名 token（HMAC 或 JWT），由调度层生成、网关校验，防止 URL 被转发/截获后被无关方访问——这是本方案里唯一还需要你显式补的安全措施，成本很低但不该省略。
4. 实例生命周期要接一个**闲置超时回收**策略：用户关闭页面或长时间无操作后，调度层主动销毁实例并清理端口映射，避免僵尸实例常驻。
5. 如果承载这些实例的平台支持**快照/预热恢复**（Firecracker microVM 快照、类似 Vercel Sandbox 的机制），务必利用：把第 4 节镜像构建之后再做一次"跑到 Chromium 首次真正渲染完成"的快照点，请求到来时直接从快照恢复而不是冷启动整个容器，这是压缩首字节延迟最有效的手段。

---

## 7. 发布与回滚检查清单

发布新版本时按顺序确认：

- [ ] `uv build` 产出新 wheel，版本号已在 `pyproject.toml` 里 bump
- [ ] `.agents/skills` / `skills` / `skills-lock.json` 若有上游更新，先在本机跑 `bash scripts/install.sh` 验证可用，再提交
- [ ] 镜像构建阶段 `verify-skills-lock.mjs` 通过（哈希与 `skills-lock.json` 一致）
- [ ] `npx hyperframes doctor --json` 在构建期跑通，`.ok` 为真
- [ ] 起一个实例做端到端烟测：至少跑通 `clip_weave.pipeline.run()` → BRIEF.md 生成 → Agent SDK 委托 → Storyboard 页面可访问
- [ ] 新镜像 tag 灰度切一小部分流量，观察渲染成功率 / 平均首字节延迟后再全量切换
- [ ] 回滚只需把调度层指回旧 tag，不涉及任何实例内的原地修改

---

## 8. 待你确认的开放问题

- 承载 agent 运行时的具体平台（K8s pod / Firecracker microVM / 某 PaaS sandbox API）会决定第 4 节 Dockerfile 是否要换成该平台自己的镜像/快照格式，请提供后我可以给出对应平台的配置骨架。
- 是否需要给 `~/.claude`（`setting_sources` 里的 `"user"` 源）注入组织级默认配置（比如统一的 `permission_mode`、审计 hook）；如果需要，这部分内容也要一起固化进镜像，纳入第 7 节的发布清单。
