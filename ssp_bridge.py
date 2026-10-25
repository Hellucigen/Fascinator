# -*- coding: utf-8 -*-
"""ssp_bridge — 把 Haru 的话语/状态推给桌面伺か（SSP ghost），走 SSTP over HTTP。

实测依据（2026-10-13，本机 SSP + ghost emily4/sagiri_tama）：
  · SSTP-over-HTTP：POST http://127.0.0.1:9801/api/sstp/v1，
    请求行必须是 `SEND SSTP/1.0`（不是裸 SSTP/1.0）；
  · SEND + Script + Option:notranslate → 200 OK（ghost 接受，气泡显示）；
  · COMMUNICATE → 400（ghost 默认拒外部对话，正常——我们只要嘴，不借脑）。

边界：SSP 是"表现层"。Haru 的大脑（图谱/表达决策/生活循环）全在 FAS 侧，
ghost 词典只负责把送来的さくらスクリプト演出成气泡+动画。失败绝不影响
主链路（错误隔离 + 只告警）。六态→表情映射暂用通用演出，将来做
Haru 专属 ghost 时在 STATE_SCRIPT 里精调（自绘 shell 后 surface 号可控）。
"""
from __future__ import annotations

import logging
import re
import urllib.request

logger = logging.getLogger("ssp_bridge")

DEFAULT_URL = "http://127.0.0.1:9801/api/sstp/v1"

# avatar 六态 → さくらスクリプト演出。原则：speaking 由话语本身承担；
# 其余态对**第三方 ghost**只发收束命令（\0\e）——给别人的角色硬塞
# "聆听中…"文本既傻也越权（那是 ghost 自己词典的叙事权）。表情级映射
# （surface 号/dressup）等 Haru 专属 ghost（自绘 shell+词典）再做，
# 届时在下表里逐态填脚本即可，桥接口不变。
STATE_SCRIPT = {
    "speaking": None,
    "listening": r"\0\e",
    "thinking": r"\0\e",
    "interrupted": r"\0\e",
    "error": r"\0\e",
    "idle": r"\0\e",             # 收束气泡/停说话动画
}

_REF = [0]


def _scrub(text: str) -> str:
    """用户文本进さくらスクリプト前的消毒：反斜杠转义、控制字符剥离，
    保证原样显示而不是被执行。"""
    t = str(text or "").replace("\\", "\\\\")
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", t)
    return t[:3000]


def _post_sstp(url: str, script: str, timeout: float = 4.0) -> bool:
    _REF[0] += 1
    body = ("SEND SSTP/1.0\r\nCharset: UTF-8\r\nSender: FAS-Haru\r\n"
            "Receiver: Shiori\r\nScript: %s\r\nOption: notranslate\r\n"
            "RefID: haru-%d\r\n\r\n" % (script, _REF[0]))
    try:
        req = urllib.request.Request(url, data=body.encode("utf-8"),
                                     headers={"Content-Type": "text/plain; charset=UTF-8"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = r.read().decode("utf-8", "ignore")
            first = resp.splitlines()[0] if resp else ""
            # 200=ghost 说了话；204=接受但无文本可展示（控制命令）——都算送达
            # （实测：纯 \e 收束命令回 204，只认 200 会把它误判为失联）
            return ("200" in first) or ("204" in first)
    except Exception as e:                        # noqa: BLE001
        logger.debug("[SSP] 推送失败（表现层，忽略）: %r", e)
        return False


def send_utterance(text: str, url: str = DEFAULT_URL) -> bool:
    r"""Haru 的话语 → ghost 气泡，说完收束（\e）。"""
    clean = _scrub(text)
    if not clean:
        return False
    return _post_sstp(url, r"\0\s[0]" + clean + r"\e")


def send_state(state: str, url: str = DEFAULT_URL) -> bool:
    """avatar 状态迁移 → 演出命令（speaking 由话语承担，不重复发）。"""
    script = STATE_SCRIPT.get(state)
    if not script:
        return True
    return _post_sstp(url, script)
