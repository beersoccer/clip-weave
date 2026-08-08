---
# ============================================================
# BRIEF.md 模板 — clip-weave + HyperFrames 视频创作配置
# 填写完成后上传到 agent 对话窗口，clip-weave 将跳过所有引导问题直接开始
# 星号 (*) 标注的字段为必填；其余字段有合理默认值
# ============================================================

# * 视频工作流（选一个，删掉其余注释行）
workflow: product-launch-video   # 产品/品牌宣传视频（有网站 URL）
# workflow: faceless-explainer   # 解说视频（纯文字，无 URL）
# workflow: motion-graphics      # 短动效 / 标题卡（<10s）
# workflow: embedded-captions    # 给现有视频加字幕
# workflow: talking-head-recut   # 给采访视频加图形包装
# workflow: music-to-video       # 音乐节拍同步视频
# workflow: slideshow            # 演示文稿（非 MP4，可导航）
# workflow: pr-to-video          # GitHub PR 解说视频
# workflow: general-video        # 其他自定义视频

# 执行模式
flow: automation    # automation = 全自动执行 | companion = 与用户共创
storyboard: no      # no = 全自动（autonomous）| yes = 逐步审批分镜（collaborative）

# * Production Profile（二选一；决定整个项目的生产链）
production_profile: html_launch  # html_launch = HyperFrames 成片 | t2v_brand_film = 生成式品牌片

# * 核心消息（视频要传达的一句话）
message: ""

# 目标平台 → 自动推导画幅（也可手动填 aspect 覆盖）
destination: social-feed   # social-feed=1920×1080 | portrait=1080×1920 | square=1080×1080 | cinema=2560×1440
# aspect: 1920x1080          # 手动指定画幅（覆盖 destination 推导）

# 语言
language: zh   # zh | en | ja | ...

# 视频时长
length: 30s   # e.g. 15s | 30s | 60s | 90s | 3m

---

## Intent
<!-- 必填：用 2-4 句话描述视频的受众、目的、风格、节奏 -->
<!-- 例：面向潜在买家的品牌宣传视频。主打颜值和驾驶体验，节奏明快，背景音乐轻快。 -->


## Assets
<!-- 可选：列出要使用的素材（URL 或 capture/ 路径），每行一条 -->
<!-- 如果留空，clip-weave 会在 capture/ 目录中自动匹配最相关的素材 -->
<!-- 例：capture/assets/0-1-1.jpg — 主视觉图，用作首帧背景 -->


## Customizations
<!-- 可选：品牌色、字体、特殊要求等 -->
<!-- 例：
- 主色 #0A0C10（背景），强调色 #238AFF
- 使用品牌字体（如已在 frame.md 中定义则自动生效）
-->


## Notes
<!-- 可选：其他补充（不要什么，风格禁忌，特殊约束）-->
<!-- 例：不要真人出镜。所有文字白色或品牌蓝。 -->
