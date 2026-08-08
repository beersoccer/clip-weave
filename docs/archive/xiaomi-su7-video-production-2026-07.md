# 小米 SU7 视频生产复盘（历史案例，2026-07）

> 这是单个项目的经验记录，含当时的模型和成本假设；不作为通用生产流程。通用原则已收敛到[生产质量流程](../production-quality-loop.md)。

> 项目路径：`videos/xiaomi-su7-promo/`  
> 框架：HyperFrames 0.7.68 · 规格：1920×1080 / 30s / 16:9  
> 定位：本文记录实验过程、质量提升原因和项目特有结论，HF 通用知识见 `docs/hyperframes-analysis.md`

---

## 一、v1 → v2 效果大幅提升的原因

### 根本原因：v1 无参考设计语言，v2 完整移植成熟范例

| 维度 | v1（失败版） | v2（重构版） |
|------|------------|------------|
| 画幅 | 9:16 竖屏 | 16:9 横屏（与 stripe 参考对齐）|
| 叙事结构 | 自创 5 段，无内在逻辑 | 移植 HF-heygen-stripe：窗口揭晓→锁定→step cards→滚筒→收尾 |
| 背景素材 | SVG 手绘车身轮廓，截图仅用 2 张 | `video_dark_1.mp4` 作 A-roll，车图作 rotary 背景 |
| 字体 | 系统默认字体 | MiSans VF 变体字体（来自 capture，品牌原版）|
| 动效语法 | 简单 y+opacity | blur-in / slow-grow / speed-ramp / 3D rotary / clipPath typewriter |
| 设计系统 | 无统一 palette | `#0A0C10` + `#238AFF` + `#F0F4F8`，逐场景角色分工明确 |
| 过渡 | 全 crossfade | swipe-left / 爆炸退出 / 硬切，节奏有张弛 |

### 核心结论

**参考高质量的同类型已验证样例，远比从零设计更有效。**

对于 HyperFrames 项目，优先寻找 `~/workspace/hyperframes-launches/` 中与目标风格最接近的样例，  
完整分析其叙事结构、动效语法、设计 tokens，再适配品牌素材，是提升输出质量的核心路径。

这也是 v1 失败的本质原因：没有参考样例，agent 自由发挥叙事结构和动效语法，  
结果是叙事逻辑弱、动效单调、设计 token 不统一。

---

## 二、本项目的能力边界确认

小米 SU7 宣传视频最终效果偏向"品牌发布动效"而非"汽车电影广告"，  
这正是 HyperFrames 的能力边界（适用/不适用场景详见 `docs/hyperframes-analysis.md` §6）。

**本项目具体判断：**
- HF 路线能做到：Kinetic type + 产品图叠加 + 品牌色动效，风格统一，制作可重现
- HF 路线做不到：电影级行驶镜头、夜晚城市追光、驾驶舱实拍质感

如果目标是复现小米官方电视广告级别的画面，HF 不是正确工具，  
应使用混合方案（见第五节）。

---

## 三、HTML 编写耗时分析

每个 composition 约需 30 分钟 + 多轮 lint/check 迭代（HF 规则特性见 `docs/hyperframes-analysis.md` §8）。

本项目具体耗时驱动因素：

1. **没有在 session 开始时建立参考上下文**：规则细节需要重新学习
2. **批量检查而非逐个检查**：多个 composition 写完后统一 check，错误交叉影响难以定位
3. **v1 重构成本高**：叙事结构问题直到视频合成才发现，导致全部重写

**本项目改进措施：**
- session 开始时明确告知"参考 `vendors/xxx` 中的哪个文件"
- 每个 composition 写完立即 `npx hyperframes check`，不等到批量检查
- 将高频错误类型记录在项目 `CLAUDE.md` 中

---

## 四、素材利用情况

capture 命令在本项目抓取了：

```
capture/assets/          ← 134 张图片 + 1 段视频 + 2 个字体文件
capture/extracted/
  asset-descriptions.md  ← AI 对每张图片的文字描述
  tokens.json            ← 色彩 tokens、字体信息
  animations.json        ← 原网站动画信息
```

**v1 中 134 张素材只用了 2 张**，根因是 agent 没有系统性地读取 `asset-descriptions.md`。  
v2 通过人工筛选 + 明确写入分镜脚本解决了这个问题。

HF 的素材管理机制（无自动匹配、支持的编辑操作）见 `docs/hyperframes-analysis.md` §8-9。

---

## 五、方案对比：HF HTML→MP4 vs HF 故事线→文生视频

### 核心问题

用 HyperFrames 生成分镜脚本，然后将其作为 prompt 输入给 Kling/Veo/Sora，是否更省时省钱？

### 对比矩阵

| 维度 | HF HTML→MP4 | HF 故事线 → 文生视频 |
|------|-------------|------------------|
| 制作时间 | 高（HTML 编写 + lint 迭代，~30min/composition）| 低（只生成故事线，无需 HTML）|
| Token 消耗 | 高（反复读规则文档、lint 修复）| 中（仅故事线生成）|
| 品牌文字精度 | 100%（代码控制）| 差（文生视频对文字支持弱）|
| 视觉写实度 | 受限于素材质量（截图/图片）| 可生成电影级画面 |
| 修改灵活性 | 极高（改代码即改视频）| 低（需重新生成，随机性高）|
| 品牌一致性 | 完全可控（palette/font/layout 精确）| 难以保证（模型幻觉）|
| 成本（文生视频部分）| 不适用 | Kling Pro ~$0.14/s，Veo 3.1 ~$0.35/s |

### 结论与推荐工作流

**两种方案不是非此即彼，而是互补的：**

```
[用 HyperFrames]              [用文生视频]              [合并]
品牌文字 / 数字 / step cards  写实行驶/场景（Kling/Veo）
品牌动效 / 叠加层             同步生成                  → FFmpeg 合流
```

**适用判断：**

- **全用 HF**：内容主要是文字、数字、图表、产品截图，画面质量靠设计而非写实度  
  → 本项目 v2 就是这种，已达 HF 路线的上限
- **全用文生视频**：内容是电影感画面，文字少或可用字幕叠加  
  → 适合 15s 以下的纯视觉片段，但文字精度、品牌一致性无法保证
- **混合方案**（推荐用于本项目未来迭代）：
  1. HF 生成分镜脚本（< 10min）
  2. 写实场景（赛道、城市、内饰特写）→ Kling image-to-video，用 `capture` 抓取的图片作起始帧
  3. 品牌文字层（锁定画面、step cards、数字、endcard）→ HF HTML 叠加层
  4. FFmpeg 合流，总耗时预计 1–2 小时，远低于纯 HF 方案

### 文生视频 prompt 结构（参考）

HF 生成的分镜脚本可直接转化为文生视频 prompt：

```
[镜头类型] [主体] [动作/状态]，[光线/色调]，[摄影机运动]，
[时长]，[风格参考]。
例：低角度跟拍镜头，小米SU7从镜头左侧驶入画面，
夜晚城市灯光背景，慢速推进，电影感，4K，5秒。
```

Kling 3.0 在高速运动+品牌汽车方面效果最好；Veo 3.1 适合需要精准物理和光影的场景。

---

## 六、关键经验教训（跨会话有效）

| 问题 | 解决方案 |
|------|---------|
| 生成前无参考样例 | 先找 `~/workspace/hyperframes-launches/` 最近似的项目，分析叙事+动效+token |
| 素材利用率低（v1: 134张只用2张）| 制作前人工筛选候选素材，写入 STORYBOARD.md 的 `asset_candidates` |
| HTML lint 迭代多 | 每写完一个 composition 立即 `npx hyperframes check`，不要批量检查 |
| 高频错误重现 | 将已知规则（media_in_subcomposition、transform 冲突）记录在 CLAUDE.md |
| 画面写实度受限 | 电影级画面用文生视频生成，HF 负责品牌文字/叠加层 |
| v1 叙事结构重做成本高 | 先通过分镜脚本（文字）确认叙事，再写 HTML |

---

## 七、环境配置备忘（非交互 shell 特有）

| 问题 | 修复 |
|------|------|
| `npx: command not found` | `.zshrc` 末尾加 `[[ -o interactive ]] \|\| _nvm_load` |
| npm EPERM 缓存错误 | 所有 npx 命令前缀 `npm_config_cache=$TMPDIR/npmcache` |
| Chrome 启动失败（capture/check） | 对 capture 和 check 命令使用 `dangerouslyDisableSandbox: true` |
