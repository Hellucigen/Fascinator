# -*- coding: utf-8 -*-
"""pc_autonomy — 自主控制电脑的分级闸（2026-10-16 用户设立）。

一句话：她能不能碰这台电脑、什么时候能碰、以什么姿态碰——由一个
档位阶梯 + 一个正交开关决定，所有想动用本机资源的活动都来过这道门。

  level = off         一律不行（只准操作已经开好的东西）
          attended    有人在才准（键鼠闲置 < present_idle_s）
          unattended  无人在也准（真自主，用户显式授权后才拧到这档）
  background（正交）  启动后尝试最小化窗口，不抢用户焦点

设计纪律：
  · 本模块是**策略**；启动动作本身委托注入的 opener（默认 os.startfile，
    测试注入假执行器）——永不 shell=True，命令只能是 config 白名单。
  · 在场检测失败（非 Windows/无桌面会话）→ 保守视为不在场：attended
    档自动不可用，只有 unattended 明确授权才放行。宁可不做，不可越权。
  · 启动冷却/失败退避不在此（宿主状态归 activities），这里只回答
    "此刻准不准"和"怎么做"。
"""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import time

logger = logging.getLogger("pc_autonomy")

LEVELS = ("off", "attended", "unattended")


def cfg_of(config: dict) -> dict:
    return (config or {}).get("pc_autonomy") or {"level": "off"}


def idle_seconds() -> float | None:
    """距最后一次键鼠输入的秒数；取不到返回 None（调用方保守处理）。"""
    try:
        class _LII(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint),
                        ("dwTime", ctypes.c_uint)]
        lii = _LII()
        lii.cbSize = ctypes.sizeof(lii)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return None
        tick = ctypes.windll.kernel32.GetTickCount()
        return (tick - lii.dwTime) / 1000.0
    except Exception:                             # noqa: BLE001
        return None


def user_present(cfg: dict, idle_fn=idle_seconds) -> bool:
    idle = idle_fn()
    if idle is None:
        return False          # 测不到=不在场（保守）
    return idle < float(cfg.get("present_idle_s", 900))


def steam_games_running(cfg: dict, exclude: list | None = None) -> list:
    """Steam 库目录下正在运行的游戏（返回安装目录名，去重）。
    用途（2026-10-16 用户规则）：用户在玩**别的**游戏时，她不开自己的
    游戏、已开着的保存退出——避免抢占运存。判定"是游戏"不靠名单硬
    编码：steamapps/common 下的进程都是游戏；exclude 传她自己那款的
    目录名（如 "Slay the Spire 2"）。探针失败返回 []（当作没有在玩，
    不拦真实请求）。"""
    root = str(cfg.get("steamapps_dir") or "").replace("/", os.sep)
    if not root:
        return []
    low_root = root.lower().rstrip(os.sep)
    excl = {str(x).lower() for x in (exclude or [])}
    found: list = []
    try:
        import ctypes.wintypes as _wt

        class _PE64(ctypes.Structure):
            _fields_ = [
                ("dwSize", _wt.DWORD), ("cntUsage", _wt.DWORD),
                ("th32ProcessID", _wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", _wt.DWORD), ("cntThreads", _wt.DWORD),
                ("th32ParentPID", _wt.DWORD), ("th32Priority", _wt.LONG),
                ("th32SizeWrSet", ctypes.c_size_t),
                ("szExeFile", _wt.WCHAR * 260)]

        k32 = ctypes.windll.kernel32
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)
        if snap in (0, -1, 0xFFFFFFFF):
            return []
        try:
            e = _PE64()
            e.dwSize = ctypes.sizeof(_PE64)
            ok = k32.Process32FirstW(snap, ctypes.byref(e))
            while ok:
                h = k32.OpenProcess(0x1000, False, e.th32ProcessID)
                if h:
                    try:
                        buf = ctypes.create_unicode_buffer(1024)
                        size = _wt.DWORD(1024)
                        if k32.QueryFullProcessImageNameW(
                                h, 0, buf, ctypes.byref(size)):
                            p = str(buf.value or "").lower()
                            if p.startswith(low_root):
                                app = p[len(low_root):].split(os.sep)[0]
                                if app and app not in excl \
                                        and app not in found:
                                    found.append(app)
                    finally:
                        k32.CloseHandle(h)
                ok = k32.Process32NextW(snap, ctypes.byref(e))
        finally:
            k32.CloseHandle(snap)
    except Exception:                             # noqa: BLE001
        return []
    return found


def can_launch(config: dict, app: str, present: bool | None = None,
               idle_fn=idle_seconds) -> tuple[bool, str]:
    """当前时刻能否为活动 app 启动白名单程序。(允许?, 理由)"""
    cfg = cfg_of(config)
    level = str(cfg.get("level", "off"))
    if level == "off":
        return False, "自主控制电脑=关（只玩已开着的）"
    if app not in (cfg.get("apps") or {}):
        return False, "该程序不在白名单"
    if level == "attended":
        p = user_present(cfg, idle_fn) if present is None else bool(present)
        if not p:
            return False, "有人在时才干（当前无人在场）"
    # unattended：无条件过
    return True, ""


def launch(config: dict, app: str, opener=None,
           process_spawner=subprocess.Popen) -> tuple[bool, str]:
    """启动白名单程序。via=steam 走 steam:// URI（官方通道，Steam 自己在
    不在线都归它管）；via=exe 直起。opener 注入点=测试假执行器。"""
    cfg = cfg_of(config)
    spec = (cfg.get("apps") or {}).get(app) or {}
    if not spec:
        return False, "无白名单条目"
    via = str(spec.get("via", "steam"))
    if via == "steam":
        target = "steam://rungameid/%s" % spec.get("appid")
    else:
        target = str(spec.get("path") or "")
        if not target or not os.path.exists(target):
            return False, "exe 路径不存在"
    try:
        if opener is not None:
            opener(target)
        elif via == "steam":
            os.startfile(target)                   # Windows 官方协议
        else:
            process_spawner([target])
        logger.info("[pc_autonomy] 已启动 %s（%s）", app, target)
        return True, ""
    except Exception as e:                         # noqa: BLE001
        logger.warning("[pc_autonomy] 启动失败 %s: %r", app, e)
        return False, "启动失败: %s" % str(e)[:80]


def minimize_window(title: str, sleep_s: float = 8.0,
                    time_fn=time.sleep) -> bool:
    """后台运行姿态：等窗口出现后最小化（SW_MINIMIZE）。尽力而为——
    找不到窗/非 Windows 返回 False，不影响调用方主流程。"""
    try:
        u = ctypes.windll.user32
        deadline = time.time() + sleep_s
        hwnd = 0
        while time.time() < deadline:
            hwnd = u.FindWindowW(None, title)
            if hwnd:
                break
            time_fn(1.0)
        if not hwnd:
            return False
        u.ShowWindow(hwnd, 6)                      # SW_MINIMIZE
        return True
    except Exception:                             # noqa: BLE001
        return False


def window_exists(title: str) -> bool:
    """该标题的窗口此刻是否存在（与 minimize_window 同一查找语义）。
    用途（2026-10-18 晚间抢控事故）：游戏窗口在、只是 mod 桥不通时，
    这个实例几乎必然是**用户**的——她不该按启动键，更不该盖所有权戳。"""
    try:
        return bool(ctypes.windll.user32.FindWindowW(None, title))
    except Exception:                             # noqa: BLE001
        return False


def foreground_title() -> str:
    """当前前台窗口标题（观测失败返回空串=不据此拦人）。"""
    try:
        u = ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return ""
        buf = ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(hwnd, buf, 256)
        return buf.value or ""
    except Exception:                             # noqa: BLE001
        return ""


def close_app(config: dict, app: str, killer=None) -> tuple[bool, str]:
    """彻底关闭白名单程序进程（launch 的逆操作，2026-10-17 用户规则）：
    不玩了 / 局已结束 → 关程序**释放运存**，而不是退到主菜单还挂着进程装死。
    安全闸与启动对称：off 档拒绝、只认 apps 白名单里配了 window_title 的项、
    按窗口标题精确定位后 taskkill（不是宽泛 kill，绝不波及别的进程）。
    killer 为测试注入点。"""
    cfg = cfg_of(config)
    if str(cfg.get("level", "off")) == "off":
        return False, "自主控制关闭（close 需 attended/unattended）"
    spec = (cfg.get("apps") or {}).get(app) or {}
    title = str(spec.get("window_title") or "").strip()
    if not spec or not title:
        return False, "无白名单条目或未配窗口标题"
    # 只杀标题匹配这一个程序；/FI 过滤把目标锁死在该窗口进程树
    cmd = ["taskkill", "/F", "/FI", "WINDOWTITLE eq %s*" % title]
    try:
        if killer is not None:
            rc = killer(cmd)
        else:
            r = subprocess.run(cmd, capture_output=True, timeout=20)
            rc = r.returncode
        if rc == 0:
            logger.info("[pc_autonomy] 已关闭 %s（窗口「%s」，运存释放）",
                        app, title)
            return True, ""
        logger.info("[pc_autonomy] 关闭 %s：未命中进程（可能已退出）", app)
        return False, "no_process"
    except Exception as e:                          # noqa: BLE001
        logger.warning("[pc_autonomy] 关闭失败 %s: %r", app, e)
        return False, "close_failed: %s" % str(e)[:80]


def launch_background(cfg: dict) -> bool:
    return bool(cfg_of(cfg if "pc_autonomy" in (cfg or {}) else
                       {"pc_autonomy": cfg}).get("background"))
