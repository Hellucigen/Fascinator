# -*- coding: utf-8 -*-
"""sts2_sim.bridge — 真实 STS2 桥接适配器（T3 预备，2026-10-15）。

状态标注（任务书诚实纪律）：
  · 接口形状来自 Gennadiyev/STS2MCP 的 README 声称（E2）与其路由参考文档
    （端点存在性 E2，参数细节 E4 未验证）——真桥连上后第一件事是
    probe() 全量对账，本文件里所有 E4 项在实测前不得当事实用。
  · 决策链约定：与沙盒完全同形（snapshot/actions/apply），brain/kb
    不感知游戏真假——这是整条实验路线的核心复用承诺。
"""
import json

try:
    from urllib.request import Request, urlopen
    from urllib.parse import quote
except ImportError:                          # pragma: no cover
    Request = urlopen = None


class HttpBridge:
    """对 Gennadiyev/STS2MCP Mod REST 的客户端。
    端口 15526 经 README 确认（E2，2026-10-15）：mod 启动后自动在
    localhost:15526 开 HTTP，GET / 返回 {"status":"ok","message":...}。"""

    def __init__(self, base="http://127.0.0.1:15526", timeout=5):
        self.base = base.rstrip("/")
        self.timeout = timeout

    def _get(self, path):
        req = Request(self.base + path, headers={"Accept": "application/json"})
        with urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def _post(self, path, body):
        data = json.dumps(body).encode("utf-8")
        req = Request(self.base + path, data=data, method="POST",
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=self.timeout) as r:
            raw = r.read().decode("utf-8", "replace")
        try:
            return json.loads(raw)
        except ValueError:
            return {"ok": bool(raw), "raw": raw[:200]}

    def health(self):
        try:
            return self._get("/")
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    def raw_state(self):
        return self._get("/api/v1/game/state")          # 路径 E2，字段 E4

    def snapshot(self):
        """真实状态 → 沙盒统一 snap 形状（brain 只见这个形状）。
        映射对账前，缺失字段一律 None/[] 并列入 unknown_fields。"""
        st = self.raw_state() or {}
        player = st.get("player") or {}
        combat = st.get("combat") or st.get("battle") or {}
        enemies = []
        unknown = []
        for e in (combat.get("enemies") or []):
            if not isinstance(e, dict):
                continue
            enemies.append({
                "name": e.get("name") or "?",
                "hp": int(e.get("hp") or 0),
                "block": int(e.get("block") or 0),
                "status": (e.get("powers") or {}),
                "intent": (e.get("intent") or {}).get("name"),
                "intent_tags": (e.get("intent") or {}).get("tags"),
                "intent_damage": (e.get("intent") or {}).get("damage"),
                "intent_hits": (e.get("intent") or {}).get("hits", 1),
            })
        hand = [c.get("name") or c.get("id") or "?"
                for c in (player.get("hand") or []) if isinstance(c, dict)]
        snap = {"hp": player.get("hp"), "block": player.get("block"),
                "energy": player.get("energy"), "hand": hand,
                "hand_idx": list(range(len(hand))),
                "status": player.get("powers") or {},
                "enemies": enemies,
                "turn": combat.get("turn"), "max_hp": player.get("max_hp"),
                "unknown_fields": unknown}
        for k in ("hp", "energy"):
            if snap[k] is None:
                unknown.append(k)
        if not enemies:
            unknown.append("enemies/intent")
        return snap

    def actions(self):
        """合法动作枚举。真实桥的 actions 端点未验证（E4）：
        优先 GET /api/v1/actions；没有则由 brain 按 snapshot 能量/手牌
        自行推导（沙盒同款降级）。"""
        try:
            r = self._get("/api/v1/actions")
            if isinstance(r, dict):
                return r.get("actions") or r.get("legal") or []
            return r or []
        except Exception:
            return []

    def apply(self, action_id, params=None):
        """POST 执行（端点与体格式 E4——probe() 会逐个探测候选路径）。"""
        for path, body in (
                ("/api/v1/play_card", {"card": action_id, **(params or {})}),
                ("/api/v1/action", {"id": action_id, **(params or {})}),
                ("/api/v1/command", {"cmd": action_id, **(params or {})})):
            try:
                return self._post(path, body)
            except Exception:
                continue
        return {"ok": False, "reason": "no_endpoint_probed"}


class MockBridge:
    """与 HttpBridge 完全同形的沙盒后端——CI/测试跑它（零网络零游戏）。
    bridge.py 的契约测试以 MockBridge 为准绳。"""

    def __init__(self, seed=0):
        import os
        from sts2_sim import world as W
        self.run = W.Run(seed=seed)

    def health(self):
        return {"ok": True, "via": "mock"}

    def snapshot(self):
        return self.run.snapshot()

    def actions(self):
        return self.run.actions()

    def apply(self, action_id, params=None):
        return self.run.apply(action_id)


def probe(bridge):
    """T3 首日对账清单：跑一遍形状断言，返回缺口报告（不猜补缺）。"""
    rep = {"health": bridge.health(), "unknown_fields": [], "endpoints": {}}
    try:
        snap = bridge.snapshot()
        rep["endpoints"]["snapshot"] = True
        rep["unknown_fields"] = snap.get("unknown_fields") or []
    except Exception as e:
        rep["endpoints"]["snapshot"] = str(e)[:120]
    try:
        acts = bridge.actions()
        rep["endpoints"]["actions"] = f"{len(acts)} 个"
    except Exception as e:
        rep["endpoints"]["actions"] = str(e)[:120]
    return rep
