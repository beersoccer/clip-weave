# AI 视频模型接入（公司网关）

`python -m clip_weave gen-video` 以 `STORYBOARD.md` 为输入，每个 Frame 生成一个视频片段。
三个模型都是「提交任务 → 轮询 → 下载」的异步协议，只是协议方言不同。

| provider | 网关地址（**http**，非 https） | 上游协议 | 默认模型 | 实测 |
|---|---|---|---|---|
| `doubao` | `http://aigateway.t1.test.noahgrouptest.com/doubaovideo` | 火山方舟 Ark content generation | `doubao-seedance-1-0-pro-250528` | ✅ 480p/5s 约 32s 出片 |
| `ali` | `http://aigateway.t1.test.noahgrouptest.com/alivideo` | 阿里百炼 DashScope 异步 video-synthesis | `wan2.5-t2v-preview` | ✅ 480p/5s 约 104s 出片 |
| `vertex` | `http://aigateway.t1.test.noahgrouptest.sg/vertexvideo` | Vertex AI `predictLongRunning` | `veo-3.1-generate-001` | ⚠️ 路由与鉴权已通，缺 GCP project |

网关只监听 **http**（https 会 TLS 握手失败），且三条路由共用同一把网关 key——
代码按 `<PROVIDER>_VIDEO_API_KEY` → `AI_GATEWAY_API_KEY` → `GEMINI_API_KEY` 依次回退，
所以现有 `.env` 不改也能直接用。

## 验证

```bash
# 只验路由 + 鉴权，不建任务、不花钱（故意发非法 body，期望上游返回 400）
uv run python scripts/verify_video_gateway.py --probe

# 全链路：提交 → 轮询 → 下载（480p / 5s，会产生费用）
uv run python scripts/verify_video_gateway.py --provider doubao --provider ali
```

## 用法

```bash
cp .env.example .env      # 已有网关 key 时无需重复填写

# 先看提示词（不发请求、不花钱）
uv run python -m clip_weave gen-video videos/xiaomi-su7-promo/STORYBOARD.md \
  --provider doubao --dry-run

# 正式生成（默认输出到 <storyboard 同级>/renders/ai-clips/<provider>/）
uv run python -m clip_weave gen-video videos/xiaomi-su7-promo/STORYBOARD.md \
  --provider doubao --resolution 720p --frames 1,2 --generate-audio
```

常用参数：`--frames 1,3`（只做指定帧）、`--duration`（覆盖帧时长）、`--ratio`、
`--resolution`、`--style "cinematic, dark, 35mm"`、`--seed`、`--include-voiceover`
（把 `voiceover` 也写进提示词，注意模型可能把台词渲染成画面文字）、
`--poll-interval` / `--max-wait`。

输出目录里除 mp4 外还有 `manifest.json`，记录每帧的提示词、task_id、耗时、失败原因。

## 提示词是怎么来的

`core/storyboard.py` 解析 storyboard 的 frontmatter 与每个 `## Frame N` 段落，然后取
`scene` + `narrativeRole` + `keyMessage` + `beat` + 全局 `message` 拼成一句提示词。
`blueprint` / `roles` / `sfx` / `src` / GSAP Scene 描述**不进提示词**——那些是 HTML 合成
的动效说明，对生成式视频模型是噪声。

## 三个协议的关键差异

**豆包 / Seedance（Ark）** — `POST {base}/api/v3/contents/generations/tasks`，
body 为 `{model, content:[{type:"text",text},{type:"image_url",…}], resolution, ratio, duration}`，
返回 `{"id": "cgt-…"}`；`GET …/tasks/{id}` 的 `status` 走
`queued → running → succeeded`，成功后取 `content.video_url`（24 小时内有效）。
时长可选值随模型不同（Seedance 1.0 只接受 5 / 10 秒，1.5 与 2.0 接受 4–15 秒），
用 `DOUBAO_VIDEO_DURATIONS=5,10` 或 `=4-15` 声明，代码会把 storyboard 的帧时长
就近对齐到合法值。
参考：[Seedance API 说明](https://apidog.com/blog/seedance-2-0-api/)。

**阿里万相（DashScope）** — `POST {base}/api/v1/services/aigc/video-generation/video-synthesis`，
**必须**带 `X-DashScope-Async: enable`，否则报 "does not support synchronous calls"；
返回 `output.task_id`，`GET {base}/api/v1/tasks/{task_id}` 的 `output.task_status` 走
`PENDING → RUNNING → SUCCEEDED`，成功后取 `output.video_url`（24 小时有效）。
分辨率有两种方言：wan2.7 用 `parameters.resolution` + `parameters.ratio`，
wan2.6 及更早用 `parameters.size`（如 `1280*720`）——由 `ALI_VIDEO_PROTOCOL` 控制，
默认 `auto` 按模型名推断。
参考：[阿里云百炼 文生视频 API](https://help.aliyun.com/en/model-studio/text-to-video-api-reference)。

**Veo（Vertex AI）** — `POST {base}/v1/{model_path}:predictLongRunning`，
body 为 `{instances:[{prompt}], parameters:{aspectRatio, durationSeconds, resolution, sampleCount, generateAudio}}`，
返回 `{"name": "…/operations/…"}`；轮询用
`POST {base}/v1/{model_path}:fetchPredictOperation`，body `{"operationName": …}`，
`done: true` 后视频在 `response.videos[0]`，可能是 `gcsUri` 也可能是 `bytesBase64Encoded`
（两种都已支持）。`model_path` 默认取网关常见的 `publishers/google/models/<model>`，
需要原生 Vertex 形态时设 `VERTEX_VIDEO_PROJECT` + `VERTEX_VIDEO_LOCATION`，
或直接用 `VERTEX_VIDEO_MODEL_PATH` 覆盖。
参考：[Vertex AI predictLongRunning](https://cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints/predictLongRunning)、
[网关形态的完整示例](https://docs.zenmux.ai/api/vertexai/generate-videos.html)。

上述外部文档内容均已改写以符合授权要求（Content was rephrased for compliance with
licensing restrictions）。

## 关于网关路径

代码默认「网关前缀 + 上游原始路径」。如果网关做了路径改写，不用改代码，用环境变量即可：
`DOUBAO_VIDEO_TASKS_PATH`、`ALI_VIDEO_SUBMIT_PATH` / `ALI_VIDEO_TASK_PATH`、
`VERTEX_VIDEO_API_VERSION` / `VERTEX_VIDEO_MODEL_PATH`。

实测结论（用 `.env` 里的测试环境 key）：

- 网关**保留上游原始路径**，前缀之外一律照传。少一层或多一层都是 404，例如
  `/doubaovideo/v3/...`、`/alivideo/services/...`、`/vertexvideo/publishers/...` 全部 404。
- 报错体也是上游原样返回：豆包是 Ark 的 `{"error":{"code":"MissingParameter",…}}`，
  阿里是 DashScope 的 `{"code":"BadRequest.EmptyModel",…}`，Vertex 是 Google 的
  `google.rpc.ErrorInfo`。这点很好用——`--probe` 就是靠它区分「路径对但参数不对(400)」
  和「路径错(404)」。
- 豆包、阿里已跑通完整链路并下载到真实 mp4（各约 2.4 MB）。
- Vertex 还差一项：`publishers/google/models/<model>` 这种精简路径会被
  Vertex 判成 `RESOURCE_PROJECT_INVALID`，说明网关是**原样透传**、不注入 project。
  需要网关背后那个 GCP project id，然后设
  `VERTEX_VIDEO_PROJECT` + `VERTEX_VIDEO_LOCATION`（代码会拼成
  `projects/{p}/locations/{l}/publishers/google/models/{model}`），
  或直接用 `VERTEX_VIDEO_MODEL_PATH` 指定完整资源路径。
  用 `projects/-` 试过，返回 `PERMISSION_DENIED / CONSUMER_INVALID`，
  网关上也没有可列模型的 discovery 接口，所以这个 id 只能问网关维护方。

Veo 3.1 的官方约束（会影响参数取值）：模型 ID 为 `veo-3.1-generate-001` /
`veo-3.1-fast-generate-001` / `veo-3.1-lite-generate-001`；目前只在 **us-central1** 提供；
时长只能 4 / 6 / 8 秒；画幅只支持 16:9 与 9:16；分辨率 720p / 1080p（部分支持 4K）。
代码已按此对齐：时长就近取 4/6/8，非 16:9/9:16 的画幅自动回落到 16:9，
`VERTEX_VIDEO_LOCATION` 默认 `us-central1`。
另外 `parameters.storageUri` 不设时，视频以 `bytesBase64Encoded` 内联返回（代码两种都收）。
参考：[Veo 3.1 模型页](https://cloud.google.com/vertex-ai/generative-ai/docs/models/veo/3-1-generate)、
[endpoints.predictLongRunning 参考](https://cloud.google.com/vertex-ai/generative-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/predictLongRunning)。

## 时长上限与拼接

三家单次生成都远短于一条完整片子,所以「一帧一段 + 拼接」是必经之路,不是变通:

| 模型 | 单次生成 | 续接(extend) |
|---|---|---|
| Veo 3.1 | **4 / 6 / 8 秒**(reference-image-to-video 只支持 8 秒) | 支持,每次固定 **+7 秒**;输入视频必须 1–30 秒、24fps、16:9 或 9:16 |
| Seedance(豆包) | 5 / 10 秒(1.5、2.0 为 4–15 秒) | 用 `return_last_frame` 取末帧再作为下一段首帧 |
| Wan(阿里) | 2–15 秒(随模型不同,wan2.2 固定 5 秒) | 无原生 extend |

Veo 的续接链条实际上到 ~29 秒就走不动了:每次只加 7 秒,而输入又必须 ≤30 秒,
所以 8 → 15 → 22 → 29 之后无法再喂回去。**要做 30 秒以上,只能自己拼。**

`gen-video --concat` 就是干这个的:按 Frame 顺序用 ffmpeg concat 把片段合成
`full.mp4`(需要本机有 ffmpeg)。

```bash
uv run python -m clip_weave gen-video videos/xxx/STORYBOARD.md \
  --provider doubao --concat
```

参考:[Veo extend 文档](https://cloud.google.com/vertex-ai/generative-ai/docs/video/extend-a-veo-video)、
[Veo 视频生成概览](https://cloud.google.com/vertex-ai/generative-ai/docs/video/overview)。

## Vertex 的 project 怎么来

**它不是视频项目名,是 GCP 项目 ID**——Vertex 用它做鉴权与计费主体,随便编一个会被
拒(实测 `projects/-` → `403 PERMISSION_DENIED / CONSUMER_INVALID`),所以没法按
storyboard 自动生成。能做的是「只配一次、之后不用再指定」,解析顺序:

1. `VERTEX_VIDEO_PROJECT` 环境变量
2. `GOOGLE_CLOUD_PROJECT` / `GCLOUD_PROJECT`(Google SDK 通用约定)
3. storyboard 的 frontmatter,或它同目录的 `BRIEF.md`——键名任一:
   `vertex_project` / `gcp_project` / `google_cloud_project` / `project_id`
4. 本机 `gcloud config get-value project`

所以团队级放 `.env`,某条片子要走别的项目就写进那条片子的 `BRIEF.md`:

```yaml
---
project: su7-launch          # HF 的视频项目名,与下面无关
vertex_project: noah-ai-xxx  # GCP 项目 ID,Vertex 用
---
```

命令行永远不需要传这个参数。取到的值不像 GCP project id 时会打 warning
(避免有人把视频项目名填进去),完全取不到时报错并说明该去哪配。

### 拿到 project id 之后的实测(2026-07-31)

运维给的 `ai-manger-dept` 是对的,project 这一关已经过了,但卡在下一关:**Veo 模型对
该项目不可见**。

| 请求 | 结果 |
|---|---|
| project = `no-such-project-zzz9` | 403 `CONSUMER_INVALID` |
| project = `ai-manager-dept`(manager 拼写) | 403 `CONSUMER_INVALID` |
| project = `ai-manger-dept` + `gemini-2.5-flash:generateContent` | **200,正常返回文本** |
| project = `ai-manger-dept` + 任意 veo 模型 | 404 `Publisher model … was not found or your project does not have access to it` |

第三行很关键:同一条 `/vertexvideo` 路由、同一把 key、同一个 project 调 Gemini 能通,
说明路由、鉴权、project 三者都没问题,**唯一缺的是 Veo 模型本身的开通/白名单**。

已穷举过的模型名(us-central1 / global / us-east4 三个 region 各试一遍,全部 404):
`veo-3.1-generate-001`、`veo-3.1-fast-generate-001`、`veo-3.1-lite-generate-001`、
`veo-3.0-generate-001`、`veo-3.0-fast-generate-001`、`veo-2.0-generate-001`,
以及 `-preview` / `-exp` 后缀的六个变体。`GET …/publishers/google/models` 列表接口在
网关上是 404,查不到该项目实际可用的模型清单。

探测技巧:探 Veo 时用 `{"instances":[{"prompt":"probe"}],"parameters":{"durationSeconds":3}}`
—— 3 秒对所有 Veo 都是非法值,所以模型若真的可用会返回 400 参数错误而**不会真正起任务**;
而 `{"instances":[]}` 会先被 "Empty instances" 挡掉、根本走不到模型查找那一步(会误判成通)。
`--probe` 已按前者实现。

### asia-southeast1 复测(2026-07-31)

按运维建议把 location 换成 `asia-southeast1`(已写入 `.env`),结论不变:

- **12 个标准 Veo 模型名 + 7 个简写别名(`veo`、`veo-3`、`veo-3.1`、`veo-3.1-generate` …)
  全部 404** `Publisher model … was not found or your project does not have access to it`。
- 同一 project、同一路由、同一 key 调 `gemini-2.5-flash:generateContent`,在
  `asia-southeast1` / `global` / `us-central1` 三个 region **都是 200**。

所以 region 不是原因(该 region 对这个项目是通的),Veo 模型确实没有对
`ai-manger-dept` 开通。另外按官方文档,Veo 3.1 目前**只在 us-central1** 提供服务,
所以即便开通,也需要确认它在 asia-southeast1 是否可用。

排查小坑:被复用的 shell 里如果早先 `export` 过 `VERTEX_VIDEO_LOCATION`,
`load_dotenv()` 默认**不覆盖**已存在的环境变量,`.env` 的改动会被静默忽略。
换新 shell 或 `env -u VERTEX_VIDEO_LOCATION …` 再跑。

## T2V 提示词:复用 HF 产出物,不重新分析

提示词不再由代码即时拼接,而是落成 storyboard 同级的 `T2V-PROMPTS.md`,可编辑、可下载、
可回传。首次运行生成,之后以该文件为准:

```bash
# 只生成/刷新提示词文件,不调模型、不花钱
uv run python -m clip_weave gen-video videos/xxx/STORYBOARD.md --provider doubao --prompts-only

# 编辑 T2V-PROMPTS.md 后直接跑,以文件为准
uv run python -m clip_weave gen-video videos/xxx/STORYBOARD.md --provider doubao

# 丢弃手工编辑、从 STORYBOARD.md 重新生成
uv run python -m clip_weave gen-video videos/xxx/STORYBOARD.md --provider doubao --regenerate-prompts
```

### 槽位顺序与来源

顺序取各厂商指南的共识:**主体 · 动作 · 场景 · 镜头 · 光线/风格 · 音频 · 负面约束**,
每段一个场景、一个主镜头运动,长度控制在 30–200 词。

| 槽位 | 来自 HF 的哪个产出物 |
|---|---|
| subject / action | 帧的 `keyMessage`、`narrativeRole` |
| scene | 帧的 `scene` + 该帧焦点素材的描述 |
| camera | 帧叙事里的镜头动词 + 全局 `Motion grammar`(push-in → slow dolly-in 等) |
| lighting_style | 全局 `Palette`(自动提取十六进制色值)+ `Motion grammar` |
| audio | 帧的 `sfx`;`voiceover` 仅在 `--include-voiceover` 时进入 |
| negative | 全局 `Negative list` + 固定的文字/UI/水印排除项 |
| reference | 帧的 `focal:` / `asset_candidates`(Asset Matcher 已有结论,不重跑) |

HF 的动效实现词汇(`gsap-effects`、`spring-pop-entrance`、反引号里的类名)会被剥掉。
以图文/数据为主的帧会被标 `needs_review: true` —— 视频模型渲染文字不可靠,这类帧建议
留在 HTML 路径。

参考(内容均已改写以符合授权要求):
[Google DeepMind Veo 提示词指南](https://deepmind.google/models/veo/prompt-guide/)、
[Runway Academy prompting guide](https://academy.runwayml.com/guides/prompting-guide)、
[阿里云百炼文生视频 API(negative_prompt / prompt_extend)](https://help.aliyun.com/en/model-studio/text-to-video-api-reference)。

## 素材:复用 storyboard 的结论 + 质量下限

每帧写入 **top-3** 候选(检索取 top-5,写前 3),格式带分数:

```
- asset_candidates: 20-1.png (0.61) — 蛟龙底盘俯视图；v6s-plus.png (0.42) — 超级电机
```

新增**匹配度下限**:低于阈值的候选直接丢弃,该帧宁可没有候选,也不给一个"最不差"的错
素材 —— 因为 T2V 会忠实地把错素材画出来。默认 0.35(embedding 余弦)/ 0.30(BM25),
用 `ASSET_MIN_SCORE` 覆盖,单次调用可传 `min_score`。

## 走 HTML 还是 T2V:用户决定

- 项目级:`BRIEF.md` frontmatter 的 `render: html | t2v | mixed`
- 帧级:`STORYBOARD.md` 帧上的 `visual_type: motion | live_action`

`run` 命令在未指定时会问一次并把答案写进 BRIEF.md(之后不再问,改那一行即可切换):

```bash
uv run python -m clip_weave run --message "..." --project x            # 交互询问
uv run python -m clip_weave run --message "..." --project x --render t2v  # 直接指定
```

默认 html —— 确定性、可复现、无推理费用,且是唯一能把精确文字/品牌色/数据图表画对的
路径。若 BRIEF.md 写的是 html 而又去跑 `gen-video`,会先提示确认(`--yes` 跳过)。
