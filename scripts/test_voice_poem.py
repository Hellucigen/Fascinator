# -*- coding: utf-8 -*-
"""语音链路实测：中文→日语转译→kokoro 合成→保存 WAV。
（用户任务 2026-10-21：验证翻译双轨 + TTS 上 GPU 后的真实出声。）

用法：python scripts/test_voice_poem.py ["任意中文句子"]
输出：data/test_audio/poem_<时间戳>.wav + provider/耗时报告
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "test_audio"
POEM = "小鸫鸟啊，当你飞过故乡时，请替我歌唱。"


def translate(text: str) -> tuple[str, str]:
    """她的"播报翻译"（与 app._voice_translate 同 prompt 同出口）。"""
    try:
        import openai
        key = json.load(open(ROOT / "data" / "llm_secret.json",
                             encoding="utf-8"))["api_key"]
        cli = openai.OpenAI(api_key=key, timeout=60,
                            base_url="https://maas.qianwenaiapi.com/"
                                     "compatible-mode/v1")
        r = cli.chat.completions.create(
            model="qwen3.8-flash",
            messages=[
                {"role": "system",
                 "content": "你是 HARU 的播报翻译。把用户消息翻成自然口语"
                            "日语（女性、柔和、简洁），只输出译文本身，不加解释。"},
                {"role": "user", "content": text[:400]}],
            max_tokens=200)
        return str(r.choices[0].message.content).strip(), "translated"
    except Exception as e:                          # noqa: BLE001
        return "", f"translate_failed:{type(e).__name__}"


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else POEM
    print(f"输入：{text}")
    t0 = time.time()
    ja, note = translate(text)
    print(f"转译[{note}] {time.time()-t0:.1f}s：{ja}")

    sys.path.insert(0, str(ROOT))
    from voice_io import TtsBackend, contains_japanese
    t0 = time.time()
    tb = TtsBackend("kokoro")
    print(f"加载：{tb.name} voice={tb.kokoro_voice} ({time.time()-t0:.1f}s)")
    try:
        import onnxruntime as ort
        print("onnxruntime providers:", ort.get_available_providers())
        sess = getattr(tb.kokoro, "_session", None) or getattr(
            tb.kokoro, "session", None)
        if sess is None:
            for attr in vars(tb.kokoro).values():
                if "InferenceSession" in type(attr).__name__:
                    sess = attr
                    break
        if sess is not None:
            print("会话实际 provider:", sess.get_providers())
    except Exception as e:                          # noqa: BLE001
        print("provider 探查失败:", e)
    if not ja or contains_japanese(ja) < 0.15:
        print("译文不可用——护栏生效：不该拿中文喂日语音，测试终止。")
        sys.exit(2)

    t0 = time.time()
    pcm, sr = tb.synthesize(ja, "ja")
    dt = time.time() - t0
    if pcm is None:
        print("合成失败:", sr)
        sys.exit(3)
    import numpy as np
    pcm = np.asarray(pcm, dtype="float32")
    if pcm.ndim > 1:
        pcm = pcm.mean(axis=1)
    OUT.mkdir(parents=True, exist_ok=True)
    import wave
    fn = OUT / ("poem_%d.wav" % int(time.time()))
    with wave.open(str(fn), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes((np.clip(pcm, -1, 1) * 32767
                       ).astype("<i2").tobytes())
    print(f"合成 {dt:.2f}s → 音频 {len(pcm)/sr:.1f}s 已存 {fn}")


if __name__ == "__main__":
    main()
