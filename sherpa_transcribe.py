#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sherpa-onnx 单文件转写（中文普通话专用，GPU 优先）。

用 live-class-skill 的 venv python 跑：<sherpa_venv_python> sherpa_transcribe.py <audio.wav>
转写文本输出到 stdout；失败输出空。
"""
import os
import sys

os.environ.setdefault('LCC_MODELS_DIR', r'D:\live-class-skill\models')

LCC_SCRIPTS = r'D:\live-class-skill\scripts'
sys.path.insert(0, LCC_SCRIPTS)
import cuda_rt  # noqa: E402
import accel  # noqa: E402
import common  # noqa: E402


def transcribe(audio_path):
    rt = cuda_rt.find_cuda_rt_dir()
    if rt:
        cuda_rt.inject_cuda_rt(rt)
    import sherpa_onnx
    mf = common.model_files()
    if mf is None:
        return ''
    forced = (os.environ.get('LCC_ASR_PROVIDER') or '').strip().lower()
    if forced:
        order = [forced]
    elif accel.detect()['accel'] == 'gpu':
        order = ['cuda', 'cpu']
    else:
        order = ['cpu']
    recognizer = None
    for prov in order:
        try:
            recognizer = sherpa_onnx.OfflineRecognizer.from_zipformer_ctc(
                model=mf['model'], tokens=mf['tokens'], num_threads=4,
                sample_rate=16000, decoding_method='greedy_search', provider=prov)
            break
        except Exception:
            continue
    if recognizer is None:
        return ''
    import soundfile as sf
    audio, sr = sf.read(audio_path, dtype='float32', always_2d=True)
    # 分块转写：超长音频一次性 decode 会让 onnxruntime 请求巨额显存（17 分钟 → ~83GB）而崩溃，
    # 按 20s 切片逐块 decode 后拼接，单块显存需求降到可承受范围。
    chunk_samples = int(sr * 20)
    mono = audio[:, 0]
    n = mono.shape[0]
    parts = []
    for start in range(0, n, chunk_samples):
        seg = mono[start:start + chunk_samples]
        if seg.shape[0] < int(sr * 0.2):  # 空/超短尾块跳过
            continue
        stream = recognizer.create_stream()
        stream.accept_waveform(sr, seg)
        recognizer.decode_stream(stream)
        t = stream.result.text.strip()
        if t:
            parts.append(t)
    return ''.join(parts)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(1)
    sys.stdout.reconfigure(encoding='utf-8')
    print(transcribe(sys.argv[1]))
