# -*- coding: utf-8 -*-
"""笔记 → 小红书图文卡片 PNG（独立于提取/整理流程）。
封面插画可选接 OpenAI 兼容生图 API（硅基流动 / 豆包 Ark 均可）：
  IMAGE_API_KEY / IMAGE_BASE_URL / IMAGE_MODEL
未配置时用优雅的纯 CSS 封面。三套样式：minimal / cartoon / serif。
"""
import base64, json, os, re, shutil, subprocess, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOTECARDS_DIR = ROOT / 'static' / 'notecards'
PAGE_W, PAGE_H = 1242, 1660
MAX_LINES_PER_PAGE = 9

CHROME_CANDIDATES = [
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
]

STYLE_LABELS = {'minimal': '暖白极简', 'cartoon': '活力卡通', 'serif': '书卷雅致'}


def _env():
    env = {}
    p = ROOT / '.env'
    if p.exists():
        for line in p.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _find_chrome():
    cand = os.environ.get('CHROME_PATH', '')
    if cand and os.path.exists(cand):
        return cand
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    return None


def _strip_md(s):
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'`(.+?)`', r'\1', s)
    return s.strip()


def _safe_title(title):
    s = re.sub(r'[^\w\-.]+', '_', title or 'note').strip('_')[:40] or 'note'
    return s


def _parse(text):
    lines = [l.strip() for l in (text or '').splitlines() if l.strip()]
    summary = ''
    blocks = []
    cur = None
    for l in lines:
        if l.startswith('##'):
            if cur:
                blocks.append(cur)
            cur = {'title': re.sub(r'^#+\s*', '', l), 'lines': []}
            continue
        if not summary and not cur and not blocks:
            summary = l
            continue
        if cur:
            cur['lines'].append(_strip_md(re.sub(r'^[-*]\s+', '', l)))
        else:
            if not blocks:
                blocks.append({'title': '', 'lines': []})
            blocks[0]['lines'].append(_strip_md(re.sub(r'^[-*]\s+', '', l)))
    if cur:
        blocks.append(cur)
    return summary, blocks


def _pages_from_blocks(blocks):
    pages = []
    for b in blocks:
        lines = [l for l in b.get('lines', []) if l]
        if not lines:
            continue
        check = any(k in b['title'] for k in ('要点', '行动', '建议', '总结'))
        for i in range(0, len(lines), MAX_LINES_PER_PAGE):
            pages.append({
                'title': b['title'] + ('（续）' if i else ''),
                'lines': lines[i:i + MAX_LINES_PER_PAGE],
                'check': check,
            })
    return pages


def _ai_cover(summary, title):
    env = _env()
    key = env.get('IMAGE_API_KEY') or os.environ.get('IMAGE_API_KEY') or ''
    if not key:
        return None
    base = (env.get('IMAGE_BASE_URL') or os.environ.get('IMAGE_BASE_URL')
            or 'https://api.siliconflow.cn/v1').rstrip('/')
    model = env.get('IMAGE_MODEL') or os.environ.get('IMAGE_MODEL') or 'black-forest-labs/FLUX.1-schnell'
    mode = (env.get('IMAGE_MODE') or os.environ.get('IMAGE_MODE') or 'openai').strip().lower()
    topic = (summary or title or '学习笔记')[:60]
    prompt = ('扁平插画，低饱和莫兰迪色系，构图简洁，画面通俗易懂，不要出现任何文字，主题：' + topic)
    headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key}
    try:
        if mode == 'dashscope':
            payload = json.dumps({
                'model': model,
                'input': {'messages': [{'role': 'user', 'content': [{'text': prompt}]}]},
                'parameters': {'size': '1024*1024', 'n': 1},
            }).encode('utf-8')
            req = urllib.request.Request(base + '/api/v1/services/aigc/multimodal-generation/generation',
                                         data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            parts = (data.get('output', {}).get('choices') or [{}])[0].get('message', {}).get('content') or []
            img_url = next((it.get('image') for it in parts if isinstance(it, dict) and it.get('image')), None)
            if img_url:
                with urllib.request.urlopen(img_url, timeout=120) as r:
                    return 'data:image/png;base64,' + base64.b64encode(r.read()).decode()
            return None
        payload = json.dumps({'model': model, 'prompt': prompt, 'n': 1, 'size': '1024x1024'}).encode('utf-8')
        req = urllib.request.Request(base + '/images/generations', data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        items = data.get('data') or []
        if not items:
            return None
        b64 = items[0].get('b64_json')
        if b64:
            return 'data:image/png;base64,' + b64
        url = items[0].get('url')
        if url:
            with urllib.request.urlopen(url, timeout=120) as r:
                return 'data:image/png;base64,' + base64.b64encode(r.read()).decode()
    except Exception:
        pass
    return None


CSS_MINIMAL = """\
*{margin:0;padding:0;box-sizing:border-box}
body{width:1242px;height:1660px;overflow:hidden;background:#FAF7F2;font-family:'PingFang SC','Microsoft YaHei',sans-serif}
.page{width:1242px;height:1660px;padding:90px 96px;position:relative;display:flex;flex-direction:column;overflow:hidden}
/* 封面 */
.cover .kicker{font-size:26px;letter-spacing:6px;color:#B09A6F;font-weight:600}
.cover h1{font-family:'STSong','SimSun','Songti SC',serif;font-size:74px;line-height:1.3;color:#2B2620;font-weight:700;margin-top:28px}
.cover .rule{width:72px;height:5px;background:#C9A227;border-radius:3px;margin-top:34px}
.cover .summary{margin-top:40px;font-size:36px;line-height:1.7;color:#57503F;padding:34px 40px;background:#FFFEFB;border:1px solid #EAE1CF;border-radius:18px}
.cover .summary b{color:#A9832A}
.cover .art{flex:1;display:flex;align-items:center;justify-content:center;margin-top:30px}
.cover .aiimg{max-height:600px;max-width:100%;object-fit:contain;border-radius:18px;box-shadow:0 24px 60px rgba(90,75,50,.18)}
.cover .emojibig{font-size:170px}
.cover .foot{position:absolute;bottom:56px;left:96px;right:96px;display:flex;justify-content:space-between;font-size:23px;color:#B5A88D;border-top:1px solid #EBE3D2;padding-top:22px}
/* 内容页 */
.content .head{display:flex;align-items:baseline;gap:26px;margin-bottom:44px}
.content .num{font-family:'STSong',serif;font-size:30px;color:#C9A227;letter-spacing:2px}
.content .num::after{content:' /';color:#DDD2BC}
.content h2{font-family:'STSong','SimSun',serif;font-size:56px;color:#2B2620;font-weight:700}
.content ul{list-style:none;display:flex;flex-direction:column;gap:26px;flex:1}
.content li{font-size:37px;line-height:1.65;color:#4A4438;padding:24px 0 24px 44px;border-bottom:1px solid #F0E9DB;position:relative}
.content li::before{content:'';position:absolute;left:6px;top:40px;width:14px;height:14px;border-radius:50%;background:#C9A227}
.content.check li::before{content:'\\2713';background:none;color:#7A9B57;font-size:26px;top:26px;left:2px;width:auto;height:auto;font-weight:700}
.content .pagefoot{font-size:23px;color:#B5A88D;text-align:center;margin-top:34px}
"""

CSS_CARTOON = """\
*{margin:0;padding:0;box-sizing:border-box}
body{width:1242px;height:1660px;overflow:hidden;background:#FFF6E9;font-family:'PingFang SC','Microsoft YaHei','Arial Rounded MT Bold',sans-serif}
.page{width:1242px;height:1660px;padding:76px 72px;position:relative;display:flex;flex-direction:column;overflow:hidden}
.cover{background:linear-gradient(155deg,#FFE9C7 0%,#FFD8E0 55%,#FFF0E8 100%)}
.cover .badge{display:inline-block;align-self:flex-start;background:#FF7A59;color:#fff;font-size:28px;font-weight:700;padding:14px 30px;border-radius:999px;box-shadow:0 10px 24px rgba(255,122,89,.38)}
.cover h1{font-size:66px;line-height:1.25;color:#3A2E39;font-weight:800;margin-top:36px}
.cover .summary{background:rgba(255,255,255,.9);border-radius:28px;padding:28px 34px;font-size:36px;line-height:1.6;color:#5A4650;margin-top:28px;box-shadow:0 12px 30px rgba(122,88,60,.13)}
.cover .summary b{color:#FF7A59}
.cover .art{flex:1;display:flex;align-items:center;justify-content:center;margin-top:24px}
.cover .aiimg{max-height:580px;max-width:100%;object-fit:contain;border-radius:28px;box-shadow:0 18px 44px rgba(122,88,60,.22)}
.cover .emojibig{font-size:180px}
.cover .foot{position:absolute;bottom:44px;left:72px;right:72px;font-size:24px;color:#A0806A;border-top:2px dashed rgba(160,128,106,.4);padding-top:18px}
.content{background:#FFFDF7}
.content .head{display:flex;align-items:center;gap:24px;margin-bottom:32px}
.content .num{width:92px;height:92px;border-radius:26px;background:#FF7A59;color:#fff;font-size:38px;font-weight:800;display:flex;align-items:center;justify-content:center;box-shadow:0 8px 18px rgba(255,122,89,.35);flex-shrink:0}
.content h2{font-size:48px;color:#3A2E39;font-weight:800}
.content ul{list-style:none;display:flex;flex-direction:column;gap:20px;flex:1}
.content li{font-size:36px;line-height:1.55;color:#5A4650;background:#FFF3E4;border-radius:22px;padding:20px 28px}
.content li::before{content:'\\2022';color:#FF7A59;font-weight:800;margin-right:14px}
.content.check li::before{content:'\\2705';margin-right:12px}
.content .pagefoot{font-size:23px;color:#C0A48E;text-align:center;margin-top:24px}
"""

CSS_SERIF = """\
*{margin:0;padding:0;box-sizing:border-box}
body{width:1242px;height:1660px;overflow:hidden;background:#F3EDE1;font-family:'STSong','SimSun','Songti SC','Source Han Serif SC',serif}
.page{width:1242px;height:1660px;padding:100px 104px;position:relative;display:flex;flex-direction:column;overflow:hidden}
.cover .kicker{font-size:26px;letter-spacing:8px;color:#8B6F47}
.cover h1{font-size:72px;line-height:1.35;color:#3A3328;font-weight:700;margin-top:30px}
.cover .rule{width:90px;height:2px;background:#8B6F47;margin-top:36px}
.cover .summary{margin-top:42px;font-size:34px;line-height:1.8;color:#57493A;border-left:3px solid #B39B77;padding-left:26px}
.cover .summary b{color:#8B6F47}
.cover .art{flex:1;display:flex;align-items:center;justify-content:center;margin-top:34px}
.cover .aiimg{max-height:580px;max-width:100%;object-fit:contain;filter:sepia(.12);border-radius:6px;box-shadow:0 20px 50px rgba(80,60,30,.16)}
.cover .emojibig{font-size:150px}
.cover .foot{position:absolute;bottom:56px;left:104px;right:104px;display:flex;justify-content:center;font-size:22px;color:#A6957A;letter-spacing:3px;border-top:1px solid #D9CDB4;padding-top:24px}
.content .head{margin-bottom:48px;padding-bottom:22px;border-bottom:1px solid #D9CDB4}
.content .num{font-size:26px;color:#B39B77;letter-spacing:3px;margin-bottom:12px}
.content h2{font-size:54px;color:#3A3328;font-weight:700}
.content ul{list-style:none;display:flex;flex-direction:column;gap:30px;flex:1}
.content li{font-size:37px;line-height:1.75;color:#4E4336;padding-left:44px;position:relative}
.content li::before{content:'\\2014';position:absolute;left:4px;top:2px;color:#B39B77;font-size:30px}
.content.check li::before{content:'\\2713';color:#6B7F4F;font-size:28px;top:4px}
.content .pagefoot{font-size:22px;color:#A6957A;text-align:center;margin-top:36px;letter-spacing:2px}
"""

CSS_MAP = {'minimal': CSS_MINIMAL, 'cartoon': CSS_CARTOON, 'serif': CSS_SERIF}


def _cover_html(title, summary, aiimg, css, emoji):
    img = ('<img class="aiimg" src="' + aiimg + '">') if aiimg else '<div class="emojibig">' + emoji + '</div>'
    sm = summary
    if sm.startswith('【'):
        label, _, rest = sm.partition('】')
        sm = '<b>' + label[1:] + '</b>' + rest
    title = (title or 'AI 笔记')[:24]
    body = ('<div class="page cover"><div class="kicker">AI 笔记卡片</div>'
            '<h1>' + title + '</h1><div class="rule"></div>'
            '<div class="summary">' + sm + '</div>'
            '<div class="art">' + img + '</div>'
            '<div class="foot"><span>长视频 → 图文笔记</span><span>通俗易懂</span></div></div>')
    return '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><style>' + css + '</style></head><body>' + body + '</body></html>'


def _page_html(p, idx, total, css):
    items = ''.join('<li>' + _strip_md(l) + '</li>' for l in p['lines'])
    check = ' check' if p.get('check') else ''
    body = ('<div class="page content"><div class="head"><div class="num">%02d</div><h2>%s</h2></div>'
            '<ul%s>%s</ul>'
            '<div class="pagefoot">%d / %d</div></div>'
            % (idx, p['title'] or '笔记要点', check, items, idx, total))
    return '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><style>' + css + '</style></head><body>' + body + '</body></html>'


def _shot(html, out_png):
    chrome = _find_chrome()
    if not chrome:
        return False
    html_path = out_png.with_suffix('.html')
    html_path.write_text(html, encoding='utf-8')
    profile = NOTECARDS_DIR / ('_profile_%d' % int(time.time() * 1000))
    try:
        subprocess.run([chrome, '--headless=new', '--no-sandbox', '--disable-gpu',
                        '--disable-software-rasterizer', '--disable-dev-shm-usage',
                        '--hide-scrollbars', '--user-data-dir=' + str(profile),
                        '--screenshot=' + str(out_png),
                        '--window-size=%d,%d' % (PAGE_W, PAGE_H),
                        html_path.as_uri()],
                       capture_output=True, timeout=90)
        return out_png.exists() and out_png.stat().st_size > 5000
    except Exception:
        return False
    finally:
        try:
            if profile.exists():
                shutil.rmtree(profile, ignore_errors=True)
            if html_path.exists():
                html_path.unlink()
        except Exception:
            pass


def build_note_card(title, text, style='minimal'):
    style = style if style in CSS_MAP else 'minimal'
    css = CSS_MAP[style]
    NOTECARDS_DIR.mkdir(parents=True, exist_ok=True)
    text = (text or '').strip()
    if not text:
        return {'ok': False, 'error': '没有可生成的内容，请先在「笔记生图」里粘贴笔记内容'}
    summary, blocks = _parse(text)
    if not summary:
        first = next((l for l in text.splitlines() if l.strip()), '')
        summary = _strip_md(first)[:60]
    pages = _pages_from_blocks(blocks)
    if not pages:
        lines = [_strip_md(l) for l in text.splitlines() if l.strip()] or ['（内容为空）']
        pages = [{'title': '', 'lines': lines[:MAX_LINES_PER_PAGE], 'check': False}]
    emoji = {'minimal': '📖', 'cartoon': '🎨', 'serif': '🖋'}[style]
    aiimg = _ai_cover(summary, title)
    ts = int(time.time())
    base = _safe_title(title)
    imgs = []
    out = NOTECARDS_DIR / ('%s-%d-00.png' % (base, ts))
    if _shot(_cover_html(title, summary, aiimg, css, emoji), out):
        imgs.append(out)
    for i, p in enumerate(pages, 1):
        out = NOTECARDS_DIR / ('%s-%d-%02d.png' % (base, ts, i))
        if _shot(_page_html(p, i, len(pages), css), out):
            imgs.append(out)
    if not imgs:
        return {'ok': False, 'error': '生成失败：没找到 Chrome/Edge 用于截图渲染'}
    return {
        'ok': True,
        'count': len(imgs),
        'style': STYLE_LABELS[style],
        'images': [{'url': '/notecards/' + im.name, 'path': str(im)} for im in imgs],
        'ai_cover': bool(aiimg),
    }
