# -*- coding: utf-8 -*-
"""screen_watch — 授权式屏幕观察（P3）。

纪律（实施任务 §P3 + 全栈审计 §4.3，Windows Recall 反面教材）：
  · 默认关闭；每次重启必回关闭（键在 PRIVACY_EPHEMERAL_KEYS，永不落盘）。
  · 只有显式开启才采集；开启期间每一次观察都发可见状态事件
    （topic=fas.screen_state，前端/壳据此亮"采集中"指示）。
  · 原始截图不落盘不上云：mss 抓屏 → 本地 RapidOCR 提文字 → 只把
    文字摘要+来源标记写入观察事件；截图字节即抛。
  · 限流：screen_observe_interval_s 最小间隔 + max_per_hour 小时上限，
    防失控轮询；观察事件带 hash 去重（同屏内容不重复入图/不重复表达）。
  · 观察≠表达：结果只作为带来源/时间/可信度标注的感知事件进现有图谱，
    "值不值得说"仍由既有表达管线裁决（不另起 LLM 调用、不重复发言）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time

logger = logging.getLogger("screen_watch")

_STATE_PATH_DEFAULT = None      # data/screen_watch_state.json（延迟解析）
_STATE = {"last_hash": "", "seen_hashes": [], "hour": "", "count": 0,
          "observations": 0, "last_error": "", "last_result": None,
          "running_since": 0.0}
_LOCK = __import__("threading").Lock()


def _state_path():
    return _STATE_PATH_DEFAULT or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data",
        "screen_watch_state.json")


def _load():
    try:
        _STATE.update(json.load(open(_state_path(), encoding="utf-8")))
    except (OSError, ValueError):
        pass


def _save():
    try:
        os.makedirs(os.path.dirname(_state_path()), exist_ok=True)
        tmp = _state_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_STATE, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _state_path())
    except OSError:
        pass


def _rate_ok(config) -> bool:
    import datetime
    hour = datetime.datetime.now().strftime("%Y-%m-%d-%H")
    with _LOCK:
        if _STATE.get("hour") != hour:
            _STATE["hour"] = hour
            _STATE["count"] = 0
        cap = int(config.get("screen_observe_max_per_hour", 6))
        if _STATE["count"] >= cap:
            return False
        _STATE["count"] += 1
        return True


def observe_once(config, observe_fn=None) -> dict:
    """一次授权观察：截屏→本地 OCR→只留文字（截图字节即抛，不落盘不上云）。

    observe_fn 可注入（测试用）；生产默认 eye.screen_ocr.recognize_text
    ——它内部截屏并返回 {items, full_text, count}，图像不出函数。
    返回 {"ok", "reason" | "digest", "duplicate", ...}；调用方据此
    注入观察事件/发可见状态。
    """
    if not config.get("screen_observe_enabled", False):
        return {"ok": False, "reason": "not_enabled(默认关；需显式开启)"}
    _load()          # 先恢复持久化计数，再过限频闸（顺序反了会重置小时计数）
    if not _rate_ok(config):
        return {"ok": False, "reason": "rate_limited(小时上限)"}
    try:
        if observe_fn is None:
            from eye.screen_ocr import recognize_text
            observe_fn = lambda: recognize_text()  # noqa: E731
        t0 = time.time()
        res = observe_fn() or {}
        items = res.get("items") or []
        flat = str(res.get("full_text") or
                   " ".join(str(it.get("text", "")) for it in items))[:600]
        h = hashlib.sha256(flat.encode("utf-8")).hexdigest()[:16]
        with _LOCK:
            dup = (h == _STATE.get("last_hash")) or (h in _STATE["seen_hashes"])
            _STATE["last_hash"] = h
            _STATE["seen_hashes"] = (_STATE["seen_hashes"] + [h])[-24:]
            _STATE["observations"] += 1
            _STATE["last_result"] = {"ts": time.time(), "digest": h,
                                     "n_texts": len(items)}
            _save()
        return {"ok": True, "digest": h, "duplicate": dup,
                "n_texts": len(items), "res": res,
                "elapsed_ms": int((time.time() - t0) * 1000),
                "preview": flat[:200]}
    except Exception as e:                        # noqa: BLE001
        _STATE["last_error"] = f"{type(e).__name__}: {e}"
        logger.warning("[Screen] 观察失败：%s", _STATE["last_error"])
        return {"ok": False, "reason": _STATE["last_error"]}


def status(config=None) -> dict:
    with _LOCK:
        st = {"observations": _STATE.get("observations", 0),
              "hour_count": _STATE.get("count", 0),
              "last_error": _STATE.get("last_error", ""),
              "running_since": _STATE.get("running_since", 0.0)}
    if config is not None:
        st["enabled"] = bool(config.get("screen_observe_enabled", False))
        st["restart_default"] = "persistent(用户 2026-10-14 授权常态；麦克风仍 ephemeral)"
    return st


def apply_runtime_toggle(on: bool):
    """PUT /api/config 联动（app 调用）：记录开启时刻，供指示器/审计。"""
    with _LOCK:
        _STATE["running_since"] = time.time() if on else 0.0
        _save()
