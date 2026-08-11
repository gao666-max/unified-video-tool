#!/usr/bin/env python3
"""统一视频提取 Web 界面 —— 粘贴任意链接即可提取文案。"""

from __future__ import annotations

import sys, io, os
from pathlib import Path
from urllib.parse import unquote

_ROOT = Path(__file__).resolve().parent

# Ensure unified_video.py is importable
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from unified_video import detect_platform, process_url

from flask import Flask, request, jsonify, send_from_directory, Response

app = Flask(__name__, static_folder='static', static_url_path='')

@app.route('/')
def index():
    resp = send_from_directory(str(_ROOT / 'static'), 'index.html')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@app.route('/api/health')
def health():
    return jsonify({'success': True, 'ffmpeg': True, 'whisper': True})

@app.route('/api/detect', methods=['POST'])
def api_detect():
    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify({'success': False, 'error': '请输入链接'}), 400
    platform = detect_platform(url)
    platforms_cn = {
        'douyin': '抖音', 'xiaohongshu': '小红书', 'bilibili': 'B站',
        'youtube': 'YouTube', 'unknown': '未知平台'
    }
    return jsonify({'success': True, 'platform': platform, 'platform_cn': platforms_cn.get(platform, platform)})

@app.route('/api/extract', methods=['POST'])
def api_extract():
    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify({'success': False, 'error': '请输入链接'}), 400

    platform = detect_platform(url)
    result = process_url(url)

    return jsonify(result)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '5051'))
    print(f'打开浏览器: http://127.0.0.1:{port}')
    app.run(host='127.0.0.1', port=port, debug=False)
