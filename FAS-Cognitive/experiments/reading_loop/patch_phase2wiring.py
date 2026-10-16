# patch_phase2wiring.py — 一次性补丁：config reader 节 + reading 持久化 + 宿主模板/app
import io
import os
import re

COG = r"E:\Project\FAS-Cognitive"
HOST = r"E:\Project\FAS-Companion"


def rw(path, fn):
    s = io.open(path, encoding="utf-8").read()
    s2 = fn(s)
    assert s2 is not None and s2 != s, path
    io.open(path, "w", encoding="utf-8").write(s2)
    print("patched", path)


# ── 1) FAS-Cognitive/config.py：reader 节（默认关）──────────────
def f_cfg(s):
    a = '''    "planner": {'''
    b = '''    # ------------------------------------------------------------------
    # Reader — 分段阅读闭环生产接入（2026-10-12；消费者=reading.py 与
    # FAS-Companion app.py 的 reader 块）。**默认关**：关时宿主块整体跳过，
    # 生产行为逐位不变。每拍最多推进一个抽取单元（无后台调度假设、
    # 不自动开启昂贵长任务；进度/继续均为对话内显式回合）。
    # ------------------------------------------------------------------
    "reader": {
        "enabled": False,               # 总开关
        "ledger_path": "data/reading_ledger.json",
        "unit_chars": 900,              # 单元聚合字符数
        "max_units": 200,               # 单来源单元上限（超出截断并标注）
    },

    "planner": {'''
    return s.replace(a, b, 1) if a in s else None


rw(os.path.join(COG, "config.py"), f_cfg)


# ── 2) FAS-Cognitive/reading.py：持久化与恢复 API ────────────────
def f_rd(s):
    s2 = s + '''

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
'''
    return s2


rw(os.path.join(COG, "reading.py"), f_rd)

# ── 3) 宿主 prompt_templates.py ─────────────────────────────────
def f_pt(s):
    old = '''从用户指令中抽取文件操作参数。仅当用户明确要求创建/写入文件时输出动作，
否则输出 {"action": null}。

""" + OUTPUT_JSON + """

输出格式：
{"action": "create_file" 或 null,
 "name": "文件名（含扩展名，用户未给扩展名时补 .txt）",
 "content": "文件内容（用户未说明时填空字符串）",
 "dir": "桌面 或 文档 或 下载（默认桌面）"}"""'''
    new = '''从用户指令中抽取文件操作参数。仅当用户明确要求创建/写入文件时输出
create_file；明确要求读取/打开/查看某个本地文本文件时输出 read_file；
否则输出 {"action": null}。

""" + OUTPUT_JSON + """

输出格式：
{"action": "create_file" 或 "read_file" 或 null,
 "name": "文件名（含扩展名，用户未给扩展名时补 .txt）",
 "content": "文件内容（仅 create_file 需要；read_file 填空字符串）",
 "dir": "桌面 或 文档 或 下载（默认桌面）"}"""'''
    if old not in s:
        return None
    s = s.replace(old, new)
    anchor = '    "file_action_extract": FILE_ACTION_EXTRACT,'
    add = anchor + '''
    "reader_extract": READER_EXTRACT,'''
    if anchor not in s:
        return None
    s = s.replace(anchor, add)
    s = s.replace('# ── 反思分析（Phase 2: 6 问；Reflection Evolution v2） '
                  '──────────────────',
                  '''READER_EXTRACT = """Extract knowledge from a text unit. Return STRICT JSON ONLY:
{"entities": [names], "relations": [{"src":.., "rel":.., "dst":..,
"kind": "text|inference", "quote": "short exact phrase from the unit"}]}
Allowed rel values: 位于 拥有 需要 导致 涉及 属于 是 叫做 相关 包含.
kind=text ONLY if the unit states it; otherwise kind=inference.
Entities: at most 8. Relations: at most 8, each a complete object.
No prose, no markdown fences."""

# ── 反思分析（Phase 2: 6 问；Reflection Evolution v2） ──────────────────''')
    return s


rw(os.path.join(HOST, "prompt_templates.py"), f_pt)

# ── 4) 宿主 app.py：FILE_READ 执行 + reader 回合块 ───────────────
def f_app(s):
    old = '''                if _fi["action"] != "FILE_CREATE":
                    _gap = "读取文件" if _fi["action"] == "FILE_READ" else "删除文件"
                    _file_result = {
                        "ok": False,
                        "error": f"暂不支持{_gap}（当前文件能力只支持创建/写入），"
                                 f"已理解你的请求",
                        "recognized": _fi["action"]}
                    logger.info(f"[FileAction] {describe_intent(_fi)} → 能力缺口如实拒绝")
                else:'''
    new = '''                if _fi["action"] == "FILE_DELETE":
                    _file_result = {
                        "ok": False,
                        "error": "暂不支持删除文件（当前文件能力支持创建/写入/读取），"
                                 "已理解你的请求",
                        "recognized": _fi["action"]}
                    logger.info(f"[FileAction] {describe_intent(_fi)} → 能力缺口如实拒绝")
                else:'''
    if old not in s:
        return None
    s = s.replace(old, new)
    # read_file 走同一条执行链（原 create 分支保留），并在 reader.enabled 时开台账
    old2 = '''                        from actions.file_action import execute_file_action
                        _file_result = execute_file_action(
                            _spec["action"], _spec.get("name", ""),
                            _spec.get("content", ""), _spec.get("dir", "桌面"))
                        logger.info(f"[FileAction] 执行结果: {_file_result}")'''
    new2 = old2 + '''
                # 阅读闭环（config.reader 默认关=整块跳过）：成功读取的
                # 文本文件建立分段台账（目标/覆盖/证据绑定），不自动连读。
                if (_file_result or {}).get("ok") and \\
                        _file_result.get("action") == "read_file" and \\
                        (config.get("reader") or {}).get("enabled"):
                    try:
                        import reading as _rd
                        _rc = config.get("reader") or {}
                        _lp = _rc.get("ledger_path",
                                      "data/reading_ledger.json")
                        _sid = "file:" + os.path.basename(
                            str(_file_result.get("path") or ""))
                        _src = _rd.ReadingLedger(
                            {"source_id": _sid, "total_units": 0,
                             "units": []},
                            "__scratch__").begin_source_text(
                            _file_result.get("content") or "", _sid,
                            uri=str(_file_result.get("path")),
                            unit_chars=int(_rc.get("unit_chars", 900)),
                            max_units=int(_rc.get("max_units", 200)))
                        _rd.open_ledger(_lp, _src)
                        _lp_probe = _rd.open_ledger(_lp)
                        _file_result["reader"] = {
                            "source_id": _sid,
                            "units": _src["total_units"],
                            "report": _lp_probe.progress_report()}
                        logger.info(f"[Reader] 台账建立 {_sid} "
                                    f"{_src['total_units']} 单元")
                    except Exception as _re2:
                        logger.warning(f"[Reader] 台账失败: {_re2}")'''
    if old2 not in s:
        return None
    s = s.replace(old2, new2, 1)
    # reader 回合块：进度真话 / 继续读一拍一单元 / 无台账如实
    anchor = '''        # -------------------------------------------------
        # 2a-pre.45. 屏幕感知动作：触发 → 截屏OCR → 注入图谱
        # -------------------------------------------------'''
    block = '''        # -------------------------------------------------
        # 2a-pre.4b. 阅读回合（config.reader 默认关）：进度询问 /
        # "继续读"每拍最多推进一个抽取单元 / 证据包挂 file_evidence
        # 通道。不后台调度、不自动连读——每拍上限 1 单元 LLM 抽取。
        # -------------------------------------------------
        try:
            _rc = config.get("reader") or {}
            if _rc.get("enabled"):
                import reading as _rd
                _lp = _rc.get("ledger_path", "data/reading_ledger.json")
                _t = str(text or "").strip()
                if _rd.any_active_reading(_lp) and re.search(
                        r"读到哪|阅读进度|读完了吗", _t):
                    _led = _rd.open_ledger(_lp)
                    _file_result = _file_result or {
                        "ok": True, "action": "reader",
                        "summary": _led.progress_report(),
                        "content": _led.progress_report()}
                if re.search(r"^(继续|接着)(读|看)", _t) and                         _rd.any_active_reading(_lp):
                    _led = _rd.open_ledger(_lp)
                    _n = _led.next_unit()
                    if _n is not None:
                        def _call(p):
                            return nlp.ask("reader_extract", p)
                        _ex = _rd.make_llm_extractor(
                            _call, max_retries=1,
                            brief="Output compact JSON.")
                        _r = _led.read_unit(_n, _ex, kg,
                                            tl=globals().get("timeline"))
                        _file_result = _file_result or {
                            "ok": _r["status"] == "confirmed",
                            "action": "reader",
                            "summary": f"第 {_n} 单元 {_r['status']}"
                                       f"（{_led.progress_report()}）"}
                        logger.info(f"[Reader] 推进单元 {_n}: "
                                    f"{_r['status']}")
        except Exception as _rde:
            logger.debug(f"[Reader] 回合块跳过: {_rde}")

''' + anchor
    if anchor not in s:
        return None
    s = s.replace(anchor, block, 1)
    return s


rw(os.path.join(HOST, "app.py"), f_app)
print("ALL PATCHES DONE")
