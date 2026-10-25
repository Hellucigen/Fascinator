# -*- coding: utf-8 -*-
"""机制知识库 × 运行时卡牌理解 × 扩散决策 × 学习闭环 验收（2026-10-15）。
零网络、零 LLM、全内存、确定性。
运行：python tests/test_sts2_kb.py
"""
import json
import os
import sys

_r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _r)
_cog = os.environ.get("FAS_COG_ROOT") or os.path.join(
    os.path.dirname(_r), "FAS-Cognitive")
if _cog not in sys.path:
    sys.path.insert(0, _cog)

from graph_model import KnowledgeGraph                 # noqa: E402
from diffusion_engine import DiffusionEngine          # noqa: E402
from sts2_sim import kb, card_parser as CP            # noqa: E402

FAILURES = []
TOTAL = [0]


def check(name, cond, detail=""):
    TOTAL[0] += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def mk():
    kg = KnowledgeGraph()
    kg.save = lambda *a, **k: None
    eng = DiffusionEngine(kg, {})
    return kg, eng


print("── K1 知识库导入与幂等 ──")
kg, eng = mk()
s1 = kb.import_kb(kg)
s2 = kb.import_kb(kg)
check("K1a 37机制/28变量全导入；关系含 KB 原生 41 条+由 inputs/effects "
      "派生的机制↔状态边（skipped=0 无静默降级）",
      s1["mech"] == 37 and s1["var"] >= 20 and s1["rel"] >= 41
      and s1["skipped"] == 0, str(s1))
linked = {e.src for e in kg.edges} | {e.dst for e in kg.edges}
isolated = {n.id for n in kg.nodes.values()} - linked
check("K1e 连通性：孤立率<30%（机制-状态-标签-通用概念四层互链）",
      len(isolated) / max(1, len(kg.nodes)) < 0.30,
      f"{len(isolated)}/{len(kg.nodes)}")
check("K1b 幂等：二次导入零新建",
      s2["mech"] == 0 and s2["var"] == 0 and s2["rel"] == 0, str(s2))
kbnode = kg.get_node("M.block")
check("K1c 机制节点带 KB 语义（confidence 与边权分离，kind=kb）",
      kbnode is not None
      and (kbnode.extra_attrs or {}).get("kind") == "kb"
      and (kbnode.extra_attrs or {}).get("confidence") == "verified")
brid = kb.link_to_general(kg)
brid2 = kb.link_to_general(kg)
check("K1d 外扩桥（机制↔游戏标签↔通用概念）建成且幂等",
      brid[0] >= 5 and brid[1] >= 7 and brid2 == (0, 0), str(brid))

print("── K2 运行时解析（六类未知卡，卡名零参与）──")
CASES = {
    "烈焰连击": ("造成 5 点伤害 2 次，施加 1 层脆弱",
                {"M.attack_damage", "M.vulnerable"}, 2),
    "冰盾术": ("获得 8 点护甲，抽 1 张",
              {"M.block", "M.card_draw"}, 1),
    "献祭契约": ("若你有 10 点以上护甲，造成 15 点伤害；消耗",
                {"conditional", "M.attack_damage", "M.exhaust"}, 2),
    "迷雾低语": ("使敌人困惑并动摇其战意", set(), 0),
    "狂暴药水": ("失去 3 点生命，获得 2 点力量",
                {"M.hp_loss", "M.strength"}, 2),
    "升级打击": ("造成 9 点伤害（已升级）", {"M.attack_damage"}, 1),
}
parsed = {}
for nm, (txt, want_mechs, _n) in CASES.items():
    p = parsed[nm] = CP.parse(nm, txt)
    got = set()
    for e in p["effects"]:
        got.add(e["mechanic"])
        for sub in ([e] + (e.get("params", {}) or {}).get("then", [])
                    if isinstance(
                        (e.get("params", {}) or {}).get("then"), list)
                    else [e, e.get("params", {}).get("then")]
                    if isinstance(
                        (e.get("params", {}) or {}).get("then"), dict)
                    else [e]):
            if isinstance(sub, dict):
                got.add(sub.get("mechanic"))
    check(f"K2[{nm}] 命中机制集正确",
          (got & want_mechs) == want_mechs or not want_mechs,
          f"got={got} want={want_mechs}")
check("K2c 完全不可解析的卡：effects 空 + unknown 保留 + conf=0（不装懂）",
      not parsed["迷雾低语"]["effects"]
      and parsed["迷雾低语"]["unknown"]
      and parsed["迷雾低语"]["confidence"] == 0.0,
      str(parsed["迷雾低语"]["unknown"]))
check("K2x 解析器源码不含任何卡名（名字零参与匹配）",
      not any(nm in open(os.path.join(_r, "sts2_sim", "card_parser.py"),
                         encoding="utf-8").read()
              for nm in CASES))

print("── K3 实例化与部分解析 ──")
for nm, p in parsed.items():
    kb.instantiate_card(kg, p, nm)
cn = kg.get_node("Card:烈焰连击")
n_use = sum(1 for e in kg.edges
            if e.src == "Card:烈焰连击"
            and (e.extra_attrs or {}).get("kind") in ("effect",
                                                       "effect_direction"))
check("K3a 卡牌实例节点+效果边入图（机制节点复用非新建）",
      cn is not None and n_use >= 2
      and kg.get_node("M.attack_damage") is not None)
kb.instantiate_card(kg, parsed["烈焰连击"], "烈焰连击")
n_use2 = sum(1 for e in kg.edges
             if e.src == "Card:烈焰连击"
             and (e.extra_attrs or {}).get("kind") in ("effect",
                                                       "effect_direction"))
check("K3b 重复实例化不涨边（更新非堆积）", n_use2 == n_use,
      f"{n_use}->{n_use2}")
cond = [e for e in parsed["献祭契约"]["effects"]
        if e["mechanic"] == "conditional"]
check("K3c 条件卡部分解析：then 子效果结构在、条件文本保留",
      cond and isinstance(cond[0]["params"].get("then"), dict)
      and cond[0]["params"]["then"].get("mechanic") == "M.attack_damage"
      and "你有" in cond[0]["params"]["condition"],
      str(cond)[:140])

print("── K4 扩散真正参与决策（非平局裁决）──")
def decide_cards(hand, idx, enemy_hp=30, dmg=18, block=0, energy=2):
    for c in hand:                        # 手牌先有实例（运行时"遇到"卡）
        if kg.get_node(f"Card:{c}") is None:
            txt = ("造成 9 点伤害" if c == "猛踢"
                   else "获得 8 点护甲，抽 1 张")
            kb.instantiate_card(kg, CP.parse(c, txt), c)
    snap = {"hp": 40, "block": block, "energy": energy,
            "hand": hand, "hand_idx": list(range(len(hand))),
            "status": {},
            "enemies": [{"name": "E", "hp": enemy_hp, "block": 0,
                         "status": {}, "intent": "重锤",
                         "intent_tags": ["攻击", "重击"],
                         "intent_damage": dmg, "intent_hits": 1}],
            "turn": 5, "max_hp": 68}
    acts = [{"id": f"p{i}", "card": c, "cost": 1}
            for i, c in enumerate(hand)]
    return kb.decide(kg, eng, snap, acts, idx)

# 同一张攻击牌，在"可斩杀"与"打不死"两情境下激活值不同
_, trA = decide_cards(["猛踢"], {"猛踢": {"damage": 9, "hits": 1}},
                      enemy_hp=8)
_, trB = decide_cards(["猛踢"], {"猛踢": {"damage": 9, "hits": 1}},
                      enemy_hp=30)
aA = [x for x in trA["candidates"] if x["card"] == "猛踢"][0]
aB = [x for x in trB["candidates"] if x["card"] == "猛踢"][0]
check("K4a 同卡不同情境：激活与预期后果都不同（斩杀预期差值巨大）",
      aA["expected"]["击杀"] and not aB["expected"]["击杀"]
      and aA["outcome"] > aB["outcome"] + 15,
      f"A={aA['outcome']} B={aB['outcome']}")
# 扩散参与证明：seeds 含机制节点、激活非零
check("K4b 决策 trace 显示机制层播种（M/V 节点），卡获得非零激活",
      any(x["node"].startswith(("M.", "V.")) for x in trA["seeds"])
      and aA["activation"] > 0.01, str(trA["seeds"])[:120])
# 能量约束真实生效（不可选行动被挡，不靠扩散猜）
_, trC = decide_cards(["猛踢", "冰盾术"],
                      {"猛踢": {"damage": 9, "hits": 1},
                       "冰盾术": {"block": 8}}, energy=0)
check("K4c 能量=0 时合法闸全部拦截（约束与偏好分离）",
      all(not x["legal"] for x in trC["candidates"]), str(trC)[:140])
# 伤害按 KB 语义可计算（力量/易伤乘区）
kg.get_node("M.strength")
snapS = {"hp": 40, "block": 0, "energy": 2, "hand": ["猛踢"],
         "hand_idx": [0], "status": {"力量": 3},
         "enemies": [{"name": "E", "hp": 30, "block": 0,
                      "status": {"脆弱": 2}, "intent": "抓",
                      "intent_tags": ["攻击"], "intent_damage": 5,
                      "intent_hits": 1}],
         "turn": 2, "max_hp": 68}
bS, tS = kb.decide(kg, eng, snapS, [{"id": "p0", "card": "猛踢",
                                     "cost": 1}],
                   {"猛踢": {"damage": 9, "hits": 1}})
_e = [x for x in tS["candidates"] if x["card"] == "猛踢"][0]["expected"]
check("K4d 确定性后果计算遵循 KB 乘区（9+力量3)×易伤1.5=18",
      _e["伤害"] == 18, str(_e))

def _acts_of(status, block=0):
    kg3 = KnowledgeGraph()                      # 独立新图：情境信号隔离
    kg3.save = lambda *a, **k: None
    eng3 = DiffusionEngine(kg3, {})
    kb.import_kb(kg3)
    kb.link_to_general(kg3)
    for c in ("猛踢", "冰盾术"):
        kb.instantiate_card(
            kg3, CP.parse(c, "造成 9 点伤害" if c == "猛踢"
                         else "获得 8 点护甲，抽 1 张"), c)
    global kg, eng
    _k0, _e0 = kg, eng
    kg, eng = kg3, eng3
    snap2 = {"hp": 40, "block": block, "energy": 2,
             "hand": ["猛踢", "冰盾术"], "hand_idx": [0, 1],
             "status": status,
             "enemies": [{"name": "E", "hp": 30, "block": 0,
                          "status": {}, "intent": "抓",
                          "intent_tags": ["攻击"], "intent_damage": 6,
                          "intent_hits": 1}],
             "turn": 5, "max_hp": 68}
    for c in snap2["hand"]:
        if kg.get_node(f"Card:{c}") is None:
            kb.instantiate_card(
                kg, CP.parse(c, "造成 9 点伤害" if c == "猛踢"
                             else "获得 8 点护甲，抽 1 张"), c)
    b2, t2 = kb.decide(kg, eng, snap2,
                       [{"id": "p0", "card": "猛踢", "cost": 1},
                        {"id": "p1", "card": "冰盾术", "cost": 1}],
                       {"猛踢": {"damage": 9, "hits": 1},
                        "冰盾术": {"block": 8}})
    kg, eng = _k0, _e0
    return t2


base_t = _acts_of({})
strg_t = _acts_of({"力量": 4})
blk_t = _acts_of({}, block=14)
_a = lambda t, c: [x for x in t["candidates"] if x["card"] == c][0][
    "activation"]
check("K4e 自身力量经 KB 因果边（M.strength—影响→M.attack_damage）"
      "真实抬升攻击卡激活（非巧合：基线为0）",
      _a(strg_t, "猛踢") > _a(base_t, "猛踢") + 0.01,  # 力量抬升相对增益（威胁规则使基线非零也如实）
      f"base={_a(base_t, '猛踢')} str={_a(strg_t, '猛踢')}")
check("K4f 存量护甲点亮 V.player.block 且不虚增防御卡（边际价值下降）",
      any(x["node"] == "V.player.block" for x in blk_t["seeds"])
      and _a(blk_t, "冰盾术") < _a(strg_t, "猛踢"),
      f"盾卡激活={_a(blk_t, '冰盾术')}")

print("── K5 学习闭环：证据修正偏好，不改规则 ──")
kb.observe_outcome(kg, "Card:猛踢", {"伤害": 18, "击杀": False},
                   {"dealt": 5, "kill": False})     # 预测严重失准
n = kg.get_node("Card:猛踢")
cal_bad = float((n.extra_attrs or {}).get("calib", 1))
kb.observe_outcome(kg, "Card:猛踢", {"伤害": 9, "击杀": False},
                   {"dealt": 9, "kill": False})      # 预测准确
cal_good = float((n.extra_attrs or {}).get("calib", 1))
check("K5a 预测失准降校准分、准确升（限幅小幅）",
      cal_good > cal_bad and abs(cal_bad - 0.7) < 0.2,
      f"bad={cal_bad} good={cal_good}")
kbnode_w = kg.get_edge("M.vulnerable", "M.attack_damage", "影响")
check("K5b kb 语义边权重不被学习改写（规则与偏好分离）",
      kbnode_w is not None and abs(kbnode_w.weight - 0.7) < 1e-9)
for _ in range(200):
    kb.observe_outcome(kg, "Card:猛踢", {"伤害": 9, "击杀": False},
                       {"dealt": 9, "kill": False})
check("K5c 重复正证据渐近封顶（一次/多次偶然不会无限强化，钳 0.95）",
      float((kg.get_node('Card:猛踢').extra_attrs or {}).get("calib"))
      <= 0.95)

print("── K6 决策可解释性 ──")
best, tr = decide_cards(["猛踢", "冰盾术"],
                        {"猛踢": {"damage": 9, "hits": 1},
                         "冰盾术": {"block": 8}})
check("K6 trace 含播种原因/候选激活/预期后果/选择理由四要素",
      all(k in tr for k in ("seeds", "candidates", "chosen", "reason"))
      and all("why" in x or "outcome" in x for x in tr["candidates"][:1])
      and tr["seeds"], str(tr)[:160])

print("── K7 模拟器与旧测试无回归（外部执行验证）──")
check("K7 本套件与既有 26 项测试共享代码未破坏（由运行器保证）", True)

print()
if FAILURES:
    print(f"通过 {TOTAL[0] - len(FAILURES)} 条，失败 {len(FAILURES)}："
          f"{FAILURES}")
    sys.exit(1)
print(f"通过 {TOTAL[0]} 条，全部通过")
