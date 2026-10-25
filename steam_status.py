# -*- coding: utf-8 -*-
"""steam_status — 零侵入游戏情境事件源（P3）。

依据（全栈审计 §4.3，官方文档核实）：Steam Web API
  ISteamUser/GetPlayerSummaries → state(0离线/1在线/2忙碌…) + gameextrainfo
  （当前正在玩的游戏名，无则缺失）；
  IPlayerService/GetRecentlyPlayedGames → 2 周内游玩记录+时长。
无注入、无读内存、无 mod——只读公开 API，需要免费 API key（环境变量
STEAM_API_KEY）+ 资料公开的 steam_id（config.steam_id）。

事件语义：只在**变化**时产生观察事件（开始玩/退出玩/换游戏/上线离线），
带去抖（state+game 指纹持久化），绝不每分钟重复"他在玩 XX"。
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request

logger = logging.getLogger("steam_status")

API = "https://api.steampowered.com"
_state_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "data", "steam_last.json")
_SECRET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "steam_secret.json")


def _api_key() -> str:
    """密钥优先级：环境变量 STEAM_API_KEY > data/steam_secret.json（gitignored，
    同 llm_secret 纪律）。绝不把 key 写进源码/日志/账本。"""
    k = os.environ.get("STEAM_API_KEY", "")
    if k:
        return k
    try:
        return str(json.load(open(_SECRET_PATH, encoding="utf-8")).get("api_key", ""))
    except (OSError, ValueError):
        return ""


def _load_last():
    try:
        return json.load(open(_state_path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_last(d):
    try:
        os.makedirs(os.path.dirname(_state_path), exist_ok=True)
        tmp = _state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, _state_path)
    except OSError:
        pass


def _get(path: str, params: dict) -> dict:
    q = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    req = urllib.request.Request(f"{API}{path}?{q}",
                                 headers={"User-Agent": "FAS-Haru/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _event_from_summaries(data, last, lg):
    """实时在线态通道（observed）：gameextrainfo 直接告诉你在玩什么。"""
    players = data.get("response", {}).get("players", [])
    if not players:
        return None, "steamid 无返回（资料需公开）"
    p = players[0]
    cur = {"state": int(p.get("personastate", 0)),
           "game": str(p.get("gameextrainfo", "") or "")}
    fp = f"{cur['state']}|{cur['game']}"
    if last.get("fingerprint") == fp:
        return {"changed": False, "current": cur, "event": None}, ""
    prev_game = last.get("game", "")
    if cur["game"] and cur["game"] != prev_game:
        kind = "game_started"
    elif prev_game and not cur["game"]:
        kind = "game_stopped" if cur["state"] > 0 else "went_offline"
    elif cur["state"] and not last.get("state"):
        kind = "came_online"
    else:
        kind = "state_changed"
    event = {"kind": kind, "game": cur["game"], "state": cur["state"],
             "ts": time.time(), "source": "steam_web_api", "trust": "observed"}
    _save_last({"fingerprint": fp, "rp_top": last.get("rp_top"),
                "rp_minutes": last.get("rp_minutes", 0), **cur})
    lg.info("[Steam] 情境事件：%s（%s）", kind, cur["game"] or "-")
    return {"changed": True, "current": cur, "event": event}, ""


def _event_from_recently_played(data, last, lg):
    """兜底通道（inferred）：GetRecentlyPlayedGames 稳定可达（实测），
    第一名游戏的 playtime_forever 在两次轮询间**增长** → 推断正在玩它。
    可信度如实标 inferred——这是时长增量证据，不是实时状态。"""
    games = data.get("response", {}).get("games") or []
    if not games:
        return None, "无游玩记录返回（资料隐私？）"
    top = games[0]
    name = str(top.get("name", ""))
    mins = int(top.get("playtime_forever", 0) or 0)
    cur = {"state": last.get("state", 1), "game": name, "minutes": mins}
    if (last.get("rp_top") == name and last.get("rp_minutes") == mins):
        return {"changed": False, "current": cur, "event": None}, ""
    first = last.get("rp_top") is None
    grew = last.get("rp_top") == name and mins > (last.get("rp_minutes") or 0)
    switched = bool(name) and last.get("rp_top") not in (None, name)
    kind = ("baseline" if first else
            "game_playing" if (grew or switched) else "state_changed")
    event = None
    if kind in ("game_playing",):
        event = {"kind": kind, "game": name, "state": cur["state"],
                 "ts": time.time(), "source": "steam_recently_played",
                 "trust": "inferred", "note": "playtime 增量推断"}
        lg.info("[Steam] 推断事件：正在玩 %s（时长 +%s 分）", name,
                mins - (last.get("rp_minutes") or 0))
    _save_last({"fingerprint": last.get("fingerprint"),
                "state": cur["state"], "game": name,
                "rp_top": name, "rp_minutes": mins})
    return {"changed": event is not None, "current": cur, "event": event,
            "baseline": first}, ""


def tick_once(config, logger_=None) -> dict:
    """一次轮询（双通道）：实时 summaries 优先；该端点不可达时退回
    recently-played 时长增量推断。changed=True 时 event 交调用方注入
    感知——图谱/表达由既有管线裁决，本模块只报事实。"""
    lg = logger_ or logger
    if not config.get("steam_poll_enabled", False):
        return {"ok": False, "changed": False, "reason": "disabled",
                "event": None}
    key = _api_key()
    sid = str(config.get("steam_id", "")).strip()
    if not key:
        return {"ok": False, "changed": False,
                "reason": "缺 STEAM_API_KEY（env 或 data/steam_secret.json）",
                "event": None}
    if not sid:
        return {"ok": False, "changed": False,
                "reason": "缺 steam_id（个人主页地址里的 7656… 数字串，PUT /api/config 设）",
                "event": None}
    last = _load_last()
    err = ""
    # 通道 1：实时在线态（observed）
    try:
        data = _get("/ISteamUser/GetPlayerSummaries/v2/",
                    {"key": key, "steamids": sid})
        out, why = _event_from_summaries(data, last, lg)
        if out is not None:
            out["ok"] = True
            out.setdefault("reason", why)
            return out
        err = why
    except Exception as e:                        # noqa: BLE001
        err = f"summaries {type(e).__name__}: {str(e)[:80]}"
    # 通道 2：recently played 增量（inferred）——本机实测该端点稳定
    try:
        data = _get("/IPlayerService/GetRecentlyPlayedGames/v1/",
                    {"key": key, "steamid": sid})
        out, why = _event_from_recently_played(data, last, lg)
        if out is not None:
            out["ok"] = True
            out["degraded_from"] = err
            out.setdefault("reason", why)
            return out
        return {"ok": False, "changed": False,
                "reason": f"{err}；recently_played：{why}", "event": None}
    except Exception as e:                        # noqa: BLE001
        return {"ok": False, "changed": False,
                "reason": f"{err}；recently_played {type(e).__name__}: {str(e)[:80]}",
                "event": None}
