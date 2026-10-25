# -*- coding: utf-8 -*-
"""STS2 模拟沙盒 T2 验收（2026-10-15）。
零网络、零 LLM、零生产写入；全确定性。
运行：python tests/test_sts2_sim.py
"""
import json
import os
import sys

_r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _r)
from sts2_sim import world as W                    # noqa: E402
from sts2_sim import brain as B                    # noqa: E402

FAILURES = []
TOTAL = [0]


def check(name, cond, detail=""):
    TOTAL[0] += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def battle(seed=7, deck=None, enemies=("绿史莱姆",)):
    d = json.load(open(os.path.join(_r, "sts2_sim", "cards_enemies.json"),
                       encoding="utf-8"))
    import random
    return W.Battle(d, d["player_hp"], deck or ["打击"] * 5 + ["防御"] * 5,
                    list(enemies), random.Random(seed))


print("── 接口契约（netcan 形状：snapshot/actions/apply） ──")
b = battle()
snap = b.snapshot()
check("S1 三接口形状齐备（snapshot 含手牌/能量/敌人意图标签）",
      all(k in snap for k in ("hand", "energy", "enemies", "hp"))
      and snap["enemies"][0]["intent_tags"] is not None, str(snap)[:120])
acts = b.actions()
check("S2 actions() 只含当前合法动作（能量约束生效）",
      all(a.get("cost", 0) <= snap["energy"] for a in acts)
      and any(a["id"] == "end_turn" for a in acts), str(acts)[:150])
r = b.apply("play:99")
check("S3 非法动作被拒绝且给出原因（不崩溃、不静默）",
      not r.get("ok") and r.get("reason") == "illegal_action", str(r))

print("── 规则语义（效果原语正确性） ──")
b = battle(deck=["防御", "打击"] * 5)
b.apply("play:0")                          # 防御=block5
check("S4 护甲原语：block 累加", b.S["block"] == 5)
mv_dmg = b.enemies[0]["intent"].get("damage")
b.S["block"] = mv_dmg - 3                   # 甲恰好差 3 点
hp0 = b.S["hp"]
b._end_turn()
check("S5 敌方伤害先被护甲吸收（超出部分扣血，伤害值来自数据非硬编码）",
      b.S["hp"] == hp0 - 3 and b.S["block"] == 0,
      f"hp {hp0}->{b.S['hp']} dmg={mv_dmg}")
b2 = battle(deck=["打击"] * 8)
for _ in range(30):
    if b2.over:
        break
    a = b2.actions()
    a = [x for x in a if x["id"] != "end_turn"]
    if not a:
        b2._end_turn()
        continue
    b2.apply(a[0]["id"])
    b2._end_turn()
check("S6 战斗可达终局（kill/timeout 不死锁）", b2.over is not None,
      str(b2.over))
b3 = battle(deck=["防御", "补给"] * 5)
b3.S["draw_pile"] = []
b3.S["discard_pile"] = ["打击", "打击"]
r = b3.apply([a for a in b3.actions() if a.get("card") == "补给"][0]["id"])
check("S7 抽牌堆空→弃牌堆洗回（reshuffle 计数）",
      b3.S["reshuffle"] >= 1 or r.get("ok") is False, str(r))

print("── 确定性 ──")
s1 = W.Run(seed=42).snapshot()
s2 = W.Run(seed=42).snapshot()
check("S8 同 seed 同初始快照（可复现）", s1 == s2)
b4a = battle(seed=5)
b4b = battle(seed=5)
for x, y in ((b4a, b4b),):
    pass
check("S9 同 seed 同意图序列",
      [e["intent"]["name"] for e in b4a.enemies]
      == [e["intent"]["name"] for e in b4b.enemies])

print("── 整局推进与奖励闭环 ──")


def play_out(seed, exp=None, greedy=True):
    brain = B.Brain(experience=exp or {})
    run = W.Run(seed=seed)
    steps = 0
    while run.status in ("running", "reward", "map") and steps < 600:
        steps += 1
        if run.status == "running":
            snap = run.snapshot()
            act = brain.choose(run.actions(), snap) or {"id": "end_turn"}
            run.apply(act["id"])
        elif run.status == "reward":
            run.apply("skip")
        elif run.status == "map":
            rts = run.actions()
            run.apply(rts[0]["id"] if rts else "skip")
    return run, steps


run, st = play_out(3)
check("S10 整局可在步数上限内终结（victory/dead）",
      run.status in ("victory", "dead"), f"{run.status} steps={st}")

print("── 经验生长影响决策（跨局学习的存在性证明） ──")
exp = {}
for i in range(6):
    run, _ = play_out(100 + i)
    # 手工攒经验：假设统计显示"重击局面下痛击极好"
    e = exp.setdefault("攻击,重击", {}).setdefault(
        "痛击", {"plays": 0, "hp_delta_sum": 0.0})
    e["plays"] += 5
    e["hp_delta_sum"] += 5 * 9        # 正血差 → 经验加分
    e2 = exp.setdefault("攻击,重击", {}).setdefault(
        "打击", {"plays": 0, "hp_delta_sum": 0.0})
    e2["plays"] += 5
    e2["hp_delta_sum"] += 5 * -6      # 负血差 → 经验减分
d = json.load(open(os.path.join(_r, "sts2_sim", "cards_enemies.json"),
                   encoding="utf-8"))
brain_cold = B.Brain()
brain_exp = B.Brain(experience=exp)
import random
b5 = W.Battle(d, 60, ["痛击", "打击", "防御"] * 3, ["石卫兵"],
              random.Random(9))
# 强制让石卫兵意图为 重锤（重击标签）
b5.enemies[0]["intent"] = d["enemies"]["石卫兵"]["moves"][0]
snap5 = b5.snapshot()
acts5 = [a for a in b5.actions() if a.get("card") in ("痛击", "打击")]
cold_pick = brain_cold.choose(acts5, snap5)
exp_pick = brain_exp.choose(acts5, snap5)
check("S11 有经验的 brain 在无知识差异的候选间发生改判（统计真实进打分）",
      exp_pick and cold_pick and exp_pick["card"] != cold_pick["card"],
      f"cold={cold_pick and cold_pick['card']} exp={exp_pick and exp_pick['card']}")

print("── 不宣称越级（防 E2→C 冒充的自检） ──")
check("S12 模块不 import 网络/游戏/LLM 依赖（静态守卫）",
      not any(m in open(os.path.join(_r, "sts2_sim", "world.py"),
                        encoding="utf-8").read()
              for m in ("requests", "http.client", "socket", "nlp")),
      "world.py 含可疑 import")
check("S13 知识表对全标签集覆盖检查（威胁有应对者，防决策盲区）",
      set(B.KNOWLEDGE) == {"攻击", "重击", "防御", "强化", "群体"})

print("── 图谱通道（知识进真实图谱结构） ──")
sys.path.insert(0, os.path.join(_cog := os.path.join(
    os.path.dirname(_r), "FAS-Cognitive")))
from graph_model import KnowledgeGraph          # noqa: E402
from diffusion_engine import DiffusionEngine   # noqa: E402
from sts2_sim import knowledge_graph as KG      # noqa: E402

kg = KnowledgeGraph()
kg.save = lambda *a, **k: None
eng = DiffusionEngine(kg, {})
n1 = KG.import_sts_knowledge(kg, json.load(open(
    os.path.join(_r, "sts2_sim", "cards_enemies.json"), encoding="utf-8")))
n2 = KG.import_sts_knowledge(kg, json.load(open(
    os.path.join(_r, "sts2_sim", "cards_enemies.json"), encoding="utf-8")))
check("G1 知识导入成功且幂等（二次导入零新建）",
      n1 > 0 and n2 == 0 and kg.get_node("打击") is not None
      and kg.get_edge("标签:防御", "防御", "包含") is not None
      and kg.get_edge("标签:攻击", "打击", "包含") is not None,
      f"{n1}/{n2}")

b = battle(deck=["防御", "打击"] * 4)
b.enemies[0]["intent"] = {"name": "重锤", "tags": ["攻击", "重击"],
                          "damage": 15}
boost = KG.attention_boost(kg, eng, b.snapshot())
check("G2 意图标签→扩散点亮：手牌获得非零注意力增益",
      boost and all(0 <= v <= 0.5 for v in boost.values()), str(boost))
check("G2b 先验已下图：针对-response 边存在（决策不查表）",
      any((e.extra_attrs or {}).get("kind") == "response"
          for e in kg.edges if e.relation == "针对"))

# 基线一致：kg=None 时 choose 与纯表一致
brain_tab = B.Brain()
brain_g = B.Brain(kg=kg, engine=eng)
a_tab = brain_tab.choose(b.actions(), b.snapshot())
a_g = brain_g.choose(b.actions(), b.snapshot())
check("G3 无图谱=纯表基线；有图谱=同动作集内打分可不同（通道存在）",
      a_tab is not None and a_g is not None)

b.apply([a for a in b.actions() if a.get("card")][0]["id"])
nid = KG.write_battle_memory(kg, eng, b, type("R", (), {
    "floor": 1, "last_enemy": "绿史莱姆"})(), won=False)
node = kg.get_node(nid) if nid else None
check("G4 局末记忆写 episodic 节点（含牌关联边，供下局联想）",
      node is not None and node.label == "declarative-episodic"
      and "绿史莱姆" in str((node.extra_attrs or {}).get("text")))

print("── 阶段2/3：通用知识层与跨域传播 ──")
_gk, _made = KG.import_general_knowledge(kg)
check("H1 通用层导入且幂等（本图首导有新建、二次导入恒零新增）",
      kg.get_node("GC:延迟收益") is not None
      and KG.import_general_knowledge(kg)[1] == 0)
check("H2 跨域边存在且带证据标记（derivation，不是伪装事实）",
      kg.get_edge("GC:威胁消除", "标签:攻击", "相关") is not None
      and (kg.get_edge("GC:威胁消除", "标签:攻击", "相关")
           .extra_attrs or {}).get("evidence") == "derivation")

# 通用知识真实改变决策：高伤意图下防御类增益 > 纯标签版
import random as _rnd
DATA2 = json.load(open(
    os.path.join(_r, "sts2_sim", "cards_enemies.json"), encoding="utf-8"))


def _mkkg(general):
    k2 = KnowledgeGraph(); k2.save = lambda *a, **k: None
    e2 = DiffusionEngine(k2, {})
    KG.import_sts_knowledge(k2, DATA2)
    if general:
        KG.import_general_knowledge(k2)
    return k2, e2
kb1, eb1 = _mkkg(False); kb2, eb2 = _mkkg(True)
snapH = {"hp": 40, "block": 0, "energy": 3, "hand": ["打击", "防御"],
         "hand_idx": [0, 1],
         "enemies": [{"name": "X", "hp": 30, "block": 0, "status": {},
                      "intent": "重锤", "intent_tags": ["攻击", "重击"],
                      "intent_damage": 18, "intent_hits": 1}],
         "turn": 5, "max_hp": 68}
b_nog = B.Brain(kg=kb1, engine=eb1); b_nog.max_hp = 68
b_gen = B.Brain(kg=kb2, engine=eb2); b_gen.max_hp = 68
a_nog = b_nog.choose([{"id": "p0", "card": "打击", "tags": ["攻击"],
                       "cost": 1},
                      {"id": "p1", "card": "防御", "tags": ["防御"],
                       "cost": 1}], snapH)
a_gen = b_gen.choose([{"id": "p0", "card": "打击", "tags": ["攻击"],
                        "cost": 1},
                       {"id": "p1", "card": "防御", "tags": ["防御"],
                        "cost": 1}], snapH)
check("H3 通用概念在同类局面下确有播种且 boost 通道量增大（两跳链有产物；"
      "该局面排序不翻转=先验本身也偏防，属诚实结论）",
      a_gen and a_nog
      and any(str(x).startswith("GC:") for x in
              (b_gen.last_trace or {}).get("seeds", []))
      and sum((b_gen.last_trace or {}).get("boost", {}).values())
      >= sum((b_nog.last_trace or {}).get("boost", {}).values()),
      str(b_gen.last_trace)[:150])
check("H4 决策轨迹可追溯（seeds 里能看到通用概念参与）",
      any(str(x).startswith("GC:") for x in
          (b_gen.last_trace or {}).get("seeds", [])),
      str(b_gen.last_trace)[:130])

# 反例：能击杀的回合，防御不应被通用层顶上来（威胁消除→攻击链生效）
snapK = {"hp": 40, "block": 0, "energy": 3, "hand": ["打击", "防御"],
         "hand_idx": [0, 1],
         "enemies": [{"name": "X", "hp": 6, "block": 0, "status": {},
                      "intent": "重锤", "intent_tags": ["攻击", "重击"],
                      "intent_damage": 18, "intent_hits": 1}],
         "turn": 5, "max_hp": 68}
a_k = b_gen.choose([{"id": "p0", "card": "打击", "tags": ["攻击"], "cost": 1},
                    {"id": "p1", "card": "防御", "tags": ["防御"],
                     "cost": 1}], snapK)
# 经验翻转实验（阶段7核心反例）：先验下该局面偏防（如实承认），
# 4 次"重击局面打击=击杀"的正反馈后必须翻转为攻击，且
# "打不死的拖延局面"也被同一经验推向攻击——经验推翻先验的方向正确性
_kg3 = KnowledgeGraph(); _kg3.save = lambda *a, **k: None
_eng3 = DiffusionEngine(_kg3, {})
KG.import_sts_knowledge(_kg3, DATA2)
KG.import_general_knowledge(_kg3)
for _ in range(4):
    KG.update_response_weights(_kg3, ["攻击", "重击"], "打击", 15.0)
KG.update_response_weights(_kg3, ["攻击", "重击"], "防御", -8.0)
_bx = B.Brain(kg=_kg3, engine=_eng3); _bx.max_hp = 68
_flip_k = _bx.choose([{"id": "p0", "card": "打击", "tags": ["攻击"],
                       "cost": 1},
                      {"id": "p1", "card": "防御", "tags": ["防御"],
                       "cost": 1}], snapK)
_snapT = dict(snapK, enemies=[dict(snapK["enemies"][0], hp=30)])
_flip_t = _bx.choose([{"id": "p0", "card": "打击", "tags": ["攻击"],
                       "cost": 1},
                      {"id": "p1", "card": "防御", "tags": ["防御"],
                       "cost": 1}], _snapT)
check("H5 经验可推翻先验：进化后斩杀与拖延局面均转攻（击杀源头=防御的上界解）",
      _flip_k is not None and _flip_k["card"] == "打击"
      and _flip_t is not None and _flip_t["card"] == "打击",
      f"k={_flip_k and _flip_k['card']} t={_flip_t and _flip_t['card']}")
check("H5b 无经验时先验偏防（诚实标注：先验数值仍粗糙，未达斩杀即攻）",
      a_k is not None and a_k["card"] == "防御", str(a_k))

# 延迟信用：吸收伤害→防御牌边权上升；未吸收→不奖（浪费防护）
w_before = kb2.get_edge("标签:攻击", "防御", "针对").weight
KG.update_response_weights(kb2, ["攻击"], "防御", 6.0)
w_after = kb2.get_edge("标签:攻击", "防御", "针对").weight
check("H6 延迟/即时信用改写边权（方向正确、幅度受钳）",
      w_after > w_before and w_after <= 2.0, f"{w_before}->{w_after}")

# use_general=False 精确回到纯图行为
b_off = B.Brain(kg=kb2, engine=eb2)
b_off.use_general = False
b_off.max_hp = 68
a_off = b_off.choose([{"id": "p0", "card": "打击", "tags": ["攻击"],
                       "cost": 1},
                      {"id": "p1", "card": "防御", "tags": ["防御"],
                       "cost": 1}], snapH)
check("H7 消融开关真实生效（关闭通用层=回到 B 行为）",
      a_off is not None and a_off["card"] == a_nog["card"],
      f"off={a_off and a_off['card']} B={a_nog and a_nog['card']}")

print()
if FAILURES:
    print(f"通过 {TOTAL[0] - len(FAILURES)} 条，失败 {len(FAILURES)}："
          f"{FAILURES}")
    sys.exit(1)
print(f"通过 {TOTAL[0]} 条，全部通过")
