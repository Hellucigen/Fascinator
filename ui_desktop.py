# ui_desktop.py — 桌面控制执行器（受 click_policy 三层白名单 + 硬总闸约束）
# ============================================================================
# 纪律（2026-10-28 用户授权接入，默认全关）：
#   1) config["desktop_control_enabled"]=False 时本模块任何入口零副作用返回，
#      绝不 import/调用任何输入合成库（pyautogui/uiautomation）——"没接"等价。
#   2) 每个动作先过 click_policy.classify：
#         allow   → 执行（仅安全层）
#         confirm → 进待批队列（不执行），返回 pending；由 /api/desktop/approve
#                   人工点头后 execute_approved 才真做。默认敏感/位置都走这里。
#         deny    → 拒绝，带理由。
#   3) 输入合成库**按需导入**：只有 allow 且真要动手时才 import pyautogui /
#      uiautomation；缺失则如实报 unavailable，不崩溃、不假装成功。
# 与 QQ 通道、多模态网关同一 fail-closed 哲学。
# ============================================================================

from __future__ import annotations

import json
import logging
import os
import time

import click_policy

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.abspath(__file__))
_PENDING_PATH = os.path.join(_ROOT, "data", "desktop_pending.json")

# 能力探测只做"能否安全执行"，不执行；进程内缓存
_syn_imports: dict = {}


def _enabled(cfg: dict) -> bool:
    return bool((cfg or {}).get("desktop_control_enabled", False))


# ── 待批队列（confirm 层动作在此排队，人工 approve 后才执行）──────────────
def _load_pending() -> list:
    try:
        with open(_PENDING_PATH, encoding="utf-8") as f:
            return json.load(f).get("pending", [])
    except Exception:
        return []


def _save_pending(items: list) -> None:
    try:
        os.makedirs(os.path.dirname(_PENDING_PATH), exist_ok=True)
        tmp = _PENDING_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"pending": items}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _PENDING_PATH)
    except OSError as e:
        logger.warning("[Desktop] 待批队列落盘失败: %s", e)


def list_pending() -> list:
    return _load_pending()


def enqueue_pending(action: dict, reasons: list, tier: str = "") -> dict:
    items = _load_pending()
    # 同动作去重（同 kind+目标+控件不重复堆）
    sig = (action.get("kind"), action.get("target_app"),
           action.get("element_name"), action.get("text"))
    items = [p for p in items
             if (p["action"].get("kind"), p["action"].get("target_app"),
                 p["action"].get("element_name"), p["action"].get("text")) != sig]
    item = {"id": f"dsk_{int(time.time()*1000)%10**10}",
            "ts": time.time(), "tier": tier, "action": action, "reasons": reasons}
    items.append(item)
    _save_pending(items[-20:])
    logger.info("[Desktop] 动作待确认（%s）: %s %s → %s",
                reasons[0][:30] if reasons else "",
                action.get("kind"), action.get("target_app", ""),
                action.get("element_name", ""))
    return item


def approve_pending(pid: str, cfg: dict) -> dict:
    """用户点头后执行该待批动作并从队列移除。仍按 cfg 总闸复核。"""
    items = _load_pending()
    target = next((p for p in items if p.get("id") == pid), None)
    if not target:
        return {"ok": False, "reason": "待批项不存在或已处理"}
    if not _enabled(cfg):
        return {"ok": False, "reason": "桌面控制未启用"}
    res = _run(target["action"], cfg, forced=True)
    _save_pending([p for p in items if p.get("id") != pid])
    if isinstance(res, dict):
        res["action"] = target["action"]           # 供上层原子记录 ACTION 经历
    return res


def deny_pending(pid: str) -> dict:
    items = _load_pending()
    if not any(p.get("id") == pid for p in items):
        return {"ok": False, "reason": "待批项不存在"}
    _save_pending([p for p in items if p.get("id") != pid])
    return {"ok": True, "cancelled": pid}


# ── 主入口：请求一个桌面动作 ─────────────────────────────────────────────
def request_action(action: dict, cfg: dict) -> dict:
    """桌面动作总入口。返回 {ok/tier/decision/reason(s)/pending?}。

    action 至少含 kind；坐标类带 x,y；语义类带 target_app+element_name；
    输入类带 text。
    """
    if not _enabled(cfg):
        return {"ok": False, "reason": "桌面控制未启用（desktop_control_enabled=false）"}
    decision = click_policy.classify(action, cfg)
    tier = decision["tier"]
    act = decision["decision"]
    if act == "deny":
        logger.info("[Desktop] 拒绝（%s）: %s", tier, decision["reasons"])
        return {"ok": False, "tier": tier, "decision": "deny",
                "reasons": decision["reasons"]}
    if act == "confirm":
        item = enqueue_pending(action, decision["reasons"], tier)
        return {"ok": False, "pending": True, "id": item["id"],
                "tier": tier, "decision": "confirm",
                "reasons": decision["reasons"],
                "note": "需你在 Charon 点『批准』后才会执行"}
    # allow → 安全层直接执行
    return _run(action, cfg)


def _run(action: dict, cfg: dict, forced: bool = False) -> dict:
    kind = str(action.get("kind") or "click").lower()
    method = str(action.get("method") or "pixel").lower()
    try:
        if kind in ("focus", "activate"):
            return _focus(action)
        if kind == "minimize":
            return _minimize(action)
        if kind in ("click", "invoke", "double_click"):
            if method == "uia" and action.get("element_name"):
                return _uia_invoke(action, double=(kind == "double_click"))
            return _click(action, double=(kind == "double_click"))
        if kind in ("type", "text"):
            return _type_text(action)
        if kind in ("key", "hotkey", "shortcut"):
            return _press_keys(action)
        return {"ok": False, "reason": f"未知桌面动作 kind={kind}"}
    except _Unavailable as u:
        return {"ok": False, "unavailable": True, "reason": str(u)}
    except Exception as e:                       # noqa: BLE001
        logger.warning("[Desktop] 动作执行异常: %r", e)
        return {"ok": False, "reason": f"执行异常：{e!r}"}


class _Unavailable(Exception):
    pass


# ── 输入合成（按需导入；缺失如实报 unavailable）──────────────────────────
def _autogui():
    if "pyautogui" not in _syn_imports:
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
            _syn_imports["pyautogui"] = pyautogui
        except Exception as e:                   # noqa: BLE001
            _syn_imports["pyautogui"] = e
    m = _syn_imports.get("pyautogui")
    if isinstance(m, Exception) or m is None:
        raise _Unavailable(f"pyautogui 不可用（未安装？）：{m}")
    return m


def _click(action: dict, double: bool = False) -> dict:
    x, y = action.get("x"), action.get("y")
    if x is None or y is None:
        return {"ok": False, "reason": "像素点击缺坐标 x,y"}
    ag = _autogui()
    ag.click(int(x), int(y), clicks=2 if double else 1, duration=0.1)
    return {"ok": True, "done": f"click@({int(x)},{int(y)})",
            "note": "像素点击（若偏移说明视觉定位需校正）"}


def _type_text(action: dict) -> dict:
    text = str(action.get("text") or "")
    if not text:
        return {"ok": False, "reason": "无输入文本"}
    ag = _autogui()
    ag.write(text, interval=0.02)
    return {"ok": True, "done": f"type {len(text)}字"}


def _press_keys(action: dict) -> dict:
    keys = action.get("keys") or action.get("combo")
    ag = _autogui()
    if isinstance(keys, str):
        parts = keys.replace("+", " ").split()
        ag.hotkey(*parts) if len(parts) > 1 else ag.press(parts[0])
    elif isinstance(keys, list):
        ag.hotkey(*keys) if len(keys) > 1 else ag.press(keys[0])
    else:
        return {"ok": False, "reason": "按键参数缺失"}
    return {"ok": True, "done": f"keys {keys}"}


def _uia(action: dict):
    """Windows UI Automation（可选）：懒导入 comtypes/uiautomation。"""
    if "uia" not in _syn_imports:
        try:
            import uiautomation as auto          # 第三方 uiautomation 库
            _syn_imports["uia"] = auto
        except Exception as e:                   # noqa: BLE001
            _syn_imports["uia"] = e
    m = _syn_imports.get("uia")
    if isinstance(m, Exception) or m is None:
        raise _Unavailable(f"UIA 不可用（未装 uiautomation）：{m}")
    return m


def _find_window(auto, app: str):
    """按标题子串找顶层窗口（不完美，够用）。"""
    root = auto.GetRootControl()
    best = None
    key = (app or "").lower()
    for w in root.GetChildren():
        name = (getattr(w, "Name", "") or "")
        if key and key in name.lower():
            best = w
            break
    return best


def _uia_invoke(action: dict, double: bool = False) -> dict:
    auto = _uia(action)
    win = _find_window(auto, action.get("target_app") or action.get("window_title") or "")
    if win is None:
        return {"ok": False, "reason": f"找不到窗口：{action.get('target_app')!r}"}
    want = (action.get("element_name") or "").strip()
    hit = None
    for c in win.GetChildren():
        if want and want.lower() in (getattr(c, "Name", "") or "").lower():
            hit = c
            break
    if hit is None:
        return {"ok": False, "reason": f"窗口内找不到控件：{want!r}"}
    # 安全层已确认控件名不含敏感词；这里再按控件模式执行
    try:
        pat = hit.GetControlPattern("InvokePattern")
    except Exception:
        pat = None
    if pat is not None:
        pat.Invoke()
        return {"ok": True, "done": f"invoke『{want}』"}
    # 退路：控件中心点坐标点击（仍属白名单应用内的语义定位）
    rect = hit.BoundingRectangle
    ag = _autogui()
    ag.click((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2,
             clicks=2 if double else 1)
    return {"ok": True, "done": f"click-control『{want}』"}


def _focus(action: dict) -> dict:
    auto = _uia(action)
    win = _find_window(auto, action.get("target_app") or "")
    if win is None:
        return {"ok": False, "reason": f"找不到窗口：{action.get('target_app')!r}"}
    try:
        win.SetActive()
    except Exception:
        pass
    return {"ok": True, "done": f"focus {action.get('target_app')}"}


def _minimize(action: dict) -> dict:
    auto = _uia(action)
    win = _find_window(auto, action.get("target_app") or "")
    if win is None:
        return {"ok": False, "reason": f"找不到窗口：{action.get('target_app')!r}"}
    try:
        win.Minimize()
        return {"ok": True, "done": f"minimize {action.get('target_app')}"}
    except Exception as e:                       # noqa: BLE001
        return {"ok": False, "reason": f"minimize 不支持该控件：{e!r}"}


# ── 视觉定位闭环（2026-10-28）：看到按钮 → 求坐标 → 进待批卡 ──────────────
# 结构性安全（不靠自觉）：① 非白名单应用前置直接拒（连视觉都不叫）；
# ② 定位结果一律 method=pixel → click_policy 必落"位置层" → 必 confirm，
#    永远经你批准卡才执行（像素点击在策略里没有 allow 分支）；
# ③ 需 vision_api_enabled 且 desktop_control_enabled 双闸开，关时任一短路，
#    不截屏、不发视觉请求。不存在无人复核的自动执行路径。
import re as _re

_VJSON_RE = _re.compile(r"\{[^{}]*\}", _re.S)


def _parse_vision_locate(raw: str):
    """从视觉模型回复里抽 {found,x,y}。返回 (found, x, y) 或 (False, None, None)。"""
    if not raw:
        return False, None, None
    for cand in _VJSON_RE.findall(str(raw)):
        try:
            d = json.loads(cand)
        except Exception:
            continue
        if d.get("found") and d.get("x") is not None and d.get("y") is not None:
            try:
                return True, int(float(d["x"])), int(float(d["y"]))
            except (ValueError, TypeError):
                continue
    return False, None, None


def vision_locate_click(target_app: str, element_label: str, cfg: dict) -> dict:
    """视觉模型在整屏截图里定位 target_app 中名为 element_label 的控件，
    得到像素坐标后作为**位置层动作**入待批队列（必过人工确认）。"""
    cfg = cfg or {}
    if not cfg.get("desktop_control_enabled", False):
        return {"ok": False, "reason": "桌面控制未启用"}
    import llm_provider as _L
    if not _L.vision_enabled():
        return {"ok": False, "disabled": True, "reason": "视觉 API 未启用"}
    safe_apps = list(cfg.get("desktop_safe_apps") or click_policy.DEFAULT_SAFE_APPS)
    if not (target_app and click_policy._app_in_list(target_app, safe_apps)):
        return {"ok": False, "tier": "sensitive",
                "reason": f"目标应用『{target_app}』不在安全白名单，拒绝视觉定位点击"}
    try:
        from eye.screen_ocr import capture_png_b64
        img = capture_png_b64()
    except Exception as e:
        return {"ok": False, "reason": f"截屏失败：{e!r}"}
    q = ("这是整块主屏的截图。请在属于应用『" + str(target_app) + "』的窗口里，"
         "找到文字/名称含『" + str(element_label) + "』的可点击控件（按钮/图标）。"
         "只返回一个 JSON 对象，键为 found(布尔)、x、y（该控件中心相对"
         "整张图的像素坐标）。找不到就 {\"found\": false}。")
    vr = _L.vision_describe(img, q, purpose="vision_locate")
    if not vr.get("ok"):
        return {"ok": False, "reason": vr.get("reason", "视觉请求失败")}
    found, x, y = _parse_vision_locate(vr.get("text", ""))
    if not found:
        return {"ok": False, "reason": "视觉未定位到该控件：" + str(element_label)}
    action = {"kind": "click", "method": "pixel", "x": x, "y": y,
              "target_app": target_app, "element_name": element_label,
              "vision_located": True}
    res = request_action(action, cfg)
    res["located_at"] = [x, y]
    return res
