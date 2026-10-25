# -*- coding: utf-8 -*-
"""config_store — 运行时配置覆盖文件（P0：配置重启不再丢）。

背景（2026-10 审计实锤）：`PUT /api/config` 只写内存 dict（app.py），
进程重启后 `config = dict(DEFAULT_CONFIG)` 一切回零；且 `type(old)(v)`
把字符串 "false" 强转成 True。本模块补上全仓缺失的通用落盘通道，
形状照抄本仓唯一已验证的持久化先例 `data/llm_config.json`（原子写）。

优先级（高→低）：环境变量硬开关 > 覆盖文件 overlay > DEFAULT_CONFIG 默认。
overlay 只记录"用户显式改过"的键；其余键不写入，出厂升级默认值照常生效。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading

_LOCK = threading.Lock()


def load_overlay(path: str) -> dict:
    """读覆盖文件；不存在/损坏 → 空 dict（绝不让坏文件阻断启动）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_overlay(path: str, overlay: dict) -> bool:
    """原子写覆盖文件（tmp+replace，与仓内 json_store 同纪律）。"""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".",
                                   prefix=".cfg_overlay_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(overlay, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def merge_overlay(config: dict, overlay: dict) -> dict:
    """把 overlay 就地合并进 config（启动时与运行时各一次）。

    dict 段做一层浅合并（段内键保留出厂缺省，只覆盖显式改过的键），
    标量直接覆盖。返回同一个 config 对象，方便调用方保持引用不变。
    """
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(config.get(k), dict):
            config[k] = {**config[k], **v}
        else:
            config[k] = v
    return config


def coerce_value(current, raw):
    """按现值类型安全转换 PUT 进来的原始 JSON 值；失败抛 ValueError。

    修复实锤 bug：bool 键曾被 `type(old)(v)` 把 "false"/0 变成 True。
    bool 严格判定；数值宽容数字/数字串；dict/list 原样（已是 JSON 结构）；
    str 接受任意标量的字符串形式。
    """
    if isinstance(current, bool):
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)) and raw in (0, 1):
            return bool(raw)
        if isinstance(raw, str):
            s = raw.strip().lower()
            if s in ("true", "1", "on", "yes", "开", "是"):
                return True
            if s in ("false", "0", "off", "no", "否", "关"):
                return False
        raise ValueError(f"无法把 {raw!r} 解释为布尔值")
    if isinstance(current, int):
        return int(raw)
    if isinstance(current, float):
        return float(raw)
    if isinstance(current, dict):
        if not isinstance(raw, dict):
            raise ValueError(f"{raw!r} 不是对象，无法替换配置段")
        return {**current, **raw}      # 段替换同样是浅合并
    if isinstance(current, list):
        if not isinstance(raw, list):
            raise ValueError(f"{raw!r} 不是数组")
        return list(raw)
    if isinstance(current, str):
        return raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    # 现值类型未知（None 等）：接受 JSON 原值，不做猜测转换
    return raw


def apply_updates(config: dict, data: dict, overlay_path: str,
                  no_persist=()) -> dict:
    """运行时更新入口：校验→就地改 config→持久化到 overlay。

    只接受已存在于 config 的键（沿用原 PUT 语义：不发明未知开关）。
    no_persist：隐私敏感开关（如 screen_observe_enabled）——改内存立即
    生效，但**不写入覆盖文件**，重启后回到出厂默认（关闭）。
    返回 {"updated": {key: new}, "rejected": {key: reason}}。
    """
    updated, rejected = {}, {}
    with _LOCK:
        for k, raw in (data or {}).items():
            if k not in config:
                rejected[k] = "unknown_key"
                continue
            try:
                new = coerce_value(config[k], raw)
            except (ValueError, TypeError) as e:
                rejected[k] = str(e)
                continue
            config[k] = new
            updated[k] = new
        persist = {k: v for k, v in updated.items() if k not in no_persist}
        if persist:
            overlay = load_overlay(overlay_path)
            for k, v in persist.items():
                if isinstance(v, dict) and isinstance(overlay.get(k), dict):
                    overlay[k] = {**overlay[k], **v}
                else:
                    overlay[k] = v
            save_overlay(overlay_path, overlay)
    return {"updated": updated, "rejected": rejected}
