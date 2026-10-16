# harness.py — Cross-Episode MEMREP 复验正式实验 harness（Phase-3，锁定预注册 v3.1 实现）
# ============================================================================
# 规则依据（唯一）：PREREGISTRATION.md v3.1（锁定 commit dc8d677）。
# 本模块只实现执行/记录/预算/断言；正式 LLM 调用仅在获得人工批准后由
# run_all() 触发。所有函数确定性、可注入假调用器测试。
#
# 锁定映射（臂配置见 ARMS；任何不一致由 verify_arms() 硬失败）：
#   A1 G3 原样  忠实域  ids       （旧路径参照/负对照）
#   A2 G3 原样  R2 域   ids       （检索对照）
#   A3 G3 原样  R2 域   memrep    （旧表示+新序列化）
#   A4 G3+repfix R2 域  ids       （确定性检验臂：输入须与 A2 逐字节相同）
#   A5 G3+repfix R2 域  memrep    （主臂：新表示+新序列化）
#   A6 G2 原样  忠实域  memrep    （描述性对照）
#   A7 B2 嵌入  ——      检索行    （外部锚，描述性）
#
# 旧序列化（ids）= 原实验 FAS 上下文格式逐字复刻（run_llm.py:62-81）：
#   "Working set (nodes with activation):\n- <id>..." + 可选
#   "\nRelations:\n- <src> -<rel>-> <dst>"（静态 JSON 图边、topk 内、≤10 条）。
#   注意：静态 JSON 边保留原始关系名（主体/客体/后继）——原实验同款。
# 重试政策（预注册 §6 字面义）："每调用 ≤3 次指数退避重试" =
#   初始尝试 + 最多 3 次重试 = 至多 4 次尝试/调用（backoff 2s,4s,6s；
#   测试可注入 sleep）。与原 LLMHead 的 3 次总尝试不同，已在准入报告声明。
# 预算：成功调用 ≤210 硬上限（先检查后调用）；尝试/重试/成功/无效分开计数。
# ============================================================================

import hashlib
import json
import os
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments", "cross_episode_recomb"))

import logging
logging.disable(logging.WARNING)

from graph_model import KnowledgeGraph, Node, Edge       # noqa: E402
from diffusion_engine import DiffusionEngine             # noqa: E402
import memrep                                            # noqa: E402
from scoring import PROMPT, check_answer                 # noqa: E402

CE = os.path.join(ROOT, "experiments", "cross_episode_recomb")
CFG = json.load(open(os.path.join(CE, "experiment_config.json"),
                     encoding="utf-8"))
QUESTIONS = CFG["questions"]
EPISODES = json.load(open(os.path.join(CE, "episodes.json"),
                          encoding="utf-8"))
GRAPH_FILES = {"isolated": "graph_isolated.json",
               "shared": "graph_shared.json",
               "eventframe": "graph_eventframe.json"}
SUCCESS_CAP = 210          # 预注册 §6：成功调用硬上限
MAX_RETRIES = 3            # 预注册 §6 字面义：初始 + ≤3 次重试
BACKOFF_S = (2.0, 4.0, 6.0)
K = 8


class HarnessError(RuntimeError):
    pass


class ArmConfigError(HarnessError):
    pass


class BudgetExhausted(HarnessError):
    pass


class ContextMismatchError(HarnessError):
    pass


# ── 锁定臂配置（与预注册 §1 表逐项对应；verify_arms 硬校验）────────

LOCKED_ARMS = [
    {"arm": "A1", "graph": "eventframe", "repfix": False, "regime": "faithful",
     "serializer": "ids", "role": "旧路径参照（负对照）"},
    {"arm": "A2", "graph": "eventframe", "repfix": False, "regime": "R2",
     "serializer": "ids", "role": "检索对照"},
    {"arm": "A3", "graph": "eventframe", "repfix": False, "regime": "R2",
     "serializer": "memrep", "role": "旧表示+新序列化"},
    {"arm": "A4", "graph": "eventframe", "repfix": True, "regime": "R2",
     "serializer": "ids", "role": "确定性检验臂"},
    {"arm": "A5", "graph": "eventframe", "repfix": True, "regime": "R2",
     "serializer": "memrep", "role": "主臂：新表示+新序列化"},
    {"arm": "A6", "graph": "shared", "repfix": False, "regime": "faithful",
     "serializer": "memrep", "role": "描述性对照（G2+新序列化）"},
    {"arm": "A7", "graph": None, "repfix": False, "regime": "embedding",
     "serializer": "flat", "role": "外部锚（B2 参照）"},
]

MAIN_COMPARISONS = [("H1", "A2", "A3"), ("H2", "A3", "A5"),
                    ("H3", "A4", "A5"), ("H4", "A2", "A5")]


def verify_arms(arms=None):
    """臂配置与锁定预注册一致性校验：任何不一致硬失败。"""
    arms = arms if arms is not None else ARMS
    if len(arms) != 7:
        raise ArmConfigError(f"臂数 {len(arms)} ≠ 7")
    for got, locked in zip(arms, LOCKED_ARMS):
        for key in ("arm", "graph", "repfix", "regime", "serializer"):
            if got.get(key) != locked[key]:
                raise ArmConfigError(
                    f"臂 {locked['arm']} 字段 {key} 不一致: "
                    f"{got.get(key)!r} ≠ 锁定值 {locked[key]!r}")
    return True


ARMS = [dict(a) for a in LOCKED_ARMS]      # 运行时副本（校验基准=LOCKED_ARMS）

ENGINES_CFG = {"beta_spread": 1.0, "activation_epsilon": 1e-4,
               "min_spread_threshold": 0.01, "activation_max": 5.0}


def graph_hash(gname, repfix):
    h = hashlib.sha256()
    h.update(json.dumps(CFG["graphs"][gname], sort_keys=True,
                        ensure_ascii=False).encode())
    h.update(f"|repfix={repfix}".encode())
    return h.hexdigest()[:16]


def build_kg(gname, repfix=False):
    """从原档图 JSON 构建引擎（同原 run_mech.build_engine 口径 +
    serial_fix 的 rep_fix 事件属性化）。"""
    g = CFG["graphs"][gname]
    kg = KnowledgeGraph()
    kg.save = lambda *a, **k: None
    for n in g["nodes"]:
        kg.add_node(Node(id=n["id"], weight=1.0, label=n["label"],
                         graph_space=n.get("graph_space", "semantic")))
    for e in g["edges"]:
        kg.add_edge(Edge(src=e["src"], dst=e["dst"], relation=e["relation"],
                         weight=e["weight"],
                         relation_category=e["relation_category"]))
    if repfix:
        epmap = {ep["id"]: ep for ep in EPISODES}
        for nid, n in kg.nodes.items():
            t = str(nid)
            if t.startswith("事件:") and t[3:] in epmap:
                ep = epmap[t[3:]]
                n.extra_attrs.update({"action": ep["action"],
                                      "subject": ep["subject"],
                                      "object": ep["object"],
                                      "seq": int(t[3:][1:])})
    eng = DiffusionEngine(kg, dict(ENGINES_CFG))
    eng.name_to_node = dict(kg.nodes)
    return kg, eng


def r2_ignition_ids(kg):
    """R2 情节新近域（预注册 §0 锁定）：全部 事件 节点均匀点火。
    与问题无关（固定全集，无 gold 泄漏）；断言=全集本身。"""
    return sorted([str(nid) for nid in kg.nodes
                   if str(nid).startswith("事件:")])


def seeds_for(q, gname):
    """原口径：问题种子实体匹配图节点 id（共享/eventframe 精确匹配）。"""
    ids = [n["id"] for n in CFG["graphs"][gname]["nodes"]]
    return [i for i in ids if i in q["seeds"]]


def activate(kg, eng, arm, q):
    """按臂的激活域点火。返回 (topk_ids, activations, top_nodes, edges)。"""
    if arm["regime"] == "embedding":
        raise HarnessError("embedding 域无图激活（A7 走 retrieval_lines）")
    eng.activate_from_inputs(seeds_for(q, arm["graph"]), [],
                             source_type="question")
    if arm["regime"] == "R2":
        if arm["graph"] != "eventframe":
            raise HarnessError("R2 仅定义于 eventframe")
        eng.activate_from_inputs(r2_ignition_ids(kg), [],
                                 source_type="episodic_recency")
    eng.diffuse_round(max_steps=4)
    top, edges = eng.get_topk(k=K)
    topk = [n.id for n in top]
    acts = {n.id: round(float(n.activation or 0), 4) for n in top}
    return topk, acts, top, edges


def serial_ids_original(topk, g):
    """旧序列化：原实验 FAS 上下文格式逐字复刻（含 Relations 段）。"""
    ids = set(topk)
    edges = ["%s -%s-> %s" % (e["src"], e["relation"], e["dst"])
             for e in g["edges"]
             if e["src"] in ids and e["dst"] in ids][:10]
    ctx = "Working set (nodes with activation):\n" + "\n".join(
        "- " + t for t in topk)
    if edges:
        ctx += "\nRelations:\n" + "\n".join("- " + e for e in edges)
    return ctx


def serial_memrep(top_nodes, edges, kg):
    return memrep.serialize_working_set(top_nodes, edges, kg, tl=None)


_EMB = None


def retrieval_lines_for_a7(q):
    """A7：嵌入检索 top-6 经历行（原 B2 代码路径，embedding_manager）。
    模型进程内缓存（结果等价，避免 30 次重复加载）。"""
    global _EMB
    from embedding_manager import EmbeddingProvider
    import numpy as np
    if _EMB is None:
        _EMB = EmbeddingProvider()
    emb = _EMB
    lines = ["%s: %s %s %s" % (e["id"], e["subject"], e["action"],
                               e["object"]) for e in EPISODES]
    M_ = emb.encode(lines)
    qv = emb.encode_single(q["text"])
    sims = M_ @ (qv / (np.linalg.norm(qv) + 1e-9))
    idx = sorted(range(len(lines)), key=lambda i: -float(sims[i]))[:6]
    return "Relevant experiences:\n" + "\n".join(
        lines[i] for i in idx)


def build_context(arm, q, kg=None, eng=None):
    """构造上下文。返回 (context, meta)。不含任何 gold 信息（R2 点火集
    为固定全集；ids/memrep 序列化只读图）。"""
    if arm["serializer"] == "flat":
        return retrieval_lines_for_a7(q), {"mode": "embedding"}
    g = CFG["graphs"][arm["graph"]]
    topk, acts, top_nodes, eng_edges = activate(kg, eng, arm, q)
    if arm["serializer"] == "ids":
        ctx = serial_ids_original(topk, g)
    elif arm["serializer"] == "memrep":
        ctx = serial_memrep(top_nodes, eng_edges, kg)
    else:
        raise HarnessError(f"未知序列化器 {arm['serializer']}")
    return ctx, {"topk": topk, "activations": acts}


# ── 预算与调用（区分尝试/重试/成功/无效）────────────────────────

class BudgetTracker:
    def __init__(self, success_cap=SUCCESS_CAP):
        self.success_cap = int(success_cap)
        self.successes = 0
        self.attempts = 0
        self.retries = 0
        self.invalid = 0

    def can_call(self):
        return self.successes < self.success_cap

    def register_attempt(self, is_retry):
        self.attempts += 1
        if is_retry:
            self.retries += 1

    def register_success(self):
        self.successes += 1
        if self.successes > self.success_cap:
            raise BudgetExhausted("成功调用超过锁定预算 210")
        return self.successes <= self.success_cap


PARENTS = [r"E:\Project\FAS-Companion", r"E:\Project\Fascinator"]


def _find_secret():
    for pth in PARENTS:
        for cand in (os.path.join(pth, "data", "llm_secret.json"),
                     os.path.join(pth, "llm_secret.json")):
            if os.path.exists(cand):
                return cand
    raise FileNotFoundError("llm_secret.json not found under "
                            + ", ".join(PARENTS))


def _find_provider():
    for pth in PARENTS:
        for cand in (os.path.join(pth, "llm_provider.py"),
                     os.path.join(pth, "scripts", "llm_provider.py")):
            if os.path.exists(cand):
                return os.path.dirname(cand)
    raise FileNotFoundError("llm_provider.py not found")


class OpenAICaller:
    """真实调用器（仅在 Phase-3 正式运行时实例化；测试用 Fake）。
    2026-10-12 ADDENDUM-4：供应商切换为千问 qwen3.8-flash
    （人工批准，见 PREREGISTRATION ADDENDUM；预算/其余规则不变）。"""
    model = None

    def __init__(self):
        import openai
        sec = json.load(open(_find_secret(), encoding="utf-8"))
        sys.path.insert(1, _find_provider())
        from llm_provider import QwenBackend
        self.model = QwenBackend._DEFAULT_MODEL          # qwen3.8-flash
        self.client = openai.OpenAI(
            api_key=sec["api_key"],                      # 千问 Key
            base_url=QwenBackend._DEFAULT_BASE_URL,
            timeout=120.0, max_retries=1)

    def call(self, prompt, max_tokens=400, temperature=0):
        r = self.client.chat.completions.create(
            model=self.model, temperature=temperature, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}])
        u = getattr(r, "usage", None)
        return (r.choices[0].message.content or "",
                {"prompt_tokens": (u.prompt_tokens or 0) if u else 0,
                 "completion_tokens": (u.completion_tokens or 0) if u else 0})


def call_with_retry(caller, prompt, budget, sleep=time.sleep,
                    max_retries=MAX_RETRIES):
    """初始尝试 + ≤MAX_RETRIES 次指数退避重试。返回
    (answer, usage, attempts, retries, error)。error=None=无基础设施失败。"""
    err = None
    usage = {}
    for attempt in range(1 + max_retries):
        budget.register_attempt(attempt > 0)
        try:
            ans, usage = caller.call(prompt)
            return ans, usage, attempt + 1, attempt, None
        except Exception as e:                     # 基础设施失败（含超时）
            err = f"{type(e).__name__}: {e}"[:200]
            if attempt < max_retries:
                sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
    return "", usage, 1 + max_retries, max_retries, err


# ── 四阶段诊断（预注册 §5）─────────────────────────────────

def gold_triples(q):
    epmap = {ep["id"]: ep for ep in EPISODES}
    return [(epmap[e]["subject"], epmap[e]["action"], epmap[e]["object"])
            for e in q.get("gold_episodes", []) if e in epmap]


def facts_in_graph(arm):
    """A 阶段：gold 三元组在所选图表示中可表达？（G3 原样：动作不可
    表达=0；rep_fix/G2 直连边=1。臂级设计常量。）"""
    if arm["graph"] == "eventframe":
        return 1 if arm["repfix"] else 0
    return 1                                     # G2 直连边带动作词


def serialized_facts(ctx, q):
    """C 阶段：gold 三元组可从上下文重构的数量（同行含三要素，子串）。"""
    ok = 0
    for subj, act, obj in gold_triples(q):
        for ln in ctx.splitlines():
            if subj in ln and obj in ln and act in ln:
                ok += 1
                break
    return ok


def d_stage(row):
    """D 阶段判定（G2：基础设施错误不计入推理失败）。"""
    if row["infra_failure"]:
        return "not_applicable_infra"
    if row["facts_in_graph"] == 0:
        return "not_applicable_representation"
    return "evaluated"


# ── 单次运行 ─────────────────────────────────────────────

def _commit():
    import subprocess
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT,
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "unknown"


def run_single(arm, q, seed, budget, caller, log, cfg_snapshot,
               a2_ctx_hash=None, sleep=time.sleep):
    """一次 (臂, 问题, 种子) 运行。返回 row dict（已写日志）。"""
    gid = q["id"]
    if arm["serializer"] == "flat":
        ctx, meta = build_context(arm, q)
        prompt = PROMPT.format(question=q["text"], context=ctx)
        ctx_hash = hashlib.sha256(ctx.encode()).hexdigest()[:16]
        topk, acts = [], {}
    else:
        kg, eng = build_kg(arm["graph"], repfix=arm["repfix"])
        ctx, meta = build_context(arm, q, kg=kg, eng=eng)
        prompt = PROMPT.format(question=q["text"], context=ctx)
        topk, acts = meta.get("topk", []), meta.get("activations", {})
        ctx_hash = hashlib.sha256(ctx.encode()).hexdigest()[:16]
        if arm["arm"] == "A4":
            # 确定性检验臂断言：A4 输入须与 A2 逐字节相同（预注册 §1）
            if a2_ctx_hash is None:
                raise ContextMismatchError("A4 运行缺少 A2 参照哈希")
            if ctx_hash != a2_ctx_hash:
                raise ContextMismatchError(
                    f"A4 输入哈希不一致 q={gid} seed={seed}: "
                    f"A4={ctx_hash} A2={a2_ctx_hash}")
    if not budget.can_call():
        raise BudgetExhausted("成功调用已达锁定预算 210，停止")
    ans, usage, attempts, retries, err = call_with_retry(
        caller, prompt, budget, sleep=sleep)
    infra = err is not None
    if not infra:
        budget.register_success()
    else:
        budget.invalid += 1
    scores = check_answer(ans, q) if (ans and not infra) else {
        "exact_success": 0, "partial_success": 0, "path_validity": 0,
        "relation_validity": 0, "mentioned": []}
    row = {
        "arm": arm["arm"], "qid": gid, "seed": seed,
        "attempts": attempts, "retries": retries,
        "final_status": ("success" if not infra else "infra_failed"),
        "infra_failure": infra, "error": err or "",
        "answer": (ans or "")[:400], "empty_answer": (ans == "" and not infra),
        "scores": scores, "exact_success": scores["exact_success"],
        "topk": topk, "activations": acts,
        "context": ctx, "context_hash": ctx_hash,
        "prompt": prompt, "usage": usage,
        "facts_in_graph": facts_in_graph(arm),
        "retrieved_gold": sorted(
            set(q["gold_chain"]) & set(topk)) if topk else [],
        "serialized_facts": serialized_facts(ctx, q),
        "time_source_available": False,     # 数据集无真实时间/来源（预注册声明）
        "d_stage": ("not_applicable_infra" if infra else
                    ("not_applicable_representation"
                     if facts_in_graph(arm) == 0 else "evaluated")),
        "graph_hash": (graph_hash(arm["graph"], arm["repfix"])
                       if arm["graph"] else "n/a"),
        "arm_config": {k: arm[k] for k in
                       ("arm", "graph", "repfix", "regime", "serializer")},
        "code_commit": _commit(), "memrep_switch": _memrep_switch(),
        "ts": time.time(),
        "log_ref": None,
    }
    log(row)
    return row


def _memrep_switch():
    try:
        import config as _C
        return bool((_C.DEFAULT_CONFIG.get("memrep") or {}).get("enabled"))
    except Exception:
        return None


def run_all(caller=None, log=None, out_dir=None, sleep=time.sleep,
            success_cap=SUCCESS_CAP, arms=None, skip=None,
            a2_seed=None):
    """正式编排：A4 哈希断言 → 预算硬限 → 逐 run 记录。
    log 可注入（测试用）；默认追加写 raw_runs.jsonl。"""
    verify_arms(arms)
    arms = arms if arms is not None else ARMS
    budget = BudgetTracker(success_cap)
    if log is None:
        os.makedirs(out_dir or HERE, exist_ok=True)
        path = os.path.join(out_dir or HERE, "raw_runs.jsonl")
        f = open(path, "a", encoding="utf-8")

        def log(row):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
    cfg_snapshot = {"arms": ARMS, "success_cap": success_cap,
                    "max_retries": MAX_RETRIES, "k": K,
                    "code_commit": _commit(),
                    "memrep_switch": _memrep_switch(),
                    "graphs": {g: graph_hash(g, False)
                               for g in GRAPH_FILES}}
    a2_ctx = {}            # (qid, seed) → ctx_hash（供 A4 断言）
    rows = []
    skip = skip or set()
    a2_ctx.update(a2_seed or {})
    # 先跑 A2（参照），逐 (q,seed) 缓存其上下文哈希供 A4 断言
    order = sorted(arms, key=lambda a: 0 if a["arm"] == "A2" else 1)
    for arm in order:
        for q in QUESTIONS:
            for seed in range(5):
                if (arm["arm"], q["id"], seed) in skip:
                    if arm["arm"] == "A2":
                        a2_ctx.setdefault((q["id"], seed), "SKIPPED")
                    continue
                if not budget.can_call():
                    raise BudgetExhausted("预算耗尽，停止全部后续调用")
                try:
                    if arm["arm"] == "A4":
                        ref = a2_ctx.get((q["id"], seed))
                        row = run_single(arm, q, seed, budget, caller, log,
                                         cfg_snapshot, a2_ctx_hash=ref,
                                         sleep=sleep)
                    else:
                        row = run_single(arm, q, seed, budget, caller, log,
                                         cfg_snapshot, sleep=sleep)
                        if arm["arm"] == "A2":
                            a2_ctx[(q["id"], seed)] = row["context_hash"]
                except (ContextMismatchError, ArmConfigError,
                        BudgetExhausted):
                    raise                      # 断言/配置/预算：硬停
                except Exception as e:         # 环境类故障：如实记 error 行
                    row = {"arm": arm["arm"], "qid": q["id"],
                           "seed": seed, "attempts": 0, "retries": 0,
                           "final_status": "context_error",
                           "infra_failure": True, "error": repr(e)[:200],
                           "answer": "", "empty_answer": False,
                           "exact_success": 0,
                           "scores": {"exact_success": 0,
                                      "partial_success": 0,
                                      "path_validity": 0,
                                      "relation_validity": 0,
                                      "mentioned": []},
                           "topk": [], "activations": {}, "context": "",
                           "context_hash": "", "prompt": "",
                           "usage": {}, "facts_in_graph":
                               facts_in_graph(arm),
                           "retrieved_gold": [], "serialized_facts": 0,
                           "time_source_available": False,
                           "d_stage": "not_applicable_infra",
                           "graph_hash": "n/a", "arm_config": {},
                           "code_commit": _commit(),
                           "memrep_switch": _memrep_switch(),
                           "ts": time.time(), "log_ref": None}
                    log(row)
                rows.append(row)
    return rows, budget, cfg_snapshot
