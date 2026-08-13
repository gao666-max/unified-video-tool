# HANDOFF.md — Unified Video Tool

> AI 接管指引：接手这个项目后，先读本文件，再读 `ARCHITECTURE.md` 了解架构，最后读 `README.md` 了解启动。

## 一句话

粘贴抖音/小红书/B站/YouTube 链接 → 本地提取文案 → AI 整理 → 存 Obsidian 或生成图文 PPT。纯 Python，单文件 Web 服务，本地运行。

## 启动

```bash
python server.py
# 浏览器打开 http://127.0.0.1:5051
```

依赖：`yt-dlp`、`faster-whisper`、`zhconv`、`requests`。ffmpeg 需在 PATH 或改 `server.py` 里的 `FFMPEG` 路径。

## 目录结构

| 路径 | 职责 |
|------|------|
| `server.py` | 单文件 Web 服务（提取/整理/保存/生成PPT 全在这） |
| `deck.py` | 长视频 → 图文 HTML PPT 生成器 |
| `static/` | 前端页面（内嵌在 server.py 的 HTML，实际不读这目录） |
| `tastes/` | 皮肤 Token（tcq-dark / light-minimal 两套） |
| `outputs/` | 下载与转写工作目录（gitignore） |

## 关键环境

| 变量 | 作用 |
|------|------|
| `PROXY` | `http://127.0.0.1:7897`，SakuraCat 代理端口 |
| `FFMPEG` | `D:\ffmpeg\bin\ffmpeg.exe` 硬编码路径 |
| `WHISPER_DIR` | `D:\whisper-models`，本地 Whisper 模型缓存 |
| `DOUYIN_BACKEND` | `D:\obsidian-content-capture-backend`，抖音解析器来源 |
| `VENV_PY` | `D:\obsidian-content-capture-backend\.venv\Scripts\python.exe` |

## 踩过的坑（不要再犯）

1. **CMD 的 `&` 符号**：小红书 URL 里 `xsec_token=...&xsec_source=...` 的 `&` 会被 CMD 当命令分隔符。用 `_xhs_clean_url()` 只保留 xsec_token 参数。
2. **GBK 编码**：subprocess 调 OpenCLI 时 stdout 是 GBK，读中文会报 UnicodeDecodeError。加 `encoding='utf-8', errors='replace'`。
3. **B站 1080p 权限**：非会员没有 1080p，写死 `best[height<=1080]` 直接失败。用三层降级 best→480p→worst。
4. **抖音 yt-dlp 需要 Cookie**：Chrome Cookie 文件被锁，yt-dlp 读不到。抖音必须走专用解析器，不要走 yt-dlp。
5. **小红书 SSR JSON 截断**：`__INITIAL_STATE__` 的 JSON 有嵌套转义问题，正则或 json.loads 都会失败。用 OpenCLI 读 Chrome 登录态最稳。

## 修改约定

- 改 `server.py` 前先 `cp server.py server.py.bak`
- HTML 内嵌在 server.py 的 `HTML` 变量里，改前端要改这里，不是 `static/` 目录
- 启动服务用桌面 `unified-video.bat`（先杀旧进程再启动），不要手动 python 起

## 用户信息

- 用户叫佳慧（高佳慧），软件工程大三，天津
- 不擅长纯编码，用 AI 辅助开发，需要明确流程
- 沟通：直接、口语化，用单行命令，不用多行反斜杠续行
