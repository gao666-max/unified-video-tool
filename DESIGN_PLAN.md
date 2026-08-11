# DESIGN_PLAN — 长视频 → 图文幻灯片（HTML Deck）

接入: capture-taste 项目（来源 tcq.hcds.cc，capture 模式，passive 授权）
皮肤: `tcq-dark`（深色阅读风，已捕获）+ `light-minimal`（浅色简洁风，本项目新设计）

## 产品形态
输入长视频链接 → 输出一页页图文幻灯片（自包含 HTML）：
- 每页上方 = 视频关键帧截图（960px JPG，base64 内嵌）
- 每页下方 = 该时刻讲话原话（原文模式）+ 时间戳
- 一键切换「AI 改版」：同一段话的润色书面版
- 键盘 ←/→ 翻页、点击按钮翻页、可全屏

## tcq-dark 规则映射（来源 taste/tcq, rules/design-rules.json）
- `attention.single-reading-line` → 每屏只有一个视觉焦点：大图 + 一行主引文
- `color.dark-reader-light-tools` → 幻灯片画布=暗色 #151616/#F5F3EE，控件=深灰面 #252626
- `geometry.radius-two-token` → 圆角只有 6px(控件/卡片)，无阴影、无渐变
- `typography.serif-reader-large-line-height` → 引文用中文衬线宋体栈，行高 1.5-1.6
- `restraint.one-primary-action` → 每屏主操作只有「切原文/AI改版」一个
- 强调色唯一 #EEE5AA，只用于时间戳/当前态，面积 <1%

## light-minimal 规则（新组件推导，author 于本项目）
- 白底 #FAFAF8、墨色 #1A1A1A，低信息密度、充足留白
- 强调色单色 #2563EB，只用于时间戳/当前页标识
- 卡片圆角 12px、1px 细边框、无阴影无渐变
- UI 无衬线（Inter 栈），引文衬线可读

## 实现
- `deck.py`: 下载 → 转写(带时间戳 segments) → 关键帧(间隔采样+灰度签名去重) → 台词对齐 → 渲染
- `tastes/<theme>/tokens.json` 驱动 CSS 变量；换皮肤=换 tokens
- `/api/deck?url=&theme=` → 生成到 `static/decks/<file>.html`，浏览器打开 http://127.0.0.1:5051/decks/<file>.html

## 验收
- 每页有截图、有对应时刻原话、有时间戳
- 原文/AI改版可切换（无 key 时自动隐藏改版）
- 两套皮肤均能渲染，无源站品牌元素