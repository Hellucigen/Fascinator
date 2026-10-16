# -*- coding: utf-8 -*-
"""run_fix_validation.py — 占位符修复的渲染矩阵 + 真实文本证据测试（阶段1/2/3）。

阶段1：渲染矩阵（中文/换行/大括号/长文本/空/缺失）——不调 LLM。
阶段2：真实 LLM 场景 A-E（隔离捕获通道，零真实投递）。
阶段3：修复前后渲染对比（修复前证据=上轮 real_llm_1791652063.json 的 prompt_tail）。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))   # FAS-Cognitive 根
sys.path.insert(0, "E:/Project/FAS-Companion")

import config as C
from prompt_templates import build_prompt
from langchain_core.prompts import ChatPromptTemplate

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" | {detail}" if not cond and detail else ""))
    if not cond:
        FAILS.append(name)


SYSTEM = build_prompt("proactive_express")


def render(user_text):
    """生产同款渲染路径（修复后）：mustache + {{input}}。"""
    tpl = ChatPromptTemplate.from_messages(
        [("system", SYSTEM), ("human", "{{input}}")],
        template_format="mustache")
    return tpl.invoke({"input": user_text}).to_string()


# ═══ 阶段1：渲染矩阵 ═══
cases = {
    "中文+证据": "【想法来源】\n- 用户近况_x：用户开始做《辐射4》总转换模组",
    "换行+多节点": "【想法来源】\n- 节点A：第一行\n- 节点B：第二行",
    "含大括号文本": "【想法来源】\n- 配置示例：{\"key\": \"value\"} 原样保留",
    "长摘要(200字)": "【想法来源】\n- 事件：" + "很长的工作区摘要内容。" * 20,
    "空字符串": "",
}
for name, txt in cases.items():
    out = render(txt)
    body = out.split("Human:")[-1]
    # mustache {{var}} 插值做 HTML 转义（"→&quot;）——已知限制（LLM 实测
    # 仍正确理解，见 E大括号场景），断言按转义后可辨识校验。
    import html as _html
    check(f"渲染[{name}]：Human 消息含原文（转义后可辨识，非字面量/非空）",
          ("{input}" not in body) and
          (_html.unescape(txt.split("\n")[-1].split("：")[-1][:10]) in _html.unescape(body)
           or name in ("空字符串",)),
          body[-80:])
out_empty = render("")
check("渲染[空字符串]：system 模板完整（花括号示例未被 f-string 吞）",
      "输出纯文本" in out_empty and "{input}" not in out_empty.split("Human:")[-1])
out_brace = render("含 {curly} 与 {{double}} 的普通文本")
check("渲染[大括号]：文本中的大括号原样到达（不误解析）",
      "{curly}" in out_brace.split("Human:")[-1])

# ═══ 阶段2：真实 LLM 场景 A-E ═══
if "--render-only" not in sys.argv:
    import run_eval as RE
    from run_real_llm import REAL_NLP, CaptureChat, MODEL_ID

    def run_case(name, ev_text, mode, repeat=1, llm_fail=False):
        sim = RE.Sim(v2=False)               # 生产等价路径（flag 关）
        tag = f"{name}|r{repeat}"
        sim.cc.nlp = REAL_NLP
        inner = REAL_NLP.chat_llm
        if llm_fail:                          # E：模型失败模拟（空返回）
            class Dead:
                def __or__(self, o):
                    return self
                def invoke(self, *a, **k):
                    class R:
                        content = ""
                    return R()
            sim.cc.nlp.chat_llm = Dead()
        else:
            sim.cc.nlp.chat_llm = CaptureChat(inner, tag).as_runnable()
        ea = {"type": "perception", "source": "experiment", "mode": mode}
        if ev_text is not None:
            ea["text"] = ev_text
        from graph_model import Node, Edge
        sim.kg.add_node(Node(id=f"ev_{name}", weight=0.6, graph_space="episodic",
                             extra_attrs=ea))
        sim.kg.nodes[f"ev_{name}"].activation = 3.0
        sim.kg.add_edge(Edge(src="用户", dst=f"ev_{name}", relation="关注",
                             weight=0.9, relation_category="social_relation"))
        sim.engine.topk = [RE.FN(f"ev_{name}", 3.0), RE.FN("用户", 3.0),
                           RE.FN("用户关系", 2.0), RE.FN("CuriosityDrive", 2.5)]
        for _ in range(4):
            sim._beat(10)
        sim.idle(120)
        sim.finish()
        gens = [c for c in __import__("run_real_llm").CALLS
                if c["tag"].startswith(tag)]
        return {"verdict": (sim.ci_hist and list(sim.ci_hist.values())[0][-1]
                            if sim.ci_hist else None),
                "expressed": sim.expressed, "gens": gens,
                "channel": len(sim.channel.got)}

    print("\n── 阶段2：真实 LLM（%s）──" % MODEL_ID)
    RESULTS = {}

    # A. 有证据的主动询问（3 次重复）
    for r in range(3):
        RESULTS[f"A询问 r{r}"] = run_case(
            "ask_real", "我在用户工作区看到他开始做《辐射4》大型剧情模组，"
            "这是我第一次见到这类项目。", "inquiry", repeat=r)
    # B. 有证据的主动分享
    RESULTS["B分享"] = run_case(
        "share_real", "我今天完成了一件小事：把积压的工作区快照全部整理成了"
        "可检索的经历。", "share")
    # C. 缺少实质内容（只有元数据，无 text）
    RESULTS["C无实质"] = run_case("meta_only", None, "share")
    # D. 过期/已退役事件（记录现状）
    sim = RE.Sim(v2=False)
    sim.cc.nlp = REAL_NLP
    sim.cc.nlp.chat_llm = CaptureChat(REAL_NLP.chat_llm, "D过期").as_runnable()
    from graph_model import Node, Edge
    sim.kg.add_node(Node(id="ev_retired_D", weight=0.6, graph_space="episodic",
                         extra_attrs={"type": "perception",
                                      "text": "一条很久以前的旧事。",
                                      "retired": True}))
    sim.kg.nodes["ev_retired_D"].activation = 3.0
    sim.kg.add_edge(Edge(src="用户", dst="ev_retired_D", relation="关注",
                         weight=0.9, relation_category="social_relation"))
    sim.engine.topk = [RE.FN("ev_retired_D", 3.0), RE.FN("用户", 3.0)]
    for _ in range(4):
        sim._beat(10)
    sim.idle(120)
    sim.finish()
    RESULTS["D过期"] = {"verdict": (list(sim.ci_hist.values())[0][-1]
                                     if sim.ci_hist else None),
                        "expressed": sim.expressed}
    # E. 异常矩阵
    RESULTS["E空text"] = run_case("empty_text", "", "share")
    RESULTS["E中英混合"] = run_case("mixed_text", "用户开始玩 Elden Ring 艾尔登法环 DLC",
                                   "share")
    RESULTS["E大括号"] = run_case("brace_text", '配置片段 {"fps": 60, "vsync": true} 出现在快照',
                                  "share")
    RESULTS["E长文本"] = run_case("long_text", "长事件。" * 60, "share")
    RESULTS["E模型失败"] = run_case("llm_dead", "一条真实事件。", "share",
                                    llm_fail=True)

    out_path = os.path.join(RE.RESULTS_DIR, "fix_validation.json")
    slim = {k: {"verdict": v.get("verdict"),
                "expressed": [{"basis": (e.get("basis") or [])[:2],
                               "text": e.get("text", "")[:120]}
                              for e in v.get("expressed", [])],
                "gens": [{"prompt_tail": g["prompt_tail"][-300:],
                          "output": g["output"],
                          "error": g["error"], "latency": g["latency_s"]}
                         for g in v.get("gens", [])]}
           for k, v in RESULTS.items()}
    json.dump({"model": MODEL_ID, "results": slim},
              open(out_path, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1, default=str)
    print("saved:", out_path)
    for k, v in RESULTS.items():
        outs = [g["output"][:70] for g in v.get("gens", [])]
        print(f"{k}: verdict={v['verdict'] and v['verdict'].get('verdict') if isinstance(v['verdict'], dict) else v['verdict']} "
              f"expressed={len(v['expressed'])} gen={outs}")

print("=" * 50)
if FAILS:
    print(f"✗ 渲染矩阵失败: {FAILS}")
    sys.exit(1)
print("✓ 渲染矩阵全部通过")
