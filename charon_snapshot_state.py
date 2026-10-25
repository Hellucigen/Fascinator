# -*- coding: utf-8 -*-
"""charon_snapshot_state.py — Charon 工作区快照的去重状态（2026-10-11）。

修复 02:08 案例的第一环：poller 的 last 快照 hash 存在进程内存，重启即丢，
导致未变化的旧笔记标题清单在重启首轮被当成满格新鲜事件重新注入。

语义（2026-10-11 诊断报告 §3）：
  unchanged  内容与上次完全一致 → 背景资料，不产生事件、不刷新激活
  first      无历史基线（首次安装/状态文件损坏）→ 允许建立初始快照，
             但按"背景资料"降档处理，不得伪装成"用户刚刚执行了动作"
  changed    实质内容变化 → 合法的新感知事件（满格激活）

纯 stdlib；状态文件 data/charon_snapshot_state.json（随 data/ 不入库）。
"""
import hashlib
import json
import os

STATE_FILENAME = "charon_snapshot_state.json"


def state_path(data_dir: str) -> str:
    return os.path.join(data_dir, STATE_FILENAME)


def load_prev_hash(data_dir: str):
    """读取上次成功处理的 digest hash；缺失/损坏 → None（安全降级为 first）。"""
    try:
        with open(state_path(data_dir), "r", encoding="utf-8") as f:
            h = json.load(f).get("digest_md5")
        return h if isinstance(h, str) and h else None
    except (OSError, ValueError):
        return None


def save_hash(data_dir: str, digest_md5: str) -> bool:
    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(state_path(data_dir), "w", encoding="utf-8") as f:
            json.dump({"digest_md5": digest_md5}, f, ensure_ascii=False)
        return True
    except OSError:
        return False


def digest_hash(digest: str) -> str:
    return hashlib.md5(digest.encode("utf-8")).hexdigest()


def decide(prev_hash, digest: str):
    """纯函数：返回 (kind, new_hash)，kind ∈ unchanged|first|changed。"""
    h = digest_hash(digest)
    if prev_hash is None:
        return "first", h
    if h == prev_hash:
        return "unchanged", h
    return "changed", h
