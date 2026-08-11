# 视频文案提取 + 长视频图文 PPT

粘贴抖音 / 小红书 / B站 / YouTube 链接 → 本地一键提取文案；长视频还能一键生成「关键帧截图 + 原话语录」的图文 HTML PPT，支持原文 / AI 改版双模式、深色 / 浅色两套皮肤，单文件可直接分享。

## 功能
- **多平台文案提取**：抖音、小红书、B站、YouTube 视频文案（本地下载 + faster-whisper 转写，不依赖付费转写 API）
- **小红书图文笔记**：标题 / 作者 / 正文提取，视频语音自动补充转写
- **AI 整理笔记**：一键把转录文本整理成结构化 Markdown 笔记（DeepSeek / 任何 OpenAI 兼容 API）
- **Obsidian 一键入库**：直接保存到你的 Vault 指定文件夹
- **笔记生图（独立空间）**：粘贴笔记文本→ 小红书 3:4 图文卡片，三套样式（暖白极简/活力卡通/书卷雅致），可配 AI 生图封面
- **长视频 → 图文 PPT**：
  - 自动抽取关键帧（灰度签名去重，跳过重复画面）
  - 台词按时间轴对齐到每一页
  - 「原文」/「AI 改版」两种阅读模式切换
  - 深色阅读风 / 浅色简洁风两套皮肤，Token 化可自定义
  - 生成自包含单文件 HTML（图片 base64 内嵌），`←` `→` 翻页，可发给任何人

## 快速开始
```bash
# 1. 安装依赖
pip install yt-dlp faster-whisper zhconv

# 2. 安装 ffmpeg 并加入 PATH（或修改 server.py / deck.py 里的 FFMPEG 路径）

# 3. 配置 .env（复制 .env.example 并重命名）
copy .env.example .env
# 填入 LLM_API_KEY 与 OBSIDIAN_VAULT

# 4. 启动
python server.py
# 浏览器打开 http://127.0.0.1:5051
```

> 说明：抖音解析复用本地后端 `obsidian-content-capture-backend`（douyin_resolver + whisper pipeline），可修改 `server.py` 中的 `DOUYIN_BACKEND` 换成你自己的实现；其余平台开箱即用。

## 皮肤设计（tastes/）
| 皮肤 | 风格 | 配色要点 |
| --- | --- | --- |
| tcq-dark | 深色阅读风 | 墨黑 `#151616` + 羊皮纸金 `#EEE5AA`，宋体大字重，杂志阅读感 |
| light-minimal | 浅色简洁风 | 纸张白 `#FAFAF8` + 蓝 `#2563EB`，思源宋体 + 大留白，清爽干净 |

皮肤 Token 放在 `tastes/<theme>/tokens.json`，改颜色 / 字体 / 圆角即可定制，无需改代码。

## 目录结构
```
server.py          # 本地 Web 服务（提取 / 整理 / 保存 / 生成 PPT）
deck.py            # 长视频 → 图文 HTML PPT 生成器
tastes/            # 皮肤 Token（两套）
static/decks/      # 生成的 PPT 输出（gitignore）
outputs/           # 下载与转写工作目录（gitignore）
.env               # 本地配置（gitignore，勿提交）
```


## 配置 AI 生图封面（可选）
在 `.env` 里加三行即可，未配置时自动用 CSS 卡片 + emoji 兜底：
```
IMAGE_API_KEY=你的key
IMAGE_BASE_URL=https://api.siliconflow.cn/v1
IMAGE_MODEL=black-forest-labs/FLUX.1-schnell
```
任意 OpenAI 兼容的 `images/generations` 接口，或阿里云百炼的多模态生图接口都可以：
- 硅基流动：`IMAGE_BASE_URL=https://api.siliconflow.cn/v1` + `IMAGE_MODEL=black-forest-labs/FLUX.1-schnell`
- 豆包火山 Ark：`IMAGE_BASE_URL=https://ark.cn-beijing.volces.com/api/v3` + `IMAGE_MODEL=doubao-seedream-3-0-t2i`
## License
MIT
