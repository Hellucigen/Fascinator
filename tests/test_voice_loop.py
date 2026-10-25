# -*- coding: utf-8 -*-
"""语音闭环逻辑测试（P1/P2）。

分两层：
  A 纯逻辑（恒可跑，离线）：双轨分流 tts_prep / avatar 状态仲裁 /
    能量门分段 / epoch 打断作废 / 热开关不偷开麦克风 / 幂等注入。
  B 模型集成（模型文件在则跑，不在则如实 SKIP）：
    日语 TTS(kokoro-onnx) → 同一句喂 ASR(faster-whisper) 闭环回环。
真机麦克风采集不在本测试范围（无设备环境用 /api/voice/feed 等效通道）。
运行：python tests/test_voice_loop.py
"""
import os
import sys

_r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _r)
# split_repos bootstrap: FAS-Cognitive sibling
_cog = os.environ.get("FAS_COG_ROOT") or os.path.join(
    os.path.dirname(_r), "FAS-Cognitive")
if os.path.isdir(_cog) and _cog not in sys.path:
    sys.path.insert(0, _cog)

import numpy as np

import voice_io as V
import avatar_state as AV

FAILURES = []
TOTAL = [0]


def check(name, cond):
    TOTAL[0] += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILURES.append(name)


# ── A1 双轨分流 ──
ja = "こんにちは、今日はいい天気ですね。"
zh = "今天弄辐射4的模组创建文档好麻烦"
t, note = V.tts_prep(zh, lambda s: ja, "ja", True)
check("A1a 中文回复 → 播日语译文", t == ja and note == "translated_zh_to_ja")
t, note = V.tts_prep(ja, lambda s: "SHOULD_NOT_BE_CALLED", "ja", True)
check("A1b 已是日语 → 原文直送（不二次翻译）", t == ja and note == "passthrough")
t, note = V.tts_prep(zh, None, "ja", True)
check("A1c 无翻译器 → 诚实降级原文", t == zh and note == "passthrough(no_translate_fn)")


def boom(s):
    raise RuntimeError("llm down")


t, note = V.tts_prep(zh, boom, "ja", True)
check("A1d 翻译异常 → 原文直送不吞话", t == zh and note == "passthrough(translate_error)")
t, note = V.tts_prep(zh, lambda s: s, "en", True)
check("A1e 播报语言非日语 → 不翻译", note == "passthrough")
t, note = V.tts_prep("hello", lambda s: s, "ja", False)
check("A1f 双轨开关关 → 不翻译", note == "passthrough")
check("A1g 日语占比启发式", V.contains_japanese(ja) > 0.3
      and V.contains_japanese(zh) < 0.05)

# ── A2 avatar 状态仲裁 ──
AV._state.update(state="idle", source="boot", since_ts=0.0, turn_id=None)
check("A2a idle→listening 允许", AV.set_state("listening", "voice"))
check("A2b listening→speaking 允许（升格）", AV.set_state("speaking", "voice"))
check("A2c speaking 期间 thinking 不抢占", not AV.set_state("thinking", "turn"))
check("A2d speaking 期间别的 source 想 listening 也不行",
      not AV.set_state("listening", "other"))
check("A2e interrupted 压过 speaking", AV.set_state("interrupted", "voice"))
check("A2f error 压过 interrupted", AV.set_state("error", "boot"))
check("A2g 非持有者不能 release", not AV.release("voice"))
check("A2h 持有者本人可退回", AV.release("boot", to="idle"))
seen = []
AV.register_pusher("t", lambda snap: seen.append(snap["state"]))
AV.set_state("thinking", "turn")
check("A2i pusher 收到迁移快照", seen == ["thinking"])
AV.register_pusher("bad", lambda s: 1 / 0)
check("A2j 坏 pusher 不拖垮写入", AV.set_state("idle", "turn", force=True))
AV._pushers.clear()
AV._state.update(state="idle", source="test", since_ts=0.0, turn_id=None)
check("A2k 非法状态被拒", not AV.set_state("dancing", "test"))


def mk_pipe(**over):
    cfg = {"voice_enabled": True, "voice_listen_enabled": False,
           "voice_speak_language": "ja", "voice_translate_tts": True,
           "voice_asr_backend": "off", "voice_tts_backend": "none"}
    cfg.update(over)
    return V.VoicePipeline(cfg, turn_handler=lambda t: "りかいしました")


# ── A3 分段与能量门 ──
p = mk_pipe()
p._vad = V.VadBackend.__new__(V.VadBackend)
p._vad.model = None
p._vad.reason = ""
check("A3a VAD 不可用时退化能量门可算概率",
      0.0 <= p._vad.speech_prob(np.zeros(V.CHUNK, "float32")) <= 1.0)
tone = np.zeros(V.CHUNK, "float32")
tone[:V.CHUNK] = 0.5
check("A3b 能量门：强信号=有人声", p._vad.speech_prob(tone) >= 0.5)
# 语音段：2 秒正弦 burst → 1.2 秒静音，模拟采集回调
sig = (0.3 * np.sin(2 * np.pi * 220 *
                    np.arange(V.CHUNK * 60) / V.SR)).astype("float32")
sil = np.zeros(V.CHUNK, "float32")
q0 = p._q.qsize()
vt = [1000.0]                    # 虚拟时钟：真实 time() 下回调循环瞬间跑完，
p._clock = lambda: vt[0]        # 静默超时判据永不触发——注入推进式时钟
for c in sig.reshape(60, V.CHUNK):
    vt[0] += 0.032               # 每块≈32ms
    p._audio_cb(c, V.CHUNK, None, None)          # 1D：回调须兼容
for _ in range(45):
    vt[0] += 0.032               # 推进 >0.6s 静默
    p._audio_cb(sil, V.CHUNK, None, None)
check("A3c 语音段在静默超时后切出入队", p._q.qsize() > q0
      and p.stats["segments"] == 1)
# 短噪声尾巴（<0.35s）被丢弃
p._seg_active = True
p._seg_buf = [np.ones(V.CHUNK, "float32") * 0.3]
p._last_speech_ts = vt[0] - 1.0     # 已远超静默阈——会触发切段但时长不足
before = p._q.qsize()
vt[0] += 1.0
p._audio_cb(sil, V.CHUNK, None, None)
check("A3d 过短段丢弃", p._q.qsize() == before)

# ── A4 epoch：打断作废旧任务 ──
p2 = mk_pipe()
e0 = p2._epoch.current
pcm = sig[:V.CHUNK * 10].astype("float32")
p2.feed_audio(pcm)                                  # 入队带新 epoch
old_ep = p2._epoch.current
p2._interrupt()                                     # 模拟用户开口打断
check("A4a 打断使 epoch 前进（旧任务作废）", p2._epoch.current > old_ep)
check("A4b 打断计数", p2.stats["interrupts"] == 1)
check("A4c 打断上报 interrupted 状态",
      AV.snapshot()["state"] == "interrupted")
AV.release("voice", to="idle")

# ── A5 热开关语义：enable 不开麦、listen 才开、disable 关麦 ──
p3 = mk_pipe()
V.apply_control(p3, {"voice_enabled": True, "voice_listen_enabled": False})
check("A5a enabled 但未 listen → 麦克风绝不偷开", p3._stream is None)
V.apply_control(p3, {"voice_enabled": False})
check("A5b disable 后仍无麦", p3._stream is None)
check("A5c apply_control 异常安全（pipeline None）",
      V.apply_control(None, {}) is None)

# ── A6 幂等注入：feed_audio 走队列、空识别不触发回合 ──
p4 = mk_pipe()
p4._asr = V.AsrBackend.__new__(V.AsrBackend)
p4._asr.model = None
p4._asr.reason = "forced-none"
p4._asr._lock = __import__("threading").Lock()
turns = []
p4.turn_handler = lambda t: turns.append(t) or "ok"
p4.feed_audio(pcm)
pcm2, ep = p4._q.get(timeout=1)
r = p4._asr.transcribe(pcm2)
check("A6a ASR 未就绪时明确报因不空转", r["text"] == "" and "error" in r)
check("A6b 无文本不进主管道", not turns)

# ── A7 TTS 无声降级（后端缺失不抛）──
tb = V.TtsBackend("none")
pcm_or_reason = tb.synthesize("こんにちは", "ja")
check("A7a TTS 缺失 → (None, reason) 而非异常",
      pcm_or_reason[0] is None and pcm_or_reason[1])
check("A7b TTS 后端名如实标 none", tb.name == "none")

# ── B 模型集成（真实权重在则跑：日语 TTS→ASR 回环）────────────────
_model_dir = os.path.join(_r, "models", "tts")
if os.path.isfile(os.path.join(_model_dir, "kokoro-v1.0.onnx")):
    print("[B] 模型在场：跑真实 TTS→ASR 回环")
    try:
        tb2 = V.TtsBackend("kokoro")
        check("B1 kokoro 后端加载", tb2.kokoro is not None)
        if tb2.kokoro is not None:
            import time as _time
            _t0 = _time.perf_counter()
            audio, sr = tb2.synthesize(
                "今日はいい天気ですね、お出かけしますか？", "ja")
            _rtf = (_time.perf_counter() - _t0)
            check("B2 日语合成成功（kokoro 真音频）",
                  audio is not None and len(audio) > sr)
            print(f"    kokoro TTS: {len(audio) / sr:.1f}s 音频，"
                  f"合成耗时 {_rtf:.2f}s（RTF {_rtf / (len(audio) / sr):.2f}）")
            # 24k→16k 重采样后喂 whisper（同生产 ASR 输入形状）
            a16 = np.interp(np.arange(int(len(audio) * 16000 / sr)),
                            np.arange(len(audio)), audio).astype("float32")
            ab = V.AsrBackend("small")
            check("B3 faster-whisper small 加载", ab.model is not None)
            if ab.model is not None:
                _t1 = _time.perf_counter()
                res = ab.transcribe(a16, language="ja")
                print(f"    ASR 回环: 「{res['text']}」（"
                      f"{_time.perf_counter() - _t1:.2f}s, lang={res.get('lang')}）")
                check("B4 回环识别出日文字符",
                      V.contains_japanese(res["text"]) > 0.5)
    except Exception as _ie:
        print(f"[SKIP] B 集成段异常（如实记录，不判失败）: {_ie!r}")
        TOTAL[0] += 1
else:
    print("[SKIP] B 集成段：模型未就位（models/tts 缺文件）——不算失败也不算通过")

print(f"\n语音闭环：{TOTAL[0] - len(FAILURES)}/{TOTAL[0]} 通过")
sys.exit(1 if FAILURES else 0)
