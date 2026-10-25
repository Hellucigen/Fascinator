# -*- coding: utf-8 -*-
"""usage_ledger — 云端调用记录、费用估算与月度预算降级（实施任务 §5）。

原则：
  · 记录一切经 llm_provider 出口的调用（模型/用途/耗时/token/错误/费用估算）；
  · 密钥绝不入日志与账本（本模块只见不到 key）；
  · 预算阈值来自 config["llm_monthly_budget_cny"]（0=不限，默认零行为变化）；
  · 超限=降级闸 over_budget()：调用出口直接抛 BudgetExhausted（快速失败，
    不重试、不换贵供应商静默烧钱），上层按既有失败路径走人设内致歉。
数据：data/usage_ledger.jsonl（追加式；按月统计即时解析，当前月才读得到）。
"""
from __future__ import annotations

import datetime
import json
import os
import threading

_LOCK = threading.Lock()
_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "data", "usage_ledger.jsonl")
_config: dict = {}


def configure(config: dict):
    """注入共享 config 引用（PUT /api/config 改动即时可见）。"""
    global _config
    _config = config if isinstance(config, dict) else {}


class BudgetExhausted(RuntimeError):
    """本月云端费用已达预算阈值——快速失败，拒绝继续消耗。"""


def estimate_cost_cny(model: str, prompt_tokens, completion_tokens) -> float:
    table = _config.get("llm_price_table") or {}
    price = table.get(model) or {}
    pin = float(price.get("in", 0) or 0)
    pout = float(price.get("out", 0) or 0)
    return round((int(prompt_tokens or 0) / 1000.0 * pin
                  + int(completion_tokens or 0) / 1000.0 * pout), 6)


def record(*, provider: str, model: str, purpose: str, latency_ms: int,
           prompt_tokens=None, completion_tokens=None, ok: bool,
           error: str = None, transport: str = "cloud"):
    """一行一调用；本地后端 transport="local" → 费用记 0。"""
    cost = 0.0 if transport != "cloud" else estimate_cost_cny(
        model, prompt_tokens, completion_tokens)
    row = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
           "provider": provider, "model": model, "purpose": purpose or "unlabeled",
           "latency_ms": int(latency_ms), "pt": prompt_tokens,
           "ct": completion_tokens, "ok": bool(ok),
           "err": (error or "")[:160] or None, "cost_cny": cost,
           "transport": transport}
    try:
        with _LOCK:
            os.makedirs(os.path.dirname(_PATH), exist_ok=True)
            with open(_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 账本坏了不拖垮调用主路


def _month_rows(now=None) -> list:
    prefix = (now or datetime.datetime.now()).strftime("%Y-%m")
    rows = []
    try:
        with open(_PATH, encoding="utf-8") as f:
            for line in f:
                if f'"{prefix}' in line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
    except OSError:
        return []
    return [r for r in rows if str(r.get("ts", "")).startswith(prefix)]


def month_summary(now=None) -> dict:
    rows = _month_rows(now)
    by_model, failed, calls = {}, 0, len(rows)
    total = 0.0
    for r in rows:
        c = float(r.get("cost_cny") or 0)
        total += c
        if not r.get("ok"):
            failed += 1
        m = f"{r.get('provider')}/{r.get('model')}"
        s = by_model.setdefault(m, {"calls": 0, "failed": 0, "cost_cny": 0.0,
                                    "prompt_tokens": 0, "completion_tokens": 0})
        s["calls"] += 1
        s["failed"] += 0 if r.get("ok") else 1
        s["cost_cny"] = round(s["cost_cny"] + c, 6)
        s["prompt_tokens"] += int(r.get("pt") or 0)
        s["completion_tokens"] += int(r.get("ct") or 0)
    return {"month": (now or datetime.datetime.now()).strftime("%Y-%m"),
            "calls": calls, "failed": failed,
            "cost_cny": round(total, 6),
            "budget_cny": float(_config.get("llm_monthly_budget_cny") or 0),
            "by_model": by_model}


def over_budget(now=None) -> bool:
    """预算闸：阈值>0 且本月估算费用已达 → True。阈值 0=不限（默认）。"""
    budget = float(_config.get("llm_monthly_budget_cny") or 0)
    if budget <= 0:
        return False
    return month_summary(now)["cost_cny"] >= budget


def guard():
    """llm_provider 出口前置检查：超限快速失败（抛 BudgetExhausted）。"""
    if over_budget():
        raise BudgetExhausted(
            f"本月云端费用估算已达预算阈值 "
            f"{_config.get('llm_monthly_budget_cny')} 元——已降级")
