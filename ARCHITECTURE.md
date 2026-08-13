# 架构图 · Unified Video Tool

## 整体架构

```mermaid
flowchart TB
    subgraph INPUT[输入层]
        U[用户粘贴链接]
        D[检测平台<br/>douyin/xhs/bilibili/youtube]
    end
    subgraph EXTRACT[提取层]
        DY[抖音专用解析器<br/>douyin_resolver]
        XHS[小红书 OpenCLI<br/>读 Chrome 登录态]
        YT[yt-dlp 通用下载<br/>B站/YouTube]
        WH[本地 Whisper 转写<br/>faster-whisper]
    end
    subgraph PROCESS[加工层]
        AI[DeepSeek AI 整理<br/>结构化 Markdown]
        DECK[长视频 PPT 生成器<br/>关键帧抽取+台词对齐]
    end
    subgraph OUTPUT[输出层]
        O1[Obsidian Vault]
        O2[图文卡片<br/>小红书 3:4]
        O3[单文件 HTML PPT]
    end
    U --> D
    D -->|抖音| DY
    D -->|小红书| XHS
    D -->|B站/YouTube| YT
    DY --> WH
    XHS --> WH
    YT --> WH
    WH --> AI
    WH --> DECK
    AI --> O1
    AI --> O2
    DECK --> O3
```

## 平台路由决策

```mermaid
flowchart TD
    U[链接] --> P{检测域名}
    P -->|douyin.com| DY[抖音专用解析器<br/>移动端 UA 伪装, 无需 Cookie]
    P -->|xiaohongshu.com| XHS[OpenCLI + 页面抓取<br/>复用 Chrome 登录态]
    P -->|bilibili/youtube| YT[yt-dlp 三层降级<br/>best→480p→worst]
    DY --> WH[Whisper 转写]
    XHS --> WH
    YT --> WH
```

## 关键架构决策

| 决策 | 原因 | 位置 |
|------|------|------|
| 抖音走专用解析器 | yt-dlp 对抖音需要 Cookie，被 Chrome 锁读不到；专用解析器用移动端 UA 无需登录 | `server.py process_douyin` |
| 小红书走 OpenCLI | 页面 SSR JSON 有转义问题 parse 失败；OpenCLI 直接读 Chrome 登录态最稳 | `server.py process_xiaohongshu` |
| 三层下载降级 | B站非会员无 1080p 权限，写死 best 会失败；best→480p→worst 兜底 | `server.py process_other` |
| URL 清理 xsec_token | CMD 会把 `&` 当命令分隔符；只保留 xsec_token 参数 | `server.py _xhs_clean_url` |
| 字幕优先 Whisper 兜底 | 有字幕直接读，没字幕才跑本地 Whisper，省时间 | `server.py process_other` |
