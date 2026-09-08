#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长视频 → 图文幻灯片（HTML Deck）
下载视频 → 本地转写(带时间戳) → 关键帧抽取(灰度签名去重) → 台词对齐 → 渲染两套皮肤 HTML。
"""
import base64, json, os, re, subprocess, time, urllib.request, urllib.error
from pathlib import Path

FFMPEG = r'D:\ffmpeg\bin\ffmpeg.exe'
FFMPEG_DIR = r'D:\ffmpeg\bin'
PY_BIN = r'D:\obsidian-content-capture-backend\.venv\Scripts\python.exe'
WHISPER_DIR = r'D:\whisper-models'
PROXY = 'http://127.0.0.1:7897'
ROOT = Path(__file__).resolve().parent
OUTPUT_BASE = ROOT / 'outputs'
DECKS_DIR = ROOT / 'static' / 'decks'
TASTES_DIR = ROOT / 'tastes'
MAX_SLIDES = 24
FRAME_W = 960


def _env():
    e = os.environ.copy()
    e.setdefault('HTTP_PROXY', PROXY); e.setdefault('HTTPS_PROXY', PROXY)
    return e


def _env_file():
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


def load_tokens(theme):
    p = TASTES_DIR / theme / 'tokens.json'
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding='utf-8'))


def list_themes():
    out = []
    if TASTES_DIR.exists():
        for d in sorted(TASTES_DIR.iterdir()):
            t = load_tokens(d.name)
            if t:
                out.append({'name': d.name, 'label': t.get('label', d.name)})
    return out


def download_video(url, vf):
    for strat in [
        ['-f', 'bv*+ba/b', '--merge-output-format', 'mp4', '--ffmpeg-location', FFMPEG_DIR, '--no-playlist', '--no-check-certificates'],
        ['-f', 'bv*[height<=480]+ba/b[height<=480]', '--merge-output-format', 'mp4', '--ffmpeg-location', FFMPEG_DIR, '--no-playlist', '--no-check-certificates'],
        ['-f', 'wv*+wa/w', '--merge-output-format', 'mp4', '--ffmpeg-location', FFMPEG_DIR, '--no-playlist', '--no-check-certificates'],
    ]:
        try:
            subprocess.run([PY_BIN, '-m', 'yt_dlp', '-o', str(vf)] + strat + [url],
                           capture_output=True, timeout=300, check=True, env=_env())
            if vf.exists() and vf.stat().st_size > 10000:
                return True
        except Exception:
            pass
    return False


def transcribe_segments(vf, wd):
    af = wd / 'audio.wav'
    subprocess.run([FFMPEG, '-y', '-i', str(vf), '-vn', '-acodec', 'pcm_s16le',
                    '-ar', '16000', '-ac', '1', str(af)], capture_output=True, timeout=180, check=True)
    import transcribe_engine
    return transcribe_engine.transcribe_whisper_segments(str(af))


def _duration(vf):
    r = subprocess.run([FFMPEG, '-i', str(vf)], capture_output=True, text=True)
    m = re.search(r'Duration: (\d+):(\d+):(\d+\.?\d*)', r.stderr or '')
    if not m:
        return 0.0
    h, mm, ss = m.groups()
    return int(h) * 3600 + int(mm) * 60 + float(ss)


def _frame_sig(vf, ts):
    try:
        r = subprocess.run([FFMPEG, '-ss', str(ts), '-i', str(vf), '-frames:v', '1',
                            '-vf', 'scale=16:16,format=gray', '-f', 'rawvideo', '-'],
                           capture_output=True, timeout=30)
        return r.stdout or b''
    except Exception:
        return b''


def _sig_diff(a, b):
    if not a or not b or len(a) != len(b):
        return 1.0
    return sum(1 for x, y in zip(a, b) if abs(x - y) > 12) / max(1, len(a))


def extract_frames(vf, wd, dur, max_slides=MAX_SLIDES, dedupe=0.12):
    if dur <= 0:
        dur = 60.0
    interval = max(4.0, dur / max_slides)
    frames_dir = wd / 'frames'
    frames_dir.mkdir(exist_ok=True)
    frames = []
    last_sig = None
    t = 1.0
    while t < dur and len(frames) < max_slides:
        img = frames_dir / ('%03d.jpg' % len(frames))
        subprocess.run([FFMPEG, '-ss', str(t), '-i', str(vf), '-frames:v', '1',
                        '-vf', 'scale=%d:-2' % FRAME_W, '-q:v', '3', '-y', str(img)],
                       capture_output=True, timeout=60)
        if not img.exists() or img.stat().st_size < 2000:
            t += interval
            continue
        sig = _frame_sig(vf, t)
        if last_sig is not None and _sig_diff(sig, last_sig) < dedupe:
            try:
                img.unlink()
            except Exception:
                pass
            t += interval
            continue
        last_sig = sig
        frames.append({'time': round(t, 1), 'img': str(img)})
        t += interval
    return frames


def _pick_quote(segments, t):
    best = None
    for s in segments:
        if s['start'] <= t <= s['end']:
            return s
        if best is None or abs(s['start'] - t) < abs(best['start'] - t):
            best = s
    return best


def ai_polish_quotes(title, quotes):
    env = _env_file()
    key = env.get('LLM_API_KEY') or os.environ.get('LLM_API_KEY') or ''
    if not key:
        return None
    base = (env.get('LLM_BASE_URL') or os.environ.get('LLM_BASE_URL') or 'https://api.deepseek.com/v1').rstrip('/')
    model = env.get('LLM_MODEL') or os.environ.get('LLM_MODEL') or 'deepseek-chat'
    system = ('你是中文笔记润色助手。把视频每段原话润色成书面中文：修正错别字、去掉口语和重复、'
              '保留数字人名术语等事实。要求：输入几个元素就输出几个元素的 JSON 数组，数量严格一致，'
              '禁止合并或拆分任何一条。只输出 JSON 数组，不要输出其它内容。')
    strict_system = system + ' 再次强调：数组长度必须与输入完全一致，逐条一一对应，不许合并或拆分。'

    def _call(sysmsg):
        payload = {
            'model': model,
            'messages': [{'role': 'system', 'content': sysmsg},
                         {'role': 'user', 'content': json.dumps(quotes, ensure_ascii=False)}],
            'temperature': 0.2,
            'max_tokens': 4000,
        }
        req = urllib.request.Request(base + '/chat/completions',
                                     data=json.dumps(payload).encode('utf-8'),
                                     headers={'Content-Type': 'application/json',
                                              'Authorization': 'Bearer ' + key})
        # DeepSeek 国内站直连，禁用系统代理
        no_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with no_proxy.open(req, timeout=180) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        content = (data.get('choices') or [{}])[0].get('message', {}).get('content', '')
        m = re.search(r'\[.*\]', content or '', re.S)
        arr = json.loads(m.group(0)) if m else None
        if not isinstance(arr, list):
            return None
        return [str(x) for x in arr]

    arr = None
    try:
        arr = _call(system)
    except Exception:
        pass
    if not arr or len(arr) != len(quotes):
        try:
            arr2 = _call(strict_system)
            if arr2 and len(arr2) == len(quotes):
                arr = arr2
        except Exception:
            pass
    if not arr:
        return None
    if len(arr) == len(quotes):
        return arr
    # 个别情况下模型仍会合并条目：按顺序比例映射回各页，保证每页都有改版
    n, m = len(quotes), len(arr)
    return [arr[min(m - 1, int(i * m / n))] for i in range(n)]


def _fmt_time(sec):
    sec = int(round(sec))
    return '%02d:%02d' % (sec // 60, sec % 60)


def _css_var(tokens):
    c = tokens['color']; t = tokens['typography']; r = tokens['radius']
    return (':root{--bg:%(bg)s;--surface:%(surface)s;--text:%(text)s;--muted:%(muted)s;'
            '--border:%(border)s;--accent:%(accent)s;--controlBg:%(controlBg)s;'
            '--radius:%(card)s;--radiusCtl:%(control)s;--serif:%(serif)s;--ui:%(ui)s;'
            '--mono:%(mono)s;--quoteSize:%(quoteSize)s;--titleSize:%(titleSize)s}'
            % dict(c, **t, **r))


def render_deck(title, slides, theme, tokens, source_url):
    css = _css_var(tokens)
    data = json.dumps({'title': title, 'theme': theme, 'slides': slides}, ensure_ascii=False)
    html = '''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>@TITLE@</title>
<style>
@CSS@
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--ui);height:100vh;overflow:hidden}
.bar{position:fixed;top:0;left:0;right:0;display:flex;align-items:center;justify-content:space-between;
gap:10px;padding:12px 3vw;z-index:20;background:var(--bg);border-bottom:1px solid var(--border)}
.bar .tt{font-family:var(--serif);font-size:15px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar .ctr{display:flex;gap:8px;align-items:center;flex-shrink:0}
.bar button{background:var(--controlBg);color:var(--text);border:1px solid var(--border);border-radius:var(--radiusCtl);
padding:7px 13px;font-size:12px;cursor:pointer;font-family:var(--ui)}
.bar button.on{color:var(--accent);border-color:var(--accent)}
.count{color:var(--muted);font-family:var(--mono);font-size:12px}
.slide{position:absolute;inset:0;top:56px;display:none;flex-direction:column;padding:3vh 3vw 6vh;gap:2vh}
.slide.on{display:flex}
.frame{flex:1;min-height:0;display:flex;align-items:center;justify-content:center;
background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden}
.frame img{max-width:100%;max-height:100%;object-fit:contain}
.quote{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
padding:18px 22px;max-height:34vh;overflow-y:auto}
.quote .meta{display:flex;gap:10px;align-items:center;margin-bottom:8px;color:var(--muted);font-size:12px}
.quote .ts{color:var(--accent);font-family:var(--mono);font-weight:600}
.quote .txt{font-family:var(--serif);font-size:var(--quoteSize);line-height:1.55;color:var(--text)}
.empty{color:var(--muted);font-family:var(--serif);font-size:20px}
.hint{position:fixed;left:50%;bottom:8px;transform:translateX(-50%);color:var(--muted);
font-size:11px;z-index:20;opacity:.7}
::-webkit-scrollbar{width:5px}::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}
</style></head><body>
<div class="bar"><div class="tt"></div>
<div class="ctr"><button id="mode" class="on">原文</button><span class="count"></span></div></div>
<div class="hint">← → 翻页 · AI改版需在页面上切换</div>
<div id="deck"></div>
<script id="data" type="application/json">@DATA@</script>
<script>
var D=JSON.parse(document.getElementById('data').textContent);
var cur=0, mode=0, slides=D.slides;
var deck=document.getElementById('deck');
function el(tag,cls){var e=document.createElement(tag);if(cls)e.className=cls;return e}
function show(){
  document.querySelectorAll('.slide').forEach(function(s){s.classList.remove('on')});
  var s=slides[cur];
  var node=document.createElement('div');node.className='slide on';
  var fr=el('div','frame');
  if(s.img){var im=document.createElement('img');im.src=s.img;im.alt='';fr.appendChild(im)}
  node.appendChild(fr);
  var q=el('div','quote');
  var meta=el('div','meta');
  var ts=el('span','ts');ts.textContent=s.time;
  var idx=el('span');idx.textContent=(cur+1)+' / '+slides.length;
  meta.appendChild(ts);meta.appendChild(idx);
  var txt=el('div','txt');txt.textContent=mode? (s.polish||s.text) : s.text;
  if(!s.text&&!s.polish){txt.className='empty';txt.textContent='（此段无语音）'}
  q.appendChild(meta);q.appendChild(txt);
  node.appendChild(q);
  deck.innerHTML='';deck.appendChild(node);
  document.querySelector('.tt').textContent=D.title;
  document.querySelector('.count').textContent=(cur+1)+' / '+slides.length;
  document.querySelector('#mode').textContent=mode?'AI改版':'原文';
  document.querySelector('#mode').classList.toggle('on',!mode);
}
document.addEventListener('keydown',function(e){
  if(e.key==='ArrowRight'&&cur<slides.length-1){cur++;show()}
  if(e.key==='ArrowLeft'&&cur>0){cur--;show()}
});
document.getElementById('mode').addEventListener('click',function(){mode=mode?0:1;show()});
document.body.addEventListener('click',function(e){
  var r=e.target.closest?e.target.closest('.frame,.bar'):null;
  if(r&&slides.length>1){var x=e.clientX;if(x>window.innerWidth*0.7&&cur<slides.length-1){cur++;show()}
  else if(x<window.innerWidth*0.3&&cur>0){cur--;show()}}
});
show();
</script></body></html>
'''.replace('@TITLE@', title).replace('@CSS@', css).replace('@DATA@', data)
    return html


def build_deck(url, theme='tcq-dark', with_polish=True):
    tokens = load_tokens(theme)
    if not tokens:
        return {'ok': False, 'error': '皮肤不存在: %s' % theme}
    out = OUTPUT_BASE
    out.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[^\w\-.]+', '_', url.split('/')[-1] or 'video').strip('_.')[:40] or 'video'
    wd = out / ('deck_%s_%d' % (safe, int(time.time())))
    wd.mkdir(parents=True, exist_ok=True)
    vf = wd / 'video.mp4'
    if not download_video(url, vf):
        return {'ok': False, 'error': '视频下载失败，请确认链接和代理'}
    try:
        segments = transcribe_segments(vf, wd)
    except Exception as e:
        return {'ok': False, 'error': '转写失败: %s' % e}
    dur = _duration(vf)
    frames = extract_frames(vf, wd, dur)
    if not frames:
        return {'ok': False, 'error': '没有抽到关键帧'}
    slides = []
    for f in frames:
        q = _pick_quote(segments, f['time'])
        slides.append({
            'time': _fmt_time(f['time']),
            'img': 'data:image/jpeg;base64,' + base64.b64encode(Path(f['img']).read_bytes()).decode(),
            'text': (q or {}).get('text', ''),
        })
    polished = None
    if with_polish:
        quotes = [s['text'] for s in slides if s['text']]
        if quotes:
            arr = ai_polish_quotes(url, quotes)
            if arr:
                polished = iter(arr)
    for s in slides:
        if s['text'] and polished is not None:
            s['polish'] = next(polished, '')
    html = render_deck('视频笔记 · ' + safe, slides, theme, tokens, url)
    DECKS_DIR.mkdir(parents=True, exist_ok=True)
    fname = '%s-%s.html' % (safe[:30], int(time.time()))
    fpath = DECKS_DIR / fname
    fpath.write_text(html, encoding='utf-8')
    return {'ok': True, 'file': fname, 'url': '/decks/' + fname, 'path': str(fpath),
            'slides': len(slides), 'theme': theme, 'label': tokens.get('label', theme)}