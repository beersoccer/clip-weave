# 素材输入指南

clip-weave 支持 4 种素材输入方式。以下是每种方式的处理流程。

---

## 1. 网站 URL

**触发条件：** 用户提供 `http://` 或 `https://` 开头的网址（非 figma.com）

**处理流程：**

```bash
# HF capture 命令自动抓取：
# - 页面截图 → capture/assets/
# - 设计 tokens（颜色、字体）→ capture/extracted/tokens.json
# - 素材 AI 描述 → capture/extracted/asset-descriptions.md（需 GEMINI_API_KEY）
npx hyperframes capture "<URL>" -o "videos/<project>/capture"
```

**适合的 workflow：** `product-launch-video`

**注意：** capture 时间约 30-90s，取决于网站复杂度。完成后 Asset Matcher 自动处理 asset-descriptions.md。

---

## 2. Figma URL

**触发条件：** 用户提供 `figma.com/` 开头的链接

**处理流程：**

```
运行 /figma skill（在 /clip-weave 之前）
    → 导出 Figma 设计稿中的图片资产 → capture/assets/
    → 提取 design tokens（颜色、字体、间距）→ capture/extracted/tokens.json
    → 如果有 Motion 动画标注 → 转换为 GSAP 代码片段
```

**实操步骤：**
1. 先在 Claude 对话中输入 `/figma`
2. `/figma` skill 完成后，`capture/` 目录已准备好
3. 再继续 clip-weave 流程（Project Setup + Asset Matcher + HF workflow）

**所需权限：** Figma API token（`FIGMA_TOKEN` env var）或 MCP Figma 工具

---

## 3. 用户上传文件

**触发条件：** 用户在 agent 对话窗口上传图片、音频、视频文件

**处理流程：**

上传的文件会出现在 agent 的工作目录中，clip-weave 将其组织到 HF 标准结构：

```bash
# 图片 → capture/assets/
cp <uploaded-image> "videos/<project>/capture/assets/"

# 音频 → 根据用途放置
# BGM：capture/assets/ 或 videos/<project>/audio/
# 配音脚本：SCRIPT.md 中引用

# 视频素材：capture/assets/（HF 可从 video 中提取帧作为素材）
cp <uploaded-video> "videos/<project>/capture/assets/"
```

**生成 synthetic tokens.json（无网站可抓时）：**

```python
# clip-weave 从上传的图片中提取颜色和字体信息
python -m clip_weave synthesize-tokens "videos/<project>/capture/assets/" \
    --out "videos/<project>/capture/extracted/tokens.json"
```

**适合的 workflow：** 取决于 brief（通常 `product-launch-video` 或 `general-video`）

---

## 4. 纯文字描述

**触发条件：** 用户没有提供任何 URL 或文件，只有文字描述

**处理流程：**

跳过 `npx hyperframes capture` 步骤。clip-weave 生成空的 tokens.json 并标记 no-capture：

```json
// capture/extracted/tokens.json（合成版）
{
  "title": "<from brief message>",
  "description": "<from brief intent>",
  "colors": [],
  "fonts": []
}
```

HF `faceless-explainer` workflow 支持此路径：所有视觉元素（排版、图形、抽象背景）
由 LLM 根据 brief 发明，不依赖真实素材。

**适合的 workflow：** `faceless-explainer`（默认）、`motion-graphics`（无素材类别）

---

## 混合输入

多种输入可以组合使用。例如：

- URL + 用户上传 logo 文件 → capture 抓 URL，logo 手动放入 `capture/assets/`
- Figma URL + 用户提供文案 → /figma 导出，文案写入 `BRIEF.md` 的 Intent + Notes
- 用户上传多张图片 + 背景音乐 → 图片入 `capture/assets/`，音乐入 `capture/assets/`，走 `general-video`
