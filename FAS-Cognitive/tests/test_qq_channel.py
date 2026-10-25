# -*- coding: utf-8 -*-
"""QQ 通道（OneBot v11 适配）离线测试：全程只打本地 mock 服务，
绝不触碰任何真实网络/真实消息（2026-10-22 验收约束）。"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from qq_channel import QQChannel, flatten_segment

_APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

FRIEND = 10001          # 白名单内的假好友号
STRANGER = 20002        # 白名单外
OWNER = 30003           # 主人号（回显防环）

received = []           # mock OneBot 收到的 /send_private_msg payload


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode("utf-8"))
        received.append((self.path, body))
        out = json.dumps({"status": "ok", "retcode": 0,
                          "data": {"message_id": 999}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def _serve():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _cfg(url):
    return {"qq_enabled": True, "qq_onebot_url": url,
            "qq_friends": [FRIEND], "qq_owner_uin": OWNER, "qq_token": ""}


def _ev(uid, text, mid=1):
    return {"post_type": "message", "message_type": "private",
            "user_id": uid, "time": 1792600000 + mid, "message_id": mid,
            "message": [{"type": "text", "data": {"text": text}}]}


def test_disabled_is_silent():
    ch = QQChannel({"qq_enabled": False})
    assert ch.on_event(_ev(FRIEND, "hi")) is False
    assert ch.fetch() == []
    r = ch.send("在吗", {"sender": str(FRIEND)})
    assert r["ok"] is False and "qq_enabled" in r["detail"]


def test_inbox_and_classify():
    srv = _serve()
    try:
        ch = QQChannel(_cfg("http://127.0.0.1:%d" % srv.server_port))
        assert ch.on_event(_ev(FRIEND, "你好呀", 1)) is True
        assert ch.on_event(_ev(OWNER, "我是Fascinator", 2)) is True
        assert ch.on_event({"post_type": "notice"}) is False       # 非消息事件
        assert ch.on_event({"post_type": "message",
                            "message_type": "group",
                            "user_id": FRIEND, "message": "群消息"}) is False
        msgs = ch.fetch()
        assert len(msgs) == 2
        kinds = {m["sender"]: m["kind"] for m in msgs}
        assert kinds[str(FRIEND)] == "other" and kinds[str(OWNER)] == "self"
        assert ch.fetch() == []                                   # 取空即清
    finally:
        srv.shutdown()


def test_send_whitelist_and_payload():
    srv = _serve()
    received.clear()
    try:
        ch = QQChannel(_cfg("http://127.0.0.1:%d" % srv.server_port))
        r1 = ch.send("你好，我是 Haru", {"sender": str(STRANGER)})
        assert r1["ok"] is False and "白名单" in r1["detail"]
        assert not received                                       # 真零外发
        r2 = ch.send("你好，我是 Haru", {"sender": str(FRIEND)})
        assert r2["ok"] is True
        path, payload = received[-1]
        assert path == "/send_private_msg"
        assert payload["user_id"] == FRIEND and "Haru" in payload["message"]
    finally:
        srv.shutdown()


def test_send_same_text_dedup():
    """两条应答路（主动镜像+被动回复）撞出同一句话：物理出口 120s 去重，
    后到的吞掉（2026-10-23"一句话发两遍"实锤回归位）。"""
    srv = _serve()
    received.clear()
    try:
        ch = QQChannel(_cfg("http://127.0.0.1:%d" % srv.server_port))
        a = ch.send("收到，Roger。", {"sender": str(FRIEND)})
        b = ch.send("收到，Roger。", {"sender": str(FRIEND)})
        assert a["ok"] is True and b["ok"] is False
        assert "去重" in b["detail"]
        assert len(received) == 1                                 # 物理只发一条
        c = ch.send("收到，Roger。 换个说法", {"sender": str(FRIEND)})
        assert c["ok"] is True                                    # 不同文不误吞
    finally:
        srv.shutdown()


def test_unreachable_reports_honestly():
    ch = QQChannel(_cfg("http://127.0.0.1:1"))   # 必拒端口
    r = ch.send("hi", {"sender": str(FRIEND)})
    assert r["ok"] is False and "不可达" in r["detail"]


def test_flatten():
    assert flatten_segment("plain") == "plain"
    assert flatten_segment([{"type": "text", "data": {"text": "a"}},
                            {"type": "image", "data": {}}]) == "a [image]"


# ── 主动镜像投递边界（2026-10-23 取证修复）────────────────────
# 取证：web 回合末 _charon_deliver(origin="reactive") 全通道扇出，镜像
# 无 origin 检查 → web 测试回答漏进用户 QQ；QQ 正常回复则双发。

def test_mirror_gate_rejects_reactive_and_unknown():
    from qq_channel import mirror_should_deliver
    assert mirror_should_deliver("reactive") is False      # 回合回答不镜像
    assert mirror_should_deliver("") is False
    assert mirror_should_deliver(None) is False


def test_mirror_gate_allows_proactive_only():
    from qq_channel import mirror_should_deliver
    assert mirror_should_deliver("proactive") is True      # 主动话语照常


def test_mirror_gate_wiring_in_app():
    """app._QQProactiveMirror.deliver 必须先过 mirror_should_deliver 再触
    hub（源码形态钉；行为级验收见运行时冒烟——app.py 不可离线 import）。"""
    app_src = open(os.path.join(_APP_ROOT, "app.py"),
                   encoding="utf-8").read()
    i = app_src.find("class _QQProactiveMirror")
    assert i > 0, "mirror 类应在 app.py 中"
    body = app_src[i:app_src.find("if charon_channels:", i)]
    j = body.find("mirror_should_deliver")
    assert 0 < j < body.find("channel_hub"), "gate 必须先于 hub 访问"


def test_mirror_reactive_produces_no_outbound():
    """端到端（离线）：真实 QQChannel 处于停用态时，即使误投也不外呼；
    与 gate 组合 = reactive 消息物理上到不了 OneBot。"""
    ch = QQChannel(_cfg("http://127.0.0.1:1"))
    ch.enabled = False
    r = ch.send("web 回合的回答", {"sender": str(FRIEND)})
    assert r["ok"] is False and not r.get("detail", "").startswith("已送达")
