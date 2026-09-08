#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""转写引擎统一入口。

A1-b GPU优先/CPU兜底 + A3 模型单例复用：server.py 与 deck.py 共用本模块的
faster-whisper 单例，避免每次转写重新加载模型；GPU 可用自动走 cuda(float16)，
否则静默回落 CPU(int8)，任何机器开箱即用。
"""
import os
import shutil
import sys

WHISPER_DIR = r'D:\whisper-models'

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cuda_rt  # noqa: E402

_WHISPER_MODEL = None
_WHISPER_DEVICE = None


def _has_gpu():
    return (shutil.which('nvidia-smi') is not None
            or os.path.exists(r'C:\Windows\System32\nvidia-smi.exe'))


def _ensure_cuda_rt():
    """把可复用 CUDA 运行库目录注入 DLL 搜索路径（GPU 转写前必须，否则报 cublas64_12.dll not found）。"""
    d = cuda_rt.find_cuda_rt_dir()
    if d:
        cuda_rt.inject_cuda_rt(d)
    return d


def get_whisper_model():
    """返回 (WhisperModel, device)。模块级单例：首次加载，之后复用。"""
    global _WHISPER_MODEL, _WHISPER_DEVICE
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL, _WHISPER_DEVICE
    from faster_whisper import WhisperModel
    model = None
    if _has_gpu():
        _ensure_cuda_rt()
        try:
            model = WhisperModel('small', device='cuda', compute_type='float16',
                                 download_root=WHISPER_DIR, local_files_only=True)
            _WHISPER_DEVICE = 'cuda'
        except Exception:
            model = None
    if model is None:
        model = WhisperModel('small', device='cpu', compute_type='int8',
                             cpu_threads=8, download_root=WHISPER_DIR,
                             local_files_only=True)
        _WHISPER_DEVICE = 'cpu'
    _WHISPER_MODEL = model
    return model, _WHISPER_DEVICE


def transcribe_whisper(audio_path, progress_cb=None):
    """whisper 转写音频 → 简体中文纯文本。失败返回空串。
    progress_cb(percent, detail)：转写过程中按已转秒数/总时长回调（0~95）。"""
    try:
        import zhconv
        model, _ = get_whisper_model()
        segs, info = model.transcribe(str(audio_path), language='zh', vad_filter=True, beam_size=5)
        duration = float(getattr(info, 'duration', 0) or 0)
        parts = []
        for s in segs:
            t = (s.text or '').strip()
            if t:
                parts.append(t)
            if progress_cb and duration > 0:
                pct = min(95, int((s.end / duration) * 95))
                progress_cb(pct, f'转写中 {int(s.end)}s/{int(duration)}s')
        return zhconv.convert('\n'.join(parts), 'zh-cn')
    except Exception:
        return ''


def transcribe_whisper_segments(audio_path):
    """whisper 转写音频 → 带时间戳 segment 列表 [{start,end,text}]。失败返回空列表。"""
    try:
        import zhconv
        model, _ = get_whisper_model()
        segs, _ = model.transcribe(str(audio_path), language='zh', vad_filter=True, beam_size=5)
        out = []
        for s in segs:
            t = zhconv.convert((s.text or '').strip(), 'zh-cn')
            if t:
                out.append({'start': round(s.start, 1), 'end': round(s.end, 1), 'text': t})
        return out
    except Exception:
        return []


SHERPA_PY = r'D:\live-class-skill\win\scripts\.venv\Scripts\python.exe'
SHERPA_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sherpa_transcribe.py')


def transcribe_sherpa(audio_path):
    """sherpa-onnx 中文快速转写（子进程调 live-class-skill 的 GPU venv）。失败返回空串。"""
    if not os.path.exists(SHERPA_PY):
        return ''
    try:
        import subprocess
        r = subprocess.run([SHERPA_PY, SHERPA_SCRIPT, str(audio_path)],
                           capture_output=True, text=True, timeout=120, encoding='utf-8')
        if r.returncode == 0:
            return (r.stdout or '').strip()
        return ''
    except Exception:
        return ''


FFPROBE = r'D:\ffmpeg\bin\ffprobe.exe'


def _audio_duration(audio_path):
    """探测音频时长（秒）。失败返回 0。"""
    try:
        import subprocess
        r = subprocess.run([FFPROBE, '-v', 'error', '-show_entries', 'format=duration',
                            '-of', 'default=noprint_wrappers=1:nokey=1', str(audio_path)],
                           capture_output=True, text=True, timeout=30)
        return float((r.stdout or '').strip() or 0)
    except Exception:
        return 0


def transcribe_auto(audio_path, use_sherpa=True, progress_cb=None):
    """长中文音频(>5min)优先 sherpa（摊薄子进程冷启动）；短音频 whisper 更快。失败/空回退 whisper。"""
    if use_sherpa and _audio_duration(audio_path) > 300:
        if progress_cb:
            progress_cb(5, 'sherpa 转写中（子进程）')
        t = transcribe_sherpa(audio_path)
        if t.strip():
            if progress_cb:
                progress_cb(95, '转写完成')
            return t
    return transcribe_whisper(audio_path, progress_cb=progress_cb)
