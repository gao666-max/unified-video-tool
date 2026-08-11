#!/usr/bin/env python3
"""统一视频文案提取 —— 抖音走专用解析器，其他平台走 yt-dlp。"""

from __future__ import annotations

import json, os, re, subprocess, sys, time
from pathlib import Path
from urllib.parse import urlparse

_DOUYIN_BACKEND = Path(r"D:/obsidian-content-capture-backend")
if str(_DOUYIN_BACKEND) not in sys.path:
    sys.path.insert(0, str(_DOUYIN_BACKEND))

PROXY = 'http://127.0.0.1:7897'
FFMPEG_DIR = r'D:\ffmpeg\bin'

VENV_PY = r'D:\obsidian-content-capture-backend\.venv\Scripts\python.exe'
PY_BIN = VENV_PY if os.path.exists(VENV_PY) else sys.executable

def detect_platform(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    if any(k in domain for k in ('douyin.com','iesdouyin.com','v.douyin.com')): return 'douyin'
    if any(k in domain for k in ('xiaohongshu.com','xhslink.com')): return 'xiaohongshu'
    if any(k in domain for k in ('bilibili.com','b23.tv')): return 'bilibili'
    if any(k in domain for k in ('youtube.com','youtu.be')): return 'youtube'
    return 'unknown'

def _env():
    e = os.environ.copy()
    e.setdefault('HTTP_PROXY', PROXY)
    e.setdefault('HTTPS_PROXY', PROXY)
    return e

def resolve_url(url: str) -> dict:
    r = subprocess.run([PY_BIN, '-m', 'yt_dlp', '--dump-json', '--no-playlist',
        '--skip-download', '--no-check-certificates', url],
        capture_output=True, text=True, timeout=30, env=_env())
    if r.returncode == 0 and r.stdout.strip():
        info = json.loads(r.stdout.strip().split('\n')[0])
        return {'success': True, 'title': info.get('title',''), 'platform': info.get('extractor',''),
                'duration': info.get('duration',0), 'description': info.get('description','')[:500],
                'uploader': info.get('uploader',''),
                'has_subtitles': bool(info.get('subtitles') or info.get('automatic_captions'))}
    return {'success': False, 'error': (r.stderr or 'yt-dlp无输出').strip()[-300:]}

def process_douyin(url: str, work_dir: Path) -> dict:
    from script.douyin_resolver import resolve_douyin_share
    from script.pipeline import process_douyin_share
    from script.config import Settings
    from script.paths import OUTPUT_DIR
    try:
        out_dir = process_douyin_share(url, settings=Settings(output_dir=OUTPUT_DIR, whisper_model='small'))
        meta = json.loads((out_dir / 'meta.json').read_text(encoding='utf-8')) if (out_dir / 'meta.json').exists() else {}
        txt = ''
        tp = out_dir / 'transcript.txt'
        if tp.exists():
            t = tp.read_text(encoding='utf-8')
            m = '--- 文案 ---'
            txt = t.split(m, 1)[1].strip() if m in t else t.strip()
        return {'success': True, 'title': meta.get('title',''), 'platform': 'douyin',
                'transcript': txt[:5000], 'full_length': len(txt),
                'word_count': len(txt.replace('\n','').replace(' ','')),
                'output_dir': str(out_dir), 'txt_path': str(tp)}
    except Exception as e:
        return {'success': False, 'error': f'抖音: {e}'}

def process_other(url: str, work_dir: Path, platform: str) -> dict:
    vf = work_dir / 'video.mp4'
    env = _env()
    # Download with 3 fallback strategies
    downloaded = False
    for strat in [
        ['-f', 'bv*+ba/b', '--merge-output-format', 'mp4', '--ffmpeg-location', FFMPEG_DIR, '--no-playlist', '--no-check-certificates'],
        ['-f', 'bv*[height<=480]+ba/b[height<=480]', '--merge-output-format', 'mp4', '--ffmpeg-location', FFMPEG_DIR, '--no-playlist', '--no-check-certificates'],
        ['-f', 'wv*+wa/w', '--merge-output-format', 'mp4', '--ffmpeg-location', FFMPEG_DIR, '--no-playlist', '--no-check-certificates'],
    ]:
        try:
            subprocess.run([PY_BIN, '-m', 'yt_dlp', '-o', str(vf)] + strat + [url],
                capture_output=True, timeout=300, check=True, env=env)
            downloaded = True; break
        except: pass
    if not downloaded:
        return {'success': False, 'error': '下载失败（三种策略均失败，请检查链接和代理）'}

    # Subtitles
    transcript = ''
    try:
        subprocess.run([PY_BIN, '-m', 'yt_dlp', '--write-subs', '--write-auto-subs',
            '--sub-lang', 'zh-Hans,zh-CN,zh,en', '--sub-format', 'vtt',
            '--skip-download', '--no-check-certificates',
            '-o', str(work_dir / '%(title)s.%(ext)s'), url],
            capture_output=True, timeout=60, env=env)
        for ext in ('*.vtt', '*.srt'):
            for f in work_dir.glob(ext):
                t = f.read_text(encoding='utf-8', errors='ignore')
                lines = [re.sub(r'<[^>]+>', '', l.strip()) for l in t.split('\n')
                    if l.strip() and not l.strip().isdigit() and '-->' not in l and 'WEBVTT' not in l]
                transcript = '\n'.join(lines)
                if transcript.strip(): break
            if transcript.strip(): break
    except: pass

    # Whisper fallback
    if not transcript.strip() and vf.exists():
        af = str(work_dir / 'audio.wav')
        ff = r"D:\ffmpeg\bin\ffmpeg.exe"
        subprocess.run([ff, '-y','-i',str(vf),'-vn','-acodec','pcm_s16le','-ar','16000','-ac','1',af],
            capture_output=True, timeout=120, check=True)
        from faster_whisper import WhisperModel; import zhconv
        model = WhisperModel('small', device='cpu', compute_type='int8', cpu_threads=8,
            download_root='D:/whisper-models', local_files_only=True)
        segs, _ = model.transcribe(af, language='zh', vad_filter=True, beam_size=5)
        transcript = zhconv.convert('\n'.join(s.text.strip() for s in segs if s.text.strip()), 'zh-cn')

    tp = work_dir / 'transcript.txt'
    tp.write_text(f"标题：{work_dir.name}\n来源：{url}\n平台：{platform}\n\n--- 文案 ---\n\n{transcript}", encoding='utf-8')

    return {'success': True, 'title': work_dir.name, 'platform': platform,
            'transcript': transcript[:5000], 'full_length': len(transcript),
            'word_count': len(transcript.replace('\n','').replace(' ','')),
            'output_dir': str(work_dir), 'txt_path': str(tp)}

def process_xiaohongshu(url: str, work_dir: Path) -> dict:
    """Xiaohongshu: extract note text via page scrape, video via yt-dlp fallback."""
    import requests, re as re2

    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
        'Referer': 'https://www.xiaohongshu.com/',
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15, proxies={'http': PROXY, 'https': PROXY})
        html = resp.text
    except Exception:
        return {'success': False, 'error': '小红书页面请求失败，请检查代理'}

    # Extract desc from SSR state
    desc = ''
    title = ''
    for pattern in [r'"desc":"([^"]+)"', r'"noteTitle":"([^"]+)"', r'"title":"([^"]+)"']:
        m = re2.search(pattern, html)
        if m:
            val = re2.sub(r'\\u[\da-fA-F]{4}', lambda x: chr(int(x.group(0)[2:], 16)), m.group(1))
            val = val.replace('\\n', '\n').replace('\\t', '').replace('\\/', '/')
            if 'desc' in pattern and len(val) > len(desc): desc = val
            if 'title' in pattern.lower() and len(val) > len(title): title = val

    # Try extract video URL and download
    transcript = desc
    video_downloaded = False
    video_match = re2.search(r'"streamUrl":"([^"]+)"', html) or re2.search(r'"videoUrl":"([^"]+)"', html) or re2.search(r'"masterUrl":"([^"]+)"', html)
    if video_match:
        video_url = video_match.group(1).replace('\\u002F', '/')
        vf = work_dir / 'video.mp4'
        try:
            r = requests.get(video_url, headers=headers, timeout=120, proxies={'http': PROXY, 'https': PROXY})
            vf.write_bytes(r.content)
            if vf.stat().st_size > 10000:
                video_downloaded = True
        except: pass

    # If video downloaded, extract audio and transcribe
    if video_downloaded:
        af = str(work_dir / 'audio.wav')
        ff = r"D:\ffmpeg\bin\ffmpeg.exe"
        try:
            subprocess.run([ff, '-y', '-i', str(work_dir / 'video.mp4'), '-vn', '-acodec', 'pcm_s16le',
                           '-ar', '16000', '-ac', '1', af], capture_output=True, timeout=120, check=True)
            from faster_whisper import WhisperModel; import zhconv
            model = WhisperModel('small', device='cpu', compute_type='int8', cpu_threads=8,
                                 download_root='D:/whisper-models', local_files_only=True)
            segs, _ = model.transcribe(af, language='zh', vad_filter=True, beam_size=5)
            whisper_text = zhconv.convert('\n'.join(s.text.strip() for s in segs if s.text.strip()), 'zh-cn')
            if whisper_text.strip():
                transcript = (desc + '\n\n--- 视频语音转写 ---\n\n' + whisper_text) if desc else whisper_text
        except: pass

    if not desc.strip() and not video_downloaded:
        return {'success': False, 'error': '未提取到内容。该笔记可能需要登录才能查看'}

    tp = work_dir / 'transcript.txt'
    tp.write_text(f"标题：{title}\n来源：{url}\n平台：xiaohongshu\n\n--- 文案 ---\n\n{transcript}", encoding='utf-8')

    return {'success': True, 'title': title or '小红书笔记', 'platform': 'xiaohongshu',
            'transcript': transcript[:5000], 'full_length': len(transcript),
            'word_count': len(transcript.replace('\n','').replace(' ','')),
            'output_dir': str(work_dir), 'txt_path': str(tp)}

def process_url(url: str, output_dir: str = None) -> dict:
    if output_dir is None:
        output_dir = r'D:\unified-video-tool\outputs'
    m = re.search(r'https?://[^\s<>"\']+', url or '')
    if m: url = m.group(0).rstrip('.,;:!?)]}>\u3002\uff0c\u3001\u300b\u300a\u3011\u3010\u300d\u300c\u201d\u2019\u3000')
    url = (url or '').strip()
    if not url or '://' not in url:
        return {'success': False, 'error': '\u672a\u8bc6\u522b\u5230\u6709\u6548\u94fe\u63a5\u3002\u8bf7\u53ea\u7c98\u8d34\u89c6\u9891/\u7b14\u8bb0\u94fe\u63a5'}
    platform = detect_platform(url)
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    meta = resolve_url(url)
    title = (meta.get('title','') if meta.get('success') else 'video')
    safe = re.sub(r'[<>:"/\\|?*]', '_', str(title))[:60] if title else 'video'
    wd = out / f"{safe}_{int(time.time())}"; wd.mkdir(parents=True, exist_ok=True)
    if platform == 'douyin':
        return process_douyin(url, wd)
    if platform == 'xiaohongshu':
        return process_xiaohongshu(url, wd)
    return process_other(url, wd, platform)
