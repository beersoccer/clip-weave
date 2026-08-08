const pptxgen = require('pptxgenjs');

const pres = new pptxgen();
pres.layout = 'LAYOUT_WIDE'; // 13.333 x 7.5

pres.title = 'clip-weave 项目汇报';
pres.author = 'clip-weave team';

// Palette (inherited from clip-weave-presentation.pptx)
const C = {
  darkBg: '0D1117',
  darkBg2: '161D2E',
  navy: '1C2B3A',
  cyan: '00B4D8',
  purple: '6931CE',
  orange: 'E67E22',
  red: 'E74C3C',
  white: 'FFFFFF',
  lightBg: 'FFFFFF',
  tint: 'EBF5FB',
  tint2: 'D6EAF8',
  gray: '6B7280',
  grayLight: 'D1D5DB',
  divider: 'E5E7EB',
};

const FONT_TITLE = 'Cambria';
const FONT_BODY = 'Calibri';

// ---------- helpers ----------
function addFooter(slide, page, total) {
  slide.addText('clip-weave · 2026-07-30', {
    x: 0.5, y: 7.05, w: 6, h: 0.3,
    fontSize: 10, fontFace: FONT_BODY, color: C.gray, margin: 0,
  });
  slide.addText(`${page} / ${total}`, {
    x: 12.0, y: 7.05, w: 1.0, h: 0.3,
    fontSize: 10, fontFace: FONT_BODY, color: C.gray, align: 'right', margin: 0,
  });
}

function addSlideTitle(slide, title, subtitle) {
  slide.addText(title, {
    x: 0.6, y: 0.4, w: 12.1, h: 0.7,
    fontSize: 32, bold: true, fontFace: FONT_TITLE, color: C.navy, margin: 0,
  });
  if (subtitle) {
    slide.addText(subtitle, {
      x: 0.6, y: 1.05, w: 12.1, h: 0.35,
      fontSize: 14, fontFace: FONT_BODY, color: C.gray, italic: true, margin: 0,
    });
  }
  // small accent dot
  slide.addShape(pres.ShapeType.ellipse, {
    x: 0.3, y: 0.62, w: 0.18, h: 0.18, fill: { color: C.cyan }, line: { color: C.cyan },
  });
}

const TOTAL = 12;

// ============================================================
// Slide 1 — Title (dark)
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.darkBg };

  // decorative dots
  s.addShape(pres.ShapeType.ellipse, { x: 11.5, y: 0.6, w: 1.6, h: 1.6, fill: { color: C.purple, transparency: 60 }, line: { color: C.purple, width: 0 } });
  s.addShape(pres.ShapeType.ellipse, { x: 12.2, y: 5.5, w: 0.8, h: 0.8, fill: { color: C.cyan, transparency: 40 }, line: { color: C.cyan, width: 0 } });
  s.addShape(pres.ShapeType.ellipse, { x: 0.4, y: 6.4, w: 0.5, h: 0.5, fill: { color: C.orange, transparency: 30 }, line: { color: C.orange, width: 0 } });

  s.addText('clip-weave', {
    x: 0.8, y: 2.2, w: 12, h: 1.4,
    fontSize: 84, bold: true, fontFace: FONT_TITLE, color: C.white, margin: 0,
  });
  s.addText('让 AI 稳定产出可交付视频', {
    x: 0.8, y: 3.55, w: 12, h: 0.7,
    fontSize: 32, fontFace: FONT_BODY, color: C.cyan, margin: 0,
  });
  // divider line
  s.addShape(pres.ShapeType.line, {
    x: 0.85, y: 4.4, w: 2.5, h: 0, line: { color: C.orange, width: 3 },
  });
  s.addText('面向科技团队主管 · 项目进展汇报', {
    x: 0.8, y: 4.6, w: 12, h: 0.4,
    fontSize: 18, fontFace: FONT_BODY, color: C.white, margin: 0,
  });
  s.addText('2026-07-30 · 汇报时长 10 分钟', {
    x: 0.8, y: 5.05, w: 12, h: 0.4,
    fontSize: 16, fontFace: FONT_BODY, color: C.grayLight, margin: 0,
  });
}

// ============================================================
// Slide 2 — 应用场景
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  addSlideTitle(s, '应用场景：谁在用、做什么样的视频', '把"AI 能做视频"变成"非专业人员能稳定做出可交付视频"');

  // Left: 目标用户
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.6, y: 1.7, w: 6.0, h: 2.5, fill: { color: C.tint }, line: { color: C.tint }, rectRadius: 0.1,
  });
  s.addText([
    { text: '目标用户\n', options: { bold: true, fontSize: 20, color: C.navy, fontFace: FONT_TITLE } },
    { text: '每天要产出视频素材、\n但不是视频剪辑师的人', options: { fontSize: 15, color: C.navy, fontFace: FONT_BODY, bold: true } },
    { text: '\n\n· 产品经理 / 市场 / 运营\n· 技术写作 / 开发者本人', options: { fontSize: 14, color: C.gray, fontFace: FONT_BODY } },
  ], { x: 0.9, y: 1.85, w: 5.6, h: 2.2, valign: 'top', margin: 0 });

  // Right: 视频类型
  s.addShape(pres.ShapeType.roundRect, {
    x: 6.8, y: 1.7, w: 5.9, h: 2.5, fill: { color: C.tint2 }, line: { color: C.tint2 }, rectRadius: 0.1,
  });
  s.addText([
    { text: '视频类型\n', options: { bold: true, fontSize: 20, color: C.navy, fontFace: FONT_TITLE } },
    { text: '文字、图形、图表、动效', options: { fontSize: 15, color: C.navy, fontFace: FONT_BODY, bold: true } },
    { text: '\n\n· 品牌宣传 / 产品发布 / 功能演示\n· 数据可视化 / changelog / 更新公告\n· 教程讲解 / SaaS 推广 / 社交媒体切片', options: { fontSize: 14, color: C.gray, fontFace: FONT_BODY } },
  ], { x: 7.1, y: 1.85, w: 5.5, h: 2.2, valign: 'top', margin: 0 });

  // Bottom: 关键诉求
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.6, y: 4.5, w: 12.1, h: 1.9, fill: { color: C.navy }, line: { color: C.navy }, rectRadius: 0.1,
  });
  s.addText('关键诉求', {
    x: 0.9, y: 4.65, w: 4, h: 0.4,
    fontSize: 18, bold: true, color: C.cyan, fontFace: FONT_TITLE, margin: 0,
  });
  s.addText('一句自然语言输入 → 视频产出，全程高效、稳定、可交付', {
    x: 0.9, y: 5.05, w: 11.5, h: 0.5,
    fontSize: 18, bold: true, color: C.white, fontFace: FONT_BODY, margin: 0,
  });
  s.addText('不用学 After Effects · 不用写代码 · 不用一次次和 AI 反复对齐', {
    x: 0.9, y: 5.6, w: 11.5, h: 0.5,
    fontSize: 14, color: C.grayLight, fontFace: FONT_BODY, margin: 0,
  });

  addFooter(s, 2, TOTAL);
}

// ============================================================
// Slide 3 — 卡点
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  addSlideTitle(s, '卡点：现有底座还差什么', 'HyperFrames 解决了"怎么渲染"，但从 demo 到可交付还有摩擦');

  // Top summary
  s.addText([
    { text: '底座 HyperFrames（HF） ', options: { bold: true, color: C.navy } },
    { text: '已经解决了"怎么渲染" —— HTML + CSS + GSAP → Chrome 逐帧捕获 → FFmpeg 合成 MP4，AI 最擅长写 HTML，路径完全对。', options: { color: C.gray } },
  ], { x: 0.6, y: 1.55, w: 12.1, h: 0.6, fontSize: 14, fontFace: FONT_BODY, margin: 0 });

  s.addText('三个反复出现的卡点：', {
    x: 0.6, y: 2.2, w: 12, h: 0.35, fontSize: 15, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });

  // 3 columns
  const cards = [
    { num: '01', title: '规则遗忘', color: C.red,
      body: 'HF 特有约束（4 条）不在通用 Web 知识里，长会话上下文压缩后 LLM 忘掉，已修复的错误重现。' },
    { num: '02', title: 'lint 循环烧时间烧 token', color: C.orange,
      body: '单次 check 需启动 headless Chrome，10–30s；每个合成平均 2–3 轮；长视频累计上百秒。' },
    { num: '03', title: '素材利用率低', color: C.purple,
      body: 'capture 抓到 134 张图，v1 版本只用了 2 张，非专业用户看不出哪张该配哪镜。' },
  ];
  cards.forEach((c, i) => {
    const x = 0.6 + i * 4.15;
    s.addShape(pres.ShapeType.roundRect, {
      x, y: 2.65, w: 3.95, h: 3.1, fill: { color: C.tint }, line: { color: C.tint }, rectRadius: 0.08,
    });
    s.addShape(pres.ShapeType.ellipse, {
      x: x + 0.25, y: 2.85, w: 0.75, h: 0.75, fill: { color: c.color }, line: { color: c.color },
    });
    s.addText(c.num, {
      x: x + 0.25, y: 2.9, w: 0.75, h: 0.65,
      fontSize: 18, bold: true, color: C.white, align: 'center', fontFace: FONT_TITLE, margin: 0,
    });
    s.addText(c.title, {
      x: x + 1.15, y: 2.9, w: 2.7, h: 0.65,
      fontSize: 18, bold: true, color: C.navy, fontFace: FONT_TITLE, valign: 'middle', margin: 0,
    });
    s.addText(c.body, {
      x: x + 0.25, y: 3.75, w: 3.5, h: 1.85,
      fontSize: 13, color: C.gray, fontFace: FONT_BODY, valign: 'top', margin: 0,
    });
  });

  // Bottom takeaway
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.6, y: 6.0, w: 12.1, h: 0.85, fill: { color: C.navy }, line: { color: C.navy }, rectRadius: 0.08,
  });
  s.addText([
    { text: '共同后果：', options: { bold: true, color: C.cyan } },
    { text: 'AI 能出 demo，但稳定性和一次通过率不够，非专业用户被迫回到"和 AI 反复扯皮"的低效模式。', options: { color: C.white } },
  ], { x: 0.9, y: 6.05, w: 11.5, h: 0.75, fontSize: 14, fontFace: FONT_BODY, valign: 'middle', margin: 0 });

  addFooter(s, 3, TOTAL);
}

// ============================================================
// Slide 4 — 一句话结论
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  addSlideTitle(s, '一句话结论：clip-weave 是做什么的', 'HyperFrames 前置门面 + 稳定性补丁，不重造渲染引擎');

  // Formula bar
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.6, y: 1.6, w: 12.1, h: 0.85, fill: { color: C.navy }, line: { color: C.navy }, rectRadius: 0.08,
  });
  s.addText([
    { text: 'clip-weave  =  ', options: { color: C.cyan, bold: true, fontSize: 24, fontFace: FONT_TITLE } },
    { text: 'HyperFrames 前置门面  +  稳定性补丁', options: { color: C.white, bold: true, fontSize: 24, fontFace: FONT_TITLE } },
  ], { x: 0.6, y: 1.6, w: 12.1, h: 0.85, align: 'center', valign: 'middle', margin: 0 });

  // ① 前置入口
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.6, y: 2.75, w: 12.1, h: 1.15, fill: { color: C.tint }, line: { color: C.tint }, rectRadius: 0.08,
  });
  s.addShape(pres.ShapeType.ellipse, {
    x: 0.85, y: 2.95, w: 0.75, h: 0.75, fill: { color: C.cyan }, line: { color: C.cyan },
  });
  s.addText('①', { x: 0.85, y: 3.0, w: 0.75, h: 0.65, fontSize: 20, bold: true, color: C.white, align: 'center', fontFace: FONT_TITLE, margin: 0 });
  s.addText([
    { text: '前置入口 —— 意图路由\n', options: { bold: true, fontSize: 17, color: C.navy, fontFace: FONT_TITLE } },
    { text: '一句自然语言 → 自动选定 workflow + 生成 BRIEF.md → 触发无人值守执行。非专业用户无需理解 HF 概念。', options: { fontSize: 13, color: C.gray, fontFace: FONT_BODY } },
  ], { x: 1.85, y: 2.85, w: 10.7, h: 1.0, valign: 'top', margin: 0 });

  // ② 三个稳定性解法 — mapping table
  s.addText('② 三个稳定性解法 —— 分别对应上页三个卡点', {
    x: 0.6, y: 4.1, w: 12, h: 0.4,
    fontSize: 16, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });

  const rows = [
    ['规则遗忘', '规则守卫', '确定性 Python 拦截，不依赖 LLM 记忆', C.red],
    ['lint 循环慢', 'Pre-flight 预检', '<1s 静态检查，每次绕过 10–30s 的 Chrome 启动', C.orange],
    ['素材利用率低', 'Asset Matcher', '100+ 素材语义预排序，缩小到 3–5 张候选', C.purple],
  ];
  rows.forEach((r, i) => {
    const y = 4.6 + i * 0.65;
    s.addShape(pres.ShapeType.rect, {
      x: 0.6, y, w: 12.1, h: 0.6, fill: { color: i % 2 ? C.tint : C.tint2 }, line: { color: 'FFFFFF', width: 0 },
    });
    s.addShape(pres.ShapeType.rect, {
      x: 0.6, y, w: 0.15, h: 0.6, fill: { color: r[3] }, line: { color: r[3] },
    });
    s.addText(r[0], { x: 0.95, y, w: 3.0, h: 0.6, fontSize: 14, bold: true, color: C.gray, fontFace: FONT_BODY, valign: 'middle', margin: 0 });
    s.addText('→', { x: 3.9, y, w: 0.4, h: 0.6, fontSize: 16, color: C.cyan, bold: true, valign: 'middle', align: 'center', margin: 0 });
    s.addText(r[1], { x: 4.3, y, w: 3.0, h: 0.6, fontSize: 15, bold: true, color: C.navy, fontFace: FONT_TITLE, valign: 'middle', margin: 0 });
    s.addText(r[2], { x: 7.4, y, w: 5.2, h: 0.6, fontSize: 13, color: C.navy, fontFace: FONT_BODY, valign: 'middle', margin: 0 });
  });

  s.addText('当前状态：P0–P2 全部交付，33 个测试通过', {
    x: 0.6, y: 6.7, w: 12.1, h: 0.4,
    fontSize: 14, bold: true, italic: true, color: C.orange, fontFace: FONT_BODY, align: 'center', margin: 0,
  });

  addFooter(s, 4, TOTAL);
}

// ============================================================
// Slide 5 — 三种入口
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  addSlideTitle(s, '三种使用入口 —— 覆盖不同熟练度', 'BRIEF.md 一旦生成，后续无人值守直接跑到出片');

  const entries = [
    { icon: '💬', title: '对话式 intent interview',
      form: 'Claude Code 里一句话开始\nAI 逐字段问',
      fit: '首次使用\n字段还没想清楚',
      color: C.cyan },
    { icon: '📝', title: 'BRIEF.md 模板离线填写',
      form: '复制模板\n填空 → 一键跑',
      fit: '批量场景\n复用同一套参数',
      color: C.purple },
    { icon: '⌨', title: 'CLI 单行',
      form: 'python -m clip_weave run\n--url ... --message ...',
      fit: '集成到脚本\nCI / 自动化流程',
      color: C.orange },
  ];
  entries.forEach((e, i) => {
    const x = 0.6 + i * 4.15;
    s.addShape(pres.ShapeType.roundRect, {
      x, y: 1.7, w: 3.95, h: 4.5, fill: { color: C.tint }, line: { color: C.tint }, rectRadius: 0.1,
    });
    // header stripe replaced with colored circle for icon
    s.addShape(pres.ShapeType.ellipse, {
      x: x + 1.4, y: 1.95, w: 1.15, h: 1.15, fill: { color: e.color }, line: { color: e.color },
    });
    s.addText(e.icon, {
      x: x + 1.4, y: 1.95, w: 1.15, h: 1.15,
      fontSize: 36, color: C.white, align: 'center', valign: 'middle', margin: 0,
    });
    s.addText(e.title, {
      x: x + 0.15, y: 3.2, w: 3.65, h: 0.7,
      fontSize: 16, bold: true, color: C.navy, fontFace: FONT_TITLE, align: 'center', valign: 'middle', margin: 0,
    });
    s.addText('交互形式', {
      x: x + 0.3, y: 3.95, w: 3.3, h: 0.3,
      fontSize: 11, bold: true, color: e.color, fontFace: FONT_BODY, margin: 0,
    });
    s.addText(e.form, {
      x: x + 0.3, y: 4.25, w: 3.3, h: 0.7,
      fontSize: 12, color: C.navy, fontFace: FONT_BODY, margin: 0,
    });
    s.addText('适合场景', {
      x: x + 0.3, y: 5.0, w: 3.3, h: 0.3,
      fontSize: 11, bold: true, color: e.color, fontFace: FONT_BODY, margin: 0,
    });
    s.addText(e.fit, {
      x: x + 0.3, y: 5.3, w: 3.3, h: 0.7,
      fontSize: 12, color: C.navy, fontFace: FONT_BODY, margin: 0,
    });
  });

  s.addShape(pres.ShapeType.roundRect, {
    x: 0.6, y: 6.4, w: 12.1, h: 0.55, fill: { color: C.navy }, line: { color: C.navy }, rectRadius: 0.06,
  });
  s.addText([
    { text: '共同点：', options: { bold: true, color: C.cyan } },
    { text: 'BRIEF.md 生成后 → 无人值守 → LLM 不再向用户提问 → 直接跑到出片', options: { color: C.white } },
  ], { x: 0.6, y: 6.4, w: 12.1, h: 0.55, fontSize: 13, fontFace: FONT_BODY, align: 'center', valign: 'middle', margin: 0 });

  addFooter(s, 5, TOTAL);
}

// ============================================================
// Slide 6 — 两条渲染路径
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  addSlideTitle(s, '两条渲染路径 —— 覆盖不同画面性质', '共用同一份 STORYBOARD.md，选择哪条是分镜级别的决策');

  // HTML card
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.6, y: 1.7, w: 5.95, h: 4.7, fill: { color: C.tint }, line: { color: C.cyan, width: 2 }, rectRadius: 0.1,
  });
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.6, y: 1.7, w: 5.95, h: 0.75, fill: { color: C.cyan }, line: { color: C.cyan }, rectRadius: 0.1,
  });
  s.addText([
    { text: 'HTML 路径', options: { bold: true, fontSize: 20, color: C.white, fontFace: FONT_TITLE } },
    { text: '  （当前主力）', options: { fontSize: 13, color: C.white, fontFace: FONT_BODY } },
  ], { x: 0.85, y: 1.75, w: 5.7, h: 0.65, valign: 'middle', margin: 0 });

  s.addText([
    { text: '做法\n', options: { bold: true, fontSize: 12, color: C.cyan, fontFace: FONT_BODY } },
    { text: 'AI 写 HTML/CSS/GSAP → HF 逐帧渲染\n\n', options: { fontSize: 13, color: C.navy, fontFace: FONT_BODY } },
    { text: '画面性质\n', options: { bold: true, fontSize: 12, color: C.cyan, fontFace: FONT_BODY } },
    { text: '图形、文字、UI、图表  ·  代码级精度\n\n', options: { fontSize: 13, color: C.navy, fontFace: FONT_BODY } },
    { text: '可控性\n', options: { bold: true, fontSize: 12, color: C.cyan, fontFace: FONT_BODY } },
    { text: '每一帧可复现，改一个字改一行代码\n\n', options: { fontSize: 13, color: C.navy, fontFace: FONT_BODY } },
    { text: '适合\n', options: { bold: true, fontSize: 12, color: C.cyan, fontFace: FONT_BODY } },
    { text: '品牌发布、数据可视化、功能展示', options: { fontSize: 13, color: C.navy, fontFace: FONT_BODY } },
  ], { x: 0.9, y: 2.65, w: 5.45, h: 3.6, valign: 'top', margin: 0 });

  // T2V card
  s.addShape(pres.ShapeType.roundRect, {
    x: 6.75, y: 1.7, w: 5.95, h: 4.7, fill: { color: 'F5F0FF' }, line: { color: C.purple, width: 2 }, rectRadius: 0.1,
  });
  s.addShape(pres.ShapeType.roundRect, {
    x: 6.75, y: 1.7, w: 5.95, h: 0.75, fill: { color: C.purple }, line: { color: C.purple }, rectRadius: 0.1,
  });
  s.addText([
    { text: 'T2V 旁路', options: { bold: true, fontSize: 20, color: C.white, fontFace: FONT_TITLE } },
    { text: '  （P3 待验证）', options: { fontSize: 13, color: C.white, fontFace: FONT_BODY } },
  ], { x: 7.0, y: 1.75, w: 5.7, h: 0.65, valign: 'middle', margin: 0 });

  s.addText([
    { text: '做法\n', options: { bold: true, fontSize: 12, color: C.purple, fontFace: FONT_BODY } },
    { text: 'STORYBOARD.md 分镜 → 文生视频模型直出\n\n', options: { fontSize: 13, color: C.navy, fontFace: FONT_BODY } },
    { text: '画面性质\n', options: { bold: true, fontSize: 12, color: C.purple, fontFace: FONT_BODY } },
    { text: '写实、氛围、镜头运动\n\n', options: { fontSize: 13, color: C.navy, fontFace: FONT_BODY } },
    { text: '可控性\n', options: { bold: true, fontSize: 12, color: C.purple, fontFace: FONT_BODY } },
    { text: '生成结果有随机性，靠改提示词迭代\n\n', options: { fontSize: 13, color: C.navy, fontFace: FONT_BODY } },
    { text: '适合\n', options: { bold: true, fontSize: 12, color: C.purple, fontFace: FONT_BODY } },
    { text: '空镜、氛围镜头、实景铺垫', options: { fontSize: 13, color: C.navy, fontFace: FONT_BODY } },
  ], { x: 7.05, y: 2.65, w: 5.45, h: 3.6, valign: 'top', margin: 0 });

  s.addShape(pres.ShapeType.roundRect, {
    x: 0.6, y: 6.55, w: 12.1, h: 0.5, fill: { color: C.navy }, line: { color: C.navy }, rectRadius: 0.06,
  });
  s.addText('两条路径共用同一份 STORYBOARD.md —— 选择哪条是"分镜级别"的决策', {
    x: 0.6, y: 6.55, w: 12.1, h: 0.5, fontSize: 13, color: C.white, fontFace: FONT_BODY,
    bold: true, align: 'center', valign: 'middle', margin: 0,
  });

  addFooter(s, 6, TOTAL);
}

// ============================================================
// Slide 7 — 覆盖视频类型
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  addSlideTitle(s, '目前能覆盖的视频类型', 'HTML 路径已跑通的场景 —— 一句话描述，clip-weave 自动完成后续');

  const scenes = [
    { icon: '🎯', title: '产品 / 品牌宣传', input: '官网 URL + 一句描述', out: '15–30s 带 logo/主色的 promo', color: C.cyan },
    { icon: '⚡', title: '功能展示', input: '功能描述 + 截图', out: 'UI 高亮 + 说明文字的演示', color: C.orange },
    { icon: '📊', title: '数据可视化', input: '数据表 + 想表达的重点', out: '图表 + 关键数字动画', color: C.purple },
    { icon: '📋', title: 'Changelog / 公告', input: 'commit / PR 列表', out: '逐条动效呈现的更新视频', color: C.red },
    { icon: '📖', title: '教程 / 讲解', input: '分步骤脚本', out: '分镜化的教学动画', color: '10B981' },
    { icon: '➕', title: '更多 workflow', input: '9 个 HF workflow 全覆盖', out: '路由自动映射', color: C.gray },
  ];
  scenes.forEach((sc, i) => {
    const col = i % 3;
    const row = Math.floor(i / 3);
    const x = 0.6 + col * 4.15;
    const y = 1.65 + row * 1.95;
    s.addShape(pres.ShapeType.roundRect, {
      x, y, w: 3.95, h: 1.75, fill: { color: C.tint }, line: { color: C.tint }, rectRadius: 0.08,
    });
    s.addShape(pres.ShapeType.ellipse, {
      x: x + 0.2, y: y + 0.2, w: 0.7, h: 0.7, fill: { color: sc.color }, line: { color: sc.color },
    });
    s.addText(sc.icon, { x: x + 0.2, y: y + 0.2, w: 0.7, h: 0.7, fontSize: 22, color: C.white, align: 'center', valign: 'middle', margin: 0 });
    s.addText(sc.title, {
      x: x + 1.0, y: y + 0.15, w: 2.85, h: 0.55, fontSize: 15, bold: true, color: C.navy, fontFace: FONT_TITLE, valign: 'middle', margin: 0,
    });
    s.addText([
      { text: '输入  ', options: { fontSize: 10, color: sc.color, bold: true, fontFace: FONT_BODY } },
      { text: sc.input, options: { fontSize: 11, color: C.navy, fontFace: FONT_BODY } },
      { text: '\n产出  ', options: { fontSize: 10, color: sc.color, bold: true, fontFace: FONT_BODY } },
      { text: sc.out, options: { fontSize: 11, color: C.navy, fontFace: FONT_BODY } },
    ], { x: x + 0.2, y: y + 0.95, w: 3.65, h: 0.75, valign: 'top', margin: 0 });
  });

  s.addText([
    { text: '非专业用户视角：', options: { bold: true, color: C.orange, fontSize: 13 } },
    { text: '一句话描述"做什么、给谁看、多长"，剩下的 workflow 选择、设计系统提取、素材匹配、规则守卫都由 clip-weave 自动完成。', options: { color: C.gray, fontSize: 13 } },
  ], { x: 0.6, y: 5.75, w: 12.1, h: 1.05, fontFace: FONT_BODY, valign: 'top', margin: 0 });

  addFooter(s, 7, TOTAL);
}

// ============================================================
// Slide 8 — 交付状态
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  addSlideTitle(s, '交付状态一览', 'P0–P2 已全部交付 · P3–P4 规划中');

  const phases = [
    { p: 'P0', goal: '打通链路：意图 → HF autonomous 执行', status: '✅ 完成', done: true, color: C.cyan },
    { p: 'P1', goal: '减少 check 启动次数（4 条规则预检 + 违规指纹）', status: '✅ 完成', done: true, color: C.cyan },
    { p: 'P2', goal: '提升素材利用率（Asset Matcher + 噪声过滤）', status: '✅ 完成', done: true, color: C.cyan },
    { p: 'P3', goal: 'T2V 旁路：STORYBOARD.md → 文生视频 → FFmpeg 合流', status: '🔲 待验证', done: false, color: C.purple },
    { p: 'P4', goal: '两条路径混排（动效镜头 + 写实镜头并存）', status: '🔲 P3 后', done: false, color: C.purple },
  ];
  phases.forEach((ph, i) => {
    const y = 1.65 + i * 0.62;
    s.addShape(pres.ShapeType.roundRect, {
      x: 0.6, y, w: 8.4, h: 0.55, fill: { color: ph.done ? C.tint : 'F5F0FF' }, line: { color: ph.done ? C.tint : 'F5F0FF' }, rectRadius: 0.06,
    });
    s.addShape(pres.ShapeType.ellipse, {
      x: 0.75, y: y + 0.1, w: 0.35, h: 0.35, fill: { color: ph.color }, line: { color: ph.color },
    });
    s.addText(ph.p, {
      x: 0.75, y: y + 0.1, w: 0.35, h: 0.35, fontSize: 9, bold: true, color: C.white, align: 'center', valign: 'middle', fontFace: FONT_BODY, margin: 0,
    });
    s.addText(ph.goal, {
      x: 1.25, y, w: 7.6, h: 0.55, fontSize: 13, color: C.navy, fontFace: FONT_BODY, valign: 'middle', margin: 0,
    });
    s.addText(ph.status, {
      x: 9.1, y, w: 1.5, h: 0.55, fontSize: 13, bold: true, color: ph.done ? C.orange : C.gray, fontFace: FONT_BODY, valign: 'middle', margin: 0,
    });
  });

  // Right: 工程质量
  s.addShape(pres.ShapeType.roundRect, {
    x: 10.8, y: 1.65, w: 1.9, h: 3.1, fill: { color: C.navy }, line: { color: C.navy }, rectRadius: 0.08,
  });
  s.addText('工程质量', {
    x: 10.8, y: 1.75, w: 1.9, h: 0.4, fontSize: 14, bold: true, color: C.cyan, align: 'center', fontFace: FONT_TITLE, margin: 0,
  });
  s.addText('33', {
    x: 10.8, y: 2.2, w: 1.9, h: 0.9, fontSize: 60, bold: true, color: C.white, align: 'center', fontFace: FONT_TITLE, margin: 0,
  });
  s.addText('个单元测试全部通过', {
    x: 10.8, y: 3.15, w: 1.9, h: 0.35, fontSize: 11, color: C.grayLight, align: 'center', fontFace: FONT_BODY, margin: 0,
  });
  s.addShape(pres.ShapeType.line, {
    x: 11.1, y: 3.65, w: 1.3, h: 0, line: { color: C.orange, width: 1 },
  });
  s.addText('sha1 违规指纹\n三级降级无单点故障', {
    x: 10.9, y: 3.8, w: 1.7, h: 0.9, fontSize: 10, color: C.grayLight, align: 'center', fontFace: FONT_BODY, margin: 0,
  });

  s.addShape(pres.ShapeType.roundRect, {
    x: 0.6, y: 5.05, w: 12.1, h: 1.6, fill: { color: C.tint2 }, line: { color: C.tint2 }, rectRadius: 0.08,
  });
  s.addText('三种入口全部可用', {
    x: 0.9, y: 5.15, w: 11.5, h: 0.4, fontSize: 15, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });
  s.addText([
    { text: '· 对话式 intent interview  —  首次使用 / 字段未定\n', options: {} },
    { text: '· BRIEF.md 模板离线填写  —  批量 / 复用同一套参数\n', options: {} },
    { text: '· CLI 单行调用  —  集成脚本 / CI / 自动化流程', options: {} },
  ], { x: 0.9, y: 5.55, w: 11.5, h: 1.05, fontSize: 13, color: C.gray, fontFace: FONT_BODY, valign: 'top', margin: 0 });

  addFooter(s, 8, TOTAL);
}

// ============================================================
// Slide 9 — 规划一 音频
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  addSlideTitle(s, '规划一 · 音频落地', '视频从"静音"到"带配音 + BGM"');

  // Timeline: current → next
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.6, y: 1.7, w: 5.9, h: 3.9, fill: { color: C.tint }, line: { color: C.tint }, rectRadius: 0.1,
  });
  s.addText('现状 · 已跑通验证', {
    x: 0.9, y: 1.85, w: 5.4, h: 0.4, fontSize: 15, bold: true, color: C.cyan, fontFace: FONT_TITLE, margin: 0,
  });
  s.addText([
    { text: '✓  ', options: { color: C.cyan, bold: true, fontSize: 16 } },
    { text: 'api.heygen.com 内网屏蔽问题已解决\n\n', options: { fontSize: 14, color: C.navy } },
    { text: '✓  ', options: { color: C.cyan, bold: true, fontSize: 16 } },
    { text: '用 HeyGen 个人账号跑通验证：\n', options: { fontSize: 14, color: C.navy, bold: true } },
    { text: '     · TTS 配音质量满足要求\n', options: { fontSize: 13, color: C.gray } },
    { text: '     · 版权 BGM 均可用\n', options: { fontSize: 13, color: C.gray } },
    { text: '     · 中文声线清晰自然', options: { fontSize: 13, color: C.gray } },
  ], { x: 0.9, y: 2.3, w: 5.4, h: 3.2, fontFace: FONT_BODY, valign: 'top', margin: 0 });

  // Arrow
  s.addShape(pres.ShapeType.rightArrow, {
    x: 6.6, y: 3.3, w: 0.4, h: 0.7, fill: { color: C.orange }, line: { color: C.orange }, rotate: 90,
  });

  s.addShape(pres.ShapeType.roundRect, {
    x: 7.15, y: 1.7, w: 5.55, h: 3.9, fill: { color: 'FFF3E6' }, line: { color: C.orange, width: 2 }, rectRadius: 0.1,
  });
  s.addText('下一步 · 切云厂商合规通道', {
    x: 7.45, y: 1.85, w: 5.0, h: 0.4, fontSize: 15, bold: true, color: C.orange, fontFace: FONT_TITLE, margin: 0,
  });
  s.addText([
    { text: '→  ', options: { color: C.orange, bold: true, fontSize: 16 } },
    { text: '切换到公司已采购云厂商账号 / 额度\n\n', options: { fontSize: 14, color: C.navy } },
    { text: '→  ', options: { color: C.orange, bold: true, fontSize: 16 } },
    { text: '视频从"静音"变成"配音 + BGM"\n', options: { fontSize: 14, color: C.navy, bold: true } },
    { text: '     可交付性的一个明确台阶\n\n', options: { fontSize: 13, color: C.gray } },
    { text: '→  ', options: { color: C.orange, bold: true, fontSize: 16 } },
    { text: '与三种入口无缝衔接\n', options: { fontSize: 14, color: C.navy, bold: true } },
    { text: '     BRIEF.md 加一个 voice/bgm 字段即可', options: { fontSize: 13, color: C.gray } },
  ], { x: 7.45, y: 2.3, w: 5.0, h: 3.2, fontFace: FONT_BODY, valign: 'top', margin: 0 });

  s.addShape(pres.ShapeType.roundRect, {
    x: 0.6, y: 5.85, w: 12.1, h: 0.9, fill: { color: C.navy }, line: { color: C.navy }, rectRadius: 0.08,
  });
  s.addText('👤 用户价值', {
    x: 0.9, y: 5.9, w: 3, h: 0.35, fontSize: 13, bold: true, color: C.cyan, fontFace: FONT_BODY, margin: 0,
  });
  s.addText('非专业用户不再需要在剪映里补音轨，一次输出即完整可交付。', {
    x: 0.9, y: 6.25, w: 11.5, h: 0.45, fontSize: 15, bold: true, color: C.white, fontFace: FONT_BODY, margin: 0,
  });

  addFooter(s, 9, TOTAL);
}

// ============================================================
// Slide 10 — 规划二 T2V
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  addSlideTitle(s, '规划二 · T2V 旁路（P3）', 'STORYBOARD.md 复用于文生视频 —— 跳过写 HTML');

  // Motivation
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.6, y: 1.65, w: 12.1, h: 1.1, fill: { color: C.tint }, line: { color: C.tint }, rectRadius: 0.08,
  });
  s.addText('动机', {
    x: 0.9, y: 1.75, w: 2, h: 0.35, fontSize: 13, bold: true, color: C.purple, fontFace: FONT_BODY, margin: 0,
  });
  s.addText('HTML 路径画不出真实场景 —— 电影级写实、真人出镜、复杂物理效果超出 CSS/GSAP 表达范围。', {
    x: 0.9, y: 2.1, w: 11.5, h: 0.6, fontSize: 15, color: C.navy, fontFace: FONT_BODY, margin: 0,
  });

  // Method
  s.addText('方案：同一份 STORYBOARD.md 直接交给文生视频模型渲染 —— 跳过写 HTML 这一步。', {
    x: 0.6, y: 2.95, w: 12.1, h: 0.4, fontSize: 15, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });

  // 3 things to validate
  s.addText('要验证三件事', {
    x: 0.6, y: 3.5, w: 12, h: 0.4, fontSize: 14, bold: true, color: C.purple, fontFace: FONT_TITLE, margin: 0,
  });
  const checks = [
    { n: '1', title: '信息量', body: '分镜描述够不够模型生成', color: C.purple },
    { n: '2', title: '风格连贯', body: '镜头间视觉风格是否统一', color: C.cyan },
    { n: '3', title: '时长可控', body: '模型输出能否精确对齐分镜时长', color: C.orange },
  ];
  checks.forEach((c, i) => {
    const x = 0.6 + i * 4.15;
    s.addShape(pres.ShapeType.roundRect, {
      x, y: 4.0, w: 3.95, h: 1.3, fill: { color: 'F5F0FF' }, line: { color: 'F5F0FF' }, rectRadius: 0.08,
    });
    s.addShape(pres.ShapeType.ellipse, {
      x: x + 0.2, y: 4.2, w: 0.65, h: 0.65, fill: { color: c.color }, line: { color: c.color },
    });
    s.addText(c.n, { x: x + 0.2, y: 4.2, w: 0.65, h: 0.65, fontSize: 20, bold: true, color: C.white, align: 'center', valign: 'middle', fontFace: FONT_TITLE, margin: 0 });
    s.addText(c.title, { x: x + 1.0, y: 4.15, w: 2.85, h: 0.4, fontSize: 15, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0 });
    s.addText(c.body, { x: x + 1.0, y: 4.55, w: 2.85, h: 0.7, fontSize: 12, color: C.gray, fontFace: FONT_BODY, margin: 0 });
  });

  // Outcome branches
  s.addText('验证结果 · 两种走向都是可执行的下一步', {
    x: 0.6, y: 5.5, w: 12, h: 0.4, fontSize: 14, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.6, y: 5.95, w: 5.95, h: 0.9, fill: { color: 'E8F8F0' }, line: { color: '10B981', width: 2 }, rectRadius: 0.08,
  });
  s.addText([
    { text: '✓ 通过\n', options: { bold: true, fontSize: 14, color: '10B981' } },
    { text: '写实镜头场景打开，覆盖面显著扩大', options: { fontSize: 12, color: C.navy } },
  ], { x: 0.85, y: 6.0, w: 5.6, h: 0.85, fontFace: FONT_BODY, valign: 'middle', margin: 0 });

  s.addShape(pres.ShapeType.roundRect, {
    x: 6.75, y: 5.95, w: 5.95, h: 0.9, fill: { color: 'FDF2F2' }, line: { color: C.red, width: 2 }, rectRadius: 0.08,
  });
  s.addText([
    { text: '✗ 不通过\n', options: { bold: true, fontSize: 14, color: C.red } },
    { text: '明确是分镜格式要补字段，还是模型能力不够', options: { fontSize: 12, color: C.navy } },
  ], { x: 7.0, y: 6.0, w: 5.6, h: 0.85, fontFace: FONT_BODY, valign: 'middle', margin: 0 });

  addFooter(s, 10, TOTAL);
}

// ============================================================
// Slide 11 — 规划三 混排
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  addSlideTitle(s, '规划三 · 两条路径混排（P4）', '同一支视频里，动效镜头 + 写实镜头并存');

  // Left illustration: HTML segments + T2V segments -> FFmpeg
  s.addText('分镜级路径选择 → FFmpeg 层合流', {
    x: 0.6, y: 1.65, w: 12, h: 0.4, fontSize: 15, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });

  // Timeline strips
  const stripY = 2.2;
  const cells = [
    { label: 'logo 揭示', path: 'HTML', color: C.cyan },
    { label: '氛围空镜', path: 'T2V', color: C.purple },
    { label: '数据图表', path: 'HTML', color: C.cyan },
    { label: '产品实景', path: 'T2V', color: C.purple },
    { label: '功能高亮', path: 'HTML', color: C.cyan },
    { label: 'CTA 结尾', path: 'HTML', color: C.cyan },
  ];
  const cellW = 1.95;
  cells.forEach((c, i) => {
    const x = 0.6 + i * (cellW + 0.05);
    s.addShape(pres.ShapeType.roundRect, {
      x, y: stripY, w: cellW, h: 1.1, fill: { color: c.color }, line: { color: c.color }, rectRadius: 0.06,
    });
    s.addText(c.path, { x, y: stripY + 0.1, w: cellW, h: 0.35, fontSize: 11, bold: true, color: C.white, align: 'center', fontFace: FONT_BODY, margin: 0 });
    s.addText(c.label, { x, y: stripY + 0.45, w: cellW, h: 0.5, fontSize: 13, bold: true, color: C.white, align: 'center', valign: 'middle', fontFace: FONT_TITLE, margin: 0 });
  });

  // Arrow down
  s.addShape(pres.ShapeType.rightArrow, {
    x: 6.55, y: 3.4, w: 0.4, h: 0.4, fill: { color: C.orange }, line: { color: C.orange }, rotate: 180,
  });

  s.addShape(pres.ShapeType.roundRect, {
    x: 0.6, y: 3.9, w: 12.1, h: 0.6, fill: { color: C.orange }, line: { color: C.orange }, rectRadius: 0.06,
  });
  s.addText('FFmpeg 层合流  →  一支成片', {
    x: 0.6, y: 3.9, w: 12.1, h: 0.6, fontSize: 15, bold: true, color: C.white, align: 'center', valign: 'middle', fontFace: FONT_TITLE, margin: 0,
  });

  // Two column: constraint + value
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.6, y: 4.75, w: 5.95, h: 2.0, fill: { color: 'FDF2F2' }, line: { color: 'FDF2F2' }, rectRadius: 0.08,
  });
  s.addText('⚠ 关键工程约束', {
    x: 0.9, y: 4.85, w: 5.4, h: 0.4, fontSize: 14, bold: true, color: C.red, fontFace: FONT_TITLE, margin: 0,
  });
  s.addText([
    { text: '不在 HTML 内嵌 <video> 做混排\n', options: { bold: true, color: C.navy, fontSize: 13 } },
    { text: 'Chrome 视频密集渲染会解码器耗尽\n\n', options: { color: C.gray, fontSize: 12 } },
    { text: '混排必须在 FFmpeg 层做，时间轴上按段拼接', options: { color: C.navy, fontSize: 13 } },
  ], { x: 0.9, y: 5.3, w: 5.4, h: 1.4, fontFace: FONT_BODY, valign: 'top', margin: 0 });

  s.addShape(pres.ShapeType.roundRect, {
    x: 6.75, y: 4.75, w: 5.95, h: 2.0, fill: { color: C.tint }, line: { color: C.tint }, rectRadius: 0.08,
  });
  s.addText('👤 用户价值', {
    x: 7.05, y: 4.85, w: 5.4, h: 0.4, fontSize: 14, bold: true, color: C.cyan, fontFace: FONT_TITLE, margin: 0,
  });
  s.addText([
    { text: '一份 BRIEF.md，一次执行\n', options: { bold: true, color: C.navy, fontSize: 13 } },
    { text: '\n', options: { fontSize: 6 } },
    { text: '拿到既有 ', options: { color: C.gray, fontSize: 13 } },
    { text: '精度', options: { bold: true, color: C.cyan, fontSize: 13 } },
    { text: '  又有  ', options: { color: C.gray, fontSize: 13 } },
    { text: '质感', options: { bold: true, color: C.purple, fontSize: 13 } },
    { text: '  的成片', options: { color: C.gray, fontSize: 13 } },
  ], { x: 7.05, y: 5.3, w: 5.4, h: 1.4, fontFace: FONT_BODY, valign: 'top', margin: 0 });

  addFooter(s, 11, TOTAL);
}

// ============================================================
// Slide 12 — 谢谢 (dark)
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: C.darkBg };

  // decorative
  s.addShape(pres.ShapeType.ellipse, { x: 0.4, y: 0.5, w: 1.2, h: 1.2, fill: { color: C.cyan, transparency: 60 }, line: { color: C.cyan, width: 0 } });
  s.addShape(pres.ShapeType.ellipse, { x: 11.7, y: 5.8, w: 1.6, h: 1.6, fill: { color: C.purple, transparency: 55 }, line: { color: C.purple, width: 0 } });

  s.addText('一句话回顾', {
    x: 0.8, y: 0.6, w: 12, h: 0.6, fontSize: 24, bold: true, color: C.cyan, fontFace: FONT_TITLE, margin: 0,
  });
  s.addShape(pres.ShapeType.line, {
    x: 0.85, y: 1.15, w: 2.0, h: 0, line: { color: C.orange, width: 2 },
  });

  s.addText([
    { text: 'clip-weave', options: { bold: true, color: C.cyan, fontSize: 26 } },
    { text: ' 用一个低摩擦入口（意图路由）+ 三个稳定性解法（规则守卫 / lint 压缩 / 素材匹配），\n把 HyperFrames 从"能渲染视频的框架"变成', options: { color: C.white, fontSize: 22 } },
    { text: '非专业人员也能稳定交付视频的流水线', options: { bold: true, color: C.orange, fontSize: 22 } },
    { text: '。', options: { color: C.white, fontSize: 22 } },
  ], { x: 0.8, y: 1.5, w: 11.7, h: 1.9, fontFace: FONT_BODY, valign: 'top', margin: 0 });

  // Progress + next
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.8, y: 3.7, w: 5.8, h: 2.6, fill: { color: C.navy }, line: { color: C.navy }, rectRadius: 0.1,
  });
  s.addText('当前进展', {
    x: 1.1, y: 3.85, w: 5.2, h: 0.4, fontSize: 16, bold: true, color: C.cyan, fontFace: FONT_TITLE, margin: 0,
  });
  s.addText([
    { text: '✓  P0–P2 全部交付\n', options: { color: C.white, fontSize: 15 } },
    { text: '✓  三种入口可用\n', options: { color: C.white, fontSize: 15 } },
    { text: '✓  33 个测试通过', options: { color: C.white, fontSize: 15 } },
  ], { x: 1.1, y: 4.3, w: 5.2, h: 1.9, fontFace: FONT_BODY, valign: 'top', margin: 0 });

  s.addShape(pres.ShapeType.roundRect, {
    x: 6.75, y: 3.7, w: 5.8, h: 2.6, fill: { color: '2A1B4E' }, line: { color: '2A1B4E' }, rectRadius: 0.1,
  });
  s.addText('下一步', {
    x: 7.05, y: 3.85, w: 5.2, h: 0.4, fontSize: 16, bold: true, color: C.orange, fontFace: FONT_TITLE, margin: 0,
  });
  s.addText([
    { text: '1.  ', options: { color: C.orange, bold: true, fontSize: 15 } },
    { text: '音频切云厂商账号\n     视频从静音到有声\n\n', options: { color: C.white, fontSize: 14 } },
    { text: '2.  ', options: { color: C.orange, bold: true, fontSize: 15 } },
    { text: '验证 STORYBOARD.md 复用于文生视频\n     打开写实画面场景', options: { color: C.white, fontSize: 14 } },
  ], { x: 7.05, y: 4.3, w: 5.2, h: 1.9, fontFace: FONT_BODY, valign: 'top', margin: 0 });

  s.addText('Q & A', {
    x: 0.8, y: 6.5, w: 11.7, h: 0.7, fontSize: 40, bold: true, color: C.cyan, fontFace: FONT_TITLE, align: 'center', margin: 0,
  });
}

pres.writeFile({ fileName: 'docs/clip-weave-presentation-v2.pptx' })
  .then(fn => console.log('WROTE', fn));
