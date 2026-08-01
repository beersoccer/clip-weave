# T2V 渲染路径使用指南

`STORYBOARD.md` → `T2V-PROMPTS.md`（用户可编辑）→ 文生视频模型 → FFmpeg 合流。
与 HTML 路径并列的第二条渲染路径，跳过写 composition HTML。

## 何时用哪条路径

| | HTML 路径 | T2V 路径 |
|---|---|---|
| 适合 | 图形、文字、UI、图表、数据 | 写实画面、实景、真人、镜头运动 |
| 精度 | 代码级，每帧可复现 | 有随机性，靠改提示词迭代 |
| 主要开销 | LLM 写 composition + `check` 循环的时间 | 模型推理费用与排队 |
| 不适合 | 电影级写实、复杂物理 | 精确文字排版、品牌色严格一致、数据准确性 |

品牌色和文字排版必须准确的镜头**不要**交给 T2V —— 模型无法保证十六进制色值与字形。
`T2V-PROMPTS.md` 会把这类帧标记 `needs_review`，建议留在 HTML 路径。

## 路径在项目之初决定一次

写进 `BRIEF.md` frontmatter，不是逐帧决定：

```yaml
---
workflow: product-launch-video
render: t2v       # html（默认）| t2v | mixed
---
```

`run --render ask`（默认）会在缺失时问一次并持久化，同一项目不重复询问；也可以直接
`run --render t2v` 跳过询问。也接受 `render_path:` 作为别名。非法值会告警并视为未设置。

只有 `mixed` 才需要逐帧标注，指出哪些镜头走 T2V：

```markdown
## Frame 2 — 实拍开场
- scene: 城市夜景中一辆红色轿车驶过湿滑路面
- visual_type: live_action
```

识别的取值（大小写不敏感）：

- 走 T2V：`live_action` `live-action` `t2v` `footage` `realistic`
- 走 HTML：`motion` `html` `graphic` `graphics`

未标注或取值无法识别的帧跟随项目默认；`mixed` 项目里这类帧落到 **HTML** —— 确定性、
零推理费用的那一侧。

`gen-video` 会核对 `BRIEF.md` 的 `render:` 和当前操作是否一致：若 `render: html` 却在跑
`gen-video`，会打印矛盾提示并要求确认（`--yes` 跳过确认；非交互环境不询问，按用户已设置的
值继续）。

## 提示词是一个可编辑的文件，不是即时拼装

```bash
# 生成/刷新 T2V-PROMPTS.md，不调用任何模型，不产生费用
uv run python -m clip_weave gen-video "$PROJECT_DIR/STORYBOARD.md" --provider doubao --prompts-only

# 只想看看内容，不写文件也不生成
uv run python -m clip_weave gen-video "$PROJECT_DIR/STORYBOARD.md" --provider doubao --dry-run

# 编辑完 T2V-PROMPTS.md 后，真正生成
uv run python -m clip_weave gen-video "$PROJECT_DIR/STORYBOARD.md" --provider doubao --concat

# 手工编辑作废、想从 STORYBOARD.md 重新生成
uv run python -m clip_weave gen-video "$PROJECT_DIR/STORYBOARD.md" --provider doubao --regenerate-prompts --prompts-only
```

`T2V-PROMPTS.md` 首次运行由 `STORYBOARD.md` 生成，之后每次运行都复用（可手工编辑）；
`--regenerate-prompts` 才会重建并丢弃手工编辑。它按各厂商提示词指南收敛的槽位顺序组织
（主体 · 动作 · 场景 · 镜头取景与运动 · 光线 · 风格 · 音频 · 约束），复用 Asset Matcher
已经打过分的素材引用（低于分数下限的引用会被丢弃），并把 storyboard 帧上的负面提示与常备
规则合并。

## provider 与时长约束

单次生成的时长上限远小于整片，所以一份分镜必然返回 N 个片段，需要 `--concat` 用 FFmpeg 合流。

| provider | 模型 | 单次时长 | 画幅 |
|---|---|---|---|
| `doubao` | Seedance（豆包） | 默认 5 或 10 秒；其它型号用 `DOUBAO_VIDEO_DURATIONS` 声明范围或列表 | 由 `--ratio` 传入 |
| `ali` | 通义万相 Wan | 2–15 秒 | wan2.7 用 `resolution`+`ratio`；2.6 及更早用 `size`（`ALI_VIDEO_PROTOCOL` 切换，`auto` 从模型名推断）|
| `vertex` | Google Veo 3.1 | 仅 4 / 6 / 8 秒 | **仅 16:9 与 9:16**，其它比例会被强制为 16:9 |

分镜里写的 `duration` 会被自动 clamp 到 provider 允许的值，不会报错。

## 环境变量

见 `.env.example` 的「AI video models on the company gateway」段落。三家各自一组
`*_BASE_URL` / `*_API_KEY` / `*_MODEL`；未设置 `*_API_KEY` 时会回退到共享的
`AI_GATEWAY_API_KEY`，避免同一把 key 在 `.env` 里抄三遍。

**Vertex 需要真实的 GCP project id**，它是计费身份而非标签 —— 随便编一个名字会返回
`403 PERMISSION_DENIED / CONSUMER_INVALID`。解析顺序：

1. `VERTEX_VIDEO_PROJECT`
2. `GOOGLE_CLOUD_PROJECT` / `GCLOUD_PROJECT`
3. storyboard 或同目录 `BRIEF.md` 的 frontmatter（`vertex_project` / `gcp_project` /
   `google_cloud_project` / `project_id`）
4. `gcloud config get-value project`

设一次即可，之后不需要任何命令行参数。或用 `VERTEX_VIDEO_MODEL_PATH` 直接钉死完整资源路径。

## 常用开关

- `--frames 2,4` —— 只生成这几帧，无条件生成
- `--style "35mm 胶片质感"` —— 追加到每条提示词末尾的全局风格
- `--include-voiceover` —— 把旁白也喂进提示词（默认不喂，旁白是时间参考不是画面描述）
- `--seed 42` —— 固定随机种子，便于复现
- `--resolution 720p` —— 降分辨率试样，省时间和费用
- `--generate-audio` —— 请求模型自带音轨（provider 支持时）
- `--watermark` —— 保留 provider 水印（默认去除）

产物落在 `<storyboard 目录>/renders/ai-clips/<provider>/`：编号片段、`manifest.json`
（含每一帧的 provider、模型、状态），`--concat` 时的 `full.mp4`。

## 混排必须在 FFmpeg 层

`render: mixed` 项目里，动效镜头（HTML）与写实镜头（T2V）并存时，**在 FFmpeg 层合流，
不要把 T2V 片段当 `<video>` 塞进 HTML 合成。** 原因：Chrome 无法同时 seek 多个 `<video>`
（解码器耗尽），视频密集的合成会退化为单 worker 甚至超时。另外 `<video>` 必须是
`index.html` 根的直接子元素，放进 sub-composition 会渲染黑屏（Rule Guard § 7 检查的
正是这条）。

## 提示词的构造方式

`T2V-PROMPTS.md` 的每帧提示词只取画面相关信息，刻意丢弃 `blueprint`、`roles`、`sfx`、
`src`、`transition_in` —— 这些描述的是 HTML 合成的实现方式，对文生视频模型是噪声。
若 `T2V-PROMPTS.md` 缺失，`storyboard.build_prompt()` 是更简单的回落：只读
`scene`/`narrativeRole`/`keyMessage`/`beat`/全局 `message`，帧正文（HF 的时间编码分镜
序列，含 GSAP 规则名）从不读取，`scene:` 缺失时回落到帧标题而不是正文。

需要排除的元素写在帧上：

```markdown
- negative_prompt: 文字, 水印, 变形的手
```
