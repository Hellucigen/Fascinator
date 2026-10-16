"""fas.companion.charon_bridge — Charon（E:/Project/Charon）陪伴外壳通道。

Charon 是 Go+Wails 桌面 Life OS，且已是 FAS 的操作控制台。它内嵌一个
token 鉴权的本机 Bridge HTTP 服务（127.0.0.1:17734，X-Charon-Token 头，
backend/bridge/bridge.go:61–120），本客户端即对接该服务：
  - Utterance → POST /api/events {topic:"fas.utterance", payload}（前端 EventsOn 即得）
    可选同时 /api/notify toast（bridge.go:310）
  - MemoryEvent（陪伴向副本）→ /api/diary(:252) / /api/fleeting(:195) / /api/notes(:138)
  - 生活数据回读（上行感知源）→ GET /api/summary(:285)，转 CognitiveEvent
token 与端口读取自 ~/.personal-terminal/config.json（core/config.go:63–65）。

状态：临时陪伴外壳（ExpressionChannel:charon 槽，fas/registry.py）。
默认关闭：不 import 不构造则零生产行为变化；开启在 app 装配处以
config.companion_charon_enabled 控制（见 fas/companion/assembly.py）。
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error

from fas.contracts import CognitiveEvent, MemoryEvent, Utterance

logger = logging.getLogger("fas.companion.charon_bridge")

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.personal-terminal/config.json")
TOPIC_UTTERANCE = "fas.utterance"


class CharonBridgeChannel:
    """ExpressionChannel 实现（fas/protocols.ExpressionChannel.deliver）。"""

    name = "charon"

    def __init__(self, *, base_url: str = None, token: str = None,
                 config_path: str = DEFAULT_CONFIG_PATH, timeout: float = 3.0,
                 notify_toast: bool = False):
        self._base = base_url
        self._token = token
        self._config_path = config_path
        self._timeout = timeout
        self._notify_toast = notify_toast

    # ── 配置发现 ────────────────────────────────────────────

    def _ensure_config(self):
        if self._base and self._token:
            return True
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            logger.warning("[charon] 配置文件不可读：%s", self._config_path)
            return False
        port = cfg.get("bridge_port", 17734)
        self._base = self._base or f"http://127.0.0.1:{port}"
        self._token = self._token or cfg.get("bridge_token")
        return bool(self._base and self._token)

    # ── HTTP 底座 ───────────────────────────────────────────

    def _post(self, path: str, payload: dict) -> bool:
        if not self._ensure_config():
            return False
        req = urllib.request.Request(
            self._base.rstrip("/") + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "X-Charon-Token": self._token},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, OSError) as e:
            logger.warning("[charon] %s 投递失败：%s", path, e)   # 通道故障不反压
            return False

    def _get(self, path: str) -> dict | None:
        if not self._ensure_config():
            return None
        req = urllib.request.Request(
            self._base.rstrip("/") + path,
            headers={"X-Charon-Token": self._token})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            logger.warning("[charon] %s 读取失败：%s", path, e)
            return None

    # ── ExpressionChannel ───────────────────────────────────

    def deliver(self, utterance: Utterance) -> bool:
        ok = self._post("/api/events", {"topic": TOPIC_UTTERANCE,
                                        "payload": utterance.to_dict()})
        if ok and self._notify_toast and utterance.origin != "question":
            self._post("/api/notify", {"title": "Haru",
                                       "message": utterance.text[:200]})
        return ok

    # ── 陪伴向生活记录（可选，全部失败容忍） ─────────────────

    def journal(self, m: MemoryEvent) -> bool:
        return self._post("/api/diary", {
            "line": f"{m.subject} {m.predicate} {m.object}",
            "mood": m.extra.get("mood")})

    def capture(self, text: str, tags: list = None) -> bool:
        return self._post("/api/fleeting", {"body": text, "tags": tags or []})

    def read_recent(self, topic: str = None, limit: int = 50) -> list:
        """回读 Bridge 记账的事件（GET /api/events/recent，最新在前）。
        投递验证/外部工具用；bridge 未升级该端点时返回 []。"""
        import urllib.parse
        q = f"/api/events/recent?limit={int(limit)}"
        if topic:
            q += "&topic=" + urllib.parse.quote(topic, safe="")
        d = self._get(q)
        return (d or {}).get("events", [])

    def read_inbox(self) -> dict | None:
        """GET /api/inbox — 用户正在处理什么（最近便签/未完成待办/最近笔记）。
        陪伴侧感知轮询的供给源；bridge 未升级该端点时返回 None。"""
        return self._get("/api/inbox")

    def read_summary(self) -> dict | None:
        return self._get("/api/summary")


class JournalingChannel:
    """ExpressionChannel 装饰器：主动/提问话语投递成功时，另记一条 Charon 便签。

    陪伴留痕策略——她的话不只飘过屏幕成气泡，还在用户工作区落一笔，
    事后（或没看见气泡时）可查。便签失败绝不影响投递结果；reactive
    默认不留痕（聊天 UI 本身就是记录，避免噪音）。"""

    name = "charon"

    def __init__(self, inner: CharonBridgeChannel,
                 origins: tuple = ("proactive", "question"),
                 tags: tuple = ("haru",)):
        self._inner = inner
        self._origins = tuple(origins)
        self._tags = list(tags)

    def deliver(self, utterance: Utterance) -> bool:
        ok = self._inner.deliver(utterance)
        if ok and utterance.origin in self._origins:
            try:
                self._inner.capture(f"[{utterance.origin}] {utterance.text}",
                                    tags=self._tags)
            except Exception:                        # noqa: BLE001
                logger.debug("[charon] 便签留痕失败", exc_info=True)
        return ok

    def __getattr__(self, k):
        return getattr(self._inner, k)
