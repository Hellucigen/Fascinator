# test_memrep.py — 统一记忆表示：场景 A-G 验证（对应 docs/MEMREP_DESIGN §五）
# 离线、临时图、临时 timeline；断言状态迁移/流水内容/序列化语义，非"无异常"。
# 运行: E:/Miniforge.envs/Fascinator/python.exe -X utf8 tests/test_memrep.py

import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph, Node, Edge
from experience import ExperienceTimeline
import memrep as mr

FAILURES = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


TMP = tempfile.mkdtemp(prefix="memrep_test_")
TL = ExperienceTimeline(path=os.path.join(TMP, "tl.json"))


def fresh_kg():
    kg = KnowledgeGraph()
    kg.save = lambda *a, **k: None
    for nid in ("苹果", "桌子", "篮子", "厨房", "门"):
        kg.add_node(Node(id=nid))
    return kg


# ── A 概念与实例区分 ─────────────────────────────────────
kg = fresh_kg()
n1 = mr.get_or_create_instance(kg, "篮子", "厨房")
n2 = mr.get_or_create_instance(kg, "篮子", "储藏室")
check("A1 同概念两个个体=不同节点，不因同名合并",
      n1.id != n2.id and kg.get_node("篮子") is not None)
check("A2 个体→概念 实例属于 边存在（词表注册生效，未被归一成 关联）",
      kg.get_edge(n1.id, "篮子", "实例属于") is not None
      and kg.get_edge(n2.id, "篮子", "实例属于") is not None)
n1b = mr.get_or_create_instance(kg, "篮子", "厨房")
check("A3 同区分符幂等（不重复建）",
      n1b.id == n1.id
      and sum(1 for e in kg.edges if e.relation == "实例属于") == 2)
ea = n1.extra_attrs
check("A4 个体带来源与 instance_of，不虚构",
      ea.get("instance_of") == "篮子" and ea.get("discriminator") == "厨房"
      and ea.get("source") == "observed")

# ── B 状态变化：当前=图，历史=轴 ─────────────────────────
kg = fresh_kg()
t = mr.record_fact(kg, "苹果", "位于", "桌子", source="observed", tl=TL)
check("B1 事实入图且带有效期/来源属性",
      t["status"] == "added"
      and kg.get_edge("苹果", "桌子", "位于") is not None
      and kg.get_edge("苹果", "桌子", "位于").extra_attrs.get("valid_from"))
h0 = mr.fact_history(TL, "苹果", "位于")
check("B2 历史区间：当前有效（valid_until 为空）",
      len(h0) == 1 and h0[0]["valid_until"] is None
      and h0[0]["object"] == "桌子")
t = mr.supersede_fact(kg, "苹果", "位于", "桌子", "篮子",
                      source="observed", tl=TL)
check("B3 取代后：图上只剩新位置（旧边摘除，不残留旧状态）",
      kg.get_edge("苹果", "桌子", "位于") is None
      and kg.get_edge("苹果", "篮子", "位于") is not None)
h1 = mr.fact_history(TL, "苹果", "位于")
check("B4 历史查询可恢复旧位置（区间闭合）且新位置开放",
      len(h1) == 2
      and {x["object"] for x in h1} == {"桌子", "篮子"}
      and any(x["object"] == "桌子" and x["valid_until"] for x in h1)
      and any(x["object"] == "篮子" and not x["valid_until"] for x in h1))
check("B5 取代事件可回链（旧边变化进时间轴带 ev id）",
      t["ev"] and any(e["id"] == t["ev"] for e in TL.recent(10)))

# ── C 时间顺序 ──────────────────────────────────────────
evs = [e for e in TL.recent(50) if e.get("event_type") == mr.FACT_CHANGE]
ts_list = [e["ts"] for e in evs]
check("C1 事件流时间有序（recent 返回新序=严格降序，先后可判定）",
      ts_list == sorted(ts_list, reverse=True) and len(ts_list) >= 2)
check("C2 时间戳含日期（ts_iso 修复旧 ts_str 无日期问题）",
      all("-" in (e.get("meta", {}).get("ts_iso") or "") for e in evs))

# ── D 经历重建（对象/关系/时间/动作/来源）────────────────
kg = fresh_kg()
r = mr.record_episode(kg, TL, "放入", "苹果", "篮子",
                      source="action_result")
node = kg.get_node(r["node"])
ea = node.extra_attrs
check("D1 事件节点带结构槽位（动作/主客体/时间/来源）",
      ea.get("action") == "放入" and ea.get("subject") == "苹果"
      and ea.get("object") == "篮子" and "-" in (ea.get("ts_iso") or "")
      and ea.get("source") == "action_result")
check("D2 图边连参与者（涉及，角色在属性——不造未注册角色词）",
      kg.get_edge(r["node"], "苹果", "涉及") is not None
      and kg.get_edge(r["node"], "篮子", "涉及") is not None
      and kg.get_edge(r["node"], "苹果", "涉及").extra_attrs.get("role")
      == "subject")
tl_ev = next(e for e in TL.recent(20) if e["id"] == ea.get("ev"))
check("D3 双向回链：节点 ev ↔ timeline 事件 kg_node",
      tl_ev["meta"].get("kg_node") == r["node"]
      and tl_ev["event_type"] == mr.EPISODE)

# ── E 信息来源（不伪装）────────────────────────────────
kg = fresh_kg()
mr.record_fact(kg, "苹果", "位于", "桌子", source="user_stated", tl=TL)
mr.record_fact(kg, "篮子", "位于", "厨房", source="inferred", tl=TL)
mr.record_fact(kg, "门", "位于", "厨房", source="warp_drive", tl=TL)  # 非法来源
check("E1 来源如实分档；非法来源降级为 未记录 而非伪造成观察",
      kg.get_edge("苹果", "桌子", "位于").extra_attrs["source"]
      == "user_stated"
      and kg.get_edge("篮子", "厨房", "位于").extra_attrs["source"]
      == "inferred"
      and kg.get_edge("门", "厨房", "位于").extra_attrs["source"]
      == "未记录")

# ── F 检索与表达（非裸 id；1-hop 补全）──────────────────
kg = fresh_kg()
mr.get_or_create_instance(kg, "篮子", "厨房")
mr.record_fact(kg, "苹果", "位于", "桌子", source="observed", tl=TL)
mr.record_episode(kg, TL, "放入", "苹果", "篮子", source="action_result")
from diffusion_engine import DiffusionEngine
eng = DiffusionEngine(kg, {"beta_spread": 1.0, "activation_epsilon": 1e-4,
                           "min_spread_threshold": 0.01})
eng.name_to_node = dict(kg.nodes)
inst = [nid for nid in kg.nodes
        if str(nid).startswith("个体:")][0]
eng.activate_from_inputs(["苹果", inst], [])   # 个体被感知到（点火）
eng.diffuse_round()
top, edges = eng.get_topk(k=8)
ctx = mr.serialize_working_set(top, edges, kg, TL)
check("F1 序列化保留 身份/方向/时间/来源（非裸 id 行）",
      "个体:篮子:厨房（篮子 的个体）" in ctx
      and "位于" in ctx and "（来源:observed）" in ctx
      and "事件 放入：苹果 放入 篮子" in ctx,
      ctx)
check("F2 1-hop 图补全：未激活的关联对象也出现在上下文",
      "桌子" in ctx and "篮子" in ctx, ctx)

# ── G 旧功能回归：门关闭时零触碰 ────────────────────────
from action_system import ActionManager


class Emb:
    def execute(self, action):
        return {"success": True, "pending": True, "action": "x"}

    def poll_action(self):
        return {"status": "done", "detail": {"ok": True, "success": True}}

    def raw_state(self):
        return {}

    def skill_catalog(self):
        return []


kg = fresh_kg()
am = ActionManager(embodiment=Emb(), kg=kg, config={})   # 无 memrep 节=关
am.propose({"action_type": "gather_resource", "target": "oak_log",
            "params": {"resource": "oak_log"}}, source="test")
for _ in range(3):
    am.tick()
nid = next(n for n in kg.nodes if str(n).startswith("行动_"))
check("G1 门关：行动节点无 memrep 槽位/回链，行为与旧版一致",
      "action" not in (kg.nodes[nid].extra_attrs or {})
      and "ev" not in (kg.nodes[nid].extra_attrs or {})
      and "ts_iso" not in (kg.nodes[nid].extra_attrs or {}))
kg2 = fresh_kg()
am2 = ActionManager(embodiment=Emb(), kg=kg2,
                    config={"memrep": {"enabled": True}})
am2.timeline = TL                      # 生产由 app 注入；测试显式注入
am2.propose({"action_type": "gather_resource", "target": "oak_log",
             "params": {"resource": "oak_log"}}, source="test")
for _ in range(3):
    am2.tick()
nid2 = next(n for n in kg2.nodes if str(n).startswith("行动_"))
check("G2 门开：行动节点补全槽位+回链（timeline 落临时目录）",
      kg2.nodes[nid2].extra_attrs.get("action") == "gather_resource"
      and kg2.nodes[nid2].extra_attrs.get("object") == "oak_log"
      and kg2.nodes[nid2].extra_attrs.get("ev"))
check("G3 开关下旧留痕字段一字不差（type/success/created 等仍在）",
      kg.nodes[nid].extra_attrs.get("type") == "embodied_action"
      and kg2.nodes[nid2].extra_attrs.get("type") == "embodied_action"
      and kg2.nodes[nid2].extra_attrs.get("created") is not None)

shutil.rmtree(TMP, ignore_errors=True)
print("\n" + ("ALL PASS" if not FAILURES else f"FAILED: {FAILURES}"))
sys.exit(1 if FAILURES else 0)
