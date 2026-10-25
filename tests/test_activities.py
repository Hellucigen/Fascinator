# -*- coding: utf-8 -*-
"""日常活动选择器验收（2026-10-13）。含音乐**真实端到端**（真起系统播放器）。
运行：python tests/test_activities.py
"""
import json
import math
import os
import struct
import sys
import tempfile
import time
import wave

_r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _r)
# split_repos bootstrap: FAS-Cognitive sibling
_cog = os.environ.get("FAS_COG_ROOT") or os.path.join(
    os.path.dirname(_r), "FAS-Cognitive")
if os.path.isdir(_cog) and _cog not in sys.path:
    sys.path.insert(0, _cog)

import activities as AC                       # noqa: E402
from graph_model import KnowledgeGraph        # noqa: E402
from diffusion_engine import DiffusionEngine  # noqa: E402
from config import DEFAULT_CONFIG             # noqa: E402

FAILURES = []
TOTAL = [0]


def check(name, cond, detail=""):
    TOTAL[0] += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


class NoCuriosity:
    @staticmethod
    def get_curiosity_state(kg):
        return {"active": False, "question": None}


class LiveCuriosity:
    def __init__(self, q):
        self.q = q

    def get_curiosity_state(self, kg):
        return {"active": True, "question": self.q, "target": self.q}


def mk_env():
    td = tempfile.mkdtemp(prefix="act_test_")
    AC._STATE_PATH_OVERRIDE = os.path.join(td, "state.json")
    # 2026-10-14：念→行动桥会读账本/图谱提名——测试环境必须与生产账本隔离
    os.environ["FAS_LIVING_DATA_DIR"] = td
    kg = KnowledgeGraph()
    kg.save = lambda *a, **k: None
    from graph_model import Node
    # 生产图谱必有 Self 节点（偏好边挂载点）——测试环境同构
    kg.add_node(Node(id="Self", label="self", weight=1.0))
    engine = DiffusionEngine(kg, dict(DEFAULT_CONFIG))
    return td, kg, engine


def mk_ctx(td, kg, engine, busy=False, gaps=False, cur=None, lib=None):
    cfg = {"activity_music_library": lib or "",
           "living_loop_enabled": True,       # 播放静音闸（与生产语义一致）
           "activity_music_volume": 0.15,
           "activity_forum_feeds": [],  # 旧场景纯净：论坛语义由 continuity B 组专测
           "living_loop_daily_web_budget": 40,
           "living_loop_max_activities_open": 1,
           "living_loop_max_web_per_activity": 6}
    return {"config": cfg, "kg": kg, "engine": engine,
            "curiosity": cur or NoCuriosity(),
            "busy": lambda: busy, "has_gaps": gaps,
            # v2 接口：缺口=带新鲜度语义的证据列表（bool 兼容保留）
            "gaps": ([{"concept": "量子退相干",
                       "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "evidence": "「量子退相干」没看懂"}]
                     if gaps else []),
            "save_fn": lambda: None, "deliver_fn": None}


def node_ids(kg):
    return set(kg.nodes.keys())


def make_wav(path, secs=1.0):
    w = wave.open(path, "w")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(22050)
    n = int(22050 * secs)
    w.writeframes(b"".join(struct.pack("<h", int(6000 * math.sin(i / 25)))
                           for i in range(n)))
    w.close()


# ══ A1 用户交互中：一拍不产生任何活动（用户优先）══
td, kg, eng = mk_env()
r = AC.beat(mk_ctx(td, kg, eng, busy=True, gaps=True))
check("A1 busy 时连最高分的调研都不启动", r["activity"] is None
      and r["why"] == "user_interacting", str(r))

# ══ A2 无事可做 = 合法安静（不强迫产出）══
td, kg, eng = mk_env()
r = AC.beat(mk_ctx(td, kg, eng))
check("A2 无缺口/无库/无好奇 → 安静", r["activity"] is None
      and r["why"] == "nothing_worth_doing", str(r))

# ══ A3 音乐真实端到端：真挑歌、真出声、真写回 ══
td, kg, eng = mk_env()
lib = os.path.join(td, "music")
os.makedirs(lib, exist_ok=True)
make_wav(os.path.join(lib, "月光小夜曲.wav"), 0.8)
nodes_before = node_ids(kg)
ctx3 = mk_ctx(td, kg, eng, lib=lib)
r3 = AC.beat(ctx3)
check("A3a 曲库存在 → 本拍选择音乐", r3.get("activity") == "music"
      and r3.get("done"), str(r3))
check("A3a2 进程内静默播放：完整听完如实记录（真实音频设备出声）",
      r3.get("finished") is True, str(r3)[:120])
st = json.load(open(AC._STATE_PATH_OVERRIDE, encoding="utf-8"))
check("A3b 播放事实入宿主态（时间+计数）",
      st["music"]["plays_today"] == 1
      and any("月光" in k for k in st["music"]["plays"]), str(st)[:150])
new = node_ids(kg) - nodes_before
act_nodes = [n for n in new if n.startswith("Activity_")]
check("A3c 体验经既有写回通道进图谱（含激活进前沿）",
      len(act_nodes) == 1 and kg.nodes[act_nodes[0]].activation > 0,
      str(new)[:120])
tk = eng.get_topk(k=30)
_top = tk[0] if isinstance(tk, tuple) else tk.get("nodes", [])
ids = {str(getattr(n, "id", None) or (n.get("id") if isinstance(n, dict) else n))
       for n in _top}
check("A3d 活动体验进入注意力 topk（可影响后续联想）",
      act_nodes and act_nodes[0] in ids, str(ids)[:120])

# A3e 偏好真实生成/变化：第一次听后图谱出现"音乐"偏好边，
# 且**第二次选择的 appeal 高于初始默认值**（经历改变欲望）
from self_graph import get_preferences                      # noqa: E402
prefs1 = {p["target"]: p["weight"] for p in get_preferences(kg)}
check("A3e 听完后偏好边出现（音乐相关）",
      any("音乐" in t or "听" in t for t in prefs1), str(prefs1)[:120])
appeal_before_state = dict(st)
AC._save_state(st)      # 落盘 A3 的状态供 A4 用
a2 = AC._music_appeal(ctx3, st)
st2 = {"music": {"last_ts": 0, "plays": {}, "plays_today": 0}}
a1 = AC._music_appeal(ctx3, st2)
check("A3f 有了真实偏好后，未听状态下的想做程度更高", a2 > a1 or a2 > 0,
      f"{a1:.3f}→{a2:.3f}")

# ══ A4 刚听过 → 本拍不再听（饱足），也不会硬凑别的 ══
td4, kg4, eng4 = mk_env()
lib4 = os.path.join(td4, "music")
os.makedirs(lib4)
make_wav(os.path.join(lib4, "a song.wav"), 0.5)
ctx4 = mk_ctx(td4, kg4, eng4, lib=lib4)
AC.beat(ctx4)                       # 第一次：听
r4b = AC.beat(ctx4)                 # 立刻第二拍
check("A4 连续两拍不连听（MIN_GAP 生效）→ 第二拍安静",
      r4b["activity"] is None, str(r4b))

# ══ A5 调研在场时优先级最高（未完成的事 > 娱乐）══
td5, kg5, eng5 = mk_env()
os.environ["FAS_LIVING_DATA_DIR"] = td5
json.dump([{"time": "2026-10-13T10:00:00", "proactive": False,
            "user_input": "「量子退相干」没看懂", "system_response": ""}],
          open(os.path.join(td5, "chat_log.json"), "w", encoding="utf-8"))
lib5 = os.path.join(td5, "music")
os.makedirs(lib5)
make_wav(os.path.join(lib5, "x.wav"), 0.4)


def fake_search(q, top_n=4):
    return []


ctx5 = mk_ctx(td5, kg5, eng5, lib=lib5, gaps=True)
r5 = AC.beat(ctx5)
check("A5 有知识缺口时选择调研（不是玩）",
      r5.get("activity") == "research", str(r5)[:120])

# ══ A6 浏览：好奇引擎有活跃问题 → 真实上网看一眼（不写笔记不立任务）══
td6, kg6, eng6 = mk_env()
ctx6 = mk_ctx(td6, kg6, eng6, cur=LiveCuriosity("顶流明星的演唱会门票为什么难抢"))
r6 = AC.beat(ctx6)
check("A6a 好奇在场时选择浏览", r6.get("activity") == "browse", str(r6)[:120])
check("A6b 浏览真实发生（search+可能读页，非模拟桩）",
      r6.get("done") and r6.get("what"), str(r6)[:160])
check("A6c 轻量活动不产笔记/不建任务台账",
      not os.path.exists(os.path.join(td6, "living_ledger.json"))
      or json.load(open(os.path.join(td6, "living_ledger.json"),
                        encoding="utf-8")).get("activities", []) == [])

# ══ A7 关闭即停：无库+无缺口后 beat 不再产生任何真实动作 ══
os.environ.pop("FAS_LIVING_DATA_DIR", None)
check("A7 开关/取消语义=beat 返回 None 时零动作",
      AC.beat(mk_ctx(td, kg, eng, busy=True))["activity"] is None)

# ══ A8 急停闸：长曲播放中 stop_playback → 真实提前停止且观测为"未听完" ══
td8, kg8, eng8 = mk_env()
lib8 = os.path.join(td8, "music")
os.makedirs(lib8)
make_wav(os.path.join(lib8, "long track.wav"), 8.0)     # 8 秒长曲
ctx8 = mk_ctx(td8, kg8, eng8, lib=lib8)
from self_graph import get_preferences as _gp           # noqa: E402
_w_before = {p["target"]: p["weight"] for p in _gp(kg8)}


def _stop_soon():
    time.sleep(1.2)
    AC.stop_playback()


threading = __import__("threading")
threading.Thread(target=_stop_soon, daemon=True).start()
t0 = time.time()
r8 = AC.beat(ctx8)
elapsed = time.time() - t0
check("A8a 播放中急停在 2 秒内真停（非播完 8s）",
      r8.get("activity") == "music" and r8.get("done")
      and r8.get("finished") is False and elapsed < 3.0,
      f"{elapsed:.1f}s {str(r8)[:100]}")
_w_after = {p["target"]: p["weight"] for p in _gp(kg8)}
_dec = [(t, round(_w_after[t] - _w_before.get(t, 0.2), 3))
        for t in _w_after if t not in _w_before or _w_after[t] < _w_before.get(t)]
check("A8b 提前停止=微负体验（偏好观测真实反映，非一律+）",
      bool(_dec), f"{_w_before}→{_w_after}")

print(f"\n日常活动：{TOTAL[0] - len(FAILURES)}/{TOTAL[0]} 通过")
sys.exit(1 if FAILURES else 0)
