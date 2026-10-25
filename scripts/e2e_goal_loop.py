# -*- coding: utf-8 -*-
"""e2e_goal_loop.py — 目标→行动→真实反馈→认知写回→行为改变 的因果闭环证明。

与"图谱多一个节点"式假证明的区别：每一环都用**可核验的确定性断言**，
且关键因果用**全新子进程**验证（排除一切进程内残留的巧合）。

链条（隔离临时目录；FileEnv=真实磁盘；mock nlp 只做"语言→结构"这一步，
解析质量本身已由认知仓 enablement V1-V5 真实 LLM 覆盖）：
  C1 指令→校验→起步→核验完成（真实文件真的被移动）
  C2 完成结果写回图谱（数字取自台账观测，非 LLM 自述）并进入
     注意力候选（engine.get_topk）
  C3 同一目标再次下达：在**新进程**里 → 台账+观测驱动 → 零重复动作、
     直接确认完成（历史改变了行为：不重做）
  C4 未达成目标受阻：blocked 写回含失败证据；同目标再提 → 仍 blocked
     且台账零新增动作（失败历史阻止盲目重试）
  C5 自主候选对已完成/已受阻目标去重（propose_dupe，不重复研究）

用法：python scripts/e2e_goal_loop.py
"""
import json
import os
import subprocess
import sys
import tempfile

_r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _r)
# split_repos bootstrap: FAS-Cognitive sibling
_cog = os.environ.get("FAS_COG_ROOT") or os.path.join(
    os.path.dirname(_r), "FAS-Cognitive")
if os.path.isdir(_cog) and _cog not in sys.path:
    sys.path.insert(0, _cog)

import taskloop_host as TH                    # noqa: E402
from graph_model import KnowledgeGraph, Node  # noqa: E402
from diffusion_engine import DiffusionEngine  # noqa: E402
from config import DEFAULT_CONFIG             # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


class FakeNLP:
    def ask(self, task, u):
        if "ghost" in u:
            return '{"preds": ["loc:ghost.txt:archive"]}'
        return '{"preds": ["loc:goal_a.md:archive"]}'


TD = tempfile.mkdtemp(prefix="haru_e2e_loop_")


def mk_ctx(nlp):
    return {"kg": None, "engine": None, "nlp": nlp,
            "busy": lambda: False,
            "config": {"taskloop": {
                "enabled": True, "parse_enabled": True,
                "adapters": ["files"],
                "ledger_path": os.path.join(TD, "ledger.json"),
                "index_path": os.path.join(TD, "index.json"),
                "queue_path": os.path.join(TD, "queue.json"),
                "files_workspace": os.path.join(TD, "ws"),
                "max_actions_per_turn": 1,
                "autopilot_enabled": True}}}


WS = os.path.join(TD, "ws", "inbox")
os.makedirs(WS, exist_ok=True)
with open(os.path.join(WS, "goal_a.md"), "w", encoding="utf-8") as f:
    f.write("研究结论草稿")

# ── C1 指令 → 校验 → 起步 → 真实移动 ──────────────────────────────
ctx = mk_ctx(FakeNLP())
r1 = TH.handle("把 goal_a.md 移到 archive", ctx)
tid = r1["task_id"]
r2 = TH.handle("继续任务", ctx)
disk_moved = (os.path.exists(os.path.join(TD, "ws", "archive", "goal_a.md"))
              and not os.path.exists(os.path.join(WS, "goal_a.md")))
check("C1 完成判定=磁盘事实（文件真在 archive）",
      disk_moved and r2["status"] == "completed"
      and r2["terminal"] is True, str(r2)[:120])

led = json.load(open(ctx["config"]["taskloop"]["ledger_path"],
                     encoding="utf-8"))[tid]
check("C1b 台账全部步骤经观测核验",
      led["status"] == "completed" and all(s["verified"]
                                           for s in led["steps_log"]))

# ── C2 写回图谱 + 进入注意力候选（消费面打通，非只多一个节点）──────
kg = KnowledgeGraph()
engine = DiffusionEngine(kg, dict(DEFAULT_CONFIG))
rep = r2["report"]
nid = "Task_completed_e2e"
with kg._lock:
    kg.add_node(Node(id=nid, weight=0.5, activation=0.0,
                     label="declarative-episodic", graph_space="episodic",
                     extra_attrs={"type": "task_outcome", "task_id": tid,
                                  "status": "completed",
                                  "goals_met": "%s/%s" % (
                                      rep["met_by_observation"], rep["goals"]),
                                  "steps": rep["steps"],
                                  "source": "taskloop", "trust": "observed"}))
    # 生产同构：mark_active 前直写 activation（前沿不变量）
    kg.nodes[nid].activation = 0.8
engine.mark_active(nid)
_tk = engine.get_topk(k=20)
_nodes = _tk[0] if isinstance(_tk, tuple) else (_tk.get("nodes") if
                                                isinstance(_tk, dict) else _tk)
if isinstance(_nodes, dict):
    _nodes = list(_nodes.keys())


def _nid_of(n):
    if isinstance(n, dict):
        return str(n.get("id") or "")
    return str(getattr(n, "id", n))


topk_ids = {_nid_of(n) for n in (_nodes or [])}
check("C2 写回节点携带台账观测数字且进入注意力 topk（可被回合消费）",
      nid in topk_ids and rep["met_by_observation"] == 1,
      f"topk={sorted(topk_ids)[:6]} node_act={kg.nodes[nid].activation}")

# ── C3 全新进程再下同一指令：历史改变行为=零重复动作 ───────────────
_child = f'''
import json, os, sys
sys.path.insert(0, {os.path.dirname(os.path.abspath(__file__))!r})
sys.path.insert(0, {_cog!r})
sys.path.insert(0, {_r!r})
import taskloop_host as TH
class N:
    def ask(self, t, u):
        return '{{"preds": ["loc:goal_a.md:archive"]}}'
ctx = {{"kg": None, "engine": None, "nlp": N(), "busy": lambda: False,
        "config": {{"taskloop": {{"enabled": True, "parse_enabled": True,
        "adapters": ["files"],
        "ledger_path": {os.path.join(TD, 'ledger.json')!r},
        "index_path": {os.path.join(TD, 'index.json')!r},
        "queue_path": {os.path.join(TD, 'queue.json')!r},
        "files_workspace": {os.path.join(TD, 'ws')!r},
        "max_actions_per_turn": 1}}}}}}
r = TH.handle("把 goal_a.md 移到 archive", ctx)
led = json.load(open(ctx["config"]["taskloop"]["ledger_path"],
                     encoding="utf-8"))
tid = {tid!r}
print(json.dumps({{"kind": r and r.get("kind"),
                   "steps": len(led[tid]["steps_log"]),
                   "status": led[tid]["status"]}}))
'''
out = subprocess.run([sys.executable, "-X", "utf8", "-c", _child],
                     capture_output=True, text=True, timeout=120)
c3 = json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout.strip() \
    else {}
check("C3 重启后同目标：新进程直接按观测确认完成，**零重复动作**"
      "（steps 仍=1，不重放）",
      c3.get("steps") == 1 and c3.get("status") == "completed",
      f"{c3} stderr={out.stderr[:120]}")

# ── C4 未达成→受阻写回失败证据；重试不盲目 ────────────────────────
ctx4 = mk_ctx(FakeNLP())
os.makedirs(os.path.join(TD, "ws4", "inbox"), exist_ok=True)
ctx4["config"]["taskloop"]["files_workspace"] = os.path.join(TD, "ws4")
ctx4["config"]["taskloop"]["ledger_path"] = os.path.join(TD, "led4.json")
ctx4["config"]["taskloop"]["index_path"] = os.path.join(TD, "idx4.json")
r4 = TH.handle("把 ghost.txt 移到 archive", ctx4)      # ghost.txt 不存在
tid4 = r4.get("task_id")
TH.handle("继续任务", ctx4)
led4 = json.load(open(ctx4["config"]["taskloop"]["ledger_path"],
                      encoding="utf-8"))[tid4]
check("C4a 缺前提的目标被观测判阻（非谎报完成）且失败证据入台账",
      led4["status"] in ("blocked", "partial")
      and any("不可达" in d.get("why", "") for d in led4["decisions"]),
      str(led4["status"]) + str(led4["decisions"][:1])[:140])
before4 = len(led4["steps_log"])
TH.handle("继续任务", ctx4)
led4b = json.load(open(ctx4["config"]["taskloop"]["ledger_path"],
                       encoding="utf-8"))[tid4]
check("C4b 受阻后继续指令不产生盲目重试（零新动作）",
      len(led4b["steps_log"]) == before4 and led4b["status"] == led4["status"],
      f"{before4}→{len(led4b['steps_log'])}")

# ── C5 自主候选对已存在目标去重 ────────────────────────────────────
p5 = TH.propose_goal(ctx4, "把 ghost.txt 移到 archive", source="living")
check("C5 生活循环不会对已有任务重复立项",
      p5 and p5.get("kind") == "propose_dupe", str(p5)[:100])

print("\n因果闭环：" + ("全部通过 ✓" if not FAILURES else
                       f"{len(FAILURES)} 项失败"))
sys.exit(1 if FAILURES else 0)
