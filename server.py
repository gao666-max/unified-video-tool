#!/usr/bin/env python3
"""粘贴即解析 —— 抖音/小红书/B站/YouTube 统一视频文案提取。单文件，零依赖。"""

import http.server, json, os, re, shutil, subprocess, sys, time, urllib.parse, urllib.request
from pathlib import Path

# 清掉系统代理环境变量（Clash 没开时 127.0.0.1:7890 会劫持所有国内站请求）
# B站/YouTube 走下方 net_env() 显式加 PROXY，抖音/DeepSeek/图片 API 国内站直连
for _k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy'):
    os.environ.pop(_k, None)

PROXY = 'http://127.0.0.1:7897'
FFMPEG = r'D:\ffmpeg\bin\ffmpeg.exe'
FFMPEG_DIR = r'D:\ffmpeg\bin'
WHISPER_DIR = r'D:\whisper-models'
DOUYIN_BACKEND = r'D:\obsidian-content-capture-backend'
OUTPUT_BASE = os.environ.get('VIDEO_EXTRACT_OUT', r'D:\unified-video-tool\outputs')

VENV_PY = r'D:\obsidian-content-capture-backend\.venv\Scripts\python.exe'
PY_BIN = VENV_PY if os.path.exists(VENV_PY) else sys.executable

# ---------------- 配置（支持 .env / 环境变量） ----------------
def _load_env():
    env = {}
    env_file = Path(__file__).resolve().parent / '.env'
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env

_ENV = _load_env()

def _cfg(key, default=''):
    return os.environ.get(key) or _ENV.get(key) or default

OBSIDIAN_VAULT = Path(_cfg('OBSIDIAN_VAULT', r'C:\Users\TX\Documents\Obsidian Vault'))
OBSIDIAN_FOLDER = _cfg('OBSIDIAN_FOLDER', '视频笔记')
LLM_API_KEY = _cfg('LLM_API_KEY') or _cfg('OPENAI_API_KEY') or _cfg('DEEPSEEK_API_KEY')
LLM_BASE_URL = _cfg('LLM_BASE_URL', 'https://api.deepseek.com/v1').rstrip('/')
LLM_MODEL = _cfg('LLM_MODEL', 'deepseek-chat')

if DOUYIN_BACKEND not in sys.path:
    sys.path.insert(0, DOUYIN_BACKEND)

import deck  # 同目录 deck.py：长视频 → 图文 PPT
import notecard  # 同目录 notecard.py：笔记 → 图文卡片 PNG
DECKS_DIR = Path(__file__).resolve().parent / 'static' / 'decks'

def detect(url):
    d = urllib.parse.urlparse(url).netloc.lower()
    if any(k in d for k in ('douyin.com','iesdouyin.com')): return 'douyin'
    if any(k in d for k in ('xiaohongshu.com','xhslink.com')): return 'xiaohongshu'
    if any(k in d for k in ('bilibili.com','b23.tv')): return 'bilibili'
    if any(k in d for k in ('youtube.com','youtu.be')): return 'youtube'
    return 'unknown'

def net_env():
    e = os.environ.copy()
    e.setdefault('HTTP_PROXY', PROXY); e.setdefault('HTTPS_PROXY', PROXY)
    return e

def log_line(msg):
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'server.log'), 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S') + ' ' + msg + '\n')
    except Exception:
        pass

def process_douyin(url, wd):
    """抖音解析：改用 OpenCLI 浏览器（登录态）拿标题/文案，再用 network 捕获视频 CDN 地址下载。
    旧的 SSR 分享页解析已失效（抖音 2026.8 反爬升级，_ROUTER_DATA 不再内嵌数据）。"""
    import requests
    opencli_bin = r'C:\Users\TX\AppData\Roaming\npm\opencli.cmd'
    env = os.environ.copy()
    for k in ('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy'):
        env.pop(k, None)  # 抖音国内站直连，不走代理

    # 1. 从分享链接解析出视频页 URL（短链重定向）
    video_url = url
    try:
        from script.douyin_resolver import expand_share_url, normalize_to_share_page
        import requests
        share = expand_share_url(url)
        s = requests.Session(); s.trust_env = False
        s.headers.update({'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'})
        r = s.get(share, allow_redirects=True, timeout=20)
        final = str(r.url)
        m = re.search(r'/video/(\d+)', final)
        if m:
            video_url = f'https://www.douyin.com/video/{m.group(1)}'
    except Exception as e:
        log_line('douyin-redirect-err ' + str(e)[:100])

    title = desc = author = ''
    # 2. OpenCLI 浏览器打开视频页，eval 拿标题/文案
    session = 'dy_' + str(int(time.time()))
    try:
        subprocess.run([opencli_bin,'--profile','yaaqs4cg','browser',session,'open',video_url,'--window','background'],
            capture_output=True, text=True, timeout=40, env=env, encoding='utf-8', errors='replace')
        time.sleep(5)
        js = "JSON.stringify({t:document.title.replace(' - 抖音','').trim(), d:(document.querySelector('meta[name=description]')||{}).content||''})"
        r = subprocess.run([opencli_bin,'--profile','yaaqs4cg','browser',session,'eval',js],
            capture_output=True, text=True, timeout=30, env=env, encoding='utf-8', errors='replace')
        # eval 输出带 node 警告前缀，取最后一行非空 JSON
        lines = [l for l in r.stdout.splitlines() if l.strip().startswith('{')]
        if lines:
            try:
                data = json.loads(lines[-1])
                title = (data.get('t') or '').strip()
                desc = (data.get('d') or '').strip()
            except Exception:
                pass
    except Exception as e:
        log_line('douyin-browser-err ' + str(e)[:100])
    finally:
        try:
            subprocess.run([opencli_bin,'--profile','yaaqs4cg','browser',session,'close'],
                capture_output=True, text=True, timeout=15, env=env)
        except Exception:
            pass

    # 3. 尝试下载视频并转写
    transcript = ''
    if not title and not desc:
        return {'ok': False, 'error': '抖音解析失败：请确认已用 opencli douyin login 登录抖音（浏览器登录态）。'}

    # 用独立 session：打开页面同时 network --follow 监听，刷新触发视频加载，抓 douyinvod CDN 地址
    dl_session = 'dydl_' + str(int(time.time()))
    net_file = wd / 'network.log'
    try:
        subprocess.run([opencli_bin,'--profile','yaaqs4cg','browser',dl_session,'open',video_url,'--window','background'],
            capture_output=True, text=True, timeout=40, env=env, encoding='utf-8', errors='replace')
        time.sleep(3)
        # 后台启动 network --follow，输出重定向到文件（避免 PIPE 阻塞）
        with open(net_file, 'w', encoding='utf-8') as nf:
            net_proc = subprocess.Popen(
                [opencli_bin,'--profile','yaaqs4cg','browser',dl_session,'network','--follow','--all'],
                stdout=nf, stderr=subprocess.DEVNULL, text=True, env=env, encoding='utf-8', errors='replace')
            # 刷新页面触发视频地址请求
            time.sleep(1)
            subprocess.run([opencli_bin,'--profile','yaaqs4cg','browser',dl_session,'eval','location.reload()'],
                capture_output=True, text=True, timeout=20, env=env, encoding='utf-8', errors='replace')
            time.sleep(8)
            net_proc.terminate()
            try:
                net_proc.wait(timeout=5)
            except Exception:
                net_proc.kill()
        # 读文件找 douyinvod mp4 地址
        net_output = net_file.read_text(encoding='utf-8', errors='ignore') if net_file.exists() else ''
        m = re.search(r'https?://[^"\'\s]*douyinvod\.com[^"\'\s]*video_mp4[^"\'\s]*', net_output)
        if m:
            vurl = m.group(0).replace('\\u002F','/').replace('\\/','/')
            vf = wd / 'video.mp4'
            # 直连下载（抖音 CDN 国内站，不走代理）
            s2 = requests.Session(); s2.trust_env = False
            s2.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://www.douyin.com/'})
            with s2.get(vurl, stream=True, timeout=120) as resp:
                resp.raise_for_status()
                with open(vf,'wb') as f:
                    shutil.copyfileobj(resp.raw, f)
            if vf.exists() and vf.stat().st_size > 10000:
                wtxt = transcribe_video(vf, wd)
                if wtxt.strip():
                    transcript = wtxt
    except Exception as e:
        log_line('douyin-dl-err ' + str(e)[:100])
    finally:
        try:
            subprocess.run([opencli_bin,'--profile','yaaqs4cg','browser',dl_session,'close'],
                capture_output=True, text=True, timeout=15, env=env)
        except Exception:
            pass

    body = transcript if transcript.strip() else desc
    if not body.strip(): body = title
    (wd/'transcript.txt').write_text(
        f"标题:{title}\n作者:{author}\n来源:{url}\n平台:douyin\n\n--- 文案 ---\n\n{body}",
        encoding='utf-8')
    return {'ok': True, 'title': title or '抖音视频', 'platform': 'douyin',
            'text': body[:8000], 'words': len(body.replace('\n','').replace(' ','')), 'dir': str(wd)}

def transcribe_video(vf, wd):
    """ffmpeg 抽音频 -> faster-whisper 本地转写 -> 简体中文。失败返回空串。"""
    try:
        af = str(wd / 'audio.wav')
        subprocess.run([FFMPEG,'-y','-i',str(vf),'-vn','-acodec','pcm_s16le','-ar','16000','-ac','1',af],
            capture_output=True, timeout=180, check=True)
        from faster_whisper import WhisperModel
        import zhconv
        model = WhisperModel('small', device='cpu', compute_type='int8', cpu_threads=8,
            download_root=WHISPER_DIR, local_files_only=True)
        segs, _ = model.transcribe(af, language='zh', vad_filter=True, beam_size=5)
        return zhconv.convert('\n'.join(s.text.strip() for s in segs if s.text.strip()), 'zh-cn')
    except Exception:
        return ''

def _xhs_clean_url(url):
    import urllib.parse as _up
    _parsed = _up.urlparse(url)
    _q = _up.parse_qs(_parsed.query, keep_blank_values=True)
    _keep = {k: v for k, v in _q.items() if k == 'xsec_token'}
    _new_q = _up.urlencode(_keep, doseq=True)
    return _up.urlunparse((_parsed.scheme, _parsed.netloc, _parsed.path, _parsed.params, _new_q, _parsed.fragment))

def _xhs_unescape(s):
    s = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)
    return s.replace('\\n', '\n').replace('\\t', '').replace('\\/', '/').replace('\\"', '"')

def process_xiaohongshu(url, wd):
    """小红书：OpenCLI 取标题/作者/正文 + 页面抓取视频流 -> 下载 -> 本地转写。
    视频缺失或转写失败时退化为返回正文文案。"""
    env = os.environ.copy()
    env.setdefault('HTTP_PROXY', PROXY); env.setdefault('HTTPS_PROXY', PROXY)
    env.setdefault('OPENCLI_PROFILE', 'yaaqs4cg')
    opencli_bin = r'C:\Users\TX\AppData\Roaming\npm\opencli.cmd'

    title, author, caption = '', '', ''
    try:
        r = subprocess.run([opencli_bin,'xiaohongshu','note', _xhs_clean_url(url), '-f', 'json'],
            capture_output=True, text=True, timeout=30, env=env, encoding='utf-8', errors='replace')
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            if isinstance(data, list):
                info = {it.get('field',''): it.get('value','') for it in data if isinstance(it, dict)}
            else:
                info = data if isinstance(data, dict) else {}
            title = (info.get('title') or '').strip()
            author = (info.get('author') or '').strip()
            caption = (info.get('content') or '').strip()
    except Exception as e:
        log_line('xhs-opencli-err url=' + url[:80] + ' err=' + str(e)[:100])
        pass  # OpenCLI 失败不阻塞，继续走页面抓取

    video_url, desc, page_title = '', '', ''
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'http': PROXY, 'https': PROXY}))
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
            'Referer': 'https://www.xiaohongshu.com/',
        })
        html = opener.open(req, timeout=25).read().decode('utf-8', errors='ignore')
        for pat in (r'"masterUrl":"([^"]+)"', r'"streamUrl":"([^"]+)"', r'"videoUrl":"([^"]+)"'):
            m = re.search(pat, html)
            if m:
                video_url = m.group(1).replace('\\u002F','/').replace('\\/','/')
                break
        m = re.search(r'"desc":"([^"]+)"', html)
        if m: desc = _xhs_unescape(m.group(1)).strip()
        m = re.search(r'"title":"([^"]+)"', html)
        if m: page_title = _xhs_unescape(m.group(1)).strip()
    except Exception:
        pass

    if not title: title = page_title
    if not caption and desc: caption = desc

    transcript = caption
    if video_url:
        try:
            req = urllib.request.Request(video_url, headers={
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
                'Referer': 'https://www.xiaohongshu.com/',
            })
            vf = wd / 'video.mp4'
            with opener.open(req, timeout=240) as resp, open(vf, 'wb') as f:
                shutil.copyfileobj(resp, f)
            if vf.stat().st_size > 10000:
                whisper_txt = transcribe_video(vf, wd)
                if whisper_txt.strip():
                    transcript = (caption + '\n\n--- 视频语音转写 ---\n\n' + whisper_txt) if caption.strip() else whisper_txt
        except Exception:
            pass

    if not transcript.strip():
        log_line('xhs-fail url=' + url[:80] + ' opencli_title=' + str(bool(title)) + ' page_title=' + str(bool(page_title)) + ' video=' + str(bool(video_url)) + ' desc=' + str(bool(desc)))
        return {'ok': False, 'error': '未提取到内容：可能是纯图片图文笔记（文字在图片里）或链接已失效'}

    display_title = f"{title} - {author}" if (title and author) else (title or '小红书笔记')
    (wd/'transcript.txt').write_text(
        f"标题:{display_title}\n作者:{author}\n来源:{url}\n平台:xiaohongshu\n\n--- 文案 ---\n\n{transcript}",
        encoding='utf-8')
    return {'ok': True, 'title': display_title, 'platform': 'xiaohongshu',
            'text': transcript[:8000], 'words': len(transcript.replace('\n','').replace(' ','')), 'dir': str(wd)}

def process_other(url, wd, platform):
    if '://' not in url or not urllib.parse.urlparse(url).netloc:
        return {'ok': False, 'error': '\u672a\u8bc6\u522b\u5230\u6709\u6548\u94fe\u63a5\uff0c\u8bf7\u7c98\u8d34\u5b8c\u6574\u94fe\u63a5'}
    vf = wd / 'video.mp4'; env = net_env()
    for strat in [['-f','bv*+ba/b','--merge-output-format','mp4','--ffmpeg-location',FFMPEG_DIR,'--no-playlist','--no-check-certificates'],
                  ['-f','bv*[height<=480]+ba/b[height<=480]','--merge-output-format','mp4','--ffmpeg-location',FFMPEG_DIR,'--no-playlist','--no-check-certificates'],
                  ['-f','wv*+wa/w','--merge-output-format','mp4','--ffmpeg-location',FFMPEG_DIR,'--no-playlist','--no-check-certificates']]:
        try:
            r = subprocess.run([PY_BIN,'-m','yt_dlp','-o',str(vf)]+strat+[url],
                capture_output=True, timeout=300, check=True, env=env)
            break
        except subprocess.CalledProcessError as e:
            log_line('ytdlp-err strat=' + str(strat[1]) + ' url=' + url[:90] + ' rc=' + str(e.returncode) + ' err=' + (e.stderr or b'')[-300:].decode('utf-8','ignore'))
        except Exception as e:
            log_line('ytdlp-err strat=' + str(strat[1]) + ' url=' + url[:90] + ' ex=' + str(e)[:300])
    else:
        return {'ok': False, 'error': '下载失败。B站/YouTube请确认代理已开；小红书视频请先在Chrome登录后重试'}

    text = ''
    try:
        subprocess.run([PY_BIN,'-m','yt_dlp','--write-subs','--write-auto-subs','--sub-lang','zh-Hans,zh-CN,zh,en',
            '--sub-format','vtt','--skip-download','--no-check-certificates','-o',str(wd/'%(title)s.%(ext)s'),url],
            capture_output=True, timeout=60, env=env)
        for ext in ('*.vtt','*.srt'):
            for f in wd.glob(ext):
                t = f.read_text(encoding='utf-8', errors='ignore')
                lines = [re.sub(r'<[^>]+>','',l.strip()) for l in t.split('\n')
                    if l.strip() and not l.strip().isdigit() and '-->' not in l and 'WEBVTT' not in l]
                text = '\n'.join(lines)
                if text.strip(): break
            if text.strip(): break
    except: pass

    if not text.strip() and vf.exists():
        text = transcribe_video(vf, wd)

    (wd/'transcript.txt').write_text(f"标题:{wd.name}\n来源:{url}\n\n---\n{text}", encoding='utf-8')
    return {'ok': True, 'title': wd.name, 'platform': platform,
            'text': text[:8000], 'words': len(text.replace('\n','').replace(' ','')), 'dir': str(wd)}

def _extract_url(text):
    m = re.search(r'https?://[^\s<>"\']+', text or '')
    if not m: return (text or '').strip()
    u = m.group(0).rstrip('.,;:!?)]}>\u3002\uff0c\u3001\u300b\u300a\u3011\u3010\u300d\u300c\u201d\u2019\u3000')
    return u


def organize_with_llm(title, text):
    if not LLM_API_KEY:
        return {'ok': False, 'error': '未配置 LLM API Key，请在 D:\\unified-video-tool\\.env 里填写 LLM_API_KEY（DeepSeek/OpenAI 兼容均可）'}
    if not text or not text.strip():
        return {'ok': False, 'error': '没有可整理的内容'}
    system = ('你是一个中文笔记整理助手。把用户提供的视频转录文本整理成一篇结构清晰、逻辑清楚的 Markdown 笔记。'
        '要求：1) 先给一行【一句话总结】；2) 正文按逻辑分小节，用 ## 或 ### 标题；3) 关键信息用列表和加粗；'
        '4) 修正错别字、去口语和重复，但保留数字、人名、术语等事实；5) 最后给【核心要点】列表和【行动建议】（如适用）；6) 只输出整理后的笔记正文，不要解释。')
    user = f'标题：{title}\n\n转录文本：\n{text[:12000]}'
    payload = json.dumps({
        'model': LLM_MODEL,
        'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
        'temperature': 0.3,
        'max_tokens': 4000,
    }).encode('utf-8')
    req = urllib.request.Request(LLM_BASE_URL + '/chat/completions', data=payload,
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + LLM_API_KEY})
    # DeepSeek 国内站直连，禁用系统代理（否则被挂掉的 Clash 劫持导致 10061）
    no_proxy_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with no_proxy_opener.open(req, timeout=180) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        content = (data.get('choices') or [{}])[0].get('message', {}).get('content', '')
        if not content:
            return {'ok': False, 'error': 'AI 返回为空，请检查模型名或 Key'}
        return {'ok': True, 'text': content.strip()}
    except urllib.error.HTTPError as e:
        return {'ok': False, 'error': 'API 错误 %s: %s' % (e.code, e.read().decode('utf-8', 'ignore')[:200])}
    except Exception as e:
        return {'ok': False, 'error': 'AI 请求失败: %s' % e}

def save_to_obsidian(title, text):
    if not text or not text.strip():
        return {'ok': False, 'error': '没有可保存的内容'}
    try:
        folder = OBSIDIAN_VAULT / OBSIDIAN_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        safe_title = re.sub(r'[<>:"/\\|?*#\[\]]', '_', (title or '笔记').strip())[:60] or '笔记'
        fn = time.strftime('%Y-%m-%d') + '-' + safe_title + '.md'
        path = folder / fn
        content = '# ' + (title or safe_title) + '\n\n> 来源：视频提取\n> 保存：' + time.strftime('%Y-%m-%d %H:%M') + '\n\n---\n\n' + text
        path.write_text(content, encoding='utf-8')
        return {'ok': True, 'path': str(path), 'filename': fn}
    except Exception as e:
        return {'ok': False, 'error': '保存失败: %s' % e}

def handle_api(path, body):
    data = json.loads(body.lstrip('\ufeff')) if body else {}
    url = _extract_url((data.get('url') or '').strip())
    if not url or '://' not in url:
        return 400, {'ok': False, 'error': '\u672a\u8bc6\u522b\u5230\u6709\u6548\u94fe\u63a5\u3002\u8bf7\u53ea\u7c98\u8d34\u89c6\u9891/\u7b14\u8bb0\u94fe\u63a5\uff0c\u6216\u4ece\u5206\u4eab\u6587\u672c\u4e2d\u590d\u5236\u5b8c\u6574\u94fe\u63a5'}

    platform = detect(url)
    out = Path(OUTPUT_BASE); out.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[^\w\-.]+','_', url.split('/')[-1] or 'video').strip('_.')[:50] or 'video'
    wd = out / f'{safe}_{int(time.time())}'; wd.mkdir(parents=True, exist_ok=True)

    if platform == 'douyin': result = process_douyin(url, wd)
    elif platform == 'xiaohongshu': result = process_xiaohongshu(url, wd)
    else: result = process_other(url, wd, platform)
    log_line('req platform=' + platform + ' ok=' + str(result.get('ok')) + ' err=' + str(result.get('error', ''))[:120] + ' url=' + url[:90])

    return 200, result

HTML = r'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>视频文案提取</title>
<style>:root{--ink:#1B2333;--soft:#5A6478;--faint:#8A93A6;--line:#E9EAEE;--hush:#F7F8FA;--canvas:#F2F4F8;--card:#FCFCFD}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;background:var(--canvas);color:var(--ink);min-height:100vh}
body::before{content:'';position:fixed;inset:0;z-index:0;pointer-events:none;background:radial-gradient(circle at 1px 1px,rgba(27,35,51,.04) 1px,transparent 1px);background-size:26px 26px}
.wrap{max-width:760px;margin:0 auto;padding:40px 20px;position:relative;z-index:1}
h1{font-size:20px;text-align:center;margin-bottom:20px}
.tags{display:flex;gap:6px;justify-content:center;margin-bottom:18px;flex-wrap:wrap}
.tags span{padding:5px 13px;border-radius:999px;font-size:11px;font-weight:600;background:var(--card);border:1px solid var(--line);color:var(--soft);cursor:pointer}
.tags span.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.row{display:flex;gap:8px}
.row input{flex:1;padding:11px 14px;border-radius:10px;border:1px solid var(--line);background:var(--card);font-size:13px;font-family:inherit;outline:none}
.row input:focus{border-color:rgba(27,35,51,.22);box-shadow:0 0 0 3px rgba(27,35,51,.05)}
.row button{padding:0 22px;border-radius:10px;border:none;background:var(--ink);color:#fff;font-size:13px;font-weight:600;font-family:inherit;cursor:pointer;white-space:nowrap}
.row button:disabled{opacity:.4;cursor:not-allowed}
.ppt{display:none;margin-top:14px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.ppt.show{display:block}
.ppt-t{font-size:11.5px;color:var(--soft);margin-bottom:10px}
.ppt-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.th{display:flex;gap:6px;flex:1;flex-wrap:wrap}
.th span{padding:5px 13px;border-radius:999px;font-size:11px;font-weight:600;background:var(--hush);border:1px solid var(--line);color:var(--soft);cursor:pointer}
.th span.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.ppt-row button{padding:8px 18px;border-radius:9px;border:none;background:var(--ink);color:#fff;font-size:12px;font-weight:600;font-family:inherit;cursor:pointer}
.ppt-row button:disabled{opacity:.4;cursor:not-allowed}
.ng{display:none;margin-top:14px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.ng.show{display:block}
.ng-t{font-size:11.5px;color:var(--soft);margin-bottom:12px}
.ng-grid{display:flex;gap:12px;flex-wrap:wrap}
.ngit{width:170px;text-align:center}
.ngit img{width:100%;border-radius:10px;border:1px solid var(--line);display:block;margin-bottom:6px}
.ngit a{font-size:11px;color:var(--soft);text-decoration:none;font-weight:600}
.ngit a:hover{color:var(--ink)}
.loading{display:none;text-align:center;padding:28px;margin-top:16px;background:var(--card);border:1px solid var(--line);border-radius:10px}
.loading.show{display:block}
.spin{width:28px;height:28px;border:3px solid var(--line);border-top-color:var(--ink);border-radius:50%;animation:s .7s linear infinite;margin:0 auto 10px}
@keyframes s{to{transform:rotate(360deg)}}
.result{display:none;margin-top:16px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:20px}
.result.show{display:block}
.rh{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px}
.rh b{font-size:14px}.rh em{font-size:11px;padding:3px 9px;border-radius:999px;background:var(--hush);color:var(--soft);font-style:normal}
.rt{font-size:12.5px;line-height:1.7;color:var(--soft);white-space:pre-wrap;max-height:360px;overflow-y:auto;background:var(--hush);border-radius:8px;padding:14px}
.ra{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
.ra button{padding:7px 14px;border-radius:7px;border:1px solid var(--line);background:var(--card);color:var(--soft);font-size:11.5px;font-weight:600;font-family:inherit;cursor:pointer}
.ra button:hover{background:var(--hush);color:var(--ink)}
.err{display:none;margin-top:12px;padding:10px 14px;border-radius:8px;background:rgba(245,162,68,.1);color:#c7851a;font-size:12px}
.err.show{display:block}
::-webkit-scrollbar{width:5px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:rgba(27,35,51,.12);border-radius:4px}
</style></head><body><div class="wrap">
<h1>视频文案提取</h1><div class="tags"><span data-p="douyin">抖音</span><span data-p="xiaohongshu">小红书</span><span data-p="bilibili">B站</span><span data-p="youtube">YouTube</span></div>
<div class="row"><input id="u" placeholder="粘贴视频链接..." autocomplete="off"><button id="b" onclick="go()">提取</button></div>
<div class="ppt" id="ppt"><div class="ppt-t">长视频 → 图文PPT：上方关键帧 + 下方原话，可切 AI 改版</div>
<div class="ppt-row"><div class="th" id="th"><span data-th="tcq-dark" class="on">深色高级</span><span data-th="light-minimal">浅色简洁</span></div>
<button id="pb" onclick="mk()" disabled>生成PPT</button></div></div>
<div class="loading" id="ld"><div class="spin"></div><div id="ldt" style="font-size:12px;color:var(--soft)">正在提取...视频较长可能需要等待几分钟</div></div>
<div class="err" id="er"></div>
<div class="result" id="rs"><div class="rh"><b id="rt">-</b><em id="rp">-</em></div>
<div style="font-size:11px;color:var(--faint);margin-bottom:10px">字数：<b id="rw" style="color:var(--ink)">0</b></div>
<div class="rt" id="rx"></div><div class="ra">
<button onclick="cp()">复制</button><button onclick="dl()">下载TXT</button><button onclick="og()">AI整理</button><button onclick="ng()">生成笔记图</button><button onclick="od()">存Obsidian</button></div></div>
<div class="ng" id="ng"><div class="ng-t">笔记图（可直接下载，发小红书纯图）</div><div class="ng-grid" id="ngg"></div></div></div>
<script>
var R=null;
var pTh='tcq-dark';
var u=document.getElementById('u'),b=document.getElementById('b');
u.addEventListener('input',function(){var v=this.value.trim();document.querySelectorAll('.tags span').forEach(function(t){t.classList.remove('on')});if(!v)return;var d='';if(v.includes('douyin.com')||v.includes('iesdouyin'))d='douyin';else if(v.includes('xiaohongshu.com')||v.includes('xhslink'))d='xiaohongshu';else if(v.includes('bilibili.com')||v.includes('b23.tv'))d='bilibili';else if(v.includes('youtube.com')||v.includes('youtu.be'))d='youtube';document.querySelectorAll('.tags span').forEach(function(t){t.classList.toggle('on',t.dataset.p===d)});});
u.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();go();}});
document.querySelectorAll('#th span').forEach(function(t){t.addEventListener('click',function(){pTh=t.dataset.th;document.querySelectorAll('#th span').forEach(function(x){x.classList.toggle('on',x===t)})})});
function addH(h){try{var a=JSON.parse(localStorage.getItem('extract_history')||'[]');a.unshift(h);localStorage.setItem('extract_history',JSON.stringify(a.slice(0,20)))}catch(e){}}
function go(){var v=u.value.trim();var mm=v.match(/https?:\/\/[^\s<>"']+/);if(mm)v=mm[0].replace(/[.,;:!?)\]}>\u3002\uff0c\u3011\u3010\u300b\u300a]+$/,'');if(!v){se('\u8bf7\u5148\u7c98\u8d34\u94fe\u63a5');return}el('rs','');el('er','');el('ld','show');b.disabled=true;document.getElementById('pb').disabled=true;document.getElementById('ldt').textContent='正在提取...视频较长可能需要等待几分钟';
fetch('/api/extract',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:v})})
.then(function(r){return r.json()}).then(function(d){el('ld','');b.disabled=false;document.getElementById('pb').disabled=false;
if(!d.ok){se(d.error||'失败');return}R=d;
document.getElementById('rt').textContent=d.title||'未命名';
document.getElementById('rp').textContent=d.platform||'';
document.getElementById('rw').textContent=d.words||0;
document.getElementById('rx').textContent=d.text||'';
el('rs','show');addH({title:d.title,platform:d.platform,url:v,words:d.words,time:new Date().toISOString()})
}).catch(function(e){el('ld','');b.disabled=false;se('网络错误:'+e.message+'。确认终端窗口没有关闭，代理已开启。')});}
function mk(){var v=u.value.trim();var mm=v.match(/https?:\/\/[^\s<>"']+/);if(mm)v=mm[0].replace(/[.,;:!?)\]}>\u3002\uff0c\u3011\u3010\u300b\u300a]+$/,'');if(!v){se('\u8bf7\u5148\u7c98\u8d34\u94fe\u63a5');return}el('rs','');el('er','');el('ld','show');b.disabled=true;document.getElementById('pb').disabled=true;document.getElementById('ldt').textContent='\u6b63\u5728\u751f\u6210PPT：\u4e0b\u8f7d\u2192\u8f6c\u5199\u2192\u62bd\u5173\u952e\u5e27\u2192AI\u6da6\u8272，\u53ef\u80fd\u9700\u8981\u51e0\u5206\u949f';
fetch('/api/deck',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:v,theme:pTh})})
.then(function(r){return r.json()}).then(function(d){el('ld','');b.disabled=false;document.getElementById('pb').disabled=false;
if(!d.ok){se(d.error||'\u751f\u6210\u5931\u8d25');return}window.open(d.url,'_blank');se('PPT \u5df2\u751f\u6210\uff08'+d.label+'\uff0c'+d.slides+'\u9875\uff09');setTimeout(function(){el('er','')},8000)}).catch(function(e){el('ld','');b.disabled=false;document.getElementById('pb').disabled=false;se('\u7f51\u7edc\u9519\u8bef:'+e.message)})}
function ng(){if(!R)return;el('ld','show');b.disabled=true;document.getElementById('pb').disabled=true;document.getElementById('ldt').textContent='正在生成笔记图（加载浏览器截图，可能需要十几秒）';
fetch('/api/notecard',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:R.title,text:R.organized||R.text})})
.then(function(r){return r.json()}).then(function(d){el('ld','');b.disabled=false;document.getElementById('pb').disabled=false;
if(!d.ok){se(d.error||'生成失败');return}
var g=document.getElementById('ngg');g.innerHTML='';
d.images.forEach(function(im,i){var w=document.createElement('div');w.className='ngit';
var img=document.createElement('img');img.src=im.url;img.loading='lazy';
var a=document.createElement('a');a.href=im.url;a.target='_blank';a.download='';a.textContent='第'+(i+1)+'张 ↓';
w.appendChild(img);w.appendChild(a);g.appendChild(w)});
document.getElementById('ng').classList.add('show');se('已生成 '+d.count+' 张笔记图（AI封面：'+(d.ai_cover?'有':'无，可配置 IMAGE_API_KEY')+')）');setTimeout(function(){el('er','')},6000)})
.catch(function(e){el('ld','');b.disabled=false;document.getElementById('pb').disabled=false;se('网络错误:'+e.message)})}
function se(m){var e=document.getElementById('er');e.textContent=m;e.classList.add('show')}
function el(id,v){var e=document.getElementById(id);if(v==='show')e.classList.add('show');else e.classList.remove('show')}
function cp(){if(!R)return;navigator.clipboard.writeText(R.text);se('已复制');setTimeout(function(){el('er','')},1500)}
function dl(){if(!R)return;var a=document.createElement('a');a.href=URL.createObjectURL(new Blob([R.text],{type:'text/plain;charset=utf-8'}));a.download=(R.title||'transcript').slice(0,40)+'.txt';a.click()}
function od(){if(!R)return;var p={title:R.title,platform:R.platform||'',text:R.organized||R.text};fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)}).then(function(r){return r.json()}).then(function(d){if(d.ok){se('已存入: '+d.path)}else{se('保存失败: '+d.error)}setTimeout(function(){el('er','')},5000)}).catch(function(e){se('网络错误:'+e.message)})}
function og(){if(!R)return;el('ld','show');fetch('/api/organize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:R.title,text:R.text})}).then(function(r){return r.json()}).then(function(d){el('ld','');if(!d.ok){se(d.error||'整理失败');return}R.organized=d.text;document.getElementById('rx').textContent=d.text;document.getElementById('rw').textContent=(d.text||'').replace(/\s/g,'').length;se('已整理成笔记，可点“存Obsidian”');setTimeout(function(){el('er','')},4000)}).catch(function(e){el('ld','');se('网络错误:'+e.message)})}
</script></body></html>'''

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        if self.path == '/':
            html = ''
            try:
                html = (Path(__file__).resolve().parent / 'static' / 'index.html').read_text(encoding='utf-8')
            except Exception:
                pass
            if not html:
                html = HTML
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store'); self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        elif self.path == '/api/health':
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers()
            self.wfile.write(json.dumps({'ok':True}).encode())
        elif self.path.startswith('/notecards/'):
            name = urllib.parse.unquote(self.path[len('/notecards/'):])
            if not re.fullmatch(r'[\w.\-]+\.png', name or ''):
                self.send_response(404); self.end_headers(); return
            try:
                p = (Path(__file__).resolve().parent / 'static' / 'notecards' / name).resolve()
                base = (Path(__file__).resolve().parent / 'static' / 'notecards').resolve()
                if str(p).lower().startswith(str(base).lower() + os.sep) and p.is_file():
                    data = p.read_bytes()
                    self.send_response(200); self.send_header('Content-Type','image/png')
                    self.send_header('Cache-Control','no-store')
                    self.send_header('Content-Length', str(len(data))); self.end_headers()
                    self.wfile.write(data)
                    return
            except Exception:
                pass
            self.send_response(404); self.end_headers()
        elif self.path.startswith('/decks/'):
            name = urllib.parse.unquote(self.path[len('/decks/'):])
            if not re.fullmatch(r'[\w.\-]+\.html', name or ''):
                self.send_response(404); self.end_headers(); return
            try:
                p = (DECKS_DIR / name).resolve()
                base = DECKS_DIR.resolve()
                if str(p).lower().startswith(str(base).lower() + os.sep) and p.is_file():
                    data = p.read_bytes()
                    self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8')
                    self.send_header('Cache-Control','no-store')
                    self.send_header('Content-Length', str(len(data))); self.end_headers()
                    self.wfile.write(data)
                    return
            except Exception:
                pass
            self.send_response(404); self.end_headers()
        else:
            self.send_response(404); self.end_headers()
    def do_POST(self):
        if self.path in ('/api/extract', '/api/save', '/api/organize', '/api/deck', '/api/notecard'):
            cl = int(self.headers.get('Content-Length',0))
            body = self.rfile.read(cl).decode() if cl else ''
            data = json.loads(body.lstrip('\ufeff')) if body else {}
            if self.path == '/api/extract':
                code, result = handle_api(self.path, body)
            elif self.path == '/api/deck':
                url = _extract_url((data.get('url') or '').strip())
                theme = (data.get('theme') or 'tcq-dark').strip() or 'tcq-dark'
                if not url or '://' not in url:
                    code, result = 400, {'ok': False, 'error': '未识别到有效链接，请先粘贴视频链接'}
                else:
                    code, result = 200, deck.build_deck(url, theme)
            elif self.path == '/api/notecard':
                code, result = 200, notecard.build_note_card(
                    (data.get('title') or '').strip(), (data.get('text') or '').strip(),
                    (data.get('style') or 'minimal').strip())
            else:
                if self.path == '/api/save':
                    code, result = 200, save_to_obsidian((data.get('title') or '').strip(), (data.get('text') or '').strip())
                else:
                    code, result = 200, organize_with_llm((data.get('title') or '').strip(), (data.get('text') or '').strip())
            self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store'); self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        else:
            self.send_response(404); self.end_headers()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '5051'))
    print(f'服务已启动: http://127.0.0.1:{port}')
    http.server.HTTPServer(('127.0.0.1', port), Handler).serve_forever()
