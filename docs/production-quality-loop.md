# 生产级视频质量系统

> 产品承诺：非专业用户用一句需求启动创作，提供业务事实、授权素材和少量品牌偏好；系统负责把专业制作判断、生成、返工和质量检查编排为可恢复的生产流程。用户只在高杠杆的业务与品牌决策点确认，不需要写 prompt、选择模型参数、判断转场或做技术 QC。

> 适用范围：“发布级”承诺只适用于已支持的品类和已批准的品牌/制作 recipe，例如产品功能发布、录屏演示、数据叙事、官网素材改编和既有品牌模板。首次制作、缺少真实素材或要求强原创电影感的项目交付为可审片候选，不承诺首次生成即达到定制广告片质量。

> 状态：本文是目标架构和实施顺序。当前实现边界以 [architecture.md](architecture.md) 为准；各阶段完成前不得将本文中的能力描述为已上线。

## 1. 成功定义与非目标

### 1.1 什么叫“低门槛高质量”

低门槛不等于省略制作步骤，而是把步骤、专业判断和返工成本从用户界面移到受控的生产系统中。用户的最短路径是：

    一句需求 + 事实/素材/授权
      → 方向与 hero look 的少量确认（首次品牌或低置信度时）
      → Agent 自主生产、审片与局部返工
      → 用户确认发布

系统达标必须同时满足：

- 关键产品、人物、品牌和事实均可追溯到已确认来源。
- 文字、logo、价格、UI 与 CTA 由确定性层渲染，不依赖视频模型生成。
- 一次失败只重做关联镜头，已批准的镜头和关键帧不被覆盖。
- 成片经技术、镜头、接缝、全片和真实播放五层检查。
- 已批准 recipe 的下一次生产能自动复用品牌、节奏、素材策略与检查策略。

### 1.2 非目标

- 不承诺任意一句话、任意题材在第一次生成就等同于人工定制广告片。
- 不把普通用户变成剪辑师、提示词工程师或视频质检员。
- 不把任意 T2V 输出当作可信的产品 UI、品牌文字、人物身份或业务事实。
- 不把 OpenClaw、Hermes 或开源研究项目整体接入为运行时后端。
- 不在 P0--P4 阶段实现任意镜头的 HTML/T2V 自由混排编辑器。

## 2. 用户决策边界

用户只做业务和品牌决定；Agent 做所有制作专业决定。系统不得把模型、镜头运动、转场、音画同步、参数表或长 QC 清单抛给用户。

| 节点 | Agent 默认行为 | 仅升级给用户的情况 | 用户看到的内容 |
| --- | --- | --- | --- |
| 需求理解 | 补全受众、渠道、时长、主张并推荐 Production Profile | 缺失信息会改变事实承诺、价格、合规或发布目标 | 一个简短确认卡，不是 prompt 表单 |
| 首次创意 | 产生 2--3 个方向和推荐项 | 新品牌、无已批准 recipe，或方向存在等价的业务含义差异 | 每项的一句话主张、叙事骨架和 hero look 候选 |
| 品牌/主体锁定 | 生成、排序关键帧候选并做 Reference Audit | 人物、产品、品牌视觉身份首次出现；或置信度低 | 2--3 个候选和推荐理由 |
| 生成与返工 | 固定 production contract，局部重试、QC、锁定通过版本 | 必需参考无法提交；必须跨模型/供应商；连续失败超过预算 | 问题、影响、推荐降级和成本/时延 |
| 最终审片 | 自动完成技术与视觉预审 | 发布、事实声明、权利和最终品牌批准 | 完整成片、简短质量结论和已知限制 |

已有批准 recipe 时，系统可跳过首次创意和 hero look 选择，除非输入违反 recipe 的必需约束。此时“一句话启动”才是稳定且可重复的体验。

## 3. 生产边界：两条生产链，一个确定性完成层

项目在创建时选择一个 Production Profile，由 Agent 推荐并说明理由；用户不需要理解渲染引擎。项目级路径固定，所有生成任务和 QC 按该路径执行。

| Profile | 适用内容 | 主体画面 | 确定性完成层 |
| --- | --- | --- | --- |
| html_launch | 功能发布、数据叙事、UI/录屏演示、价格/CTA 强约束内容 | HyperFrames HTML、GSAP、真实录屏、获授权图片或视频 | HyperFrames 负责精确文字、logo、图表、字幕、音频、转场与渲染 |
| t2v_brand_film | 写实产品运动、人物、实景或难以拍摄的电影化镜头 | T2I 锁定关键帧后 I2V 的逐镜头片段 | FFmpeg 完成确定性 logo、价格、UI、CTA、字幕和音频总装配 |

这里的“确定性完成层”不是按镜头任意混排：

- html_launch 可以使用真实录屏、官方 B-roll 或用户授权媒体，但不提交 T2V 生成任务；视频媒体遵守 HyperFrames 的根时间线与 seek 约束。
- t2v_brand_film 不把未完成的生成任务嵌进 HyperFrames；所有已批准片段先规格归一化，再由 FFmpeg 叠加确定性品牌层。
- 同一视觉段固定供应商、模型、画幅、分辨率与 contract。跨供应商或模型是受控降级，不是自动“换一个试试”。

这避免了生成式媒体生命周期与 HTML 合成耦合，同时保留真实素材和确定性品牌表达所必需的完成能力。

## 4. 生产契约与可追溯状态

当前实现是单项目账本 `renders/production-contract.json`：每次正式决策点追加一份完整、不可覆盖的快照，默认读取当前版本，并可按 revision 追溯历史。账本冻结 Creative Contract、Facts Source、Reference Audit、Shot Card、Cue Sheet 和 Review Decision 六类对象。Agent 草稿不落盘；当前不为每个对象单独建文件，也不提供事件回放。

任务未来应钉扎 contract_revision；当前尚未接入 submit 或 manifest。因此，以下各对象的生产链接入、供应商任务追溯和完整质量流程仍是目标架构，不能视为当前已实现能力。

### 4.1 Creative Contract

任何生成前必须创建并版本化以下事实：contract version、Production Profile、受众、平台、目标时长、叙事承诺、视觉层级、色彩/材质、镜头/节奏、声音/字幕方向、必须保留项、禁止项、事实来源和 proof media 策略。

Creative Contract 是全片共享的 style bible，不是给模型的一段自由文本。

### 4.2 Facts、Proof Media 与 Reference Audit

- Facts Source 记录已批准的价格、产品规格、CTA、法律声明和来源 URL/文档；未确认事实不得进入旁白或画面。
- Proof Media 记录官网捕获、产品 B-roll、屏幕录制、演示录制、人物素材及授权状态。产品功能、UI 和实际行为优先由这些证据媒体展示，而不是由生成模型伪造。
- 每个镜头的 Reference Audit 记录产品、人物、场景、风格、首帧、末帧与 proof media 的 required、requested、submitted、dropped 和原因。
- 本地参考提交前必须物化为 provider 可读取的 URI；仅记录本地路径视为提交失败。必需参考被 provider 丢弃时必须停止并升级，不得静默退为无参考生成。

### 4.3 Shot Card 与 Beat/Cue Sheet

每个 T2V 镜头使用结构化 Shot Card，而不是单段自然语言 prompt。最小字段包括：镜头目的、锁定主体、单一动作、场景、空间关系、机位、光线、首帧、可选末帧、必须保留项、禁止项和时长。

旁白或音乐确认后，两条路径都必须建立 Cue Sheet：镜头出入点、VO 句/词、SFX、字幕、CTA、转场和 hold 的绝对时间。它使音画同步成为可检查数据，而不是审美猜测。

### 4.4 Review Decision 与 Job Ledger

每个候选和版本的 Review Decision 必须记录状态 accepted、revise 或 rejected，以及原因、评分、置信度、审阅者、审阅时间和锁定版本。

昂贵的异步任务必须从第一次 submit 前就写入原子 Job Ledger。每条记录至少包含：

    shot_id + stage + run_id + provider_task_id
    + contract_version + prompt_version + reference_version
    + idempotency_key + requested_parameters + applied_parameters
    + state + attempts + error_class + artifact_hash

submit、poll 状态变化、下载、QC 和批准决定均立即落盘。进程重启后只能 resume、status 或 retry 现有任务；429、5xx 和网络超时可退避重试，审核拒绝、不支持参数和明确终态失败不可盲目重试。

## 5. 可执行生产流程

### 5.1 html_launch

    需求 + 事实/品牌/证据媒体
      → Creative Contract + 方向推荐
      → 可选 hero look 确认 + Storyboard/线框
      → Proof Media/录屏准备 + narration/BGM/SFX
      → Cue Sheet（真实 word timing 优先）
      → HyperFrames assembly、字幕与接缝设计
      → lint + full check + contact sheet + 真实 render 审片
      → 局部修复 → 成片预览 → 发布批准

HyperFrames 继续拥有 HTML 动画、媒体 seek、lint/check 和渲染。clip-weave 负责 production contract、素材证据、cue、质量 gate 和交付决策，不重造 HyperFrames。

### 5.2 t2v_brand_film

    需求 + 事实/品牌/参考/证据媒体
      → Creative Contract + 全片 Storyboard
      → Shot Card + Reference Audit + Cue Sheet
      → 每镜头 T2I 关键帧候选
      → Agent 初筛；hero/低置信度关键帧才升级用户
      → 锁定首帧（可选末帧）并提交 I2V
      → 单镜头 QC → 接缝 QC → 仅重做失败镜头
      → 片段规格归一化 + FFmpeg 合成
      → 确定性文字/logo/UI/CTA overlay + 配音/BGM/SFX/字幕
      → 完整成片真实播放审片 → 发布批准

纯文本 T2V 仅作为无身份敏感主体、无可用关键帧且用户明确接受的降级路径。所有降级必须写入 Job Ledger 和最终审片结论。

## 6. 五层质量 Gate

自动评分只能做初筛、解释和排序；它不能替用户确认事实、权利或最终发布，也不能在无参考的首次创意中承诺“导演感”。

| Gate | 检查对象 | 必须保存的证据 | 失败动作 |
| --- | --- | --- | --- |
| G0 Preflight | capabilities、事实、授权、参考可提交性、预算 | applied/requested 参数、Reference Audit | 停止或请求业务/授权决定 |
| G1 Asset/Candidate | T2I 关键帧、录屏、音频、下载完整性 | 候选缩略图、hash、评分、置信度 | 同一 contract 内产生局部变体 |
| G2 Shot | 单镜头身份、构图、动作、文字伪影、技术规格 | ffprobe、关键帧、rubric 结果 | 仅重做该镜头 |
| G3 Seam | 相邻镜头的主体、方向、光线、景别、节奏、音画 cue | 边界前后帧、短片段、cue 偏差 | 调整相邻镜头或转场，不覆盖已锁定资产 |
| G4 Film | hook、叙事、信息密度、字幕、安全区、品牌一致性、真实播放 | contact sheet、1x 实际 render、音频/字幕检查、结论 | 定向修复后重新运行相关 Gate |

G4 必须基于真实 render，而不是仅依赖 snapshot：运动、视频帧、音画、嘴型和转场在 seek/snapshot 中可能不成立。对于已有 recipe，G4 还要与其 golden baseline 比较：时长范围、镜头密度、字幕策略、关键帧构图、接缝策略和品牌 token 都可检查。

## 7. Recipe：把第一次的专业判断变成下一次的默认值

通过发布批准后，系统冻结版本化 Production Recipe：Creative Contract、Production Profile、叙事骨架、Shot Card/Storyboard 模板、proof media 策略、品牌 token、overlay/字幕规则、Cue Sheet 模板、golden baseline、已批准决策及来源。

新项目匹配 recipe 后自动填充推荐 profile、风格、镜头骨架、素材优先级和质量检查；若品牌主体、事实来源、时长档位或必需约束变化，则只升级受影响的确认点。recipe 是低门槛可复用的基础，不是一次性 prompt 缓存。

## 8. 分阶段实施与上线门槛

实现顺序以“先不重复扣费、再做昂贵生成、最后扩大自动性”为原则。

### P0：边界收敛与当前实现对齐

- 删除 frame-level render 覆盖和混排语义；BRIEF.md 只持久化一个 Production Profile。
- 定义并测试 HTML 真实媒体挂载、T2V FFmpeg 确定性完成层的边界。
- 更新 CLI、README、architecture、测试和示例，避免文档与 render_path.py 的语义相互矛盾。

上线门槛：任意新项目只有一个主生产链；路径选择、完成层和用户可见解释一致。

### P1：昂贵任务前的可靠基础

- 实现 Creative Contract、Facts Source、Proof Media、Reference Audit、Shot Card、Cue Sheet、Review Decision 的版本化 schema。
- 实现原子 Job Ledger、幂等 submit、状态恢复、分类重试、artifact hash 与 applied/requested 参数审计。
- 实现 provider capabilities registry、参考上传/物化和 preflight。

上线门槛：在 submit、poll、下载或进程重启的任一点中断后，都能恢复且不会重复扣费；必需参考不可提交时生成不会开始。

### P2：HTML 发布视频闭环

- 将 Proof Media/录屏、真实 narration timing、Cue Sheet 和 HyperFrames 生产 loop 接通。
- 在 render 前运行 full check，在 render 后运行 G3/G4 证据采集与结论生成。
- 支持首次方向/hero look 确认与最终发布确认，其他制作判断保持自动。

上线门槛：对支持的录屏演示、数据叙事和功能发布场景，能从一次需求完成可追溯成片与最少两次用户确认。

### P3：T2I → I2V 镜头闭环

- 接入 provider-neutral T2I adapter 与 I2V adapter；先支持单镜头首帧，末帧/多视图仅在 capability 声明支持时启用。
- 实现候选初筛、锁定、单镜头/接缝 QC、局部变体和规格归一化。
- 实现 FFmpeg 的确定性 overlay、音频与字幕总装配。

上线门槛：失败镜头可局部恢复/重做；已批准镜头不会被自动替换；全片没有依赖视频模型生成的关键文字或 logo。

### P4：质量评估与 recipe Golden Baseline

- 落地 G0--G4 rubrics、证据包、置信度阈值和升级规则。
- 为每个支持品类建立人工批准的 benchmark/recipe，记录可接受的节奏、构图、字幕、转场和真实播放标准。
- 用历史成片做回归评估，保证系统升级不静默降低已批准 recipe 的质量。

上线门槛：每次交付都能说明通过了哪些 gate、哪些风险被降级、与 recipe baseline 的差异是什么。

### P5：低门槛复用与运营化

- Recipe 匹配、版本/来源/回滚、成本和时延预算、失败升级说明。
- 将用户界面收敛为“推荐 + 少量候选 + 清楚取舍”，不暴露生产参数。

上线门槛：已有 recipe 的同类项目能从一句需求自动启动，用户只需确认业务事实、必要素材和发布。

## 9. 研究来源与演进记录

以下研究保留用于理解设计来源；它们提供模式，不是运行时依赖或代码复制来源。

| 来源 | 已吸收的原则 | 明确不吸收 |
| --- | --- | --- |
| HyperFrames production loop 与官方样例 | storyboard/线框/final-look gate、真实媒体、word timing、接缝、完整项目验证、recipe | 强迫普通用户理解 composition、GSAP 或技术检查 |
| Timeline Launch 样例 | 真实产品录屏、Cue Sheet、SFX 对齐、原型迭代、匹配接缝和明确 hold | 将单个手工项目的固定坐标/动画直接泛化为产品逻辑 |
| HeyGen × Stripe 样例 | 参考成片对齐、分版本 render、音频重组、媒体时间连续性、真实 render 抽帧审片 | 把某一品牌视觉或 AE 成片复制为默认风格 |
| Hermes / OpenClaw | capability 预检、异步任务恢复、状态记录、分类重试、交付 QC | 作为创作质量运行时后端 |
| AdCraft、ViMax、VideoAgent、OpenMontage | 参考审计、资产身份、关键帧→I2V、镜头依赖、提案—批准—批量生产 | 复制 GPL/AGPL 代码、整套 agent runtime 或未经验证的自动选优器 |
| Hermes Manim checklist | 安全区、可读性、色彩语义、节奏、图表正确性与 1x 审片 | 固定字体/坐标或 Manim 专用限制 |

GPL/AGPL 项目仅借鉴公开架构和行为；除非产品主动接受相应 copyleft 义务，不复制其代码。MIT 项目也只在维护成本和接口适配合理时选择性复用。

## 10. 最终验收标准

- 用户不需要编写 prompt、选择 provider 参数或执行专业 QC。
- 首次品牌项目最多要求方向/hero look 与发布两类确认；已有 recipe 时只升级事实、授权、例外和发布。
- 每个项目固定一个主 Production Profile，并且有明确的确定性完成层边界。
- 任一最终镜头可追溯到事实、contract、参考、proof media、关键帧、provider 任务、QC 证据和批准版本。
- 任一失败镜头可以恢复或局部重做，不能覆盖已批准版本或重复扣费。
- 成片通过 G0--G4；所有降级、未解决风险和最终发布权限均可见。
- 对受支持品类，已批准 recipe 的新项目可从一句需求启动并稳定复用经验证的质量基线。
