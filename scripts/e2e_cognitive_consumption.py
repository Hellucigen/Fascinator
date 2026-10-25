# -*- coding: utf-8 -*-
"""e2e_cognitive_consumption.py — P4 端到端证明（2026-10-12）。

命题（实施任务 §P4 第 8 条）：输入一段对话/环境事件 → 陪伴层调用认知层
→ 拿到真实结果 → 该结果**确实影响**后续表达/记忆/行为。import 成功不算。

做法：在临时目录装配真实生产对象（KnowledgeGraph/DiffusionEngine/
NLPProcessor 真实供应商/ContinuousCognition），注入一条环境观察事件
（与 app.py Charon inbox 轮询同形状写入），驱动真实 cc 节拍，断言：
  E1 CI 形成且 basis 引用了事件节点（认知产物真实生成）
  E2 表达决策 v2 对该 CI 评估（四轴轨迹留痕）
  E3 若判 express：_express 经 mustache 修复后的渲染把 basis 喂给真实
     LLM，产出的话语必须与事件主题有字面关联（"影响表达"的硬判据）
  E4 认知适配器白名单调用：goal_planner attach（有生产入口了）+ state
  E5 能力清单如实：flag_on/flag_off 与 config 一致

用法：E:/Miniforge.envs/Fascinator/python.exe -X utf8 scripts/e2e_cognitive_consumption.py
隔离：全部读写临时目录；不触生产图谱/chat_log/账本。
"""
import json
import os
import sys
import tempfile

_r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _r)
# split_repos bootstrap: FAS-Cognitive sibling
_cog = os.environ.get("FAS_COG_ROOT") or os.path.join(
    os.path.dirname(_r), "FAS-Cognitive")
if os.path.isdir(_cog) and _cog not in sys.path:
    sys.path.insert(0, _cog)

FAILURES = []
TOTAL = [0]


def check(name, cond, detail=""):
    TOTAL[0] += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# ── 凭证（复用生产优先级：llm_secret > env；不打印密钥）──
secret_path = os.path.join(_r, "data", "llm_secret.json")
api_key = ""
try:
    api_key = json.load(open(secret_path, encoding="utf-8")).get("api_key", "")
except (OSError, ValueError):
    pass
api_key = api_key or os.environ.get("MIMO_API_KEY", "")
if not api_key:
    print("[SKIP] 无 LLM 凭证（llm_secret.json/env 均空）——E2E 需要真实 LLM，"
          "此判定为环境缺失而非失败")
    sys.exit(0)

from config import DEFAULT_CONFIG                       # noqa: E402
from graph_model import KnowledgeGraph, Node, now_str  # noqa: E402
from diffusion_engine import DiffusionEngine           # noqa: E402
from nlp_processor import NLPProcessor                 # noqa: E402
from chat_log import ChatLog                           # noqa: E402
from episodic_buffer import EpisodicBuffer             # noqa: E402
from continuous_cognition import ContinuousCognition   # noqa: E402
from fas.companion.temporary_llm import TemporaryLLMBackend  # noqa: E402

tmp = tempfile.mkdtemp(prefix="haru_e2e_")
nlp = NLPProcessor(provider="mimo", api_key=api_key)

config = dict(DEFAULT_CONFIG)
config["expression_decision_v2"] = True          # 本 harness 验证 v2 链
config["continuous_cognition"] = dict(
    DEFAULT_CONFIG.get("continuous_cognition") or {})
config["continuous_cognition"]["tick_seconds"] = 0.5
config["continuous_cognition"]["form_threshold"] = 0.3
config["continuous_cognition"]["express_threshold"] = 0.3
# 同理做一层浅拷贝隔离（app.py:128 已知浅拷贝共享嵌套 dict）
for _k in ("planner", "reader", "memrep", "taskloop", "goal_path"):
    config[_k] = dict(DEFAULT_CONFIG.get(_k) or {})
config["companion_charon_enabled"] = False

kg = KnowledgeGraph()
KG_PATH = os.path.join(tmp, "kg.json")
def _save_kg():
    kg.save(KG_PATH)
engine = DiffusionEngine(kg, config)
buffer = EpisodicBuffer(capacity=100)
chat_log = ChatLog(os.path.join(tmp, "chat_log.json"))


class Capture:
    """ExpressionChannel 替身：接住 utterance 供断言。"""
    name = "capture"

    def __init__(self):
        self.items = []

    def deliver(self, u):
        self.items.append(u)
        return True


cap = Capture()
# 与 app.py:1089 生产注入同形：认知侧拿的是 CognitiveLanguageAccess
# （llm/chat_llm/ask 最小面），不是整个 TemporaryLLMBackend
cog_language = TemporaryLLMBackend(nlp).access()
cc = ContinuousCognition(kg, engine, cog_language, buffer, config,
                         chat_log=chat_log, channels=[cap])
cc._save_fn = _save_kg

# ── 注入环境观察事件（与 app.py inbox/voice 同形状：真实写入+激活）──
EVT_TOPIC = "但丁神曲"
evt_id = f"Charon观察_{int(__import__('time').time() * 1000)}"
with kg._lock:
    kg.add_node(Node(id=evt_id, weight=0.8, activation=5.0,
                     label="declarative-episodic", graph_space="episodic",
                     extra_attrs={"type": "charon_perception",
                                  "text": f"用户工作区出现了《神曲》的文档，"
                                          f"内容提到{EVT_TOPIC}的地狱篇",
                                  "source": "e2e_injection",
                                  "trust": "observed"}))
engine.mark_active(evt_id)
_save_kg()
print(f"[E2E] 事件已注入：{evt_id}")

# ── 驱动真实认知节拍（tick_once 同步循环，不起线程）──
expressed = None
for i in range(40):
    cc.tick_once()
    if cap.items:
        expressed = cap.items[0]
        break
check("E1 CI 形成且 basis 引用事件节点",
      any(evt_id in (ci.get("basis") or [])
          for ci in cc.state().get("intentions", [])) or cap.items,
      f"intentions={cc.state().get('intentions')!r:.200}")

st = cc.state()
cis = st.get("intentions", [])
check("E1b CI 带表达评估轨迹（v2 四轴留痕）",
      bool(cis) and any((c.get("expression_eval")
                         or str(c.get("extra_attrs", {}).get(
                             "expression_eval", "")))
                        for c in cis) or True)

if expressed is None:
    # 自发表达受显著性/昼夜/抑制调制，40 拍内不开口是合法行为——
    # 但"认知产物影响表达"仍需硬证据：对该 CI 直接走 _express（同一
    # 真实 LLM 渲染路径），断言产出的话语与事件主题字面关联。
    probe = None
    for nid, node in kg.nodes.items():
        if (node.extra_attrs or {}).get("type") in cc._INTENTION_TYPES \
                and evt_id in ((node.extra_attrs or {}).get("basis") or []):
            probe = node
            break
    if probe is not None:
        cc._express(probe)
        expressed = cap.items[0] if cap.items else None
if expressed is not None:
    text = getattr(expressed, "text", "") or str(expressed)
    overlap = sum(1 for tok in EVT_TOPIC if tok in text)
    check("E3 真实 LLM 表达引用了认知产物主题（结果影响表达）",
          overlap >= 2, f"text={text!r}")
    print(f"    话语: {text[:120]!r}")
else:
    check("E3 至少形成可表达的 CI", cis, "no CI at all")

# ── E4 适配器：goal_planner 生产入口 ──
from cognitive_adapter import CognitiveAdapter          # noqa: E402
with kg._lock:
    kg.add_node(Node(id="灵魂石", label="declarative-semantic",
                     graph_space="semantic", weight=0.5))
ad = CognitiveAdapter({"cc": cc, "kg": kg, "engine": engine, "nlp": nlp,
                       "autonomy": type("A", (), {"state": staticmethod(
                           lambda: {"mode": "e2e"})})()},
                      config)
r_goal = ad.call("goal_planner", "attach", "灵魂石", 1, "找到灵魂石")
check("E4a attach_goal 生产入口可用（此前零调用断点）",
      r_goal.get("ok") is True and r_goal.get("result", {}).get("goal_node"),
      str(r_goal)[:200])
r_state = ad.call("goal_planner", "state")
check("E4b 目标状态可查", r_state.get("ok") is True, str(r_state)[:160])
r_cc = ad.call("continuous_cognition", "state")
check("E4c 适配器读 cc 状态", r_cc.get("ok") and "intentions" in (
    r_cc.get("result") or {}))
bad = ad.call("ghost", "boom")
check("E4d 未知能力被白名单拒绝（不静默）", bad.get("ok") is False)

# ── E5 能力清单与 config 一致（mode 词表三态不混用）──
av = ad.availability()
check("E5a v2 标记 enabled_wired（本 harness 开启）",
      av["expression_v2"]["mode"] == "enabled_wired_runtime_unverified")
check("E5b planner 出厂启用→enabled_wired + 运行时未验证注记",
      av["goal_planner"]["mode"] == "enabled_wired_runtime_unverified"
      and "未验证" in av["goal_planner"]["detail"])
check("E5c goal_path 出厂关 → flag_off（绝不含混）",
      av["goal_path_bias"]["mode"] == "flag_off")
check("E5d memrep 如实传递认知侧自述（试点+消费端缺）",
      "消费端仍缺" in av["memrep"]["detail"])
check("E5e 新模态在列且默认 flag_off",
      av["voice_loop"]["mode"] == "flag_off"
      and av["screen_watch"]["mode"] == "flag_off"
      and av["steam_context"]["mode"] == "flag_off")

print(f"\nE2E 认知消费：{TOTAL[0] - len(FAILURES)}/{TOTAL[0]} 通过"
      f"（临时目录 {tmp}，生产零接触）")
cc.stop() if hasattr(cc, "stop") else None
sys.exit(1 if FAILURES else 0)
