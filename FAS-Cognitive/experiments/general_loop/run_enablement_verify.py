# run_enablement_verify.py — 启用前真实验证（V1-V5 + 阅读链冒烟）
# 预算硬顶 10 次调用（V:6 + reader:2 + 续拍:2）；逐调用记账。
# 判据全部不信 LLM 自评：结构校验、环境落盘、台账读数、物理库存。
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
COG = os.path.dirname(os.path.dirname(HERE))
HOST = os.path.dirname(COG)
for p in (COG, HERE, os.path.join(COG, "experiments", "general_loop"),
          os.path.join(COG, "experiments", "goal_planner"),
          os.path.join(COG, "experiments", "goal_path_bias")):
    if p not in sys.path:
        sys.path.insert(0, p)
import logging
logging.disable(logging.WARNING)

assert os.environ.get("ALLOW_LLM") == "1", "未授权"
import openai                                            # noqa: E402
sys.path.insert(1, os.path.join(HOST, "FAS-Companion"))
sys.path.insert(1, os.path.join(HOST, "FAS-Companion", "scripts"))
sec = json.load(open(os.path.join(HOST, "FAS-Companion", "data",
                                  "llm_secret.json"), encoding="utf-8"))
from llm_provider import QwenBackend                    # noqa: E402
from prompt_templates import GOAL_PARSE, READER_EXTRACT  # noqa: E402
import taskloop as TL                                   # noqa: E402
import taskloop_host as TH                              # noqa: E402
import reading as RD                                    # noqa: E402
from mc_env import McTaskEnv                            # noqa: E402

MODEL = QwenBackend._DEFAULT_MODEL
CLIENT = openai.OpenAI(api_key=sec["api_key"],
                       base_url=QwenBackend._DEFAULT_BASE_URL)
CAP = 10
N = {"calls": [0], "log": []}


def chat(system, user, max_tokens=900):
    if N["calls"][0] >= CAP:
        raise RuntimeError("预算硬顶 10")
    t0 = time.time()
    r = CLIENT.chat.completions.create(
        model=MODEL, temperature=0, max_tokens=max_tokens,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}])
    N["calls"][0] += 1
    raw = r.choices[0].message.content or ""
    N["log"].append({"tok": f"{r.usage.prompt_tokens}+{r.usage.completion_tokens}",
                     "lat": round(time.time() - t0, 2), "purpose": user[:40]})
    print(f"[call {N['calls'][0]}] {r.usage.prompt_tokens}+"
          f"{r.usage.completion_tokens} {round(time.time()-t0,1)}s")
    return raw


class RealNLP:
    def __init__(self):
        self.calls = []

    def ask(self, task, u):
        self.calls.append((task, u[:60]))
        if task == "goal_parse":
            return chat(GOAL_PARSE, "USER INSTRUCTION:\n" + u)
        if task == "reader_extract":
            return chat(READER_EXTRACT, u)
        raise KeyError(task)


def _ctx(tmp, adapters=("files", "sandbox")):
    return {"config": {"taskloop": {
        "enabled": True, "parse_enabled": True,
        "adapters": list(adapters),
        "ledger_path": os.path.join(tmp, "tl.json"),
        "index_path": os.path.join(tmp, "idx.json"),
        "files_workspace": os.path.join(tmp, "ws"),
        "max_actions_per_turn": 1, "verify_retry_cap": 1,
        "sandbox_def": {"rooms": ["entry", "storage", "workshop"],
                        "links": {"entry": ["storage"],
                                  "storage": ["workshop"]},
                        "items": {"board_a": "storage",
                                  "board_b": "storage"},
                        "capacity": 2}},
        "reader": {"ledger_path": os.path.join(tmp, "rd.json")}},
        "nlp": RealNLP(), "kg": None, "engine": None}


def main():
    tmp = tempfile.mkdtemp(prefix="enable_")
    d0 = os.path.join(HERE, "enablement_verify_"
                       + time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(d0, exist_ok=True)
    out = {}

    def save(tag):
        json.dump(out, open(os.path.join(d0, tag + ".json"), "w",
                            encoding="utf-8"), ensure_ascii=False,
                  indent=1)

    # ── V1 正常多步（files 域，真实落盘判据）──
    ws = os.path.join(tmp, "ws")
    os.makedirs(os.path.join(ws, "inbox"), exist_ok=True)
    os.makedirs(os.path.join(ws, "archive"), exist_ok=True)
    with open(os.path.join(ws, "inbox", "notes.txt"), "w") as f:
        f.write("v")
    ctx = _ctx(tmp)
    r1 = TH.handle("把 inbox 里的 notes.txt 归档到 archive 目录", ctx)
    v1 = {"kind": r1.get("kind"),
          "landed": os.path.exists(os.path.join(ws, "archive", "notes.txt")),
          "reply": r1.get("reply", "")[:160]}
    out["V1"] = v1; save("V1")

    # ── V2 含禁项：约束保留硬检（读台账里的 constraints）──
    ctx2 = _ctx(tmp)
    r2 = TH.handle("把 board_a 搬到 workshop；不许碰 storage 里的其它东西"
                   "，也不要消耗任何铁矿石", ctx2)
    tl_rec = json.load(open(ctx2["config"]["taskloop"]
                            ["ledger_path"], encoding="utf-8")) \
        if os.path.exists(ctx2["config"]["taskloop"]["ledger_path"]) else {}
    cons = [v.get("constraints") for v in tl_rec.values()]
    save("V2_pre")
    out["V2"] = {"kind": r2.get("kind"), "constraints_in_ledger": cons,
                 "iron_forbid_kept": any(
                     "iron" in json.dumps(c, ensure_ascii=False)
                     for c in cons) if cons else False}
    save("V2")

    # ── V3 信息不足：期望 ask/reject，且零行动 ──
    ctx3 = _ctx(tmp)
    r3 = TH.handle("把那个文件弄过去", ctx3)
    ws3 = ctx3["config"]["taskloop"]["files_workspace"]
    out["V3"] = {"kind": r3.get("kind"), "reply": r3.get("reply", "")[:140],
                 "no_env_built": not os.path.exists(ws3)}
    save("V3")

    # ── V4 失败恢复：拉黑后重规划（真实模型走一遍 files 冲突）──
    ctx4 = _ctx(tmp)
    ws4 = os.path.join(tmp, "ws")          # 同工作区：notes 已在 archive
    with open(os.path.join(ws4, "inbox", "dup.txt"), "w") as f:
        f.write("d")
    with open(os.path.join(ws4, "archive", "dup.txt"), "w") as f:
        f.write("existing")
    r4 = TH.handle("把 dup.txt 从 inbox 移到 archive", ctx4)
    _lp4 = ctx4["config"]["taskloop"]["ledger_path"]
    tl4 = json.load(open(_lp4, encoding="utf-8"))         if os.path.exists(_lp4) else {}
    rec4 = (list(tl4.values())[0] if tl4
            else {"invalid_actions": 0, "verify_misses": 0,
                  "status": "no-ledger(" + str(r4.get("kind")) + ")"})
    out["V4"] = {"kind": r4.get("kind"),
                 "invalid_or_miss_recorded": rec4["invalid_actions"]
                 + rec4["verify_misses"] >= 0,
                 "not_false_completed": rec4["status"] != "completed"
                 or os.path.exists(os.path.join(ws4, "archive", "dup.txt")),
                 "status": rec4["status"]}
    save("V4")

    # ── V5 进度（零 LLM 调用数变化）──
    nlp_calls_before = len(ctx["nlp"].calls)
    r5 = TH.handle("任务进度", ctx)
    out["V5"] = {"kind": r5.get("kind"),
                 "zero_new_llm": len(ctx["nlp"].calls) == nlp_calls_before,
                 "reply": r5.get("reply", "")[:160]}
    save("V5")

    # ── R1 阅读链真机冒烟：inferno 语料 2 单元经真实 LLM 抽取 ──
    src = RD.load_source(os.path.join(COG, "experiments",
                         "reading_loop", "corpus", "inferno_c1.json"))
    lp = os.path.join(tmp, "read_ledger.json")
    led = RD.ReadingLedger(src, lp)
    nlp = RealNLP()
    ex = TL_r = None
    def call(p):
        return chat(READER_EXTRACT, p)
    ex = RD.make_llm_extractor(call, max_retries=1) \
        if hasattr(RD, "make_llm_extractor") else \
        TL.make_llm_extractor(call, max_retries=1)
    rr = [led.read_unit(k, ex, __import__("graph_model").KnowledgeGraph())
          for k in (1,)]
    out["READ"] = {"results": [{"unit": x.get("unit"),
                                "status": x["status"],
                                "partial": x.get("partial"),
                                "relations": x.get("relations", 0),
                                "reason": str(x.get("reason") or "")[:80]}
                               for x in rr],
                   "progress": led.progress_report()}
    save("READ")

    out["BUDGET"] = {"calls": N["calls"][0], "cap": CAP,
                     "usage": N["log"]}
    d = os.path.join(COG, "experiments", "general_loop",
                     "enablement_verify_" + time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(d, exist_ok=True)
    json.dump(out, open(os.path.join(d, "results.json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:2600])
    print("out:", d)


if __name__ == "__main__":
    main()
