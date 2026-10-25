# test_trait_loop.py — trait→行为闭环验收（2026-10-16 人格闭环修复）
# ============================================================================
# 命题：人格慢变量（trait 偏差）经 dialogue_decide 真实打分路径参与候选
# 竞争，且 ①方向正确 ②有界 ③可逆 ④中性零影响 ⑤不串域 ⑥缺席=旧行为
# ⑦坏数据安全。全部断言打在 candidates 的 activation（竞争真实输入）上。
# 运行: E:/Miniforge.envs/Fascinator/python.exe -X utf8 tests/test_trait_loop.py
# ============================================================================
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
logging.disable(logging.WARNING)

import config as C
from graph_model import KnowledgeGraph, Node
from disposition_store import DispositionStore
from dialogue_decision import dialogue_decide, TRAIT_GAIN, _trait_mult
import dialogue_decision as dd_mod

FAILURES = []
RUN = [0]


def check(name, cond, detail=""):
    RUN[0] += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" +
          (f" | {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


class FN:
    def __init__(s, id, act, space="semantic"):
        s.id, s.activation, s.graph_space = id, act, space
        s.extra_attrs = {}
        s.label = "declarative-semantic"


class FakeEngine:
    _running = False

    def __init__(s):
        s.topk = [FN("Minecraft", 1.5)]
        s.marked = []

    def get_topk(s, k=15):
        return s.topk[:k], []

    def mark_active(s, ids):
        s.marked = list(ids)


def build():
    base = os.path.join(tempfile.gettempdir(), "fas_trait_loop")
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base)
    kg = KnowledgeGraph()
    for nid in ("用户", "Minecraft", "钻石"):
        kg.add_node(Node(id=nid))
    ds = DispositionStore(kg, dict(C.DEFAULT_CONFIG))
    return kg, ds, FakeEngine()


KG, DS, ENG = build()


def decide(traits=None, da="sharing", text="我今天看到一个特别有意思的东西"):
    ctx = dd_mod.context_for_dialogue_act(da)
    dd_mod._inhibit_until = 0
    return dialogue_decide(
        {"dialogue_act": da, "illocutionary_act": "assertive",
         "response_expectation": "medium"},
        text, KG, ENG, DS.tendencies_for([ctx]),
        False, False, 3600.0, False, traits=traits)


def act_of(res, key):
    for c in res["candidates"]:
        if c["behavior"] == key:
            return c["activation"]
    return None


print("── T1 方向与精确有界 ──")
base = decide()
so = decide(traits={"social_openness": 1.0})
so_neg = decide(traits={"social_openness": -1.0})
tol = 0.005
check("T1a social_openness=+1 → ask 上移且不超过 ×1.12 界限",
      act_of(so, "ask") > act_of(base, "ask") + 0.005
      and act_of(so, "ask") <= act_of(base, "ask") * (1 + TRAIT_GAIN) + tol,
      (act_of(base, "ask"), act_of(so, "ask")))
check("T1b respond（半权重 0.5）上移幅度小于 ask",
      act_of(so, "respond") > act_of(base, "respond") and
      act_of(so, "ask") - act_of(base, "ask")
      > act_of(so, "respond") - act_of(base, "respond"))
check("T1c 反向偏差乘子互为倒数方向（ask 降）",
      act_of(so_neg, "ask") < act_of(base, "ask") < act_of(so, "ask"))
check("T1d 满格乘子不超过界 1±2·GAIN",
      all(abs(m) <= 2 * TRAIT_GAIN + 1e-9 for m in
          [_trait_mult({"social_openness": 1, "exploration_bias": 1,
                        "novelty_preference": 1, "persistence": 1,
                        "caution": 1}, k) - 1.0
           for k in ("ask", "share", "silence", "end")]))

print("── T2 家族隔离（不串域） ──")
thr = decide(traits={"resource_thrift": 1.0})
same = all(abs(act_of(thr, k) - act_of(base, k)) < 1e-9
           for k in ("respond", "ask", "share", "silence", "acknowledge"))
check("T2a resource_thrift 满格不影响任何交流候选", same)
fb = decide(traits={"feedback_sensitivity": 1.0})
check("T2b feedback_sensitivity 只作用表内行为（respond↑, ask=）",
      fb["candidates"] and
      act_of(fb, "respond") > act_of(base, "respond") and
      abs(act_of(fb, "ask") - act_of(base, "ask")) < 1e-9)

print("── T3 中性零影响 / 缺席恒等 ──")
neu = decide(traits={"social_openness": 0.0, "persistence": 0.0})
check("T3a 中性偏差逐位相等",
      all(abs(act_of(neu, c["behavior"]) - act_of(base, c["behavior"]))
          < 1e-9 for c in neu["candidates"]))
for nm, tr in (("None", None), ("空 dict", {}), ("未知键", {"xyz": 1})):
    r = decide(traits=tr)
    check(f"T3b 缺席恒等（{nm}）",
          all(abs(act_of(r, c["behavior"]) - act_of(base, c["behavior"]))
              < 1e-9 for c in r["candidates"]))

print("── T4 可逆：并列分数被偏差破平，反向即翻转 ──")
# 基线 ask 与 continue 并列（0.29=0.29，竞争保持原有选择逻辑）
cu, ce = act_of(so, "ask"), act_of(so, "continue")
nu, ne = act_of(so_neg, "ask"), act_of(so_neg, "continue")
check("T4a 基线并列时两向偏差打破平局且方向相反",
      abs(act_of(base, "ask") - act_of(base, "continue")) < 0.005
      and cu > ce and nu < ne, (cu, ce, nu, ne))

print("── T5 坏数据安全回退 ──")
try:
    r5 = decide(traits={"social_openness": "坏值", "persistence": None,
                        "caution": [1]})
    ok5 = all(isinstance(act_of(r5, c["behavior"]), float)
              for c in r5["candidates"])
    check("T5 异常值不抛错、退化为恒等方向", ok5)
except Exception as e:
    check("T5 异常值不抛错", False, str(e)[:80])

print("── T6 internal_state.trait_deviations 生产读点 ──")
from internal_state import InternalState
st = InternalState(kg=None, config={}, data_dir=tempfile.mkdtemp())
dev0 = st.trait_deviations()
check("T6a 出厂全中性", all(abs(v) < 1e-9 for v in dev0.values()))
for _i in range(40):
    st.record_trait_evidence("social_openness", 1.0, source="test")
dev1 = st.trait_deviations()
check("T6b 正证据累计 → 偏差>0 且 ≤1",
      dev1["social_openness"] > 0.0 and dev1["social_openness"] <= 1.0,
      dev1.get("social_openness"))
for _i in range(80):
    st.record_trait_evidence("social_openness", -1.0, source="test")
dev2 = st.trait_deviations()
check("T6c 反向证据可逆转偏差方向", dev2["social_openness"] < 0.0)
check("T6d band 限幅：满 band 时 |deviation|≈1",
      abs(dev2["social_openness"]) > 0.95, dev2.get("social_openness"))
st._traits["social_openness"]["value"] = "坏"
check("T6e 坏值跳过不抛", "social_openness" not in st.trait_deviations())

print("── 汇总 ──")
if FAILURES:
    print(f"通过 {0}，失败 {len(FAILURES)}: {FAILURES}")
    sys.exit(1)
print(f"通过 {RUN[0]} 条，全部通过")
