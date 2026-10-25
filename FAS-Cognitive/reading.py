# reading.py — 通用分段阅读闭环（学习目标 / 覆盖台账 / 恢复 / 来源分级 / 未知）
# ============================================================================
# 复用既有结构（不造第二套系统）：
#   * 进度/覆盖 = 文件型台账（json_store 原子写，LocationMemory/
#     experience_replay_state 同族先例）；
#   * 单元节点+事实写回 = memrep（record_fact：text_stated/inferred 来源
#     分级、valid_from、ev 回链）+ graph_model 归一漏斗（关系词必须先在
#     词表内——漏斗吸收未注册词，抽取器词表因此受控于 REL_WHITELIST）；
#   * 步骤状态机 = goal_planner 的 pending/dispatched/confirmed/failed 模式
#     （序列任务无 AND 前置，故不复用其 MC 谓词叶子，只复用模式）；
#   * 缺口 = prior_knowledge 的 缺口: 前缀思想（本模块记 reading_gap，
#     与探索缺口账目分离，避免污染 MC 域闭环）。
#
# 核心区分（任务要求）：
#   dispatched（发起过一次读取）≠ confirmed（抽取+写回成功且有证据）。
#   崩溃/中断只会留下 dispatched 单元，重启后按未读处理——进度不可伪造。
#   完成判定 = 全部单元 confirmed（证据=台账逐单元 hash+写回清单），
#   绝不按"发起过请求"宣布读完。
# ============================================================================

import hashlib
import json
import os
import re
import time

from json_store import atomic_write_json, load_json
from graph_model import Node, Edge
import memrep

# 抽取器允许的规范关系词（全部已在 relation_ontology——过归一漏斗不塌缩）
REL_WHITELIST = ("位于", "拥有", "需要", "导致", "涉及", "属于", "是",
                 "叫做", "相关", "包含")
UNIT_PREFIX = "读物"          # 单元节点 id = 读物:{source_id}#u{n}


def _now_iso():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def salvage_extract_json(raw):
    """从可能被 token 预算截断的模型输出中抢救**完整** JSON 元素。
    真跑证据（artifacts_20261012_151130）：3/6 失败全为输出预算截断——
    u1/u5 JSON 数组中途被切、u3 可见输出为 0。本函数：
      · 完整 JSON → (obj, partial=False)
      · 尾部截断 → 回退到最后一个完整元素、闭合括号 → (obj, partial=True)
      · 不可信 → raise（解析失败绝不写成成功）"""
    import json as _json
    i = (raw or "").find("{")
    if i < 0:
        raise ValueError("no json object in output")
    buf = raw[i:]
    attempts = 0
    while True:
        try:
            return _json.loads(buf), False
        except Exception:
            pass
        closed = _close_open(buf)
        if closed is not None:
            try:
                return _json.loads(closed), True
            except Exception:
                pass
        cut = _trim_to_last_complete(buf)
        if cut is None or cut == buf:
            raise ValueError("unsalvageable extractor output")
        buf = cut[:cut] if False else buf[:cut]
        attempts += 1
        if attempts > 12:
            raise ValueError("salvage budget exceeded")


def _scan_state(text):
    """(stack, in_string, esc) 扫描。"""
    stack = []
    in_s = False
    esc = False
    for idx, ch in enumerate(text):
        if in_s:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_s = False
            continue
        if ch == '"':
            in_s = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
    return stack, in_s, esc


def _close_open(text):
    stack, in_s, _ = _scan_state(text)
    if in_s:
        return None
    t = text.rstrip().rstrip(",")
    stack, in_s, _ = _scan_state(t)
    closers = {"{": "}", "[": "]"}
    return t + "".join(closers[c] for c in reversed(stack))


def _trim_to_last_complete(text):
    """返回截到最后一个 depth≥1 完整元素结束处的切点，或 None。"""
    stack = []
    in_s = False
    esc = False
    last = None
    for idx, ch in enumerate(text):
        if in_s:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_s = False
            continue
        if ch == '"':
            in_s = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
                if stack and stack[-1] == "[":
                    last = idx + 1       # 数组内一个元素刚完整闭合
                elif not stack:
                    last = idx + 1
    return last


def unit_sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class ReadingLedger:
    """一份来源的阅读台账：单元计划 + 覆盖状态 + 写回证据 + 缺口。
    持久化在 path（原子写）；重启 load() 即恢复。"""

    def __init__(self, source, path):
        """source: {source_id, uri, title, total_units, units:[{unit,text,sha256}]}"""
        self.path = path
        self.data = load_json(path, default=None) or {}
        sid = source["source_id"]
        if sid not in self.data:
            self.data[sid] = {
                "uri": source.get("uri"), "title": source.get("title"),
                "total_units": int(source["total_units"]),
                "goal": {"type": "covered", "condition":
                         "all_units_confirmed", "created": _now_iso()},
                "units": {str(u["unit"]): {"sha256": u["sha256"],
                                            "status": "pending",
                                            "written": None, "attempts": 0,
                                            "error": ""}
                          for u in source["units"]},
                "facts": [], "gaps": [], "created": _now_iso()}
            self._flush()
        elif self.data[sid].get("total_units") != int(source["total_units"]):
            raise ValueError("来源单元数与台账不符（源漂移，拒绝续读）")
        self.sid = sid
        self.source = source

    # ── 计划与恢复 ─────────────────────────────────────
    def next_unit(self):
        """下一步候选：第一个未 confirmed 的单元。dispatched 但未 confirmed
        （崩溃残留）按 pending 处理——发起过≠读过。"""
        d = self.data[self.sid]["units"]
        for n in sorted(d, key=int):
            if d[n]["status"] != "confirmed":
                return int(n)
        return None

    def progress(self):
        d = self.data[self.sid]["units"]
        conf = sum(1 for v in d.values() if v["status"] == "confirmed")
        return {"confirmed": conf, "total": len(d),
                "failed": sum(1 for v in d.values()
                              if v["status"] == "failed"),
                "dispatched": sum(1 for v in d.values()
                                  if v["status"] == "dispatched")}

    def goal_satisfied(self):
        return all(v["status"] == "confirmed"
                   for v in self.data[self.sid]["units"].values())

    def set_status(self, n, status, **fields):
        u = self.data[self.sid]["units"][str(n)]
        u["status"] = status
        u.update(fields)
        self._flush()
        return u

    # ── 读一步：mark dispatched → 抽取 → 写回 → confirmed ──────
    def read_unit(self, n, extractor, kg, tl=None, now=None):
        """extractor(text) -> {"entities":[name...],
        "relations":[{"src","rel","dst","kind":"text|inference","quote"}]}
        返回遥测。任何异常 → 单元标 failed + 记录（不静默）。"""
        src_unit = next(u for u in self.source["units"] if u["unit"] == n)
        if src_unit["sha256"] != unit_sha(src_unit["text"]):
            self.set_status(n, "failed", error="source_hash_mismatch",
                            read_ts=_now_iso())
            return {"status": "failed", "reason": "source_hash_mismatch"}
        self.set_status(n, "dispatched", attempts=self.data[self.sid][
            "units"][str(n)]["attempts"] + 1, dispatch_ts=_now_iso())
        part = False
        try:
            out = extractor(src_unit["text"])
            part = bool(isinstance(out, dict) and out.get("_partial"))
        except Exception as e:
            self.set_status(n, "failed", error=f"extract:{e!r}"[:160],
                            read_ts=_now_iso())
            return {"status": "failed", "reason": "extract_error"}
        # 写回：单元节点 + 实体节点 + 关系边（来源分级、quote 留证）
        uid = f"{UNIT_PREFIX}:{self.sid}#u{n}"
        if kg.get_node(uid) is None:
            kg.add_node(Node(id=uid, label="declarative-episodic",
                              graph_space="episodic",
                              extra_attrs={"type": "episode",
                                           "action": "read",
                                           "object": f"{self.sid}:u{n}",
                                           "source": "text_stated",
                                           "ts_iso": _now_iso(),
                                           "uri": self.source.get("uri")}))
        written = {"unit_node": uid, "nodes": [], "relations": 0}
        from graph_schema import HUB_ENTITY_NAMES
        for ent in out.get("entities", []):
            ent = str(ent)[:48]
            if not ent:
                continue
            # 无引证背书的"涉及→枢纽"不建（2026-10-19 同一误归属纪律，
            # 见 graph_schema.HUB_ENTITY_NAMES）；文本若真陈述了关于主体
            # 的事实，会走 relations 通道带着 quote 进来。
            if ent in HUB_ENTITY_NAMES:
                continue
            if kg.get_node(ent) is None:
                kg.add_node(Node(id=ent, extra_attrs={
                    "source": "text_stated",
                    "first_evidence": f"{self.sid}#u{n}"}))
                written["nodes"].append(ent)
            kg.add_edge(Edge(src=uid, dst=ent, relation="涉及", weight=0.5,
                             extra_attrs={"source": "text_stated",
                                          "role": "entity",
                                          "uri": self.source.get("uri")}))
        rels_ok = 0
        for r in out.get("relations", []):
            s, p, o = str(r.get("src"))[:48], str(r.get("rel")), str(
                r.get("dst"))[:48]
            kind = r.get("kind", "text")
            src_tag = ("text_stated" if kind == "text" else "inferred")
            if not s or not o or s == o:
                continue
            for name in (s, o):        # 端点必须存在（add_edge 丢边是静默的）
                if kg.get_node(name) is None:
                    kg.add_node(Node(id=name, extra_attrs={
                        "source": "text_stated",
                        "first_evidence": f"{self.sid}#u{n}"}))
            if p in REL_WHITELIST:
                ev = {"source": src_tag, "evidence": f"{self.sid}#u{n}",
                      "quote": str(r.get("quote") or "")[:160]}
                kg.add_edge(Edge(src=s, dst=o, relation=p, weight=0.6,
                                 extra_attrs=ev))
                if tl is not None:     # 事实+区间进时间轴（历史可恢复）
                    memrep.record_fact(kg, s, p, o, source=src_tag, tl=tl)
                facts = self.data[self.sid]["facts"]
                dup = [f for f in facts if f["s"] == s and f["p"] == p
                       and f["o"] == o]
                if dup:
                    dup[0]["citations"] = dup[0].get("citations", 1) + 1
                    dup[0]["units"] = sorted(set(
                        dup[0].get("units", []) + [n]))
                else:
                    facts.append({"s": s, "p": p, "o": o, "kind": src_tag,
                                  "unit": n, "citations": 1,
                                  "units": [n], "ts": _now_iso()})
                rels_ok += 1
            # 词表白名单外的关系词不写入：静默丢弃=隐瞒抽取器错误，
            # 因此计入 dropped 供审计
            else:
                self.data[self.sid].setdefault("dropped_relations", []) \
                    .append({"rel": p, "unit": n})
        self.set_status(n, "confirmed", written=written,
                        read_ts=_now_iso(), relations=rels_ok,
                        partial=part)
        return {"status": "confirmed", "unit": n, "written": written,
                "relations": rels_ok, "partial": part}

    # ── 查询与未知（证据绑定）───────────────────────────
    def evidence_for(self, question, kg=None):
        """返回 (units, facts)：问题与 confirmed 单元实体重合的证据集
        （failed/dispatched 单元永不作为来源）。无重合 → 空。"""
        d = self.data[self.sid]
        hits = self._entity_hits(question, kg=kg)
        hit_units, rel_facts = [], []
        for u in d["units"]:
            if d["units"][u]["status"] != "confirmed":
                continue
            w = d["units"][u].get("written") or {}
            names = set(w.get("nodes") or []) | {
                f["s"] for f in d["facts"] if int(f["unit"]) == int(u)} | {
                f["o"] for f in d["facts"] if int(f["unit"]) == int(u)}
            if names & hits:
                hit_units.append(int(u))
        seen = set(hit_units)
        for f in d["facts"]:
            if f["unit"] in seen or str(f["unit"]) in hit_units:
                rel_facts.append(f)
        return sorted(set(hit_units)), rel_facts

    def ask(self, question, kg=None):
        """只读证据包。status=no_evidence 即缺口：记录之（写而无读者按
        §7 由上层决定消费），且明确指向未读单元作为下一步候选。"""
        units, facts = self.evidence_for(question, kg=kg)
        if not units:
            gap = {"q": question[:120], "ts": _now_iso(),
                   "unread_pending": [n for n in sorted(
                       self.data[self.sid]["units"], key=int)
                       if self.data[self.sid]["units"][n]["status"]
                       != "confirmed"][:4]}
            self.data[self.sid]["gaps"].append(gap)
            self._flush()
            return {"status": "no_evidence", "gap": gap}
        return {"status": "evidence", "units": units,
                "facts": [{"s": f["s"], "rel": f["p"], "o": f["o"],
                           "kind": f["kind"], "unit": f["unit"],
                           "citations": f.get("citations", 1)}
                          for f in facts[:12]],
                "next_unit": self.next_unit()}

    def scan_conflicts(self):
        """同 (主语,关系) 出现不同宾语的 confirmed 事实 → 潜在矛盾清单
        （诊断用，不自动裁决、不静默覆盖）。"""
        by_sp = {}
        for f in self.data[self.sid]["facts"]:
            by_sp.setdefault((f["s"], f["p"]), []).append(f)
        out = []
        for (s, p), fs in by_sp.items():
            objs = {f["o"] for f in fs}
            if len(objs) > 1:
                out.append({"s": s, "p": p,
                            "objects": sorted(objs),
                            "units": sorted({f["unit"] for f in fs})})
        return sorted(out, key=lambda x: str(x))

    _ALIAS_RELS = ("名字叫", "同一")   # 图上已注册的同义/同指关系

    def _known_entities(self, kg=None):
        d = self.data[self.sid]
        ents = set()
        for u in d["units"]:
            w = d["units"][u].get("written") or {}
            ents |= set(w.get("nodes") or [])
        for f in d["facts"]:
            ents.add(f["s"])
            ents.add(f["o"])
        return ents

    def _alias_map(self, kg):
        """实体 → 等价名集合（名字叫/同一 边；两方向）。kg=None 时为空。"""
        alias = {}
        if kg is None:
            return alias
        for name in self._known_entities(kg):
            try:
                for e in kg.get_out_edges(name) + kg.get_in_edges(name):
                    if e.relation in self._ALIAS_RELS:
                        other = (e.dst if str(e.src) == str(name)
                                 else e.src)
                        alias.setdefault(name, set()).add(str(other))
                        alias.setdefault(str(other), set()).add(name)
            except Exception:
                continue
        return alias

    @staticmethod
    def _name_tokens(name):
        """实体名拆词：拉丁词（≥2）与 CJK 字符；'_' 视为分隔。"""
        n = str(name).lower().replace("_", " ")
        toks = re.findall(r"[a-z][a-z']+|[一-鿿]", n)
        return toks

    @classmethod
    def _fold(cls, w):
        return w[:-1] if len(w) > 3 and w.endswith("s") else w

    def _entity_hits(self, question, kg=None):
        """问题 ↔ 实体匹配（P2-4 修正版）：
          · 实体名完整出现在问题中；
          · 或问题词与实体词做"折叠复数后的词级相等"（实体含 ≥4 字母词
            或 ≥2 字 CJK 连续段，避免 stopword 级误命中）；
          · 别名扩展（名字叫/同一）。
        词级匹配替代任意子串——"owe"⊄"Veltro"，但"woods"↔"dark wood"
        经 token fold 命中。"""
        ql = str(question or "").lower()
        q_words = set()
        for w in re.findall(r"[a-z']{2,}|[一-鿿]+", ql):
            if re.fullmatch(r"[一-鿿]+", w):
                q_words |= {w} | {w[a:a + 2] for a in range(len(w) - 1)}
            else:
                q_words.add(self._fold(w))
        alias = self._alias_map(kg)
        hits = set()
        for name in self._known_entities(kg):
            names = {name} | alias.get(name, set())
            matched = False
            for nm in names:
                nl = str(nm).lower()
                if nl.replace("_", " ") in ql or nl in ql:
                    matched = True
                    break
                ntoks = [self._fold(t) for t in
                         re.findall(r"[a-z']{2,}|[一-鿿]", nl)]
                strong = [t for t in ntoks
                          if (t.isascii() and len(t) >= 4)
                          or (not t.isascii() and len(t) >= 2)]
                if strong and any(t in q_words for t in strong):
                    matched = True
                    break
            if matched:
                hits.add(name)
                hits |= names & self._known_entities(kg)
        return hits

    # ── 三态证据包（P2-4：有证据/冲突/不足；来源隔离）───────────
    def evidence_pack(self, question, kg=None):
        """返回 {state: sufficient|conflict|insufficient, pack, units, facts}。
        绝不把不同来源的行合并成一条事实（每行自带 source/unit/kind）。"""
        units, facts = self.evidence_for(question, kg=kg)
        if not units:
            return {"state": "insufficient", "pack": "", "units": [],
                    "facts": []}
        conflicts = {(c["s"], c["p"]) for c in self.scan_conflicts()}
        state = "sufficient"
        lines = [f"【{self.sid} @ {self.source.get('uri') or '?'}】"]
        for f in facts:
            if (f["s"], f["p"]) in conflicts and                     any(o != f["o"] for g in self.data[self.sid]["facts"]
                        if (g["s"], g["p"]) == (f["s"], f["p"])
                        for o in [g["o"]]):
                state = "conflict"
                tag = " ⚠同一(主,谓)存在不同宾语的已证事实，须并列呈不确定"
            else:
                tag = ""
            lines.append(f"- [u{f['unit']}] {f['s']} -{f['p']}-> {f['o']} "
                         f"({f['kind']}; citations={f.get('citations', 1)})"
                         + tag)
        return {"state": state, "pack": chr(10).join(lines),
                "units": units, "facts": facts}

    def progress_report(self):
        """进度真话：confirmed/total/failed/pending + 下一单元。"""
        p = self.progress()
        nxt = self.next_unit()
        return (f"已确认 {p['confirmed']}/{p['total']} 单元；"
                f"失败 {p['failed']}；"
                + (f"下一步：读第 {nxt} 单元" if nxt is not None
                   else "全部完成")
                + ("（部分单元输出被截断，已按 partial 记账）"
                   if any(u.get("partial") for u in
                          self.data[self.sid]["units"].values()) else ""))

    def register_gap(self, kg, engine, topic, config=None):
        """未解决问题 → 探索缺口（label=阅读）：进同一 hub/张力账本，
        CuriosityDrive 消费；不生成 MC 具身 inspect 候选。"""
        import prior_knowledge as pk
        return pk.open_gap(kg, engine, str(topic)[:40],
                           kind="read_gap", label="阅读", config=config)

    def begin_source_text(self, text, source_id, uri=None,
                          unit_chars=900, max_units=None):
        """通用切分（散文按空行段聚合到 unit_chars）；返回新 source dict。
        供宿主从 read_file 的 content 建立台账。"""
        paras = [re.sub(r"\s+", " ", p).strip()
                 for p in re.split(r"\n\s*\n", str(text or ""))]
        paras = [p for p in paras if p]
        units, buf = [], ""
        for p in paras:
            if buf and len(buf) + len(p) + 1 > unit_chars:
                units.append(buf)
                buf = p
            else:
                buf = (buf + " " + p).strip()
        if buf:
            units.append(buf)
        if max_units:
            units = units[:int(max_units)]
        return {"source_id": source_id, "uri": uri,
                "title": source_id, "total_units": len(units),
                "units": [{"unit": k + 1, "text": t,
                           "sha256": unit_sha(t)}
                          for k, t in enumerate(units)]}

    def _flush(self):
        atomic_write_json(self.path, self.data)

    def claims_vs_evidence(self):
        """"声称完成"与"证据完成"的一致性检查（报告用）。"""
        pr = self.progress()
        return {"claims_done": self.goal_satisfied(),
                "evidence_done": pr["confirmed"] == pr["total"],
                "progress": pr}


def load_source(path):
    return json.load(open(path, encoding="utf-8"))


# ── 抽取器工厂（生产/实验共用；LLM 调用经注入的 call_fn）──────────

def make_llm_extractor(call_fn, max_retries=1, brief=""):
    """call_fn(prompt_text)->raw_model_output。解析失败有限重试（默认 1 次，
    更严格短指令）；只写完整元素；partial 如实上账。零自有网络调用。"""
    import json as _json

    def _prompt(text, strict=False):
        head = (
            "Extract knowledge from the text unit. Return STRICT JSON ONLY "
            '(no prose): {"entities":[names], "relations":[{"src":..,'
            '"rel":..,"dst":..,"kind":"text|inference","quote":..}]}. '
            "Allowed rel values: " + " ".join(REL_WHITELIST) + ". "
            "kind=text only if stated in this unit.")
        if brief:
            head += " " + brief
        if strict:
            head += (" Previous output was invalid/truncated: at most 6 "
                     "relations, very short quotes.")
        return head + "\n---\n" + str(text)[:1500]

    def ex(text):
        last_err = None
        for attempt in range(1 + max(0, int(max_retries))):
            raw = call_fn(_prompt(text, strict=attempt > 0))
            try:
                obj, partial = salvage_extract_json(raw)
                if not isinstance(obj, dict):
                    raise ValueError("json not an object")
                # 截断可能只剩 entities（relations 从未闭合）：按
                # "可抢救部分 + partial"记账，不整体作废真实完整元素
                if not isinstance(obj.get("entities"), list):
                    obj["entities"] = []
                if not isinstance(obj.get("relations"), list):
                    obj["relations"] = []
                    partial = True
                obj["_partial"] = partial
                obj["_attempts"] = attempt + 1
                return obj
            except Exception as e:
                last_err = e
        raise RuntimeError(f"extract failed after retries: {last_err!r}")
    return ex


# ── 生产持久化辅助（宿主 app.py 消费；纯文件级，零 LLM）─────────

def sources_sidecar(ledger_path):
    return str(ledger_path) + ".sources"


def open_ledger(ledger_path, source=None):
    """有 source 建档（单元文本随 sidecar 持久化）；无 source 恢复最近
    未完成的来源。找不到 → None（宿主如实报告"没有在进行的阅读"）。"""
    import json as _json
    sp = sources_sidecar(ledger_path)
    side = load_json(sp, default=None) or {}
    if source is not None:
        src = dict(source)
        if src.get("total_units") and "units" in src:
            side[src["source_id"]] = {
                "uri": src.get("uri"), "title": src.get("title"),
                "total_units": src["total_units"],
                "units": [{"unit": u["unit"], "text": u["text"],
                           "sha256": u["sha256"]} for u in src["units"]]}
            atomic_write_json(sp, side)
        sid = src["source_id"]
    else:
        led = ReadingLedger(
            {"source_id": "__probe__", "total_units": 0, "units": []},
            ledger_path)
        # 选第一个尚未全部 confirmed 的来源
        sid = None
        data = load_json(ledger_path, default=None) or {}
        for cand in side:
            rec = data.get(cand)
            if not rec:
                sid = cand
                break
            if not all(v.get("status") == "confirmed"
                       for v in (rec.get("units") or {}).values()):
                sid = cand
                break
        if sid is None and side:
            sid = next(iter(side))
        if sid is None:
            return None
    src_full = side.get(sid)
    if src_full is None:
        return None
    return ReadingLedger({"source_id": sid, **src_full}, ledger_path)


def any_active_reading(ledger_path):
    """有没有在进行的阅读（有台账且未全部 confirmed）。"""
    data = load_json(ledger_path, default=None) or {}
    for _sid, rec in data.items():
        units = rec.get("units") or {}
        if units and not all(u.get("status") == "confirmed"
                             for u in units.values()):
            return True
    return False
