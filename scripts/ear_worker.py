# -*- coding: utf-8 -*-
"""ear_worker — 在 Ear 环境内跑 FunASR 的跨环境子进程桥。

存在的原因（2026-10-13 实测定点）：
  · 主环境 Fascinator 无 funasr/torch 栈；`Facsinator_Ear_Env` 有
    funasr 1.3.9 + torch 2.12.1 + **CUDA 可用** + 本地 Paraformer（中文）；
  · 该环境的 funasr 在默认 GBK 代码页下 import 即段错误
    （transformers 的 ffmpeg 探测在中文 locale 下 chardet 返回 None →
    原生层崩溃）——`-X utf8` 不够，必须 `chcp 65001` 进程级 UTF-8；
  · 两环境不可能合并装包（tf 2.21 与主环境冲突），子进程是最干净边界。

用法（由主环境 ear_worker_client 调用）：
    python ear_worker.py --wav <path> [--emotion] [--out <json>]
输出 stdout 一行 JSON：{"ok":..., "text":..., "lang":..., "error":...}
"""
import argparse
import json
import os
import sys
import time

MODEL_ROOT = r"E:/Models/nlp"
ASR_MODEL = os.path.join(MODEL_ROOT, "Paraformer")
EMO_MODEL = os.path.join(MODEL_ROOT, "emotion2vec_plus_large")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True)
    ap.add_argument("--emotion", action="store_true")
    args = ap.parse_args()

    out = {"ok": False, "text": "", "segments": []}
    try:
        import warnings
        warnings.filterwarnings("ignore")
        import numpy as np
        import wave
        w = wave.open(args.wav, "rb")
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
        ch = w.getnchannels()
        w.close()
        d = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        if ch > 1:
            d = d.reshape(-1, ch).mean(axis=1)
        if sr != 16000:
            n = int(len(d) * 16000 / sr)
            d = np.interp(np.arange(n), np.arange(len(d)), d).astype(
                np.float32)
            sr = 16000

        t0 = time.time()
        from funasr import AutoModel
        m = AutoModel(model=ASR_MODEL, disable_update=True)
        r = m.generate(input=d, fs=sr, disable_pbar=True)
        text = ""
        if r:
            first = r[0] if isinstance(r, list) else r
            text = str(first.get("text", ""))
        out.update(ok=True, text=text, asr_s=round(time.time() - t0, 2))

        if args.emotion and os.path.isdir(EMO_MODEL):
            try:
                t1 = time.time()
                em = AutoModel(model=EMO_MODEL, disable_update=True)
                er = em.generate(input=d, fs=sr, disable_pbar=True)
                if er:
                    e0 = er[0] if isinstance(er, list) else er
                    out["emotion"] = {"scores": e0.get("scores"),
                                      "time_s": round(time.time() - t1, 2)}
            except Exception as e:                # noqa: BLE001
                out["emotion_error"] = repr(e)[:120]
    except Exception as e:                        # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
