# -*- coding: utf-8 -*-
"""voice_io — 日语语音闭环（P1）。

链路：麦克风持续监听 → 本地 VAD（Silero）切段 → 日语/多语 ASR
（faster-whisper）→ **复用现有对话主管道**（/api/nlp 同一入口，不建第二条）
→ 播报文本双轨（display=原文；tts=日语译文，OVT 教训）→ TTS
（kokoro-onnx 本地日语 → edge-tts 云兜底）→ 播放 → 用户开口即打断。

诚实边界（2026-10-12 写就，勿当成已实测）：
  · VAD/ASR/TTS 组件均为 CPU 可跑档（官方数据：Silero <1ms/30ms 音频；
    faster-whisper small int8 显存/内存 ~1.5GB；kokoro-onnx CPU）；
    端到端延迟与识别质量需真机验收。
  · 隐私 ephemeral：麦克风开关（voice_listen_enabled）永不持久化——
    重启必回"未监听"；原始音频**绝不落盘**，只保留转录文本进既有 chat_log
    通道（沿用主管道持久化）。
  · 打断语义：半双工+语义轮次（用户在 Haru 说话期间开口→停播+作废该轮
    在飞的 ASR/生成/播放任务，新语句按新轮处理）。不做全双工（强依赖
    AEC，8GB 笔记本工程量大，见全栈审计 §4.4）。

线程模型：采集/分段在 sounddevice 回调线程；识别/生成/播放在工作线程
（queue 传段）。主 Flask 进程不受语音侧异常影响：所有后端构造失败只降级
（status 里如实标注 reason），不抛。
"""
from __future__ import annotations

import logging
import os
import queue
import re
import threading
import time

logger = logging.getLogger("voice_io")

# ── 常量（与 DEFAULT_CONFIG voice_* 键一致，config 可覆盖）──────────────
SR = 16000                # 采集/ASR 采样率
CHUNK = 512               # silero v5+ 16k 要求 512 样本/块（32ms）

STATE_IDLE, STATE_LISTEN = "idle", "listening"
STATE_RECOGNIZING, STATE_THINKING, STATE_SPEAKING = "recognizing", "thinking", "speaking"


class _Epoch:
    """代次令牌：新一句话/新打断使旧 epoch 作废——旧的识别、生成、播放
    任务在提交副作用前检查 epoch，过期即静默丢弃（不得覆盖新对话）。"""

    def __init__(self):
        self._n = 0
        self._lock = threading.Lock()

    def bump(self) -> int:
        with self._lock:
            self._n += 1
            return self._n

    @property
    def current(self) -> int:
        return self._n


_JA_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


def contains_japanese(text: str) -> float:
    """粗略日语占比（平假名/片假名/汉字混合的启发式，够双轨分流用）。"""
    if not text:
        return 0.0
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    kana = sum(1 for c in chars if "ぁ" <= c <= "ヿ")
    return kana / len(chars)


def tts_prep(text: str, translate_fn, speak_lang: str, do_translate: bool,
             ) -> tuple[str, str]:
    """双轨分流（display≠tts）：返回 (tts_text, track_note)。

    - speak_lang=ja 且 do_translate：非日语文本经 translate_fn 转日语；
    - 已是日语/翻译失败：原文直送（诚实降级，note 记录原因）；
    - speak_lang 为其他/空：原文直送。
    绝不把用户输入语言强改——只处理"她要说出口的这句"。"""
    if speak_lang == "ja" and do_translate and text and \
            contains_japanese(text) < 0.15:
        try:
            if translate_fn is None:
                return text, "passthrough(no_translate_fn)"
            ja = str(translate_fn(text) or "").strip()
            if ja and contains_japanese(ja) > 0.3:
                return ja, "translated_zh_to_ja"
            return text, "passthrough(translate_weak)"
        except Exception as e:                    # noqa: BLE001
            logger.warning("[Voice] 翻译降级原文：%r", e)
            return text, "passthrough(translate_error)"
    return text, "passthrough"


# ── 后端（全部懒加载；失败→status 如实报 reason）─────────────────────

class VadBackend:
    """Silero VAD（pip silero-vad，onnxruntime 路径）。不可用→None，
    上层退化为"能量门"（RMS 阈值），仍可端到端测试。"""

    def __init__(self):
        self.model = None
        self.reason = ""
        try:
            from silero_vad import load_silero_vad
            self.model = load_silero_vad()
        except Exception as e:                    # noqa: BLE001
            self.reason = f"silero unavailable: {type(e).__name__}: {e}"
            logger.warning("[Voice] %s → 退化能量门", self.reason)

    def speech_prob(self, chunk512f32):
        if self.model is None:
            import numpy as np
            rms = float(np.sqrt(np.mean(chunk512f32.astype("float32") ** 2)))
            return 1.0 if rms > 0.02 else 0.0
        import torch
        with torch.no_grad():
            t = torch.from_numpy(chunk512f32.reshape(1, -1))
            return float(self.model(t, SR).item())


class AsrBackend:
    """faster-whisper（multilingual：日语为主、兼容用户中文输入）。"""

    def __init__(self, model_size: str = "small", device: str = "cpu",
                 compute_type: str = "int8"):
        self.model = None
        self.reason = ""
        self._lock = threading.Lock()
        try:
            from faster_whisper import WhisperModel
            self.model = WhisperModel(model_size, device=device,
                                      compute_type=compute_type)
        except Exception as e:                    # noqa: BLE001
            self.reason = f"faster-whisper unavailable: {type(e).__name__}: {e}"
            logger.warning("[Voice] %s", self.reason)

    def transcribe(self, pcm_f32, language: str = "auto") -> dict:
        """language=auto：不假设输入语言（用户可能中文/日语混说）。"""
        if self.model is None:
            return {"text": "", "error": self.reason or "asr_not_loaded"}
        with self._lock:
            try:
                segs, info = self.model.transcribe(
                    pcm_f32,
                    language=None if language in ("", "auto", None) else language,
                    vad_filter=False)
                text = " ".join(s.text.strip() for s in segs).strip()
                return {"text": text, "lang": getattr(info, "language", None),
                        "dur_s": round(len(pcm_f32) / SR, 2)}
            except Exception as e:                # noqa: BLE001
                return {"text": "", "error": f"{type(e).__name__}: {e}"}


class TtsBackend:
    """日语 TTS 回退链：kokoro-onnx（本地 Apache）→ edge-tts（云，兜底）→ 无声。"""

    def __init__(self, prefer: str = "auto", dll_dirs: list = None):
        self.kokoro = None
        self.kokoro_voice = ""
        self.edge_ok = False
        self.reason = ""
        self._extra_dll_dirs = [str(d) for d in (dll_dirs or [])]
        if prefer in ("auto", "kokoro"):
            self._try_kokoro()
        if self.kokoro is None and prefer in ("auto", "edge"):
            self._try_edge()
        if self.kokoro is None and not self.edge_ok:
            self.reason = "no tts backend (kokoro/edge 均不可用)"

    def _register_dll_dirs(self):
        """onnxruntime-gpu 的 CUDA 运行库不在系统 PATH 上，Windows 需显式
        注册 DLL 目录：①config.voice_tts_dll_dirs（本机可指隔壁 conda 环境
        的 Library/bin）；②pip nvidia-*-cu1x 包的 site-packages/nvidia/*/bin。
        缺失时 ort 落回 CPU EP（kokoro_onnx 自适应），不会炸掉合成。"""
        try:
            import sysconfig as _sc
            import pathlib as _pl
            for _d in self._extra_dll_dirs:
                if _d and _pl.Path(_d).is_dir():
                    os.add_dll_directory(_d)
            _nv = _pl.Path(_sc.get_paths()["purelib"]) / "nvidia"
            for _sub in ("cudnn", "cublas", "nvrtc"):
                _d = _nv / _sub / "bin"
                if _d.is_dir():
                    os.add_dll_directory(str(_d))
            # onnxruntime-gpu 的 CUDA EP 用**裸名** LoadLibrary("cudnn64_9"
            # ".dll")——capi 目录（CUDA 运行库的自洽集所在）不在默认搜索
            # 集里，必须显式注册（2026-10-21 GPU 接通最后一环）。
            try:
                import onnxruntime as _rt
                _capi = _pl.Path(_rt.__file__).parent / "capi"
                if _capi.is_dir():
                    os.add_dll_directory(str(_capi))
                    # 同环境还有 ctranslate2 带着另一枚 cudnn64_9.dll，
                    # 裸名搜索谁先落地不可控（2026-10-21 "Cannot load
                    # symbol cudnnCreate" 实锤）：用全路径把 capi 配套这枚
                    # **预载占名**——ort 之后 GetModuleHandle 只会拿到它。
                    import ctypes
                    _cud = _capi / "cudnn64_9.dll"
                    if _cud.is_file():
                        ctypes.WinDLL(str(_cud))
            except Exception:                      # noqa: BLE001
                pass
        except Exception:                          # noqa: BLE001
            pass

    def _try_kokoro(self):
        try:
            self._register_dll_dirs()
            import kokoro_onnx
            _here = os.path.dirname(os.path.abspath(__file__))
            model = os.environ.get(
                "KOKORO_MODEL", os.path.join(_here, "models", "tts",
                                             "kokoro-v1.0.onnx"))
            voices = os.environ.get(
                "KOKORO_VOICES", os.path.join(_here, "models", "tts",
                                              "voices.bin"))
            if os.path.isfile(model) and os.path.isfile(voices):
                self.kokoro = kokoro_onnx.Kokoro(model, voices)
                cand = [str(n) for n in self.kokoro.get_voices()]
                # 日语女声优先（Kokoro v1.0 ja：jf_alpha 等）；退回任意可用
                jf = [c for c in cand if c.startswith(("jf_", "jm_"))]
                self.kokoro_voice = (jf[:1] or cand[:1] or [""])[0]
        except Exception as e:                    # noqa: BLE001
            self.reason = f"kokoro unavailable: {type(e).__name__}: {e}"

    def _try_edge(self):
        try:
            import edge_tts  # noqa: F401
            self.edge_ok = True
        except Exception:                         # noqa: BLE001
            pass

    @property
    def name(self) -> str:
        return ("kokoro" if self.kokoro is not None
                else ("edge-tts" if self.edge_ok else "none"))

    def synthesize(self, text: str, lang: str = "ja"):
        """返回 (pcm_f32 mono, sample_rate)；失败返回 (None, reason)。"""
        if self.kokoro is not None and self.kokoro_voice:
            try:
                # kokoro-onnx 0.6.1：create() 同步返回 (audio, sr)——
                # 曾误用 asyncio.run 包装导致 "a coroutine was expected"
                # （2026-10-12 真机回环抓到）。
                # speed：实测（2026-10-22 速度矩阵）全假名日语在 1.0x 就是
                # 7.3字/s 正常语速；此前 15.7s 的拖沓是**汉字多的译文**被
                # espeak-ja 逐字长停造成（汉字文本 0.75字/s）——药方在翻译
                # 端（多假名 prompt），加倍速只会变快进音。保持 1.0，
                # KOKORO_SPEED_JA 环境变量留作调音口。
                _spd = float(os.environ.get("KOKORO_SPEED_JA", "1.0")) \
                    if lang == "ja" else 1.0
                samples, out_sr = self.kokoro.create(
                    text, voice=self.kokoro_voice, speed=_spd, lang=lang)
                return samples, int(out_sr or 24000)
            except Exception as e:                # noqa: BLE001
                logger.warning("[Voice] kokoro 合成失败，试兜底：%r", e)
        if self.edge_ok:
            try:
                return self._edge(text, lang), 24000
            except Exception as e:                # noqa: BLE001
                return None, f"edge failed: {e}"
        return None, self.reason or "tts_not_loaded"

    def _edge(self, text: str, lang: str):
        import asyncio
        import edge_tts
        import io
        import numpy as np
        voice = "ja-JP-NanamiNeural" if lang == "ja" else "zh-CN-XiaoxiaoNeural"
        buf = bytearray()

        async def _run():
            com = edge_tts.Communicate(text, voice)
            async for chunk in com.stream():
                if chunk["type"] == "audio":
                    buf.extend(chunk["data"])
        asyncio.run(_run())
        # edge 输出 mp3——需解码；无解码器时抛错由上层降级（记录原因）
        try:
            import soundfile as sf
            data, sr = sf.read(io.BytesIO(bytes(buf)), format="mp3")
        except Exception:                         # noqa: BLE001
            import imageio_ffmpeg  # 常见可选件；不可用则真降级
            raise RuntimeError("mp3 decode unavailable")
        import numpy as np
        if getattr(data, "ndim", 1) > 1:
            data = data.mean(axis=1)
        return data.astype("float32")


class FunAsrZhBackend:
    """中文专职识别（FunASR Paraformer，2026-10-13 接入主环境）。

    动机：whisper small 对中文/合成日语精度有限（回环实测）；本机
    E:/Models/nlp/Paraformer 中文整句实测全对、0.69s/句（CPU）。
    策略=级联：whisper 先自动检语种，判为 zh 的段交 FunASR 精认。"""

    def __init__(self, model_dir: str = r"E:\Models\nlp\Paraformer"):
        self.model = None
        self.reason = ""
        self._lock = threading.Lock()
        self.model_dir = model_dir

    def _ensure(self):
        if self.model is not None:
            return True
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from funasr import AutoModel
            self.model = AutoModel(model=self.model_dir,
                                   disable_update=True, disable_pbar=True)
            return True
        except Exception as e:                    # noqa: BLE001
            self.reason = f"funasr unavailable: {type(e).__name__}: {e}"
            logger.warning("[Voice] %s", self.reason)
            return False

    def transcribe(self, pcm_f32) -> str:
        if not self._ensure():
            return ""
        with self._lock:
            try:
                r = self.model.generate(input=pcm_f32, fs=SR,
                                        disable_pbar=True)
                return str(r[0].get("text", "")).replace(" ", "") if r else ""
            except Exception as e:                # noqa: BLE001
                logger.info("[Voice] funasr 识别失败：%r", e)
                return ""


class VoicePipeline:
    """陪伴层语音闭环协调器。

    构造即就绪但不碰麦克风：enabled 且 listen 时才开采集设备。
    主管道复用：turn_handler(text)->reply_text（由 app 注入，走 /api/nlp
    同一函数；语音只是"另一种输入通道"，不是第二套对话）。
    """

    def __init__(self, config, turn_handler, translate_fn=None,
                 logger_=None):
        self.config = config
        self.turn_handler = turn_handler
        self.translate_fn = translate_fn
        self.log = logger_ or logger
        self._epoch = _Epoch()
        self._q: queue.Queue = queue.Queue(maxsize=4)
        self._worker = None
        self._state = STATE_IDLE
        self._lock = threading.Lock()
        self._vad = None
        self._asr = None
        self._asr_zh = None          # FunASR 中文级联（懒加载，首次用时后台起）
        self._tts = None
        self._speaking_busy = False    # speak_async 并发闸
        self._stream = None          # sounddevice InputStream
        self._out = None             # sounddevice OutputStream（播放中）
        self.stats = {"segments": 0, "recognized": 0, "turns": 0,
                      "spoken": 0, "interrupts": 0, "asr_errors": 0,
                      "tts_errors": 0}
        self._progress = None          # speak 阶段进度（前端进度条轮询用）
        # 分段状态（回调线程持有）
        self._seg_buf: list = []
        self._seg_active = False
        self._seg_max_s = 15
        self._min_speech_s = 0.35
        self._last_speech_ts = 0.0
        self._reason = ""
        # 可注入时钟（默认真实时钟；测试可推进模拟静默超时）
        self._clock = time.time

    # ── 状态与后端（懒加载：只有用到才付模型成本）──
    def _ensure_backends(self):
        if self._vad is None:
            self._vad = VadBackend()
        if self._asr is None and \
                self.config.get("voice_asr_backend", "faster-whisper") != "off":
            self._asr = AsrBackend(
                str(self.config.get("voice_asr_model", "small")))
        if self._tts is None:
            self._tts = TtsBackend(str(self.config.get("voice_tts_backend", "auto")),
                           dll_dirs=list(self.config.get("voice_tts_dll_dirs") or []))

    def warm_tts(self) -> str:
        """TTS 常态开启：启动即加载本地合成后端（不动 ASR/VAD——麦克风
        仍守隐私闸，重启必关）。返回 'ready'/'unavailable:<原因>'。首次
        "读吧"因此不再卡在十几秒的模型加载上。幂等：已加载直接返回。"""
        if self._tts is not None and self._tts.name != "none":
            return "ready"
        if self._tts is None:
            self._tts = TtsBackend(
                str(self.config.get("voice_tts_backend", "auto")),
                dll_dirs=list(self.config.get("voice_tts_dll_dirs") or []))
        return "ready" if self._tts.name != "none" \
            else "unavailable:" + (self._tts.reason or "no backend")

    def status(self) -> dict:
        st = {"state": self._state,
              "enabled": bool(self.config.get("voice_enabled", False)),
              "listening": bool(self.config.get("voice_listen_enabled", False)),
              "speak_lang": self.config.get("voice_speak_language", "ja"),
              "asr_language": self.config.get("voice_asr_language", "auto"),
              "backends": {}, "stats": dict(self.stats),
              "progress": dict(self._progress) if self._progress else None,
              "reason": self._reason}
        for name, obj in (("vad", self._vad), ("asr", self._asr),
                          ("asr_zh", self._asr_zh), ("tts", self._tts)):
            if obj is None:
                st["backends"][name] = "not_loaded_yet"
            elif name == "vad":
                st["backends"][name] = "silero" if obj.model is not None \
                    else ("energy-fallback: " + obj.reason)
            elif name == "asr":
                st["backends"][name] = (obj.model is not None
                                        and f"faster-whisper:{self.config.get('voice_asr_model','small')}"
                                        or obj.reason)
            elif name == "asr_zh":
                st["backends"][name] = ("funasr-paraformer" if obj.model is not None
                                        else (obj.reason or "not_loaded_yet"))
            else:
                st["backends"][name] = obj.name if obj.name != "none" else obj.reason
        return st

    # ── 采集控制（幂等；失败不抛，只记 reason）──
    def start(self):
        """voice_enabled=true 时调用：确保 worker 在跑；listen=true 才开麦。"""
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._work_loop,
                                            daemon=True, name="voice-worker")
            self._worker.start()
        if self.config.get("voice_listen_enabled", False):
            self._open_mic()

    def stop(self):
        self._close_mic()

    def _open_mic(self):
        if self._stream is not None:
            return True
        try:
            import sounddevice as sd
            self._ensure_backends()
            self._stream = sd.InputStream(
                samplerate=SR, channels=1, dtype="float32",
                blocksize=CHUNK, callback=self._audio_cb)
            self._stream.start()
            self._set_state(STATE_LISTEN)
            self.log.info("[Voice] 麦克风已开（VAD=%s, ASR=%s）",
                          "silero" if self._vad.model is not None else "energy",
                          "ready" if self._asr.model is not None else "MISSING")
            return True
        except Exception as e:                    # noqa: BLE001
            self._close_mic()
            self._reason = f"mic open failed: {type(e).__name__}: {e}"
            self.log.warning("[Voice] %s", self._reason)
            return False

    def _close_mic(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:                     # noqa: BLE001
                pass
            self._stream = None
        if self._state == STATE_LISTEN:
            self._set_state(STATE_IDLE)

    # ── 采集回调（sounddevice 线程）：VAD→分段→入队 ──
    def _audio_cb(self, indata, frames, _t, status_ex):
        if status_ex:
            self.log.debug("[Voice] 流状态: %s", status_ex)
        # sounddevice 传 (frames, channels) 二维；兼容一维（注入/单测路径）
        arr = indata[:, 0] if getattr(indata, "ndim", 1) == 2 else indata
        chunk = arr.copy()
        prob = self._vad.speech_prob(chunk) if self._vad else 0.0
        now = self._clock()
        if prob >= 0.5:
            self._last_speech_ts = now
            if not self._seg_active:
                self._seg_active = True
                # 用户在 Haru 说话时开口 → 打断：停播 + 作废在飞任务
                if self._state == STATE_SPEAKING or self._out is not None:
                    self._interrupt()
                self._seg_buf = [chunk]
            else:
                self._seg_buf.append(chunk)
                if sum(len(c) for c in self._seg_buf) / SR > self._seg_max_s:
                    self._finish_segment(force=True)
        elif self._seg_active and now - self._last_speech_ts > 0.6:
            self._finish_segment()

    def _finish_segment(self, force=False):
        if not self._seg_active:
            return
        self._seg_active = False
        import numpy as np
        pcm = np.concatenate(self._seg_buf) if self._seg_buf else None
        self._seg_buf = []
        if pcm is None:
            return
        dur = len(pcm) / SR
        if dur < self._min_speech_s and not force:
            return                               # 噪声尾巴
        self.stats["segments"] += 1
        ep = self._epoch.current
        try:
            self._q.put_nowait((pcm, ep))
        except queue.Full:
            self.log.info("[Voice] 队列满，丢旧段")
            try:
                self._q.get_nowait()
                self._q.put_nowait((pcm, ep))
            except queue.Empty:
                pass

    # ── 注入接口（无麦克风环境的验收通道：测试音频/文件同样走主管道）──
    def feed_audio(self, pcm_f32):
        """外部（测试/文件解码）直接投一段语音样本，等效麦克风分段。"""
        self.stats["segments"] += 1
        self._q.put((pcm_f32, self._epoch.bump()))

    # ── 工作线程：ASR→主管道→双轨→TTS→播放（epoch 贯穿，作废即弃）──
    def _work_loop(self):
        while True:
            try:
                pcm, ep = self._q.get(timeout=1.0)
            except queue.Empty:
                if self.config.get("voice_enabled", False):
                    # 热开关同步：listen 关了但 stream 还开着→关
                    if not self.config.get("voice_listen_enabled", False):
                        self._close_mic()
                    elif self._stream is None:
                        self._open_mic()
                else:
                    self._close_mic()
                continue
            if ep != self._epoch.current:
                continue                          # 已被打断的旧段
            self._set_state(STATE_RECOGNIZING)
            res = self._asr.transcribe(
                pcm, str(self.config.get("voice_asr_language", "auto"))) \
                if self._asr and self._asr.model is not None \
                else {"text": "", "error": "asr_not_loaded"}
            text = (res.get("text") or "").strip()
            # 级联精认：whisper 判为中文的段交 FunASR（中文专职，实测更准；
            # 零 LLM 费用，本地模型 0.7s/句）。config 可关。
            if res.get("lang") == "zh" and text and \
                    self.config.get("voice_funasr_zh_enabled", True):
                if self._asr_zh is None:
                    self._asr_zh = FunAsrZhBackend()
                zh = self._asr_zh.transcribe(pcm)
                if zh:
                    self.log.info("[Voice] 中文精认：%r ← %r", zh[:40],
                                  text[:40])
                    text = zh
                    res["text"] = zh
                    res["asr"] = "funasr-paraformer"
            if not text:
                self.stats["asr_errors"] += 1
                self.log.info("[Voice] 识别为空/失败: %s", res.get("error", ""))
                self._set_state(STATE_LISTEN if self._stream else STATE_IDLE)
                continue
            self.stats["recognized"] += 1
            self.log.info("[Voice] 听到[%s]: %s", res.get("lang"), text[:60])
            if ep != self._epoch.current:
                continue
            self._set_state(STATE_THINKING)
            try:
                # 幂等闸：同一句转录在 8s 内不重复进主管道（防重复分段）
                reply = self.turn_handler(text)
            except Exception as e:                # noqa: BLE001
                self.log.warning("[Voice] 主管道异常：%r", e)
                self._set_state(STATE_LISTEN if self._stream else STATE_IDLE)
                continue
            self.stats["turns"] += 1
            if ep != self._epoch.current:
                self.log.info("[Voice] 回合完成时已被打断，出声作废")
                self._set_state(STATE_LISTEN if self._stream else STATE_IDLE)
                continue
            if reply:
                self.speak(str(reply))
            self._set_state(STATE_LISTEN if self._stream else STATE_IDLE)

    def speak_async(self, text: str) -> str:
        """后台线程出声（/api/voice/speak 端点用）：立即返回，进度走
        status()。返回 'ok' / 'disabled'（语音开关未开）/ 'busy'（正在出声）。"""
        if not self.config.get("voice_enabled", False):
            return "disabled"
        if self._speaking_busy:
            return "busy"
        self._speaking_busy = True

        def _run():
            try:
                self.speak(text)
            finally:
                self._speaking_busy = False

        threading.Thread(target=_run, daemon=True, name="voice-speak").start()
        return "ok"

    # ── 出声（双轨：说的是译文，显示是原文——显示由主管道负责）──
    def _set_progress(self, stage: str, pct: int, detail: str = ""):
        """出声进度上报（前端 BODY 进度条轮询 /api/voice/status 取此）。"""
        self._progress = {"seq": (self._progress or {}).get("seq", 0) + 1,
                          "stage": stage, "pct": pct, "detail": detail[:120],
                          "ts": time.time()}

    def speak(self, text: str):
        if not self.config.get("voice_enabled", False):
            self._set_progress("error", 100, "语音开关未开")
            return False
        self._set_progress("loading_models", 3, "首次会加载 kokoro+espeak（十几秒）")
        self._ensure_backends()
        self._set_progress("translating", 18, "显示原文→播报日语（双轨）")
        tts_text, note = tts_prep(
            text, self.translate_fn,
            str(self.config.get("voice_speak_language", "ja")),
            bool(self.config.get("voice_translate_tts", True)))
        # 语言匹配护栏（2026-10-21 实锤）：翻译服务掉线时 tts_prep 会把
        # 中文原文直送，日语音读中文 = "in Chinese yereta" 乱码音。这不是
        # 内容闸：只是**用 jf 声线念不出中文**这一物理事实——念不出就不念，
        # 显示轨（原文）不受影响，progress 如实报因。
        if (str(self.config.get("voice_speak_language", "ja")) == "ja"
                and contains_japanese(tts_text) < 0.15):
            self.stats["tts_errors"] += 1
            self.log.info("[Voice] 译文未就绪，跳过出声（不拿中文硬喂日语音）track=%s",
                          note)
            self._set_progress("error", 100,
                               "翻译服务暂不可用：本条只显示原文，不出声")
            return False
        self._set_progress("synthesizing", 40, "TTS 合成中（CPU 约 10-30s）")
        pcm, sr = self._tts.synthesize(tts_text, str(
            self.config.get("voice_speak_language", "ja")))
        if pcm is None:
            self.stats["tts_errors"] += 1
            self.log.warning("[Voice] TTS 不可用，无声降级：%s", sr)
            self._set_progress("error", 100, str(sr))
            return False
        import numpy as np
        pcm = np.asarray(pcm, dtype="float32")
        if getattr(pcm, "ndim", 1) > 1:
            pcm = pcm.mean(axis=1)
        ep = self._epoch.current
        dur_s = len(pcm) / sr
        self.log.info("[Voice] 出声 %dms（track=%s backend=%s）",
                      int(dur_s * 1000), note, self._tts.name)
        self._set_progress("playing", 55, "%.1fs 音频播放中" % dur_s)
        self._set_state(STATE_SPEAKING)
        try:
            import sounddevice as sd
            self._out = sd.OutputStream(samplerate=sr, channels=1,
                                        dtype="float32")
            self._out.start()
            step = sr // 10
            played = 0
            for i in range(0, len(pcm), step):
                if ep != self._epoch.current:     # 播放中被打断
                    break
                self._out.write(pcm[i:i + step])
                played += min(step, len(pcm) - i)
                if played % (step * 5) == 0:      # 每 0.5s 上报播放进度
                    self._set_progress("playing",
                                       55 + min(40, int(40 * played / len(pcm))),
                                       "%.1f/%.1fs" % (played / sr, dur_s))
        except Exception as e:                    # noqa: BLE001
            self.stats["tts_errors"] += 1
            self.log.warning("[Voice] 播放失败（可能无声卡输出）：%r", e)
            # 无输出设备时：合成已成功仍记 spoken（链路部分验证，如实标注）
            self._set_progress("error", 100, "播放设备异常：%s" % e)
        finally:
            try:
                if self._out is not None:
                    self._out.stop()
                    self._out.close()
            except Exception:                     # noqa: BLE001
                pass
            self._out = None
        self.stats["spoken"] += 1
        self._set_progress("done", 100,
                           "被打断收束" if ep != self._epoch.current else "说完")
        return True

    def _interrupt(self):
        """用户开口→立即停播 + 在飞回合作废 + interrupted 状态可见。"""
        self.stats["interrupts"] += 1
        self._epoch.bump()
        out = self._out
        if out is not None:
            try:
                out.stop()
            except Exception:                     # noqa: BLE001
                pass
        try:
            from avatar_state import set_state as _av
            _av("interrupted", source="voice")
        except Exception:                         # noqa: BLE001
            pass

    def _set_state(self, st):
        with self._lock:
            self._state = st
        try:
            from avatar_state import set_state as _av
            map_ = {STATE_IDLE: "idle", STATE_LISTEN: "listening",
                    STATE_RECOGNIZING: "listening", STATE_THINKING: "thinking",
                    STATE_SPEAKING: "speaking"}
            _av(map_.get(st, "idle"), source="voice")
        except Exception:                         # noqa: BLE001
            pass


# ── 单例（app.py 装配；热开关经 apply_control）────────────────────────
PIPELINE: VoicePipeline | None = None


def build_pipeline(config, turn_handler, translate_fn=None):
    global PIPELINE
    PIPELINE = VoicePipeline(config, turn_handler, translate_fn)
    return PIPELINE


def apply_control(pipeline: VoicePipeline | None, config):
    """按 config 热同步（flag 门控哲学同生活循环：每拍自查，无需重启）。
    隐私闸：listen 键重启后必然为出厂 False（不持久化），麦克风不会
    在无人显式开启时自开。"""
    if pipeline is None:
        return
    if config.get("voice_enabled", False):
        pipeline.start()
        if config.get("voice_listen_enabled", False):
            pipeline._open_mic()
        else:
            pipeline._close_mic()
    else:
        pipeline._close_mic()
