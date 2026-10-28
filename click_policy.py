# click_policy.py — 桌面操作的三层白名单分类器（安全 / 位置 / 敏感）
# ============================================================================
# 背景（2026-10-28 用户授权接入）：Haru 要能"点她看到的按钮"。能点任意按钮
# 的 agent = 能替你付款/删文件/发消息的 agent——社区里"agent 买东西"惊艳也
# 危险。本模块把每个待执行的桌面动作按**危害**分三层，决定直接做 / 要你确认 /
# 拒绝。它**只判定不执行**（纯函数、零副作用、不碰 pyautogui），是桌面控制的
# 策略内核；执行器（ui_desktop）拿它的裁决行事。
#
# 三层语义（默认策略，全部 config 可调）：
#   safe       安全操作：白名单应用窗口内、控件语义不碰敏感词的**语义点击**
#              (UIA Invoke)，以及无破坏性的窗口级操作（聚焦/最小化）。→ allow
#   positional 位置操作：基于像素坐标的点击（视觉定位天然不可靠——偏移、
#              DPI、遮挡都可能点错）。→ 默认 confirm（要你点头）
#   sensitive  敏感操作：目标应用不在白名单 / 控件名命中敏感词（删/付/发/
#              提交/登出…）/ 任何文本输入或按键（往不确定的字段写字）。→ confirm
#
# 硬总闸：config["desktop_control_enabled"] 默认 False——关时本模块对任何动作
# 直接返回 deny("未启用")，调用方不得触碰任何输入合成库。fail-closed：
# 判定异常一律降级为 deny，绝不因"读不到信息"而放行。
# ============================================================================

from __future__ import annotations

import re

# ── 默认敏感词（中英文控件/动作语义；命中即升敏感层）──────────────────
# 判据是"这个控件名暗示它会做不可逆/花钱/对外/毁数据的事"，而非控件位置。
DEFAULT_SENSITIVE_KEYWORDS = [
    # 破坏性 / 不可逆
    "删除", "清空", "卸载", "移除", "格式化", "重置", "还原", "注销", "销户",
    "退出登录", "登出", "退订", "取消订阅", "unsubscribe", "delete", "remove",
    "uninstall", "format", "reset", "log out", "logout", "sign out",
    "cancel subscription", "cancel order",
    # 花钱 / 交易
    "付款", "支付", "购买", "下单", "结算", "转账", "充值", "提现", "发送",
    "pay", "buy", "purchase", "checkout", "order now", "transfer", "wire",
    # 对外发声 / 提交 / 授权（离开本机、影响他人或第三方）
    "提交", "发送", "发布", "分享", "上传", "关注", "点赞", "回复", "转发",
    "授权", "同意", "接受", "许可", "submit", "send", "post", "publish",
    "share", "upload", "follow", "approve", "agree", "accept", "grant",
    # 系统级破坏
    "关机", "重启", "休眠", "power off", "shutdown", "restart", "suspend",
]

# ── 默认应用白名单（低危：点了也不可变难收场的本地生产力/娱乐）──────────
# 注意：白名单只让"语义点击 + 控件名不含敏感词"落到 safe；它**不放行**像素
# 点击、不放行文本输入、不放行敏感词控件——那三层各有自己的闸。用户可经
# config["desktop_safe_apps"] 增删。浏览器/银行/邮箱/支付类**故意不列**。
DEFAULT_SAFE_APPS = [
    "calculator", "notepad", "记事本", "写字板", "wordpad",
    "spotify", "vlc", "potplayer", "pot player",
    "personalterminal", "charon",           # Haru 自己的家（操作自己）
    "task manager", "任务管理器",            # 只读观察/无害
    "paint", "画图", "photos", "照片",
    "clock", "闹钟", "sticky notes", "便笺", "便签",
]

# 键入/组合键天然敏感（写进任意字段=任意文本注入；热键可触发系统行为）
_WRITING_KINDS = {"type", "text", "key", "hotkey", "shortcut"}
# 无副作用窗口级动作（聚焦/最小化/读标题：不改动应用内状态）→ safe 直放行
_BENIGN_WINDOW_OPS = {"focus", "minimize", "foreground", "title", "activate"}

# 合并敏感词表缓存（编译一次）
_re_cache: dict[str, re.Pattern] = {}


def _kw_patterns(cfg: dict) -> re.Pattern:
    words = list(DEFAULT_SENSITIVE_KEYWORDS)
    extra = cfg.get("desktop_sensitive_keywords") or []
    words += [str(w) for w in extra if w]
    key = "\x00".join(words)
    pat = _re_cache.get(key)
    if pat is None:
        parts = []
        for w in words:
            w = str(w)
            if re.match(r"[a-z]", w):
                # 英文：词边界 + 空格转 \s+
                parts.append(r"\b" + re.escape(w).replace(r"\ ", r"\s+") + r"\b")
            else:
                parts.append(re.escape(w))
        pat = re.compile("|".join(parts), re.I)
        _re_cache[key] = pat
    return pat


def _norm(s) -> str:
    return str(s or "").strip().lower()


def _app_in_list(app: str, whitelist: list) -> bool:
    a = _norm(app)
    return any(k.lower() in a or a in k.lower() for k in map(str, whitelist) if k)


def classify(action: dict, cfg: dict) -> dict:
    """把一次桌面动作判为 {tier, decision, reasons}。

    action 可用键（缺=更保守）：
      kind: click|invoke|type|key|focus|minimize|...
      method: pixel|uia|title（像素=视觉坐标；uia=无障碍语义元素；缺按 pixel 从严）
      target_app / window_title: 目标程序窗口标识
      element_name: 被点控件的语义名（UIA Name/AutomationId）
      text: 要输入的文本
    cfg: 读 desktop_control_enabled / desktop_safe_apps / desktop_sensitive_keywords
         / desktop_positional_confirm / desktop_sensitive_confirm
    返回 decision ∈ {allow, confirm, deny}。
    """
    reasons: list[str] = []
    if not (cfg or {}).get("desktop_control_enabled", False):
        return {"tier": "sensitive", "decision": "deny",
                "reasons": ["桌面控制未启用（desktop_control_enabled=false）"]}

    try:
        act = str(action.get("kind") or action.get("action") or "click").lower()
        method = str(action.get("method") or "pixel").lower()
        app = _norm(action.get("target_app") or action.get("window_title"))
        elem = str(action.get("element_name") or "")
        safe_apps = list((cfg or {}).get("desktop_safe_apps")
                         or DEFAULT_SAFE_APPS)

        # ① 敏感词命中（控件语义名）→ 直接敏感
        hit = None
        if elem:
            m = _kw_patterns(cfg).search(elem)
            if m:
                hit = m.group(0)
                reasons.append(f"控件『{elem[:24]}』命中敏感词『{hit}』")

        # ② 书写类动作（输入文本/按键）→ 敏感
        if act in _WRITING_KINDS and not hit:
            reasons.append(f"{act} 会向目标写入文本/按键（字段去向不可控）")

        # ③ 目标应用不在白名单 → 敏感
        app_ok = bool(app) and _app_in_list(app, safe_apps)
        if not app_ok and act not in _BENIGN_WINDOW_OPS and not hit:
            reasons.append("目标应用不在安全白名单"
                           + (f"（{app[:30]}）" if app else "（未标明目标）"))

        # ── 分层裁决 ──
        if act in _BENIGN_WINDOW_OPS and not hit:
            # 聚焦/最小化/读标题：可逆、不改动应用内数据 → 安全（白名单与否都可，
            # 但目标应用未知时仍保守要确认）
            tier = "safe" if app_ok or not app else "positional"
            if tier == "safe":
                reasons.append("安全层：窗口级无副作用操作（聚焦/最小化，可逆）")
        elif hit or act in _WRITING_KINDS or not app_ok:
            tier = "sensitive"
        elif method == "pixel":
            tier = "positional"          # 在白名单应用，但像素点击不可靠
        else:  # app_ok + 语义点击 + 无敏感词
            tier = "safe"

        # 决策
        if tier == "safe":
            decision = "allow"
            reasons.append("安全层：白名单应用内的无副作用语义操作")
        elif tier == "positional":
            # 像素点击默认可否直放由 desktop_positional_confirm 决定（默认需确认）
            decision = "deny" if (cfg or {}).get(
                "desktop_positional_deny", False) else "confirm"
            reasons.append("位置层：视觉像素坐标点击，需你确认（定位不可靠）")
        else:  # sensitive
            decision = "confirm" if (cfg or {}).get(
                "desktop_sensitive_confirm", True) else "deny"
            reasons.append("敏感层：需你逐次确认，默认不自动执行")
        return {"tier": tier, "decision": decision, "reasons": reasons}
    except Exception as e:                       # fail-closed
        return {"tier": "sensitive", "decision": "deny",
                "reasons": [f"策略判定异常，按拒绝处理：{e!r}"]}


def is_auto_allowed(action: dict, cfg: dict) -> bool:
    """便捷谓词：只有 allow 才 True（confirm/deny 都不自动执行）。"""
    return classify(action, cfg).get("decision") == "allow"
