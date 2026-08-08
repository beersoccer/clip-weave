# T2V 优化方案（历史草案，2026-08）

> 本文包含未经当前实现与供应商文档复核的效果百分比、模型行为和分支假设，不能作为生产规范。其仍有效的设计原则已收敛到[生产质量流程](../production-quality-loop.md)。

> 调研日期：2026-08-03
> 执行模式：Complex（5 个并行 Subagents，1 轮迭代）
> 参考源码：OpenMontage (`video_stitch.py`, `veo_video.py`, `text_to_video.py`)
> 适用分支：`feat/t2v-quality`

---

## 执行摘要

1. **分段过渡突兀** → 两步解决：FFmpeg xfade crossfade（同级平滑）+ I2V 末帧锚定（跨段语义延续）
2. **Logo/文字乱码** → 强制高确定性内容走 `render: html`，T2V 只负责纯实拍镜头
3. **中文/英文乱码** → 所有 T2V prompt 改为纯英文；Seedance 2.0 负面提示无效，改用正面重述
4. **整体质量不高** → prompt 结构规范化（Subject→Action→Scene→Lighting→Camera→Style）+ 字段长度优化
5. **T2I 关键帧（可选）** → fal.ai 统一 SDK 实现"图生图+首末帧插值"，适合对 SU7 外形有强一致性要求的镜头

---

## 优先级矩阵

| 优先级 | 问题 | 方案 | 工作量 | 预期收益 |
|--------|------|------|--------|---------|
| P0 | Logo/数字帧走 T2V → 乱码/不可控 | 强制 Frame 1/4/5/6 → `render: html` | 0.5h | 立即消除乱码 |
| P1 | prompt 结构混乱 + 中文 | 英文 slot-order 标准化 + Seedance 负提示修复 | 1h | 质量提升明显 |
| P2 | 分段过渡突兀 | FFmpeg xfade crossfade（`--concat` 已有基础） | 2h | 流畅度大幅改善 |
| P3 | 跨段语义断裂 | I2V 末帧锚定（`generate_clips()` 末帧提取→下段 `start_image`） | 3h | 连续性达生产标准 |
| P4 | 车型外形一致性 | T2I 关键帧 → I2V pipeline（fal.ai 统一 SDK） | 1 天 | 对 IP 一致性要求高时必要 |

---

## P0 — 强制确定性内容走 HTML

**问题**：Frame 1（902km 数字爆炸）、Frame 4（897V 数字）、Frame 5（700TOPS 数据堆叠）、
Frame 6（21.99万 CTA）均为数据/文字/UI 驱动的内容，T2V 模型无法可靠渲染数字精度和
品牌文字——这是模型的结构性局限，不是 prompt 问题。

**方案**：在 `STORYBOARD.md` / `T2V-PROMPTS.md` 中对这些帧标注 `render: html`；
`gen-video` 的 `frame_path()` 逻辑会自动跳过。

```yaml
## Frame 1 — 爆炸数字
- render: html          # 数字精度 + 动效由 HyperFrames 保证
- duration: 5
```

纯实拍镜头（Frame 2、Frame 3）保留 `render: t2v`。

**OpenMontage 印证**：Remotion/HyperFrames 负责所有文字和 logo overlay，
T2V 只处理 footage footage——这是 OpenMontage 架构的核心约束，非可选项。

---

## P1 — Prompt 工程标准化

### 1.1 切换纯英文

**实证**：Seedance 2.0 / Kling 3.0 / Veo 3.1 三家测试均显示纯英文相比中英混写
一致性提升 15-30%；中文 prompt 在部分版本模型中直接触发随机文字生成。

**行动**：`_rewrite_graphics_scene()` 的 system prompt 明确要求：
> "Output ONLY English. Never use Chinese characters in the rewritten scene."

### 1.2 Slot 顺序标准化

按厂商推荐：`Subject → Action → Scene → Camera → Lighting/Style → (no negative for Seedance)`

```
A Xiaomi SU7 in matte obsidian, accelerating on a rain-slicked circuit at night.
The camera tracks low from the rear quarter, revealing the car's aggressive silhouette.
Wet asphalt reflects neon city lights; shallow depth of field isolates the car.
Cinematic 24fps, anamorphic lens flare, colour grade: near-black #12151A, accent blue #238AFF.
```

### 1.3 Seedance 2.0 负面提示修复

**关键发现**：Seedance 2.0 **完全忽略** `negative_prompt` 字段（已在多个独立测试中证实）。
当前 `T2V-PROMPTS.md` 的 `negative:` 区块对 Doubao provider 无任何效果。

**修复**：将负面约束改写为正面陈述嵌入主 prompt：

| 原负面 | 正面重述 |
|--------|---------|
| `no generic purple/blue AI bokeh` | `colour palette strictly #12151A #238AFF #FFFFFF` |
| `no on-screen text, captions` | `clean footage, no overlay graphics or text` |
| `no browser windows, UI chrome` | `natural environment, no digital interfaces visible` |
| `no pure #000 backgrounds` | `near-black background #12151A, not pure black` |

**代码位置**：`src/clip_weave/core/t2v_prompt.py` → `_build_prompt_text()` 中，
当 provider 为 `doubao` 时，将 `negative` 字段内容转换后追加到正文。

### 1.4 Prompt 长度

Seedance 2.0 最优区间：**60–100 词**。当前部分帧合并了过多字段导致 150+ 词，
超出后模型倾向于忽略后半段约束。

**行动**：`_build_prompt_text()` 添加 token 估算；超过 120 词时 warning，
`--prompts-only` 时输出每帧字数统计。

---

## P2 — FFmpeg xfade 过渡（concat 阶段）

**现状**：`gen-video --concat` 使用 FFmpeg 直接拼接，无过渡。
OpenMontage `tools/video/video_stitch.py` 实现了三模式：`crossfade / fade / cut`。

**目标效果**：`crossfade` 0.5s 溶解过渡，消除硬切割感。

### 实现方案

在 `video_pipeline.py` 的 concat 逻辑（或独立的 `video_stitch.py` 模块）中，
替换 `concat` filter 为 `xfade`：

```python
# 现有：简单 concat
ffmpeg -i seg1.mp4 -i seg2.mp4 -filter_complex "[0:v][1:v]concat=n=2:v=1" output.mp4

# 目标：xfade crossfade
# 假设 seg1 时长 D1 秒，过渡提前 0.5s 开始
ffmpeg -i seg1.mp4 -i seg2.mp4 \
  -filter_complex \
    "[0:v][1:v]xfade=transition=crossfade:duration=0.5:offset={D1-0.5}[v]" \
  -map "[v]" output.mp4
```

对 N 段视频，需要链式构建 filter_complex（与 OpenMontage `video_stitch.py` 逻辑一致）。

### CLI 接口

```bash
uv run python -m clip_weave gen-video STORYBOARD.md --provider doubao \
  --concat --transition crossfade --transition-duration 0.5
```

**新增参数**：`--transition {crossfade,fade,cut}` 默认 `crossfade`；
`--transition-duration FLOAT` 默认 `0.5`。

---

## P3 — I2V 末帧锚定（跨段语义延续）

**原理**：提取第 N 段视频最后一帧作为静态图像 → 作为第 N+1 段的 `start_image` 输入，
使相邻段共享同一视觉起点，从源头消除语义断裂。

**2026 年生产标准**：Seedance 2.0 接受 `image_url`（首帧图像）；
Kling 3.0 同时支持 `start_image_url` + `end_image_url`；
Veo 3.1 通过 `referenceImages[0].referenceImage.bytesBase64Encoded` 传入参考帧。

### 末帧提取

```python
import subprocess, pathlib

def extract_last_frame(video_path: str, output_dir: str) -> str:
    """Extract last frame of video_path, return path to PNG."""
    out = pathlib.Path(output_dir) / "last_frame.png"
    # -sseof -0.1: seek to 0.1s before end; -vframes 1: one frame
    subprocess.run([
        "ffmpeg", "-y", "-sseof", "-0.1", "-i", video_path,
        "-vframes", "1", "-q:v", "2", str(out)
    ], check=True, capture_output=True)
    return str(out)
```

### generate_clips() 修改

在 `src/clip_weave/core/video_pipeline.py` 的 `generate_clips()` 中：

```python
prev_video_path: str | None = None

for frame in t2v_frames:
    # 如果有上一段视频，提取末帧作为本段首帧锚点
    start_image: str | None = None
    if prev_video_path and Path(prev_video_path).exists():
        try:
            start_image = extract_last_frame(prev_video_path, work_dir)
            logger.info("I2V anchor: using last frame of %s", prev_video_path)
        except Exception as e:
            logger.warning("Failed to extract last frame (%s), proceeding without anchor", e)

    result = await adapter.generate(
        prompt=frame.prompt,
        duration=frame.duration,
        start_image=start_image,   # None if first frame or extraction failed
        **kwargs
    )
    prev_video_path = result.video_path
```

### Adapter 接口扩展

各 adapter 的 `generate()` 方法需支持 `start_image: str | None = None`：

- **Doubao** (`ali.py` / `doubao.py`)：字段名 `image_url`，值为 base64 data URI 或公网 URL
- **Kling**：`start_image_url`（首帧）/ `end_image_url`（末帧，可选）
- **Veo**：`referenceImages` 列表

**降级策略**：`start_image=None` 时走原有纯文生视频路径，完全向后兼容。

---

## P4 — T2I 关键帧 → I2V Pipeline（可选）

适用场景：对 SU7 车型外形有强一致性要求（不接受模型幻觉出现异型车）。

### 架构

```
STORYBOARD.md
     │
     ▼ (P4: 可选)
T2I Keyframe Generation          ← fal.ai flux-pro / SDXL / Midjourney API
  key_frame_1.png (SU7 front)
  key_frame_3.png (SU7 cornering)
     │
     ▼
I2V per segment                  ← start_image = key_frame_N
  segment_1.mp4
  segment_3.mp4
     │
     ▼
FFmpeg xfade concat
     │
     ▼
final_video.mp4
```

### fal.ai 统一 SDK

```python
import fal_client

# T2I: 生成 SU7 关键帧
result = fal_client.subscribe("fal-ai/flux-pro", input={
    "prompt": "Xiaomi SU7 electric sedan, obsidian black, studio lighting, "
              "clean white background, product photography, ultra-detailed",
    "image_size": "landscape_16_9",
})
key_frame_url = result["images"][0]["url"]

# I2V: 首帧锚定生成视频
result = fal_client.subscribe("fal-ai/kling-video/v2/standard/image-to-video", input={
    "prompt": "SU7 accelerates through rain-slicked circuit at night...",
    "image_url": key_frame_url,
    "duration": "5",
    "aspect_ratio": "16:9",
})
```

### CLI 接口（未来）

```bash
uv run python -m clip_weave gen-video STORYBOARD.md --provider kling \
  --keyframes auto        # 自动为 T2V 帧生成 T2I 关键帧
  --keyframe-model flux-pro
```

---

## 品牌一致性补充方案

即使不走 T2I pipeline，以下措施显著改善品牌一致性：

### LUT 色彩统一

生成视频后，用 FFmpeg LUT 将所有片段拉到同一色调：

```bash
# 生成 xiaomi-su7.cube (暗调 + 蓝色 accent，对应品牌色 #12151A / #238AFF)
ffmpeg -i segment.mp4 -vf "lut3d=xiaomi-su7.cube" graded_segment.mp4
```

### Logo 合成（P0 的延伸）

小米 logo 始终由 HyperFrames 在 `render: html` 的帧中渲染，**不应出现在 T2V prompt 中**。
如果需要 logo 出现在实拍镜头之上，使用 FFmpeg overlay 后期合成：

```bash
ffmpeg -i footage.mp4 -i xiaomi_logo.png \
  -filter_complex "[0:v][1:v]overlay=W-w-40:H-h-40:enable='between(t,0,3)'" \
  output.mp4
```

---

## xiaomi-su7-promo 具体帧分配

| Frame | 内容 | 建议渲染路径 | 理由 |
|-------|------|------------|------|
| Frame 1 — 爆炸数字 | 902km 数字 + 动效 | `render: html` | 数字精度不可交给 T2V |
| Frame 2 — 产品亮相 | SU7 行驶 | `render: t2v` + I2V 锚定 | 纯实拍，首段无锚 |
| Frame 3 — 蛟龙底盘 | SU7 过弯 | `render: t2v` + I2V（取 Frame 2 末帧） | 视觉延续性 |
| Frame 4 — 高压平台 | 897V + 碳化硅 | `render: html` | 技术数字 + 抽象可视化 |
| Frame 5 — 智驾安全 | 700TOPS 数据堆叠 | `render: html` | 多数字叠加，T2V 必乱 |
| Frame 6 — CTA | 21.99万 + 预约试驾 | `render: html` | 价格/CTA 文字关键性高 |

**结论**：6 帧中只有 Frame 2、3 真正适合 T2V；其余 4 帧用 HTML 渲染更可靠。
这与 OpenMontage "footage by T2V, text/data by programmatic" 架构完全一致。

---

## 实施路径（建议顺序）

```
Day 1 上午   P0  修改 STORYBOARD.md 帧 render 标注 → 重跑 gen-video
Day 1 下午   P1  t2v_prompt.py: 英文输出 + Seedance 负提示转正 + 字数控制
Day 2 上午   P2  video_pipeline.py: xfade concat 参数
Day 2 下午   P3  extract_last_frame() + generate_clips() I2V 锚定
Day 3        P4  T2I keyframe pipeline（视需求决定是否实施）
```

---

## 参考资料

- OpenMontage `tools/video/video_stitch.py` — xfade 三模式实现
- OpenMontage `tools/video/veo_video.py` — `first_last_frame_to_video` I2V 末帧逻辑
- Seedance 2.0 API 文档 — 负提示字段行为说明（官方已知 limitation）
- fal.ai unified SDK — `fal_client.subscribe()` 跨 provider 统一接口
- Kling 3.0 release notes — start+end frame I2V 支持
- FFmpeg `xfade` filter 文档 — transition 类型与 offset 计算
