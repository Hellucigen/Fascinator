# qq_channel.py — QQ 通道（OneBot v11 HTTP 协议适配）
# ============================================================================
# 接法：NapCat / LLOneBot 等 OneBot 实现由用户自装，把"HTTP 事件推送"指向
# FAS 的 POST /api/qq/events；FAS 经 /send_private_msg 回发。选 OneBot 这个
# 通用 IM 协议而非 QQ 私有接口——任何 OneBot v11 服务端都走同一条通道代码。
#
# 安全边界（2026-10-22 验收约束，全部 fail-closed）：
#   · qq_enabled 默认 false：关时事件丢弃、fetch 恒空、send 拒发——零外呼；
#   · 出站白名单 qq_friends：只回给"名单内且主动给她发过话的人"
#     （回复目标取来话 sender），本通道没有主动 @ 任何人的路径；
#   · 主人自己的消息（user_id==qq_owner_uin，含她借主人号发出的回显）
#     标 self 交 hub 机械防回环；
#   · 事件端点仅应监听 127.0.0.1（与 FAS 同机），token 可配。
# ============================================================================
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from collections import deque

logger = logging.getLogger(__name__)


def mirror_should_deliver(origin, refs=None) -> bool:
    """主动镜像的投递边界（2026-10-23 取证修复）。

    只有**主动话语**（origin="proactive"——CI 表达、生活分享、任务汇报）
    允许镜像进 QQ。回合回答（origin="reactive"）属于它的来源通道：
    web/charon 的回答不得进 QQ（取证实锤：web 测试回答漏进用户 QQ）；
    QQ 回合的回答由通道回复路径（hub._run_turn）送达，不经镜像——
    否则同一条回答双发。origin 由各调用点显式标注，是当前唯一可靠的
    来源信号；refs 目前不参与判定，保留形参便于未来带目标通道时扩展。
    """
    return str(origin or "").strip() == "proactive"


def flatten_segment(message) -> str:
    """OneBot 消息段 → 纯文本。str 原样；list 取 text/描述型段。"""
    if isinstance(message, str):
        return message.strip()
    parts = []
    if isinstance(message, list):
        for seg in message:
            if not isinstance(seg, dict):
                continue
            t = str(seg.get("type") or "")
            data = seg.get("data") or {}
            if t == "text":
                parts.append(str(data.get("text") or ""))
            elif t == "at":
                parts.append(f"[某人:{data.get('qq', '')}]")
            elif t in ("image", "record", "face"):
                parts.append(f"[{t}]")
    return " ".join(p for p in parts if p).strip()


class QQChannel:
    """收：/api/qq/events 把私聊消息塞进 _inbox；hub 轮询 fetch 进认知管线。
    发：只走 send_private_msg，且目标必须在 qq_friends 白名单里。"""

    id = "qq"
    kind = "bidirectional"

    def __init__(self, config: dict):
        self._cfg = config if config is not None else {}
        self.profile = {"max_reply_chars": 300, "strip_markdown": True,
                        "poll_interval_s": 2.0}
        self._inbox = deque(maxlen=50)
        # 出口同文去重账（2026-10-23 实锤"一句话发两遍"）：主动镜像与
        # 被动回复是两条独立应答路，同一刺激下 LLM 会吐同文；hub 的
        # send_text 节流只拦得住镜像那条，回复走 _deliver→ch.send 绕过。
        # 去重放在这个**唯一物理出口**上：[(归一文本, ts)]，窗口内同文拒发。
        self._sent_log = deque(maxlen=40)
        self._lock = threading.Lock()
        self.stats = {"events_in": 0, "accepted": 0, "sent": 0,
                      "rejected_whitelist": 0, "rejected_disabled": 0,
                      "rejected_dup": 0, "send_failed": 0}
        self.last_error = ""

    # ── 配置读（热生效，config 是活字典）──────────────────
    def _enabled(self) -> bool:
        return bool(self._cfg.get("qq_enabled"))

    # hub 的 _channel_enabled 读属性——做成 property 保持热更新；
    # setter 供 hub.set_enabled 用：写回 config（单一真源，热生效）
    @property
    def enabled(self) -> bool:
        return self._enabled()

    @enabled.setter
    def enabled(self, val: bool):
        self._cfg["qq_enabled"] = bool(val)

    def _url(self) -> str:
        return str(self._cfg.get("qq_onebot_url") or "").rstrip("/")

    def _allow(self) -> set:
        out = set()
        for x in (self._cfg.get("qq_friends") or []):
            try:
                out.add(int(str(x).strip()))
            except ValueError:
                continue
        return out

    # ── 入站 ──────────────────────────────────────────────
    def on_event(self, body) -> bool:
        """POST /api/qq/events 调用。只认私聊消息事件；返回是否受理。"""
        self.stats["events_in"] += 1
        if not self._enabled():
            self.stats["rejected_disabled"] += 1
            return False
        if not isinstance(body, dict):
            return False
        if str(body.get("post_type")) != "message":
            return False
        if str(body.get("message_type")) != "private":
            return False          # 本期只接私聊；群消息留给认知成熟后
        try:
            uid = int(body.get("user_id") or 0)
        except (TypeError, ValueError):
            return False
        text = flatten_segment(body.get("message"))
        if not uid or not text:
            return False
        try:
            owner = int(self._cfg.get("qq_owner_uin") or 0)
        except (TypeError, ValueError):
            owner = 0
        kind = "self" if (owner and uid == owner) else "other"
        with self._lock:
            self._inbox.append({
                "text": text[:500], "sender": str(uid), "kind": kind,
                "time": float(body.get("time") or time.time()),
                "key": str(body.get("message_id") or
                           f"{uid}|{text[:60]}|{time.time():.0f}")})
        self.stats["accepted"] += 1
        logger.info("[QQ] 收到私聊 %s←%s: %s", kind, uid, text[:60])
        return True

    def classify(self, raw) -> str:
        return str((raw or {}).get("kind") or "other")

    def available(self) -> bool:
        return self._enabled() and bool(self._url())

    def fetch(self):
        if not self._enabled():
            return []
        with self._lock:
            out = list(self._inbox)
            self._inbox.clear()
        return out

    # ── 出站 ──────────────────────────────────────────────
    def send(self, text, meta=None):
        m = meta or {}
        try:
            to = int(m.get("sender") or m.get("to") or 0)
        except (TypeError, ValueError):
            to = 0
        if not to:
            # 主动投递（send_text）的 meta 没有 sender——回落到配置的默认
            # 目标（qq_default_target=柘榴）。白名单照旧把关：默认目标
            # 不在 qq_friends 里同样拒发。
            try:
                to = int(self._cfg.get("qq_default_target") or 0)
            except (TypeError, ValueError):
                to = 0
        if not self._enabled():
            self.stats["rejected_disabled"] += 1
            return {"ok": False, "detail": "qq_enabled=false（未发送）"}
        if to not in self._allow():
            self.stats["rejected_whitelist"] += 1
            return {"ok": False,
                    "detail": f"目标 {to} 不在 qq_friends 白名单（未发送）"}
        url = self._url()
        if not url:
            return {"ok": False, "detail": "qq_onebot_url 未配置（未发送）"}
        # 同文短时去重（见 __init__ 注释）：两条应答路撞出同一句话时，
        # 后到的那条在物理出口被吞——用户视角"一句话只出现一次"。
        norm = "".join(str(text).split())
        win = 120.0
        now = time.time()
        with self._lock:
            if any(n == norm and now - t < win for n, t in self._sent_log):
                self.stats["rejected_dup"] += 1
                logger.info("[QQ] 同文 %ss 内已发过，去重吞掉：%s",
                            int(win), str(text)[:40])
                return {"ok": False, "detail": "同文短时去重（未重复发送）"}
            self._sent_log.append((norm, now))
        payload = {"user_id": to, "message": str(text)[:300]}
        tok = str(self._cfg.get("qq_token") or "")
        if tok:
            payload["token"] = tok
        req = urllib.request.Request(
            url + "/send_private_msg",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     **({"Authorization": "Bearer " + tok} if tok else {})},
            method="POST")
        try:
            # 30s：NapCat 首条外发可能冷启动（消息管线/数据库同步），
            # 10s 实测在 17:32 咬过一次超时丢回复（send_failed 实锤）
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.loads(r.read().decode("utf-8", "ignore"))
            ok = (str(j.get("status")) in ("ok", "async")
                  or int(j.get("retcode") or -1) == 0)
            if ok:
                self.stats["sent"] += 1
                return {"ok": True, "detail": "已送达 OneBot 服务"}
            self.stats["send_failed"] += 1
            self.last_error = str(j)[:120]
            return {"ok": False, "detail": f"OneBot 拒绝: {str(j)[:100]}"}
        except (urllib.error.URLError, OSError, ValueError) as e:
            self.stats["send_failed"] += 1
            self.last_error = str(e)[:120]
            return {"ok": False, "detail": f"OneBot 不可达: {str(e)[:80]}"}

    def state(self) -> dict:
        return {"enabled": self._enabled(), "available": self.available(),
                "url_set": bool(self._url()),
                "whitelist": sorted(self._allow()),
                "inbox": len(self._inbox), "stats": dict(self.stats),
                "last_error": self.last_error}
