# -*- coding: utf-8 -*-
"""avatar_state — 陪伴形象状态协议（P2：先接口后皮）。

设计约束（实施任务 §P2/§四-形象）：
  · 状态是"真实行为的结果"，不是装饰——由语音/回合/表达/故障各写入方
    显式设置，禁止随机卖萌；
  · 多写入方用优先级仲裁（高优先级状态存在期间，低优先级不抢占）；
  · 形象渲染端（未来 Live2D/立绘小窗）只读订阅本状态 + Charon 事件
    （topic=fas.avatar_state），换皮不重写对话系统；
  · 状态词不出现在用户可见文案（协议层，同 interaction_planner 纪律）。

状态机：idle / listening / thinking / speaking / interrupted / error
"""
from __future__ import annotations

import threading
import time

# 优先级：高者不被低者覆盖（低优先级写入被拒绝但不报错）。
# error/interrupted 属"必须被看见"的状态，压过一切活动态。
_PRIORITY = {"idle": 10, "listening": 20, "thinking": 30,
             "speaking": 40, "interrupted": 50, "error": 60}
VALID = frozenset(_PRIORITY)

# RLock：release() 持锁调用 set_state()（不可重入 Lock 会自死锁——
# 2026-10-12 tests/test_voice_loop.py A2h 真机抓到冻死进程）。
_LOCK = threading.RLock()
_state = {"state": "idle", "source": "boot", "since_ts": 0.0,
          "turn_id": None}
_history = []                     # 最近 24 条迁移（调试/审计面）
_pushers = []                     # [(name, fn(snapshot)->None)] 渲染/事件桥


def register_pusher(name: str, fn):
    """订阅状态迁移：fn(snapshot dict)。异常隔离，绝不反哺主链路。"""
    _pushers.append((name, fn))


def set_state(state: str, source: str = "", turn_id=None,
              force: bool = False) -> bool:
    """申请进入某状态。低优先级写入在高优先级存续时被拒（返回 False）。

    特例：同一 source 重入允许（刷新 since_ts）；idle 是"释放"——任何
    source 都能请求，但只会在无人持有更高优先级时生效。
    """
    if state not in VALID:
        return False
    with _LOCK:
        cur = _state["state"]
        if not force and _PRIORITY[state] < _PRIORITY[cur] and \
                _state["source"] != source:
            return False
        if state == "idle" and not force and _PRIORITY[cur] > _PRIORITY["idle"] \
                and _state["source"] != source:
            # 别的模块还持有高优先级 → 不越权释放
            return False
        prev = cur
        _state.update(state=state, source=source, since_ts=time.time(),
                      turn_id=turn_id)
        _history.append({"t": _state["since_ts"], "from": prev, "to": state,
                         "source": source})
        del _history[:-24]
        snap = snapshot()
    for name, fn in list(_pushers):
        try:
            fn(snap)
        except Exception:                          # noqa: BLE001 — 渲染端坏了不拖垮行为
            pass
    return True


def release(source: str, to: str = "idle") -> bool:
    """释放：只有当前状态的持有者本人（或 force）能退回。"""
    with _LOCK:
        if _state["source"] != source:
            return False
        return set_state(to, source=source, force=True)


def snapshot() -> dict:
    return dict(_state)


def recent(n: int = 12) -> list:
    return list(_history[-n:])
