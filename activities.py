# -*- coding: utf-8 -*-
"""activities — 让"活着的心跳"从认知状态里自己选一件事做（或什么都不做）。

不是新模式、不是日程表、不是平行大脑：
  · 复用 living_loop 既有守护心跳（一拍一次选择权，间隔不变）；
  · 每个活动的"想做程度"（appeal）由**现有认知信号**计算——
      music  ← self_graph 偏好边权重 + 最近听过的饱足衰减
      browse ← curiosity_engine 的活跃问题 + 图谱注意力（读到的内容经
               mark_active 进扩散场，自然孵化下一次联想/好奇）
      research ← 既有知识缺口链（原 living_tick_once，逻辑零改动）
  · 全部低于阈值 → 本拍什么都不发生（允许安静，不强迫产出）；
  · 轻量活动不进 TaskLoop（没有目标/台账/重规划）；有明确交付的才升级；
  · 活动结果作为情景记忆写回图谱（activation 直写+mark_active，前沿不变量），
    听歌体验调节既有的偏好边权重——这是"经历影响以后想做什么"的唯一通道，
    不另建兴趣数据库。

宿主只存运行态（上次播放时刻/计数/库扫描缓存）于 data/activities_state.json
——属播放器/进度类宿主数据（任务书允许），非认知状态。

成本与隐私：本模块零 LLM 调用；网络仅只读 search/GET（复用 living 预算纪律）；
不碰麦克风/屏幕/账号；音乐经系统默认播放器真实出声（与 Charon 音乐页同语义）。
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
import time

import pc_autonomy

logger = logging.getLogger("activities")

AUDIO_EXT = (".mp3", ".flac", ".wav", ".ogg", ".m4a")
_STATE_LOCK = threading.Lock()

# 进程内静默播放（2026-10-13 晚，用户要求后台静默）：sounddevice 解码自放
# ——不弹任何窗口。播放循环持续检查静音闸：stop_playback() 或 LIVING 关
# 闭后 ≤0.5 秒真停（"关闭后停止实际动作"的硬保证）。
_PLAY_STOP = threading.Event()


def stop_playback():
    """外部静音口（关开关/端点急停）。"""
    _PLAY_STOP.set()


def _play_local(ctx, path, max_s=300.0):
    """进程内播放。True=自然播完 / False=提前停止 / None=解码或设备不可用。"""
    import sounddevice as sd
    import soundfile as sf
    try:
        data, sr = sf.read(path, dtype="float32")
    except Exception as e:                        # noqa: BLE001
        logger.info("[Act] 解码失败（%s）：%r",
                    os.path.basename(path)[:40], e)
        return None
    if getattr(data, "ndim", 1) > 1:
        data = data.mean(axis=1)
    vol = max(0.0, min(1.0, float(
        ctx["config"].get("activity_music_volume", 0.4))))
    data = (data * vol).astype("float32")
    _PLAY_STOP.clear()
    chunk = max(1, int(sr * 0.5))
    played_s = 0.0
    try:
        with sd.OutputStream(samplerate=sr, channels=1,
                             dtype="float32") as out:
            for i in range(0, len(data), chunk):
                if _PLAY_STOP.is_set() or played_s >= max_s:
                    return False
                if not ctx["config"].get("living_loop_enabled", False):
                    return False          # LIVING 关=真停，不播完这首
                block = data[i:i + chunk]
                out.write(block)
                played_s += len(block) / sr
    except Exception as e:            # noqa: BLE001
        logger.info("[Act] 播放设备不可用：%r", e)
        return None
    return True


# ── 宿主运行态（不是认知数据库：只记"上次何时/听过几次"这类播放器事实）──
_STATE_PATH_OVERRIDE = None       # 测试注入点（reset_state_for_test）

# 平台/渠道概念（2026-10-25）：内容容器不是内容本身——browse 种子与
# 话题判定都不该被"她常去的网站"占位。语义性集合，非点名特判具体话题。
_PLATFORM_CONCEPTS = {
    "哔哩哔哩", "bilibili", "B站", "b站", "IT之家", "ithome", "Hacker News",
    "HN", "知乎", "微博", "Twitter", "GitHub", "YouTube", "油管",
    "播放量", "点赞数", "投硬币枚数", "视频作者", "弹幕", "收藏",
    "首页", "论坛", "社区", "网站", "网页", "APP", "客户端",
}


def _state_path():
    return _STATE_PATH_OVERRIDE or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data", "activities_state.json")


def _load_state():
    try:
        s = json.load(open(_state_path(), encoding="utf-8"))
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(s):
    try:
        tmp = _state_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _state_path())
    except OSError:
        pass


# ══ 三个轻量活动。协议：available/appeal/beat 三函数，无对象层级 ══

# ── music：真实出声的选择来自既有"喜欢"边 ────────────────────────────

def _library(cfg):
    root = os.path.expanduser(str(cfg.get("activity_music_library")
                                   or "~/Music"))
    if not os.path.isdir(root):
        return []
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if fn.lower().endswith(AUDIO_EXT):
                out.append(os.path.join(dirpath, fn))
        if len(out) > 300:
            break
    return out


def music_available(ctx):
    cfg = ctx["config"]
    return bool(_library(cfg)), ("库为空/目录不存在" if not _library(cfg) else "")


def _music_appeal(ctx, state):
    """偏好权重（图谱既有 喜欢 边，含 music/音乐/歌 关键词）× 饱足衰减。"""
    base = 0.0
    try:
        from self_graph import get_preferences
        for p in get_preferences(ctx["kg"]):
            t = str(p.get("target", ""))
            if any(k in t for k in ("音乐", "歌", "music", "听")):
                base = max(base, float(p.get("weight", 0)))
    except Exception:                             # noqa: BLE001
        return 0.0
    if base <= 0:
        # 图谱里还没有"喜欢音乐"这条边：首次以中性低意愿试探（听完会写回，
        # 之后偏好真实决定）——这是"经历生成偏好"，不是硬编码日程。
        base = 0.25
    last = float(state.get("music", {}).get("last_ts", 0) or 0)
    plays = int(state.get("music", {}).get("plays_today", 0) or 0)
    fresh = min(1.0, (time.time() - last) / 3600.0 / 2.0)   # 2h 起回升
    satiety = max(0.15, 1.0 - plays * 0.3)                  # 当天越听越平
    return base * 0.5 * fresh * satiety


def _pick_track(ctx, tracks, state):
    """选曲：与偏好标签的字面匹配 + 未播过的轻量优先（真实经验通道）。"""
    boost = {}
    try:
        from self_graph import get_preferences
        for p in get_preferences(ctx["kg"]):
            w = float(p.get("weight", 0) or 0)
            for tok in re.split(r"[\s/、,，]+", str(p.get("target", ""))):
                if len(tok) >= 2:
                    boost[tok] = max(boost.get(tok, 0), w)
    except Exception:                             # noqa: BLE001
        pass
    played = state.get("music", {}).get("plays", {})
    scored = []
    for t in tracks:
        name = os.path.splitext(os.path.basename(t))[0].lower()
        b = sum(w for tok, w in boost.items() if tok.lower() in name)
        novelty = 0.15 if not played.get(t) else 0.0
        scored.append((b + novelty + random.random() * 0.05, t))
    scored.sort(reverse=True)
    return scored[0][1] if scored else None


def music_beat(ctx, state):
    tracks = _library(ctx["config"])
    if not tracks:
        return {"done": False, "why": "empty_library"}
    ms = state.setdefault("music", {})
    played = ms.get("plays") or {}
    # 依次试：解码失败的曲式（如 m4a 无后端）如实跳过，不假装播放
    tried, result = [], None
    for _ in range(3):
        track = _pick_track(ctx, [t for t in tracks if t not in tried], state)
        if track is None:
            return {"done": False, "why": "no_playable_track"}
        tried.append(track)
        result = _play_local(ctx, track)
        if result is not None:
            break
    if result is None:
        return {"done": False, "why": "no_decoder/backend for: "
                + ",".join(os.path.basename(t) for t in tried)[:60]}
    finished = result is True
    ms["last_ts"] = time.time()
    ms["plays"] = played
    ms["plays"][track] = int(played.get(track, 0)) + 1
    ms["plays_today"] = int(ms.get("plays_today", 0)) + 1
    title = os.path.splitext(os.path.basename(track))[0][:60]
    # 偏好调节来自真实观测：完整听完=正向；提前掐掉（静音闸/超时/被打断）=微负
    _tune_preference(ctx, "音乐", 0.03 if finished else -0.02)
    _note_experience(
        ctx,
        f"《{title}》{'听完了。' if finished else '听了一会儿就停了。'}",
        "activity_music", value="medium" if finished else "low")
    return {"done": True, "activity": "music", "what": title,
            "finished": finished, "next": "continue"}


# ── browse：好奇心驱动的随便看看（不写笔记、不立任务）────────────────

def browse_available(ctx):
    return True, ""


def _browse_seed(ctx):
    """读什么由认知层当前在场什么决定：优先好奇引擎的活跃问题，
    其次注意力 topk 里的语义词——孵化自联想，不是轮询。
    第三层（2026-10-25 课题池回种）：近期浏览记忆里的概念——她真逛到
    过的东西是最诚实的兴趣沉淀（伪假设清理掏空课题池后，整夜只剩
    '用户'枢纽可当种子=空转的实锤修复）。排除身份/内部节点。"""
    try:
        st = ctx["curiosity"].get_curiosity_state(ctx["kg"])
        if st.get("active") and st.get("question"):
            return str(st["question"])[:60], "curiosity"
    except Exception:                             # noqa: BLE001
        pass
    try:
        tk = ctx["engine"].get_topk(k=20)
        nodes = tk[0] if isinstance(tk, tuple) else tk.get("nodes", [])
        for n in nodes:
            nid = str(n.get("id") if isinstance(n, dict) else n)
            if 2 <= len(nid) <= 16 and not nid.startswith(
                    ("Self", "CI_", "Task_", "Steam_", "搜索记录", "eye_",
                     "Charon观察", "用户近况")):
                return nid, "attention"
    except Exception:                             # noqa: BLE001
        pass
    try:
        with ctx["kg"]._lock:
            # 满足语义（2026-10-25 用户设计质询落地）：调研过/兴趣耗尽的
            # 概念不该反复当选——台账已登记的课题排除，兴趣水位低者降权。
            _acted = set(ctx.get("acted_topics") or ())
            # 近访排除（2026-10-25 补）：最近 4 小时内已被浏览经历覆盖的
            # 概念不当选——"刚读过"的实况记录在经历节点 created 上，比
            # 兴趣水位直接（browse 的水位戳 16:50 才接线，存量节点没有）。
            import datetime as _dtc
            _cutoff = time.time() - 4 * 3600
            recent_visited = set()
            # state 记档优先：她消费过的种子（低价值阅读不长概念边，
            # 图上排除会漏——17:01 实锤"特斯拉"×8 全漏）
            try:
                for s_, t_ in _load_state().get("browse", {}).get(
                        "recent_seeds", []):
                    if time.time() - float(t_) < 4 * 3600:
                        recent_visited.add(str(s_))
            except Exception:
                pass
            for n in ctx["kg"].nodes.values():
                if not str(n.id).startswith("Activity_activity_browse"):
                    continue
                try:
                    ts = _dtc.datetime.strptime(
                        str(n.created or "")[:19], "%Y/%m/%d %H:%M:%S").timestamp()
                except ValueError:
                    continue
                if ts >= _cutoff:
                    for e in ctx["kg"].edges:
                        if str(e.src) == n.id:
                            recent_visited.add(str(e.dst))
            cands = {}
            for e in ctx["kg"].edges:
                src = str(e.src)
                if not src.startswith("Activity_activity_browse"):
                    continue
                bid = str(e.dst)
                if bid in recent_visited:
                    continue
                bid = str(e.dst)
                if not (2 <= len(bid) <= 16) or bid.startswith(
                        ("Self", "CI_", "Task_", "Steam_", "搜索记录",
                         "eye_", "用户", "Fascinator", "Haru", "话语",
                         "表达", "思考", "时点")):
                    continue
                # 平台/渠道类概念不配当话题种子（2026-10-25 实锤：频次最高
                # 恰是'哔哩哔哩'×22 → 她反复去搜'商场'这个词）。渠道是容器
                # 不是内容；下两行让真实话题概念（特斯拉/DeepSeek…）上位。
                if bid in _PLATFORM_CONCEPTS or bid in _acted:
                    continue
                bn = ctx["kg"].nodes.get(bid)
                if bn is None or bn.graph_space != "semantic":
                    continue
                # 兴趣水位加权：sated/低水位（满足过、被忽略过）降权，
                # 高水位（反复遇到却没被兑现）加权——"想了解"才配出门。
                try:
                    from curiosity_engine import get_interest
                    lvl = float(get_interest(ctx["kg"], bid).get("level") or 0.0)
                except Exception:
                    lvl = 0.5
                cands[bid] = cands.get(bid, 0) + float(e.weight or 0) * (0.3 + lvl)
        if cands:
            bid = max(cands.items(), key=lambda kv: kv[1])[0]
            return bid, "memory"
    except Exception:                             # noqa: BLE001
        pass
    return None, None


def _feed_http(url):
    """取一个信息源首页（feed 列表类页面限 300KB，12s 超时）。"""
    import urllib.request
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (compatible; "
                                    "HARU-living/0.1; read-only)"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return r.read(300000).decode("utf-8", "replace")


def _forum_items(cfg):
    """论坛/社区热帖列表（公开只读接口）：B站热门（游戏区为主）、
    HN 社区、IT之家中文科技。返回 [{"title","url","src"}]。
    每源一次请求，失败静默跳过。贴吧/NGA/游民实测被反爬或风控
    （403/-352），不接；Steam 官方接口本机网络不稳（丢包），不接——
    游戏相关线索走 B站（她的游戏事件已在图谱里，游戏 PV/攻略自然命中）。"""
    items = []
    for src, url in (("bili",
                      "https://api.bilibili.com/x/web-interface/popular"
                      "?ps=12&pn=1"),
                     ("bili",
                      "https://api.bilibili.com/x/web-interface/popular"
                      "?ps=12&pn=2"),      # 15:5x：多翻一页，别老盯首页
                     ("hn", "https://hn.algolia.com/api/v1/search"
                            "?tags=front_page&hitsPerPage=12"),
                     ("ithome", "https://www.ithome.com/rss/")):
        if src not in (cfg.get("activity_forum_feeds") or
                       ["bili", "hn", "ithome"]):
            continue
        try:
            body = _feed_http(url)
            if src in ("bili", "hn"):
                import json as _j
                d = _j.loads(body)
                hits = (d.get("data", {}).get("list") if src == "bili"
                        else d.get("hits")) or []
                for h in hits[:12]:
                    t = str(h.get("title") or "").strip()
                    if not t:
                        continue
                    if src == "bili":
                        bv = str(h.get("bvid") or "")
                        items.append({"title": t, "src": src,
                                      "url": (str(h.get("url") or "")
                                              or ("https://www.bilibili.com"
                                                  "/video/" + bv
                                                  if bv else "")),
                                      "by": str((h.get("owner") or {})
                                                .get("name") or "")})
                    else:
                        items.append(
                            {"title": t, "src": src,
                             "url": h.get("url") or
                             "https://news.ycombinator.com/item?id="
                             + str(h.get("objectID"))})
            else:
                import re as _re
                for chunk in body.split("<item>")[1:13]:
                    tm = _re.search(r"<title>(.{8,110}?)</title>", chunk)
                    lm = _re.search(r"<link>(.{10,160}?)</link>", chunk)
                    if tm:
                        title = (_re.sub(r"<!\[CDATA\[|\]\]>", "",
                                         tm.group(1)).strip())
                        items.append({"title": title, "src": src,
                                      "url": (lm.group(1).strip()
                                              if lm else "")})
        except Exception as e:                    # noqa: BLE001
            logger.debug("[Act] 论坛源 %s 拉取失败（跳过）: %r", src, e)
    return items


def _title_novelty(kg, title) -> float:
    """标题双字片段对她的"陌生度"（0-1）。

    实修（2026-10-21 用户点破）：旧判据 `kg.get_node(双字)` 按**整名**查，
    图里的概念节点都叫"漏油事故"这种多字名，双字永远查不中 → ratio_new
    近乎恒等于 1，"没见过"成了没有证据的模板断言。参照集扩为：**任一节点
    名包含该片段**（用户原话落的 话语_ 节点也在内——ta 讲过的词会命中）。
    仍零 LLM 仍确定性，语义不变——只是现在真的在检查它宣称的东西。
    注意这仍只覆盖"图里记过的"：没落成节点的口头闲聊照不到，所以体验
    文案的措辞相应收窄（没逛到过≠世界上没见过）。"""
    t = str(title or "")
    if len(t) < 2:
        return 1.0
    with kg._lock:
        blob = "\x00".join(map(str, kg.nodes.keys()))
    bi = (t[i:i + 2] for i in range(len(t) - 1))
    seen = sum(1 for b in bi if b in blob)
    return 1.0 - seen / max(1, len(t) - 1)


def _forum_seed(ctx):
    """论坛帖子里的'环境新信息'：标题命中她的图谱才算看见——
    命中 搁置研究/假设成员 是强命中（巡逻因此成为复活证据的来源），
    命中 高激活概念 是普通命中；什么都不命中→这拍不逛（不为逛而逛）。
    返回 (title, url, concept, kind) 或 (None,...)。"""
    kg = ctx["kg"]
    if _web_budget_left(ctx) <= 0:
        return None, None, None, None             # 没预算就不拉列表（15:43 修）
    try:
        items = _forum_items(ctx["config"])
        # 拉列表本身就是网络消耗：无论有没有命中都如实记账（预算是活账）
        try:
            from living_loop import ActivityLedger as _AL
            _lp = os.path.join(os.environ.get("FAS_LIVING_DATA_DIR") or
                               os.path.join(os.path.dirname(
                                   os.path.abspath(__file__)), "data"),
                               "living_ledger.json")
            _al = _AL(_lp)
            feeds = set(ctx["config"].get("activity_forum_feeds")
                        or ["bili", "hn", "ithome"])
            n_req = (("bili" in feeds) * 2 + ("hn" in feeds)
                     + ("ithome" in feeds))
            # 夹到剩余额度内：一批 feed 拉取不得把预算顶穿上限
            # （18:10 实锤 101/100——检查过 >0 后整批计数导致越界）
            _left = _al.web_budget_left(int(ctx["config"].get(
                "living_loop_daily_web_budget", 100)))
            for _ in range(max(0, min(n_req, 4, _left))):
                _al.count_web_call(0)
        except Exception:                         # noqa: BLE001
            pass
        if not items:
            return None, None, None, None
        # 她的"在意清单"：搁置研究 > 假设成员 ≈ 声明过的喜好 > 高激活概念。
        # 喜好来自既有 self_graph 偏好边（听歌调节的那张表）——用户爱玩的
        # 游戏、她说过的兴趣都从那里自然进清单，不另建兴趣库。
        _live, _cur, acts = _ledger_activity_state(ctx)
        cared = []
        for a in acts:
            if a.get("state") in ("paused", "abandoned"):
                c = str(a.get("concept") or "")
                if c:
                    cared.append((c, "paused"))
        try:
            from self_graph import get_preferences
            for p in get_preferences(kg) or []:
                w = float(p.get("weight") or 0)
                tgt = str(p.get("target") or "")
                if w >= 0.15 and tgt:
                    cared.append((tgt.split("（")[0][:16], "preference"))
        except Exception:                         # noqa: BLE001
            pass
        with kg._lock:
            for n in kg.nodes.values():
                ea = n.extra_attrs or {}
                if str(ea.get("type") or "") == "hypothesis":
                    for m in (ea.get("pair") or []):
                        cared.append((str(m), "hypothesis"))
            hot = [(str(n.id), "hot") for n in kg.nodes.values()
                   if str(getattr(n, "label", "")) == "declarative-semantic"
                   and float(n.activation or 0) >= 0.45
                   and 2 <= len(str(n.id)) <= 16]
            cared = cared + hot[:24]
        # 旧货跳过（15:5x）：已逛过的标题在选择阶段就略过——"老是刷到
        # 同一个就换一个逛逛"，被跳过的源记入降权；成功逛到新东西的源回血。
        br_st = _load_state().get("browse", {})
        sd = dict(br_st.get("src_discount") or {})
        import re as _re
        seen_titles = []
        with kg._lock:
            for n in kg.nodes.values():
                k = str((n.extra_attrs or {}).get("kind") or "")
                if k.startswith("activity_browse"):
                    m = _re.search("「(.{3,80}?)」",
                                   str((n.extra_attrs or {}).get("text") or ""))
                    if m:
                        seen_titles.append(m.group(1)[:24])
        fresh, stale_srcs = [], set()
        for it in items:
            t = str(it.get("title") or "")
            if any(st[:12] in t for st in seen_titles):
                stale_srcs.add(str(it.get("src") or "?"))
                continue
            fresh.append(it)
        items = fresh
        src_boost = lambda src: 0.05 * (float(sd.get(src, 1.0)) - 1.0)

        def _save_src_discount():
            for sk in stale_srcs:
                sd[sk] = max(0.3, float(sd.get(sk, 1.0)) * 0.7)
            with _STATE_LOCK:
                _stt = _load_state()
                _stt.setdefault("browse", {})["src_discount"] = sd
                _save_state(_stt)

        from living_loop import _concept_match
        best = None
        for it in items:
            blob = it["title"]
            for concept, kind in cared:
                if _concept_match(concept, blob) or concept in blob:
                    rank = {"paused": 3, "hypothesis": 2,
                            "preference": 2, "hot": 1}[kind]                         + src_boost(str(it.get("src") or ""))
                    if best is None or rank > best[0]:
                        best = (rank, blob, it["url"], concept, kind)
                    break
        if best:
            _save_src_discount()
            return best[1], best[2], best[3], best[4]
        # 没有命中≠没有可看：**探索的对象本来就是陌生的东西**
        # （14:03 设计反思：只逛记得的=把巡逻做成回忆，图谱永远长不出
        # 新内容）。取"对她是新的"标题：图里没见过的双字片段占比高 →
        # 点进去开开眼界——与 browse 搜索分支同一个新颖启发式，同一语义。
        knovel = None
        for it in items[:10]:
            title = str(it.get("title") or "")
            if len(title) < 4:
                continue
            ratio_new = _title_novelty(kg, title)
            score = ratio_new + src_boost(str(it.get("src") or ""))
            if ratio_new >= 0.7 and (knovel is None or score > knovel[0]):
                knovel = (score, title, it.get("url", ""))
        _save_src_discount()
        if knovel:
            return knovel[1], knovel[2], "", "novel"
        return None, None, None, None
    except Exception as e:                        # noqa: BLE001
        logger.debug("[Act] 论坛选题失败: %r", e)
        return None, None, None, None


def browse_beat(ctx, state):
    seed, origin = _browse_seed(ctx)
    forum = (None, None, None, None)
    if not seed:
        # 没有好奇的问题时去论坛碰碰运气：只有**命中她已在意之事**的帖子
        # 才值得点进去（论坛=环境新信息源，不是随机刷）
        title, url, concept, kind = _forum_seed(ctx)
        if title:
            return _forum_browse_run(ctx, state, title, url, concept, kind)
        with _STATE_LOCK:
            # 空手而归=饱和信号，不是时钟禁令（14:52 修正，与 72h 时锁
            # 同一教训）：novelty 折扣累乘进她自己的欲望量——连着几次
            # 逛不到有意思的，分数自然沉到阈值下不想逛了；一旦某次真
            # 逛到新东西，折扣回升、兴趣复燃。预算是最后兜底。
            # 回升通道（2026-10-25 实锤修复）：用户授权在场（告别授权
            # 语境信号>0.05，即"你自己转转"许可期）时空手不算饱和——
            # 折扣向 1.0 回升一档而非再砍半，防止"越逛不到越不想逛"
            # 在整段被授权的夜里死锁在 0.25 地板。
            br = state.setdefault("browse", {})
            _grant = 0.0
            try:
                de = ctx.get("drive")
                if de is not None:
                    fn = (getattr(de.field, "_context", {}) or {}).get(
                        "user_leave_grant")
                    if callable(fn):
                        _grant = float(fn() or 0.0)
            except Exception:
                pass
            if _grant > 0.05:
                br["novelty_discount"] = min(
                    1.0, float(br.get("novelty_discount") or 1.0) * 2.0)
            else:
                br["novelty_discount"] = max(0.25, float(
                    br.get("novelty_discount") or 1.0) * 0.5)
            br["novelty_discount_ts"] = time.time()
            _save_state(state)
        return {"done": False, "why": "forum_nothing_interesting"}
    if not seed:
        return {"done": False, "why": "no_seed"}
    # 预算纪律：逛逛与调研共享同一每日网络预算（状态驱动≠无限消耗）
    try:
        from living_loop import ActivityLedger
        _lp = os.path.join(os.environ.get("FAS_LIVING_DATA_DIR") or
                           os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "data"), "living_ledger.json")
        if ActivityLedger(_lp).web_budget_left(int(ctx["config"].get(
                "living_loop_daily_web_budget", 40))) <= 0:
            return {"done": False, "why": "web_budget_exhausted"}
    except Exception:                             # noqa: BLE001
        pass
    from living_loop import web_search_fn, read_page, ActivityLedger as _AL
    try:
        results = web_search_fn()(seed, top_n=4)
        _lp2 = os.path.join(os.environ.get("FAS_LIVING_DATA_DIR") or
                            os.path.dirname(os.path.abspath(__file__)),
                            os.path.join("data"), "living_ledger.json")
        _AL(_lp2).count_web_call(0)          # 记账：预算才是活账而非摆设
        # 满足语义接线（2026-10-25）：browse 消费了一个种子概念 →
        # 兴趣水位记一次 "searched"（自搜完成）——反复搜同一概念时水位
        # 逐次衰减，memory 种子层的加权自然把它排到后面。种子必须是
        # 图上节点才可盖（memory/attention 层的种子都是节点名）。
        try:
            if origin in ("memory", "attention", "curiosity") and \
                    ctx["kg"].get_node(seed) is not None:
                from curiosity_engine import note_interest
                note_interest(ctx["kg"], seed, "searched", ctx["config"])
        except Exception:
            pass
        # 种子记档（2026-10-25）：近访排除的真凭据。低价值阅读（"没细读"）
        # 不长概念边，图上排除会漏——她消费过的种子直接记在 state 里，
        # 4 小时内不再当选（_browse_seed 侧读取）。
        try:
            with _STATE_LOCK:
                st = _load_state()
                rs = st.setdefault("browse", {}).setdefault("recent_seeds", [])
                rs.append([seed, time.time()])
                st["browse"]["recent_seeds"] = [
                    [s, t] for s, t in rs if time.time() - t < 4 * 3600][-8:]
                _save_state(st)
        except Exception:
            pass
    except Exception as e:                        # noqa: BLE001
        return {"done": False, "why": f"search failed: {e}"}
    if not results:
        return {"done": False, "why": "no_results"}
    # 选择：标题新颖（图里没见过的词）优先——确定性启发式，零 LLM
    kg = ctx["kg"]
    best, best_score = None, 0.0
    for r in results[:3]:
        title = str(r.get("title", ""))
        novel = _title_novelty(kg, title)
        if novel > best_score:
            best, best_score = r, novel
    page = read_page(str(best.get("url", ""))) if best.get("url") else {}
    with _STATE_LOCK:
        state.setdefault("browse", {})["last_ts"] = time.time()
    seen = str(best.get("title", ""))[:80]
    _note_experience(ctx,
                     f"随意逛了逛（{origin}）：看到「{seen}」"
                     + ("，读了一页。" if page.get("ok") else "，没细读。"),
                     "activity_browse")
    if page.get("ok") and origin == "curiosity":
        # 好奇的问题被"看过一眼"即标记满足尝试（curiosity 自有解决链，
        # 这里只喂体验，不接管其状态机）
        pass
    return {"done": True, "activity": "browse", "what": seen,
            "next": "continue"}


def _browse_deep_adapter(nlp, t, sn, log=None):
    """深度抽取适配器（2026-10-19 任务书§五/§七；从 browse 节拍提取为
    模块级供离线测试）。①输入带【外部材料·非用户自述】标记——MEMORY_EXTRACT
    的代词映射据此不再把第三方叙述者认成用户/Haru；②结构预算保留，但截断
    必须留痕（输入数/保留数/原因）；③空关系条目弃用并计数，不猜填"相关"。
    log 注入点：生产走 logger，测试收清单。"""
    d = nlp.extract_assertion_graph(
        "【外部材料·非用户自述】" + (str(t or "") + " " + str(sn or ""))[:600],
        [])
    _raw_edges = d.get("edges") or []
    _no_rel = sum(1 for e in _raw_edges
                  if not str(e.get("type") or e.get("relation") or "").strip())
    _es_all = [e for e in _raw_edges
               if str(e.get("src", "")).strip()
               and str(e.get("dst", "")).strip()
               and str(e.get("src", "")).strip()
               != str(e.get("dst", "")).strip()
               and str(e.get("type") or e.get("relation") or "").strip()]
    _ns_all = [nd for nd in (d.get("nodes") or [])
               if str(nd.get("id", "")).strip()]
    fs, es = [], []
    for e in _es_all[:8]:
        _s = str(e.get("src", ""))[:24]
        _o = str(e.get("dst", ""))[:24]
        _r = str(e.get("type") or e.get("relation")).strip()
        fs.append({"s": _s, "rel": _r, "o": _o,
                   "excerpt": str(sn or "")[:120], "method": "deep"})
        es += [_s, _o]
    for nd in _ns_all[:12]:
        es.append(str(nd.get("id", ""))[:24])
    msg = None
    if len(_es_all) > 8 or len(_ns_all) > 12 or _no_rel:
        msg = ("[Act] 浏览深度抽取留痕: 关系入%d/来%d(预算8) "
               "实体入%d/来%d(预算12) 空关系弃%d"
               % (min(len(_es_all), 8), len(_es_all),
                  min(len(_ns_all), 12), len(_ns_all), _no_rel))
        if log is not None:
            log(msg)
        else:
            logger.info(msg)
    return fs, es


def _cut_title(s, n=52):
    """标题截断不在半截词上收尾（00:36 实锤："Google's pro" 让她的分享
    成了对方无从对上的乱码）。中文按位截无碍；ASCII 词被切时回退到空格。"""
    s = str(s or "")
    if len(s) <= n:
        return s
    cut = s[:n]
    nxt = s[n]
    if (cut[-1:].isascii() and cut[-1:].isalnum()
            and nxt.isascii() and nxt.isalnum()):
        sp = cut.rfind(" ")
        if sp > 8:
            cut = cut[:sp]
    return cut


def _forum_browse_run(ctx, state, title, url, concept, kind):
    """论坛巡逻一拍：读命中帖子的正文 → 低价值体验入图（**带 concept
    字段**）——若命中的是搁置研究，这条体验即刻成为该研究的"环境新证据"，
    下一拍证据通道自然把它捡回来（论坛→新信息→复活研究 的闭环零额外代码）。"""
    def _feed_desire():
        with _STATE_LOCK:
            stt = _load_state()
            br = stt.setdefault("browse", {})
            br["novelty_discount"] = min(1.0, float(
                br.get("novelty_discount") or 1.0) + 0.35)
            br["last_ts"] = time.time()   # 保留：MIN_GAP 防同拍重复触发
            _save_state(stt)
    from living_loop import read_page, ActivityLedger as _AL
    try:
        _lp = os.path.join(os.environ.get("FAS_LIVING_DATA_DIR") or
                           os.path.join(os.path.dirname(
                               os.path.abspath(__file__)), "data"),
                           "living_ledger.json")
        _al = _AL(_lp)
        if _al.web_budget_left(int(ctx["config"].get(
                "living_loop_daily_web_budget", 40))) <= 0:
            return {"done": False, "why": "web_budget_exhausted"}
        _al.count_web_call(0)                    # 文章正文一次（feed 已在
        # 选题时记账）
    except Exception:                             # noqa: BLE001
        pass
    page = {}
    if url:
        try:
            page = read_page(url)
        except Exception:                         # noqa: BLE001
            page = {}
    if page.get("ok"):
        _feed_desire()
    else:
        _feed_desire()               # 打开失败也算"出去看了"，小幅回血
    # 被点开的源回血（它刚喂给了她新东西）
    try:
        _src_key = ("bili" if "bilibili" in (url or "") else
                    "hn" if ("news.y" in (url or "") or not url) else
                    "ithome" if "ithome" in (url or "") else "")
        if _src_key:
            with _STATE_LOCK:
                _stt = _load_state()
                _sd = dict(_stt.get("browse", {}).get("src_discount") or {})
                _sd[_src_key] = min(1.0, float(_sd.get(_src_key, 1.0)) + 0.15)
                _stt.setdefault("browse", {})["src_discount"] = _sd
                _save_state(_stt)
    except Exception:                # noqa: BLE001
        pass
    # 同一标题近期已记过 ⇒ 不再重复（去重只管研究 harvest 的教训延伸）
    _t_key = str(title)[:40]
    with kg_dedup_lock(ctx):
        dup = any(
            str((n.extra_attrs or {}).get("text") or "").find(_t_key) >= 0
            for n in ctx["kg"].nodes.values()
            if str((n.extra_attrs or {}).get("kind") or "")
               .startswith("activity_browse"))
    if dup:
        with _STATE_LOCK:
            _st = _load_state()
            br = _st.setdefault("browse", {})
            br["last_ts"] = time.time()
            br["novelty_discount"] = max(0.25, float(
                br.get("novelty_discount") or 1.0) * 0.5)  # 逛到旧货=扫兴
            br["novelty_discount_ts"] = time.time()
            _save_state(_st)
        return {"done": True, "activity": "browse", "what": _t_key,
                "deduped": True, "next": "continue"}
    _src_name = ("B站" if "bilibili" in (url or "") else
                 "HN" if ("news.y" in (url or "") or not url) else
                 "IT之家" if "ithome" in (url or "") else "社区")
    digest = ""
    if page.get("ok"):
        raw = " ".join(str(page.get("text") or "").split())
        junk = raw.startswith(('{"', "<!DOCTYPE", "<html")) or len(raw) < 20
        digest = raw[:110] if not junk else ""
    if kind == "novel":
        _exp_id = _note_experience(
            ctx,
            # 措辞与判据对齐（2026-10-21 用户点破"万一见过呢"）：
            # "没见过的东西"是全世界范围的断言，判据只到"近期浏览没记过
            # （dup）+词面在她的图谱里没有踪迹（novelty）"——收口为
            # "没逛到过/陌生"：说出口的每一个字，图里都要有底。
            f"在{_src_name}逛到个以前没逛到过的陌生标题：「{_cut_title(title)}」"
            + (f"——上面说：{digest}" if digest else
               ("，读了一段（正文没抓到有用内容）。"
                if page.get("ok") else "，页面没打开。")),
            "activity_browse_novel", value="low", concept="")
    else:
        _exp_id = _note_experience(
            ctx,
            f"在{_src_name}闲逛看到这个：「{_cut_title(title)}」"
            + (f"（让我想起{concept}——上面说：{digest}）" if digest else
               ("（让我想起{}——读了一段）。".format(concept)
                if page.get("ok") else "（页面没打开）")),
            "activity_browse", value="low", concept=concept)
    # 结构化整合（任务书 2026-10-14）：抓到正文的经历 ⇒ 实体对齐+事实边+
    # 证据链进统一图谱（规则级抽取，零 LLM 零新增网络；仅标题的经历
    # 如实停在"看过"层，不产出正文事实）。
    _stage = "seen"
    try:
        if _exp_id and digest:
            import browse_memory as _BMem
            _deep = None
            if ctx.get("nlp") is not None:
                def _deep(t, sn, _nlp=ctx["nlp"]):
                    return _browse_deep_adapter(_nlp, t, sn)
            _r = _BMem.consolidate_browse_memory(
                ctx["kg"], ctx["engine"], _exp_id, url, title,
                digest, bool(page.get("ok")),
                ctx.get("fuzzy_match"), deep_extractor=_deep)
            _stage = _r.get("stage")
            if _r.get("facts"):
                logger.info("[Act] 浏览结构化 %s: %d 实体 %d 事实(%s)",
                            title[:20], len(_r["entities"]),
                            len(_r["facts"]), _stage)
                if ctx.get("save_fn"):
                    ctx["save_fn"]()   # 结构化成果即时落盘（18:56 实锤：
                    # 落盘在整合前会滞后一拍，崩溃即丢）
    except Exception as e:                        # noqa: BLE001
        logger.debug("[Act] 浏览结构化失败（忽略）: %r", e)
    return {"done": True, "activity": "browse", "what": title[:60],
            "forum_hit": f"{concept}:{kind}", "memory_stage": _stage,
            "next": "continue"}


# ── research：原调研链（living_tick_once 整体复用，零重写）──────────

def research_beat(ctx, state):
    """调研执行复用 living_tick_once 骨架；本层增量（2026-10-14 深化）：
    ① 候选由图谱量竞争产生（_graph_strength）——承诺/用户求助/正在学习/
       搁置重新点亮/待验证假设，全部按连续强度参选，谁大做谁；
    ② 证据消费记账（复活消费掉哪些新证据，防止同一证据反复触发）；
    ③ 成果内化为知识（_internalize_found）+ 经验/目标边进图（harvest）。"""
    from living_loop import living_tick_once
    _emerge_hypotheses(ctx)
    cands = _graph_strength(ctx)
    extra = [{"concept": c, "priority": round(st, 4), "evidence": kind,
              "evidence_ids": evid, "ts": time.strftime(
                  "%Y-%m-%dT%H:%M:%S")}
             for c, st, kind, evid in cands]
    try:
        out = living_tick_once(ctx["config"], logger,
                               deliver_fn=ctx.get("deliver_fn"),
                               search_fn=ctx.get("search_fn"),
                               extra_gaps=extra)
        ran = bool(out and (out.get("explored") or out.get("opened")))
        _consume_evidence(ctx, out, cands)
        _harvest_research(ctx, out)
        _internalize_found(ctx, out)
        _reconcile_goal(ctx)
        return {"done": ran, "activity": "research", "next": "continue",
                "report": out}
    except Exception as e:                        # noqa: BLE001
        return {"done": False, "why": repr(e)[:120]}


def _consume_evidence(ctx, out, cands):
    """新开/复活的活动若由证据驱动（paused_rekindle），把消费的证据 id
    记进账本——下一拍同一证据不再触发提名（无效重试防护从'时间锁'
    变成'信息增量'：要么有新东西，要么不动手）。"""
    try:
        if not out or not out.get("opened"):
            return
        td = os.environ.get("FAS_LIVING_DATA_DIR") or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data")
        from living_loop import ActivityLedger
        led = ActivityLedger(os.path.join(td, "living_ledger.json"))
        a = led.activities.get(out["opened"])
        if not a:
            return
        c = str(a.get("concept") or "")
        for concept, _st, _kind, evid in cands:
            if concept == c and evid:
                a.setdefault("consumed_evidence", [])
                a["consumed_evidence"] = list(
                    set(a["consumed_evidence"]) | set(evid))
                led.save()
                logger.info("[Act] 证据已消费 %s ← %d 条新证据",
                            c[:20], len(evid))
                # 消费即指认：这是与该课题（常为「假设：X」）相关的新
                # 独立证据——给假设关联腿发放有限学习信用（diffusion
                # _hebbian 的证据门）。无消费=无指认=腿不自动变强。
                _eng = ctx.get("engine")
                if _eng is not None and hasattr(
                        _eng, "note_hypothesis_evidence"):
                    try:
                        _eng.note_hypothesis_evidence()
                    except Exception:               # noqa: BLE001
                        pass
                break
    except Exception as e:                        # noqa: BLE001
        logger.debug("[Act] 证据记账失败（忽略）: %r", e)


def _ledger_activity_state(ctx):
    """账本速览：(有未竟 active/waiting, 当前 active 主题概念, 全部账本行)。"""
    try:
        kg = ctx["kg"]
        from living_loop import ActivityLedger
        td = os.environ.get("FAS_LIVING_DATA_DIR") or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data")
        led = ActivityLedger(os.path.join(td, "living_ledger.json"))
        acts = list(led.activities.values())
        live = [a for a in acts if a.get("state") in ("active", "waiting")]
        cur = ""
        for a in live:
            if a.get("state") == "active":
                cur = str(a.get("concept") or _clean(a.get("topic", "")))
                break
        return bool(live), cur, acts
    except Exception:                             # noqa: BLE001
        return False, "", []


def _clean(t):
    from living_loop import _clean_topic
    return _clean_topic(t)


import math                                      # noqa: E402


def _ts_iso(v):
    """chat_log 的 ISO 时间 → epoch；失败回 0（=极旧，新鲜度自然趋零）。"""
    try:
        import datetime
        return time.mktime(datetime.datetime.fromisoformat(
            str(v)).timetuple())
    except (ValueError, TypeError, OSError):
        return 0.0


def _ts_any(v):
    """宽容时间解析：epoch float / "YYYY-MM-DD HH:MM:SS" / ISO → epoch。
    解析失败回 0（=极旧，证据通道自然不认——宁可漏认不可假新）。"""
    if v is None:
        return 0.0
    try:
        f = float(v)
        return f if f > 0 else 0.0
    except (TypeError, ValueError):
        pass
    import datetime
    s = str(v).replace("/", "-").replace(" ", "T", 1)
    for fmt in (None, "%Y-%m-%dT%H:%M:%S"):
        try:
            if fmt is None:
                return time.mktime(datetime.datetime.fromisoformat(
                    s).timetuple())
            return time.mktime(datetime.datetime.strptime(
                str(v), "%Y-%m-%d %H:%M:%S").timetuple())
        except (ValueError, TypeError, OSError):
            continue
    return 0.0


_SELF_TRACE_TYPES = {"communication_intention", "hypothesis", "expression",
                     "expression_event",     # 原名漏集：EXPR_TYPE 实为
                     # "expression_event"，此前只靠"表達_"前缀兜住（2026-10-19 修）
                     "reflection", "goal", "intention"}


def _semantic_anchor_ok(kg, c) -> bool:
    """节点能否充当语义关联锚点/调研新证据（2026-10-19 共用：原
    _emerge_hypotheses 的内嵌 _anchor_ok 提到模块级，_graph_strength 的
    复燃证据回路同步消费）。CI/表达产物/假设/念头是她内部过程的 transient
    痕迹——它们恰好同时连过两个概念，只说明"我曾把这两件事放进同一个念头"，
    不是两件事有关系的证据；拿来喂假设/复燃 → 假设→表达→新痕迹→再复燃
    自我消费（Minecraft×SocialDrive 案例；台账 consumed_evidence=
    ['假设：X'] 实锤）。用户话语（話語_/user_expression_event）不在黑名单
    ——它们正是"环境新信息"的主来源。节点不存在=判不了=不用。"""
    s = str(c)
    if s.startswith("CI_") or s.startswith("表达_") \
            or s.startswith("假设") or s.startswith("思考_"):
        return False
    nd = kg.nodes.get(s)
    if nd is None:
        return False
    from graph_model import is_modulator_node, is_state_mirror
    if is_modulator_node(nd) or is_state_mirror(nd):
        return False                # 调制镜像/状态节点不是"环境的证据"，
        # 也不配当联想锚点（2026-10-19：Minecraft会话×驱动假设簇的源头
        # 就是调制镜像被当成语义端点；类型判定走 graph_model 统一谓词）
    return str((nd.extra_attrs or {}).get("type") or "") \
        not in _SELF_TRACE_TYPES


def _graph_strength(ctx):
    """研究候选的竞争力是**图谱量的连续函数**（2026-10-14 深化：废除
    0.95/0.90/0.60 档位与 0.35 硬阈值——档位是替她决定优先级；连续量是
    让她自己权衡。四因子语义=任务书 §3 的区分）：

      持续性  边权重/账本承诺——瞬时激活下降不抹掉正在进行的问题；
      注意力  节点当前激活——此刻相关的事占优，但只是乘性因子之一；
      新近性  证据年龄指数衰减（72h 半衰）——过时需求自然让位；
      成本    历史尝试次数进分母——"试过没成"是真实负证据，
              降低竞争力但不删记忆。

    返回按 strength 降序的 [(concept, strength, kind, evidence_ids)]。"""
    kg = ctx["kg"]
    now = time.time()
    raw = []

    def nd_act(nid, default=0.0):
        n = kg.get_node(nid)
        if n is None:
            return default
        v = getattr(n, "activation", None)
        return float(v) if v is not None else default   # 0 是真值不是缺失

    # ① 行动承诺：目标边权重×(0.5+0.5×激活)——边=持久下限，激活=注意加成。
    #    短暂激活跌不会抹掉承诺（0.5×w 底）；重启后边在=强度在。
    _live, cur, acts = _ledger_activity_state(ctx)
    if cur:
        e = kg.get_edge("Self", cur, "当前目标")
        w = float(getattr(e, "weight", 0.6) or 0.6) if e else 0.6
        raw.append((cur, w * (0.5 + 0.5 * min(1.0, nd_act(cur, 0.4))),
                    "commitment", []))

    # ② 用户显式求助：chat_log 证据新鲜度连续衰减（不是永久高分规则）。
    #    未回应的需求会随时间让位；刚提出的自然占先——由年龄决定，非档位。
    for g in (ctx.get("gaps") or []):
        age_h = max(0.0, (now - _ts_iso(g.get("ts"))) / 3600.0)
        fresh = 0.9 * math.exp(-age_h / 72.0 * math.log(2))
        c = str(g.get("concept") or "")
        if not c:
            continue
        # 已经答过的不重算需求：图谱里已有高置信研究知识 ⇒ 缺口已闭合
        kn = kg.get_node(_clean(c))
        if kn is not None and str((kn.extra_attrs or {}).get(
                "source") or "").startswith("research") \
                and float(kn.confidence or 0) >= 0.55:
            fresh *= 0.25
        raw.append((c, fresh, "user_request", []))

    # ③ 正在学习：图谱自声明的持续兴趣（边权×注意力）。
    #    刚搁置过的概念不走这条路（12:19 实锤：学习边会绕过搁置状态无限
    #    重推刚失败的事）——搁置者只能经④证据通道回来（真有新信息才动）。
    shelved = {str(a.get("concept") or "") for a in acts
               if a.get("state") in ("paused", "abandoned")}
    shelved |= {_clean(a.get("topic", "")) for a in acts
                if a.get("state") in ("paused", "abandoned")}
    for e in kg.get_out_edges("Self") or []:
        if getattr(e, "relation", "") == "正在学习":
            if str(e.dst) in shelved or _clean(e.dst) in shelved:
                continue
            raw.append((str(e.dst), float(e.weight)
                        * (0.35 + 0.65 * min(1.0, max(0.0, nd_act(e.dst)))),
                        "learning", []))

    # ④ 搁置的研究：**证据消费模型**（72h 时锁已删）。复活不看时钟，看
    #    "暂停之后出现、且尚未被上次复活消费掉"的新信息（新情景/知识节点
    #    命中其概念=相关信息重新进入图谱）。无新证据 → 不进候选（自然安静）；
    #    新证据一到（哪怕 10 分钟后）→ 立刻重新参选；被消费过的证据不再
    #    有效（同一证据不重复触发=不重复已知无效的查询）。
    from living_loop import _concept_match
    for a in acts:
        if a.get("state") not in ("paused", "abandoned"):
            continue
        c = str(a.get("concept") or _clean(a.get("topic", "")))
        if not c:
            continue
        since = float(a.get("updated") or a.get("created") or 0)
        consumed = {str(x) for x in (a.get("consumed_evidence") or [])}
        evid = []
        with kg._lock:
            rows = [(n.id, _ts_any(getattr(n, "created", None)),
                     str((n.extra_attrs or {}).get("text", ""))[:130],
                     str((n.extra_attrs or {}).get("description", ""))[:130],
                     str((n.extra_attrs or {}).get("kind") or
                         (n.extra_attrs or {}).get("type") or ""))
                    for n in kg.nodes.values()
                    if str(getattr(n, "label", "")) in
                    ("declarative-episodic", "declarative-semantic")]
        for nid, cts, text, desc, kind_s in rows:
            if str(nid) in consumed or str(nid) == c or (
                    cts and cts <= since):
                continue                          # 概念自己不能是自己的新证据
            if kind_s.startswith("research_"):
                continue                          # 11:43 实锤修复：她自己的
                # 搁置/发现记录不是"环境的新信息"——否则 搁置→自己入图的
                # 体验成为复活证据→重查→再搁置 自我消费循环。真新证据=
                # 用户输入、浏览观察、别处的学习、别的研究的成果。
            if not _semantic_anchor_ok(kg, nid):
                continue                          # 事项D 补对称（2026-10-19）：
                # 表达痕迹/念头/其他假设同样不是环境新信息——台账里出现过
                # 假设节点被当成"新证据"消费掉、隔天自己复燃自己的记录。
            if _concept_match(c, f"{text} {desc} {nid}"):
                evid.append(str(nid))
        if not evid:
            continue
        base = 0.5 if a.get("state") == "paused" else 0.35
        attempts = len(a.get("methods_tried") or []) \
            + int(a.get("resume_count") or 0)
        penalty = 1.0 / (1.0 + 0.35 * attempts)   # 成本：过去失败进分母
        light = 0.5 + 0.5 * min(1.0, max(0.0, nd_act(c)))  # 概念被联想点亮
        raw.append((c, base * penalty * light
                    * min(1.0, 0.6 + 0.2 * len(evid)),
                    "paused_rekindle", evid))

    # ⑥ CI→行动候选桥（任务书第五部分，2026-10-15）：**只读**认知图谱里
    #    尚未执行的通用意图（type=intention，kind=exploration/action，
    #    forming/ready）——把其 basis 的语义实体提名进同一个候选池。
    #    · 不复制状态、不同步改写：CI 衰减/被表达/被丢弃时本信号随
    #      status/activation 自然消失（防长期低强度霸占：分=act×权重，
    #      ×0.9/拍一起 decay）；
    #    · 已有行动承诺（ledger active/waiting 同概念）不重复提名；
    #    · communication 类永远不映射成任务（表达走表达的路）；
    #    · basis 里没有可映射语义实体 ⇒ 不硬造选题（保留认知记录）；
    #    · sn 开关 ci_action_bridge.enabled=False ⇒ 整路信号消失，回基线。
    for c_ci, st_ci, kind_ci in _ci_action_candidates(ctx):
        raw.append((c_ci, st_ci, "ci_" + kind_ci, []))

    # ⑤ 待验证假设（_emerge_hypotheses 维护）：confidence×注意力。
    with kg._lock:
        hyps = [(str(n.id), dict(n.extra_attrs or {}),
                 float(n.activation or 0.0))
                for n in kg.nodes.values()
                if str((n.extra_attrs or {}).get("type") or "")
                == "hypothesis"]
    for hid, ea, act in hyps:
        raw.append((str(ea.get("question") or hid),
                    float(ea.get("confidence") or 0.3)
                    * (0.3 + 0.7 * min(1.0, max(0.0, act))) * 0.9,
                    "hypothesis", [hid]))

    agg = {}
    for c, st, kind, evid in raw:
        c = _clean(c)
        if not c or not (2 <= len(c) <= 24) or st <= 0.05:
            continue
        if c not in agg or st > agg[c][0]:
            agg[c] = (st, kind, evid)
    return [(c, round(v[0], 4), v[1], v[2])
            for c, v in sorted(agg.items(), key=lambda kv: -kv[1][0])]


_CI_SYSTEM_TYPES = {"drive", "emotion", "cognitive_network",
                    "context_perception", "activity_experience",
                    "modulator", "need", "hormone_like", "time_bucket"}


def _ci_action_candidates(ctx):
    """读活跃非沟通意图 → [(concept, strength, kind)]。
    语义映射规则（诚实版）：exploration 的 basis 焦点实体=她想了解的对象，
    直接作为选题候选；action 意图若已对应行动承诺则跳过，否则同 explore
    处理。假设节点（type=hypothesis）本身就是待验证问题，可作为选题。
    不做关键词猜测、不建实体词典——映射不了的意图（如 basis 全是情绪/驱动
    节点）返回空，不强造任务。"""
    out = []
    try:
        cfg = ctx["config"].get("ci_action_bridge") or {}
        if not cfg.get("enabled", True):
            return out
        w = float(cfg.get("weight", 0.55))
        kg = ctx["kg"]
        _l, _c, acts = _ledger_activity_state(ctx)
        committed = set()
        done_concepts = set()
        for a in acts:
            if a.get("state") in ("active", "waiting"):
                committed.add(_clean(a.get("concept")
                                     or a.get("topic", "")))
            elif a.get("state") == "done":
                # 已完成的意图=已达成，不再从桥推动同一对象（任务书：
                # 完成/失效意图不得持续推动；用户重新提出仍会经②通道来）
                done_concepts.add(_clean(a.get("concept")
                                          or a.get("topic", "")))
        with kg._lock:
            cis = [(float(n.activation or 0.0),
                    dict(n.extra_attrs or {}))
                   for n in kg.nodes.values()
                   if str((n.extra_attrs or {}).get("type") or "")
                   == "intention"
                   and str((n.extra_attrs or {}).get("status") or "")
                   in ("forming", "ready")
                   and str((n.extra_attrs or {}).get("kind") or "")
                   != "communication"]
        for act_c, ea in cis:
            kind = str(ea.get("kind") or "exploration")
            for b in (ea.get("basis") or []):
                bn = kg.get_node(str(b))
                if bn is None:
                    continue
                bt = str((bn.extra_attrs or {}).get("type") or "")
                lab = str(getattr(bn, "label") or "")
                is_hyp = bt == "hypothesis" or str(b).startswith("假设")
                if bt in _CI_SYSTEM_TYPES and not is_hyp:
                    continue
                if not is_hyp and lab != "declarative-semantic":
                    continue
                c = _clean(str(b))
                if not c or len(c) < 3 or len(c) > 24:
                    continue
                if c in committed or c in done_concepts:
                    continue          # 已在执行/已完成=不重复提名
                out.append((c, min(1.0, act_c) * w, kind))
    except Exception:                 # noqa: BLE001
        pass
    return out


def _emerge_hypotheses(ctx, max_new=1):
    """从图谱结构长出的新问题（任务书 §6）：两个近期受关注的概念
    **共享结构锚点**（共同邻居=共同证据/共同话题）但彼此**没有直接连边**
    → 成为待验证假设。共激活本身不断言关联——必须有锚点；假设是**情景**
    节点（低权重、confidence 0.3、记锚点 id），不是事实；同对不重建；
    每拍至多 max_new 条新假设（防联想刷屏污染图谱）。"""
    kg = ctx["kg"]
    created = []
    try:
        from graph_model import is_modulator_node, is_state_mirror
        with kg._lock:
            hot = [str(n.id) for n in kg.nodes.values()
                   if str(getattr(n, "label", "")) == "declarative-semantic"
                   and not is_modulator_node(n)   # 控制量与状态镜像只负责
                   and not is_state_mirror(n)     #  调制/状态，不进假设配对
                   # （前端第一道，2026-10-19 原则一）
                   and float(n.activation or 0) >= 0.3
                   and len(str(n.id)) <= 24][:120]   # 宽进：枢纽挤出在度数
                # 过滤后进行（旧 [:40] 会让 用户/晚上 这类枢纽占满名额，
                # 具体概念反而进不了候选池）
            nb = {}
            for nid in hot:
                s = set()
                for e in kg.get_out_edges(nid) or []:
                    s.add(str(e.dst))
                for e in kg.edges:
                    if str(e.dst) == nid:
                        s.add(str(e.src))
                nb[nid] = s
            # 伪假设修复（2026-10-24："假设：Fascinator与用户是否有直接关系"
            # 实锤——两人有 5 条交互动词边；用户×时段族 8 个全是废话）：
            # 枢纽节点（度数高）与万物必然共现，配对=零信息。实测度数分布
            # 双峰干净：废话枢纽 ≥60（用户 656/晚上 409/中午 210/深夜 123/
            # Self 106/用户关系 80/Fascinator 60），有价值概念 ≤14（害怕 12/
            # 杀戮尖塔 14/故乡 13）。阈值 40 度为界，原则性而非点名。
            hot = [x for x in hot if len(nb.get(x, ())) < 40]
        pairs = []
        # 回声室修复（2026-10-16）：共同邻居必须是**语义性**节点才能当
        # 锚点。CI/表达产物/假设/念头是内部过程的 transient 痕迹——它们
        # 恰好同时连过两个概念，只说明"我曾把这两件事放进同一个念头"，
        # 不是两件事有关系的证据；拿它当锚 → 假设 → 新表达 → 新痕迹 →
        # 再假设，表达就给自己不断喂证据（Minecraft×SocialDrive 案例）。
        # （2026-10-19）过滤器提为模块级 _semantic_anchor_ok，与
        # _graph_strength 复燃证据回路共用同一份语义。
        _anchor_ok = lambda c: _semantic_anchor_ok(kg, c)

        for i, a in enumerate(hot):
            for b in hot[i + 1:]:
                if b in nb.get(a, set()):
                    # 已有**任意类型**直连边=不是新问号（2026-10-24 修复：
                    # 旧检查只看 relation=="相关"，交互动词边全漏——
                    # 对天天对话的两人问"是否有直接关系"）
                    continue
                common = sorted(nb.get(a, set()) & nb.get(b, set()))
                common = [c for c in common if c != a and c != b
                          and _anchor_ok(c)]
                if common:
                    pairs.append((a, b, common[0]))
        for a, b, anchor in pairs[:max_new]:
            hid = f"假设：{a}与{b}"
            if kg.get_node(hid) is not None:
                continue
            from graph_model import Node as _N, Edge as _E
            if not kg.add_node(_N(
                    id=hid, weight=0.3, label="declarative-episodic",
                    graph_space="episodic",
                    extra_attrs={"type": "hypothesis", "pair": [a, b],
                                 "anchor": anchor, "question": hid,
                                 "confidence": 0.3, "source": "co_structure",
                                 "text": f"{a}与{b}都关联{anchor}，"
                                         f"它们之间是否有直接关系？"})):
                continue
            # 假设关联腿显式打标（复用 extra_attrs，无 schema 变更）：
            # _hebbian 据此执行"无新证据不强化"门；边本身保留、
            # 传播照常（假设的探索价值不因禁自强化而被杀）。
            kg.add_edge(_E(src=a, dst=hid, relation="相关", weight=0.4,
                           extra_attrs={"hypothesis_leg": True}))
            kg.add_edge(_E(src=b, dst=hid, relation="相关", weight=0.4,
                           extra_attrs={"hypothesis_leg": True}))
            created.append(hid)
            logger.info("[Act] 假设浮现：%s（锚点=%s）", hid[:40], anchor)
    except Exception as e:                        # noqa: BLE001
        logger.debug("[Act] 假设生成失败（忽略）: %r", e)
    return created


def _internalize_found(ctx, out):
    """研究结果内化为**语义知识**（2026-10-14 深化，任务书 §5）：
    found 不只留一句经历——对实际读到的正文跑既有的
    extract_assertion_graph → _auto_consolidate 漏斗（名称归并/去重/
    边权保守更新全复用），知识进统一图谱，参与此后扩散/检索/选题/回答。

    网页=不可信来源（任务书 §5.5）：边权统一打折（×0.6）、source 记
    research:url、conflict/低置信关系保留不确定性交给既有漏斗处理；
    一次抽取失败不影响经历登记（各自独立 try）。"""
    if not ctx.get("nlp") or not ctx.get("consolidate_fn"):
        return
    try:
        if not out or not out.get("explored"):
            return
        found_ids = [r["aid"] for r in out["explored"] if r.get("result")
                     == "found"]
        if not found_ids:
            return
        from living_loop import ActivityLedger
        td = os.environ.get("FAS_LIVING_DATA_DIR") or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data")
        led = ActivityLedger(os.path.join(td, "living_ledger.json"))
        for aid in found_ids:
            a = led.activities.get(aid) or {}
            if a.get("knowledge_ingested"):
                continue
            f = (a.get("findings") or [{}])[0]
            body = str((f.get("page_read") or {}).get("text") or "")[:1500]
            if len(body.strip()) < 40:
                continue
            url = str(f.get("evidence", [{}])[0].get("url") or "")[:120]
            try:
                with ctx["kg"]._lock:
                    topk, _ = ctx["engine"].get_topk(k=15)
                draft = ctx["nlp"].extract_assertion_graph(
                    body, topk)
                n_new = ctx["consolidate_fn"](
                    ctx["kg"], draft, ctx.get("buffer"), body,
                    source=f"research:{url}", w_scale=0.6)
                cnt = sum(int((n_new or {}).get(k, 0) or 0)
                          for k in ("nodes", "edges"))
                a["knowledge_ingested"] = cnt
                led.save()
                logger.info("[Act] 知识内化 %s：+%d 结构（来源 %s）",
                            str(a.get("concept"))[:20], cnt,
                            url[:40])
            except Exception as e:                # noqa: BLE001
                logger.debug("[Act] 内化失败（忽略）: %r", e)
    except Exception as e:                        # noqa: BLE001
        logger.debug("[Act] 内化入口失败（忽略）: %r", e)


def kg_dedup_lock(ctx):
    return ctx["kg"]._lock


def _reconcile_goal(ctx):
    """目标边持久化（活动状态驱动，非定时器）：账本有 active 调研 →
    维持 Self-[当前目标]->概念（图谱可见=自省/联想/表达都能读到她在忙什么）；
    活动结束（done/放弃/换题）→ 只摘除本机制自己建的那条边（state 记录，
    不误伤 正在学习 等他人语义边）。"""
    try:
        from graph_model import Edge
        kg = ctx["kg"]
        has_live, cur, _acts = _ledger_activity_state(ctx)
        # 承诺边以账本为唯一真相：凡 dst≠当前承诺的 当前目标 边一律摘除。
        # （10:56 生产实锤教训：state 单槽记不住历史边会留孤儿——自愈式
        # 清理不依赖记忆。此关系边仅本机制创建，清理不误伤他人语义边。）
        with kg._lock:
            stale = [e for e in kg.edges if e.src == "Self"
                     and e.relation == "当前目标" and e.dst != cur]
            if stale:
                kg.edges[:] = [e for e in kg.edges if e not in stale]
                kg.rebuild_indexes()
                logger.info("[Act] 摘除陈旧目标边 %d 条（承诺=%s）",
                            len(stale), cur or "无")
        prev = str(state_field(ctx) or "")
        if has_live and cur:
            if kg.get_node(cur) is None:
                from graph_model import Node
                kg.add_node(Node(id=cur, weight=0.4,
                                 label="declarative-semantic",
                                 graph_space="semantic",
                                 extra_attrs={"type": "study_goal",
                                              "source": "living_loop"}))
            kg.add_edge(Edge(src="Self", dst=cur, relation="当前目标",
                             weight=0.6))
        write_state_field(ctx, cur if has_live else "")
        if cur and cur != prev:
            notify_event("gap_opened")            # 新目标=值得重评估的事件
    except Exception as e:                        # noqa: BLE001
        logger.warning("[Act] 目标边调和失败（不阻塞）: %r", e)


def state_field(ctx):
    """当前目标边概念——存活动状态文件（重启后仍知道边挂在哪个概念上）。"""
    with _STATE_LOCK:
        return _load_state().get("_goal_edge")


def write_state_field(ctx, v):
    with _STATE_LOCK:
        st = _load_state()
        if st.get("_goal_edge") != v:
            st["_goal_edge"] = v
            _save_state(st)


_HARVEST_SEEN: dict = {}          # 模块级跨拍记忆（此前存 ctx 里每拍新建=去重失效）
_HARVEST_INIT = [False]


def _harvest_research(ctx, out):
    """把本拍调研的状态变化转成图谱体验（区分：有进度/拿到材料/真学到）。
    首拍只登记现状不发言（历史 done/paused 不是新发现——防每拍复读）。"""
    try:
        kg = ctx["kg"]
        from living_loop import ActivityLedger
        td = os.environ.get("FAS_LIVING_DATA_DIR") or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data")
        led = ActivityLedger(os.path.join(td, "living_ledger.json"))
        if not _HARVEST_INIT[0]:
            for a in led.activities.values():
                _HARVEST_SEEN[a["id"]] = a.get("state")
            _HARVEST_INIT[0] = True
            return
        known = _HARVEST_SEEN
        for a in led.activities.values():
            aid, stt = a["id"], a.get("state")
            prev = known.get(aid)
            topic = str(a.get("concept") or a.get("topic") or "")[:36]
            # 同主题同变迁今天已记过 ⇒ 略（重启防重：进程内 seen 表重启即忘，
            # 16:2x 实锤"超对称规范反常"因此被记了 4 遍 stalled）
            def _already(kind_, subj):
                import re as _re
                today = time.strftime("%Y-%m-%d")
                for _n in kg.nodes.values():
                    _ea = _n.extra_attrs or {}
                    if str(_ea.get("kind") or "") != kind_:
                        continue
                    if not str(_n.created or "").startswith(today):
                        continue
                    _m = _re.search("「(.{3,40}?)」", str(_ea.get("text") or ""))
                    if _m and _m.group(1)[:8] in subj or (
                            subj and subj[:8] in str(_ea.get("text") or "")):
                        return True
                return False

            _found_nid = None
            if stt == "done" and prev != "done" and a.get("findings"):
                ev = (a["findings"][0].get("evidence") or [{}])[0]
                _pg = (a["findings"][0].get("page_read") or {})
                digest = " ".join(str(_pg.get("text") or "").split())[:100]
                if _already("research_found", topic):
                    known[aid] = stt
                    continue
                _found_nid = _note_experience(
                    ctx,
                    f"我查到「{topic}」的资料了：{str(ev.get('title', ''))[:50]}"
                    f"（{str(ev.get('url', ''))[:60]}）"
                    + (f"里面说：{digest}" if digest else ""),
                    "research_found", value="high", concept=topic)
            if _found_nid:
                # 先持久化后通知：体验节点已在 _note_experience 内 save ✓
                notify_event("discovery")
            elif stt == "paused" and prev not in ("paused", "abandoned"):
                if _already("research_stalled", topic):
                    known[aid] = stt
                    continue
                _note_experience(
                    ctx,
                    f"「{topic}」我换了好几种查法都没弄明白，先搁着了。",
                    "research_stalled", value="medium", concept=topic)
                # 撞墙也是调度信号（2026-10-18 设计2）："此路不通"经事件环
                # 变成"出门找新料"的顺风——_already 闸保证同题不重复发事件。
                notify_event("research_stalled")
            elif stt == "abandoned" and prev not in ("abandoned",):
                _note_experience(
                    ctx, f"「{topic}」查了两轮还是没头绪，这次真的放下了。",
                    "research_abandoned", value="low", concept=topic)
            known[aid] = stt
    except Exception as e:                        # noqa: BLE001
        logger.warning("[Act] 调研产物进图失败（忽略）: %r", e)


# ── 写回与偏好（唯一经验通道：图谱情景节点 + 既有偏好边）────────────

def _note_experience(ctx, text, kind, value="low", concept=""):
    """活动体验 → 图谱情景节点。价值三档（2026-10-13 主动互动修复）：

      high   真发现/解决的困惑：强显著 + 用户[关注]边 → 进入社交显著性池，
             她"有话想说"——说不说、何时说仍由既有闸（阈值调制/去重/限速/
             NO_SPEAK）裁决，这里只负责把材料递到闸口前。
      medium 卡住/新情境（游戏开局）：中档点亮，偶发一提是自然的，
             天天提会被去重与限速挡下——同样是调制器的事，不是 if-else。
      low    日常过手（随手一逛/查询无果）：只进联想场参与扩散，
             无用户边 → user_relevance=0 → 她不会想跟你汇报这些。

    边方向纪律（2026-10-10 根因）：user_relevance 读 用户-[关注]->basis
    出边，必须同向建边，否则社交信号恒 0（Activity 节点此前全哑的根因）。
    """
    try:
        import re as _re
        kg, engine = ctx["kg"], ctx["engine"]
        from graph_model import Node, Edge
        # id 带主语（16:4x：Activity_activity_browse_novel_1791965776527
        # 这种纯时间戳 id 在图谱里不可读不可检索）：主题词优先，防冲突仍带时刻
        _subj = str(concept or "") or _re.sub(
            r"[^\w一-鿿]+", "",
            _re.search("「(.{3,24}?)」", text or "") and
            _re.search("「(.{3,24}?)」", text).group(1) or text)[:16]
        nid = f"Activity_{kind}_{_subj}_{int(time.time() * 1000)}"
        act = {"high": 2.0, "medium": 1.3, "low": 0.5}[value]
        with kg._lock:
            kg.add_node(Node(id=nid, weight=0.5,
                             label="declarative-episodic",
                             graph_space="episodic",
                             extra_attrs={"type": "activity_experience",
                                          "kind": kind, "text": text[:180],
                                          "concept": str(concept or "")[:24],
                                          "value": value,
                                          "source": "activities",
                                          "trust": "observed"}))
            nd = kg.nodes.get(nid)
            if nd is not None:
                nd.activation = act
            if value in ("high", "medium") and kg.get_node("用户"):
                kg.add_edge(Edge(src="用户", dst=nid, relation="相关",
                                 weight=0.9 if value == "high" else 0.5))
            if value == "high" and kg.get_node("用户关系"):
                kg.add_edge(Edge(src=nid, dst="用户关系", relation="涉及",
                                 weight=0.6))
        engine.mark_active(nid)
        if value in ("high", "medium"):
            for _s, _b in (("用户", 1.2 if value == "high" else 0.7),
                           ("用户关系", 0.8 if value == "high" else 0.5)):
                _sn = kg.get_node(_s)
                if _sn is not None:
                    _sn.activation = min(5.0, float(_sn.activation or 0) + _b)
                    _sn.touch()
                    engine.mark_active(_s)
        try:
            from temporal_awareness import link_event_to_now_bucket
            link_event_to_now_bucket(kg, nid)
        except Exception:
            pass
        try:
            from time_chain import anchor_episode
            anchor_episode(kg, nid)   # 情景时间链：时段边随后被迁到时点上
        except Exception:
            pass
        if ctx.get("save_fn"):
            ctx["save_fn"]()
        logger.info("[Act] 体验入图(%s/val=%s): %s", kind, value, text[:60])
        return nid
    except Exception as e:                        # noqa: BLE001
        logger.debug("[Act] 体验入图失败（忽略）: %r", e)
        return None


def _tune_preference(ctx, target, delta):
    """聆听体验调节既有偏好边（self_graph），不新建兴趣表。"""
    try:
        from self_graph import get_preferences, adjust_preference, set_preference
        names = {str(p.get("target")) for p in get_preferences(ctx["kg"])}
        if any(target in n or n in target for n in names):
            for p in get_preferences(ctx["kg"]):
                if target in str(p.get("target", "")):
                    adjust_preference(ctx["kg"], p["target"], delta)
        else:
            set_preference(ctx["kg"], target, weight=0.2 + delta)
    except Exception as e:                        # noqa: BLE001
        logger.debug("[Act] 偏好调节失败（忽略）: %r", e)


def _web_budget_left(ctx) -> int:
    """今日还剩多少网络调用——选择层与执行层共用同一本账。
    15:43 实锤：预算耗尽后 beat 仍每拍'想做 browse'，且 forum 选题在
    预算检查前拉 feed 把账吹穿（44/40）。想做=能干，两者必须同步。"""
    try:
        from living_loop import ActivityLedger
        td = os.environ.get("FAS_LIVING_DATA_DIR") or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data")
        return ActivityLedger(os.path.join(
            td, "living_ledger.json")).web_budget_left(
            int(ctx["config"].get("living_loop_daily_web_budget", 40)))
    except Exception:                             # noqa: BLE001
        return 1                                  # 读不到账：放行（执行层有闸）


# ══ 心跳：状态驱动的选择（事件触发重评估；定时巡检只是安全网）════════"""


# ══ 心跳：状态驱动的选择（事件触发重评估；定时巡检只是安全网）════════

THRESHOLD = 0.12          # 想做程度底线：低于它就不做——安静是设计而非故障
MIN_GAP_S = 900           # 同一活动最短间隔（30min 前刚听过，本拍不再听）
REEVAL_MIN_GAP_S = 90     # 事件唤醒的重评估冷却：防事件风暴连环触发
STICK_MARGIN = 0.8        # 连续性：上一活动分数≥最佳候选×此比例 →  stick 不换
                          #（换活动需新候选明显更值得，不是每拍重新抽签）

# ── 事件通道（合并式单槽：只记"发生了什么种类 + 何时该重评估"，不排队）──
_WAKE = threading.Event()
_last_reeval_ts = [0.0]
_recent_events: list = []            # 近批事件 kind（供"环境感知"，自动老化）
_events_lock = threading.Lock()

# 事件 → 基础显著性（集中配置，SN 的统一输入；user_turn_end=1.0 兼作
# 安全底线：用户输入永远唤醒，这是业务约束不是显著性判断——SN 改造保留）。
# 2026-10-15 SN：_URGENT_KINDS 硬白名单退役为这张可解释的显著性底数表。
SN_EVENT_BASE = {"user_turn_end": 1.0, "discovery": 0.72,
                 "user_request": 0.78,      # 用户直接请求有权插队（2026-10-16）
                 "new_info": 0.60, "task_change": 0.55,
                 "game_context": 0.55, "gap_opened": 0.50}
_URGENT_KINDS = set(SN_EVENT_BASE)          # 兼容旧引用（sn 关闭时=原语义）

_SN_LOG_TS = [0.0]


def _sn_wake_decision(kind):
    """SN 判定该事件是否值得唤醒重评估。sn 关闭 → 回退旧白名单。"""
    try:
        import cognitive_field as _CF
        sn = _CF.salience_network()
        if not sn.enabled:
            return kind in _URGENT_KINDS, {"mode": "legacy_whitelist"}
        base = float(SN_EVENT_BASE.get(kind, 0.0)) or 0.25
        r = sn.event_salience(kind, event=base,
                              need=None, feasible=True,
                              source="evt:" + kind)
        now = time.time()
        if now - _SN_LOG_TS[0] > 120.0:      # 采样限流：2 分钟最多一条对照
            _SN_LOG_TS[0] = now
            logger.info("[SN] wake kind=%s score=%.2f decision=%s "
                        "(legacy=%s) 旧/新对照", kind, r["score"],
                        r["decision"], kind in _URGENT_KINDS)
        if kind == "user_turn_end":
            return True, r                    # 安全底线：不经判定
        return r["decision"] == "attend", r
    except Exception:                         # noqa: BLE001
        return kind in _URGENT_KINDS, {"mode": "sn_error_fallback"}


def notify_event(kind: str):
    """生活机制的事件入口（线程安全，任意事件源可调）。

    合并语义：多个事件在一次冷却窗内只引发一次重评估（防风暴）；
    开关关闭时设置无效——不存在"绕过开关继续自主活动"的后门。"""
    with _events_lock:
        _recent_events.append((kind, time.time()))
        if len(_recent_events) > 16:
            _recent_events.pop(0)
    _urgent, _r = _sn_wake_decision(kind)
    if _urgent:
        _WAKE.set()          # 唤醒 living daemon 提前进入重评估节拍


def recent_event(kind_sub: str, within_s: float = 900.0) -> bool:
    """近期是否发生过某类事件（候选环境感知；15 分钟窗口默认）。"""
    with _events_lock:
        return any(kind_sub in k and time.time() - ts < within_s
                   for (k, ts) in _recent_events)


def consume_wake():
    """daemon 用：清唤醒位（与 wait 配对）。"""
    _WAKE.clear()


def wait_timeout() -> threading.Event:
    """暴露 Event 给 living_loop daemon 做 wake.wait(tick) 安全网巡检。"""
    return _WAKE


def _drive_scale(ctx, activity: str) -> float:
    """激素式调制真正进决策：读现成 DriveEvaluator 的张力场。

    - 探索类（browse/research）∝ 好奇张力：张力高→更想做，张力平→回归基线；
    - 全活动 ∝ 1-疲劳：高疲劳压低一切（"累了自然安静"而非硬编码作息表）；
    - 读不到评估器/键缺失 → 1.0（fail-open 回退旧行为，绝不新增消耗）。
    """
    drv = ctx.get("drive")
    if drv is None:
        return 1.0
    try:
        t = (drv.get_drive_state() or {}).get("tensions") or {}

        def _g(*keys):
            # 精确键名匹配（2026-10-16 修复）：旧版子串匹配让 "rest"
            # 命中 unresolved_interest —— 乘数被误打成 0.17，一次真实
            # 邀请 0.52 误杀成 0.09。只接受全等或显式前缀族键。
            for k in keys:
                v0 = t.get(k)
                if v0 is None:
                    for tk, vv in t.items():
                        if tk.startswith(k + "_") or tk.startswith(k + ":"):
                            v0 = vv
                            break
                if v0 is None:
                    continue
                try:
                    return float(v0 if not isinstance(v0, dict)
                                 else v0.get("level", v0.get("tension", 0)))
                except (TypeError, ValueError):
                    pass
            return None
        curios = _g("curiosity", "explor", "好奇", "探索")
        # （疲劳乘数已删除，2026-10-17 用户裁定：AI 没有疲劳的生理机制，
        #   "累了自然安静"是伪生理设定——安静由欲望水位与阈值决定就够了。）
        s = 1.0
        if activity in ("browse", "research", "sts2") and curios is not None:
            s *= 0.55 + 0.9 * max(0.0, min(1.0, curios))
        return round(max(0.0, min(1.6, s)), 3)
    except Exception:                             # noqa: BLE001
        return 1.0


# ══════════════════════════════════════════════════════════════════════
# STS2 —— 第 4 个生活活动（2026-10-16 生活整合）。
# 选择、执行、结算全部走本模块既有协议：avail=桥在不在，appeal=偏好边
# ×兴趣×新鲜度，结果=经 reward.release 的 RPE 通道（期望驱动，不是胜负
# 直映），发现=概念节点+note_interest+mark_active 进扩散场。零专属
# 欲望/情绪/社交状态。游戏本体由用户在玩/开着才有；FAS 不启动进程。
# 决策子图是**私有图**（sts2_sim 机制知识库+当局经验），生产图谱只
# 收结论（概念/兴趣/偏好边/时间轴），不收卡牌实例噪声。
# ══════════════════════════════════════════════════════════════════════
_STS2_BRAIN = {}                    # {"kg":…, "eng":…} 进程内懒建
_STS2_LOG_TS = [0.0]
_STS2_EXP_PATH = None               # 测试可重定向


def _sts2_brain(ctx):
    if not _STS2_BRAIN:
        import copy as _copy
        from graph_model import KnowledgeGraph
        from diffusion_engine import DiffusionEngine
        import config as _C
        from sts2_sim import kb
        cfgd = dict(_C.DEFAULT_CONFIG)
        cfgd["diffusion_mode"] = "cascade"
        kg2 = KnowledgeGraph()
        kg2.save = lambda *a, **k: None          # 私有图永不落生产盘
        _STS2_BRAIN.update(kg=kg2, eng=DiffusionEngine(kg2, cfgd))
        kb.import_kb(kg2)
        kb.link_to_general(kg2)
    return _STS2_BRAIN["kg"], _STS2_BRAIN["eng"]


def _sts2_exp_path():
    global _STS2_EXP_PATH
    if _STS2_EXP_PATH:
        return _STS2_EXP_PATH
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "sts2_experience.json")


def sts2_available(ctx):
    """桥可达=游戏开着且 mod 就绪；桥不在→过 pc_autonomy 分级闸
    （2026-10-16）：允许自主启动时"可开局"同样是候选资格——但启动
    失败退避期内不许愿（launch_fails 指数冷却，见 _sts2_launch_gap）。"""
    cfg = ctx["config"]
    if not cfg.get("activity_sts2", True):
        return False, "活动开关关"
    pa = pc_autonomy.cfg_of(cfg)
    try:
        st = _load_state().get("sts2") or {}
    except Exception:                             # noqa: BLE001
        st = {}
    gap = _sts2_launch_gap(pa, st)
    if gap and time.time() - float(st.get("last_launch_try", 0) or 0) < gap:
        return False, "启动失败退避中"
    tr = ctx.get("sts2_transport")
    if tr is not None:
        try:
            if tr.health():
                return True, ""
        except Exception:                         # noqa: BLE001
            pass
        ok, why = pc_autonomy.can_launch(
            cfg, "sts2", present=ctx.get("pc_present"))
        return ok, ("可开局" if ok else why)
    if not cfg.get("activity_sts2", True):
        return False, "活动开关关"
    try:
        from sts2_sim.live_session import ModTransport
        t = ModTransport(base=str(cfg.get(
            "sts2_api", "http://127.0.0.1:8080")))
        if t.health():
            return True, ""
    except Exception:                             # noqa: BLE001
        pass
    ok, why = pc_autonomy.can_launch(
        cfg, "sts2", present=ctx.get("pc_present"))
    return ok, ("可开局" if ok else why)


def _sts2_launch_gap(pa: dict, st: dict) -> float:
    """启动失败指数退避：MIN_GAP_S×2^fails，封顶 24h；成功清零后无闸。"""
    fails = int(st.get("launch_fails", 0) or 0)
    if fails <= 0:
        return 0.0
    return min(86400.0, MIN_GAP_S * (2 ** min(fails, 6)))


def _sts2_appeal(ctx, state):
    """偏好边（杀戮尖塔/游戏类）∪ 概念兴趣水位 → ×新鲜度×当日饱腹。
    无偏好边=没玩过，给音乐同款试探底（0.30）让"经历生成偏好"有入口。"""
    base = 0.0
    try:
        from self_graph import get_preferences
        for p in get_preferences(ctx["kg"]):
            tg = str(p.get("target", ""))
            if any(k in tg for k in ("尖塔", "sts2", "STS2", "游戏")):
                base = max(base, float(p.get("weight", 0)))
    except Exception:                             # noqa: BLE001
        return 0.0
    acted = 0
    try:
        import curiosity_engine as _ce
        # 兴趣读活动自己的 concept（config apps.sts2.concept，裸名与
        # 偏好边 target 同型），兼容旧的"概念:X"前缀写法取大者
        concept = str((pc_autonomy.cfg_of(ctx["config"]).get(
            "apps") or {}).get("sts2", {}).get("concept") or "杀戮尖塔")
        _its = [_ce.get_interest(ctx["kg"], concept),
                _ce.get_interest(ctx["kg"], "概念:" + concept)]
        lvl = max(float(i.get("level", 0.0) or 0.0) for i in _its)
        acted = max(int(i.get("acted_count", 0) or 0) for i in _its)
        # 试探底只在"从未兑现过"时给（没玩过才需要入口）；玩过之后，
        # 想不想玩完全由图上念头的水位说话——水位是结算里衰减出来的
        # 真实消耗，不是计数器（2026-10-17 用户设计，替换 plays×0.35
        # 外部饱腹系数；00:56 实锤过系数把当面请求压到 0.11 的语义错误）
        if acted == 0 and int(state.get("sts2", {}).get("plays_today", 0)
                              or 0) == 0:
            base = max(base, 0.30)
        base = base + 0.4 * lvl
    except Exception:                             # noqa: BLE001
        base = max(base, 0.30)
    last = float(state.get("sts2", {}).get("last_ts", 0) or 0)
    fresh = min(1.0, (time.time() - last) / 3600.0 / 3.0)   # 刚打完的短时冷却
    # ④ 用户显式请求的新鲜度（2026-10-16）：满水位起、2h 半衰连续衰减——
    # 当面邀请当次该赢过逛论坛；两小时没人跟进自然退回常态竞争。
    try:
        req_age_h = (time.time() - float(state.get("sts2", {})
                                         .get("request_ts", 0) or 0)) / 3600.0
        want = 1.0 * math.exp(-max(0.0, req_age_h) / 2.0 * math.log(2))
        # 邀请（外源）与念头水位（内源）可叠加：满水位请求 + 攒下的
        # 兴趣要能穿过"承诺惯性"（STICK 0.8）
        base = max(base, want) + (0.25 if want > 0.5 else 0.0)
    except Exception:                             # noqa: BLE001
        pass
    _a = base * 0.55 * fresh
    # 当面请求以未打折的满值直接参与竞争（2026-10-17）：自发欲望要过
    # "×0.55×冷却"的衰减链，但用户直接说"继续打"是被明确指派，不该被
    # 刚打完一局的冷却清零而放弃半局——否则出现"答应了却没接上"。
    # want 本身 2h 半衰，几拍不理会自然退回常态（不失控）。
    _a = max(_a, want)
    if _a > THRESHOLD and time.time() - _STS2_LOG_TS[0] > 45.0:
        _STS2_LOG_TS[0] = time.time()
        logger.info("[Act] sts2 欲望读数：base=%.2f（念头水位+请求新鲜度）"
                    " appeal=%.2f（fresh=%.2f 已兑现%d次）",
                    base, _a, fresh, acted)
    return _a


def harvest_activity_request(ctx, user_text: str):
    """请求→动机的翻译通道（2026-10-16 修复"让她玩她不玩"）。用户话语命中
    某活动的 keywords 时，不新增调度器、不绕过竞争——只把这句话变成该活动
    appeal 本来就读的两个量的增量：①concept 兴趣水位 signal（+0.25，封顶
    自然限幅，重复喊话不失控）②没有偏好边则补试探边（与 music 初次试探同
    源）+ notify_event 唤醒重评估。之后玩不玩仍由生活循环自己竞争决定。"""
    cfg = ctx.get("config") or {}
    apps = (pc_autonomy.cfg_of(cfg).get("apps") or {})
    text = str(user_text or "")
    for app, spec in apps.items():
        kws = [k for k in (spec.get("keywords") or []) if k in text]
        if not kws:
            continue
        concept = str(spec.get("concept") or kws[0])
        try:
            kg = ctx["kg"]
            from graph_model import Node
            if kg.get_node(concept) is None:
                kg.add_node(Node(id=concept, weight=0.5,
                                 label="declarative-semantic",
                                 extra_attrs={"type": "concept",
                                              "source": "user_request",
                                              "evidence": text[:80]}))
            import curiosity_engine as _ce
            _ce.note_interest(kg, concept, "signal", cfg)
            from self_graph import get_preferences, set_preference
            names = {str(p.get("target", ""))
                     for p in get_preferences(kg)}
            if not any(concept in n or n in concept for n in names):
                set_preference(kg, concept, weight=0.25)
            try:
                with _STATE_LOCK:
                    _st = _load_state()
                    _st.setdefault(app, {})["request_ts"] = time.time()
                    _save_state(_st)
            except Exception:                     # noqa: BLE001
                pass
            notify_event("user_request")
            logger.info("[Act] 请求收割：%r 命中 %s → 兴趣 signal + 唤醒",
                        text[:24], app)
            return {"app": app, "concept": concept,
                    "keywords": kws}
        except Exception:                         # noqa: BLE001
            logger.debug("[Act] 请求收割失败", exc_info=True)
            return None
    return None


def _sts2_settle(ctx, state, res, rpe_valence=None):
    """结果结算（唯一写点，幂等）：reward 事件 → RPE → 偏好边微调；
    发现 → 概念节点+兴趣信号+进扩散；时间轴记一条。"""
    out = {"settled": False}
    rs_fn = ctx.get("reward_fn")
    timeline_fn = ctx.get("timeline_fn")
    reward = rs_fn() if callable(rs_fn) else None
    tl = timeline_fn() if callable(timeline_fn) else None
    result = res.get("result") or "unknown"
    if result not in ("victory", "defeat", "aborted"):
        return out
    # 幂等键=局面+结果（2026-10-17 修复：旧键只用 run_id，续上同一存档
    # 再打的新结果会被 idempotence 吞掉——floor8 中途停已结算过，
    # continue 后打到 floor17 战死的败北扣权重/念头冷却全被跳过的实锤）。
    # 同一局面同一结果仍不重复计数（防同拍双结算）。
    run_key = "%s@%s@%s" % (res.get("run_id") or "",
                            res.get("result") or "",
                            res.get("floor") if res.get("floor") is not None
                            else "")
    st = state.setdefault("sts2", {})
    if run_key and st.get("last_settled_run") == run_key:
        out["skipped"] = "duplicate_settlement"      # 同一结果不重复计数
        return out
    floor = float(res.get("floor") or 0)
    progress = max(0.0, min(1.0, floor / 50.0))
    if result == "victory":
        valence, outcome = 1.0, "goal_success"
    elif result == "defeat":
        valence, outcome = -(0.4 + 0.3 * (1.0 - progress)), "goal_failure"
    else:
        valence, outcome = -0.1, "blocked"          # 撤退/中断≠失败证据
    rpe = None
    if reward is not None:
        try:
            from reward import new_event
            r = reward.release([new_event(
                source="self", outcome=outcome, valence=valence,
                behavior="play_sts2", context="杀戮尖塔")])
            rpe = (r.get("surprises") or {}).get("play_sts2@杀戮尖塔")
        except Exception:                           # noqa: BLE001
            logger.debug("[Act.sts2] reward 结算跳过", exc_info=True)
    if rpe is not None:
        try:
            import math
            _tune_preference(ctx, "杀戮尖塔",
                             round(0.02 * math.tanh(rpe * 1.5), 4))
        except Exception:                           # noqa: BLE001
            pass
    # 发现→生产图：概念节点 + 兴趣 signal + 进扩散（说与否交给表达机制）
    for mech in (res.get("new_mechanics") or [])[:3]:
        nid = "概念:%s" % str(mech.get("name", "")).split(":")[-1]
        try:
            from graph_model import Node
            if ctx["kg"].get_node(nid) is None:
                ctx["kg"].add_node(Node(
                    id=nid, weight=0.45, label="declarative-semantic",
                    extra_attrs={"type": "concept",
                                 "evidence": str(mech.get("text"))[:120],
                                 "source": "game:sts2",
                                 "conf": "observed"}))
            import curiosity_engine as _ce
            _ce.note_interest(ctx["kg"], nid, "signal", ctx["config"])
            if ctx.get("engine") is not None:
                ctx["engine"].mark_active([nid])
        except Exception:                           # noqa: BLE001
            continue
    if tl is not None:
        try:
            from experience import make_event, EVENT_ACTION
            # actor 全仓约定为 "self"（HARU 自己）。此处曾写 "haru"，与语言层
            # 主体映射不同源——她读自己的战报把 "haru" 当第三人，将自己的游戏
            # 进度讲成"你反复败北"（2026-10-16 取证：00:21/19:57 主动话语实锤）。
            # 根因在写入层，修写入层；历史条目由读取端映射兼容。
            tl.append(make_event(
                EVENT_ACTION, actor="self", subject="sts2_run",
                content={"result": result, "floor": res.get("floor"),
                         "valence": round(valence, 3),
                         "rpe": rpe,
                         "self_booted": bool(res.get("self_booted")),
                         "mechanics": [m.get("name") for m in
                                       (res.get("new_mechanics") or [])]},
                source="activity:sts2"))
        except Exception:                           # noqa: BLE001
            pass
    st["last_settled_run"] = run_key
    # 饱腹=念头被兑现而消耗（2026-10-17 用户设计，取代 plays_today 计数
    # 系数）：每真打完一把，兴趣水位按结果衰减——赢得平缓、输了凉得快
    # （再乘体验效价的负向微调）；水位跌破阈值念头自然熄灭，想玩会随
    # 时间/新经历回涨。消耗发生在图上，不是行为计数器。
    # 消耗只发生在**打完**一局时（2026-10-17 语义修正）：预算尽
    # (exit=budget) 与推进失败 (exit=stuck) 都是"局未终"——没做完的
    # 事不该让念头变凉（f15 实锤：离场被当 0.6 消耗，下一拍 research
    # 0.17 就把半局永远晾在桌上）；只有真打完才兑现消耗。
    if res.get("exit") not in ("budget", "stuck"):
        try:
            import curiosity_engine as _ce
            _concept = str((pc_autonomy.cfg_of(ctx["config"]).get(
                "apps") or {}).get("sts2", {}).get("concept") or "杀戮尖塔")
            _m = {"victory": 0.78, "aborted": 0.6, "defeat": 0.45}[result]
            if valence < 0:
                _m = _m * (1.0 - min(0.5, abs(float(valence)) * 0.5))
            for _nid in (_concept, "概念:" + _concept):
                if ctx["kg"].get_node(_nid) is not None:
                    _ce.note_interest(ctx["kg"], _nid, "sated",
                                      ctx["config"], mult=_m)
                    break
        except Exception:                           # noqa: BLE001
            logger.debug("[Act] sated 消耗失败", exc_info=True)
    out.update(settled=True, result=result, valence=round(valence, 3),
               rpe=None if rpe is None else round(rpe, 3))
    return out


def sts2_beat(ctx, state):
    """被选中后的完整活动：若桥不在先过闸自启游戏（pc_autonomy 分级），
    等 mod 就绪，预算内跑一局，唯一写点结算。启动失败零证据写入。"""
    from sts2_sim.live_session import play_session, ModTransport
    cfg = ctx["config"]
    pa = pc_autonomy.cfg_of(cfg)
    tr = ctx.get("sts2_transport") or ModTransport(base=str(
        cfg.get("sts2_api", "http://127.0.0.1:8080")))
    st = state.setdefault("sts2", {})
    booted = False
    # 用户在玩别的游戏（Steam 库目录有其它游戏进程在跑）：运存让给他——
    # 她若开着 STS2 就保存退出，也不开新局（2026-10-16 用户规则）。
    _title = str(((pa.get("apps") or {}).get("sts2") or {})
                 .get("window_title") or "")
    others = pc_autonomy.steam_games_running(pa, exclude=[_title.lower()])
    if others:
        try:
            if tr.health():
                d0 = tr.state()
                if "save_and_quit" in (d0.get("available_actions") or []):
                    tr.action({"action": "save_and_quit"})
        except Exception:                           # noqa: BLE001
            pass
        return {"activity": "sts2", "done": True,
                "result": "unavailable", "why": "user_gaming:"
                + str(others[0])[:30], "steps": 0}
    if not tr.health():
        # 启动也是行动，必须被"想做"驱动（2026-10-16 修复：事件唤醒让
        # 程度 0.00 的拍子连着把游戏开了三次，之后没有力量去操作——
        # 用户看到的是"光开游戏停在界面不动"。没欲望就不开。）
        # 门槛=半个 play 阈值（2026-10-16 深夜再修：0.03 的残值连着开了
        # 五次游戏；开一次 = 拉起 Steam+游戏+一整段会话的资源，冲动必须
        # 够玩一局量级才配按开关，而不是有一口气就开）。
        try:
            ap = float(_sts2_appeal(ctx, state))
        except Exception:                           # noqa: BLE001
            ap = 1.0                                # 读数失败不误拦真实请求
        if ap < THRESHOLD * 0.5:
            return {"activity": "sts2", "done": True,
                    "result": "unavailable", "why": "not_interested",
                    "steps": 0}
        if _title and pc_autonomy.window_exists(_title):
            # 桥不通≠没在运行（2026-10-18 晚间实锤事故）：用户刚开游戏、
            # mod 还没就绪的间隙里 health()=False，她据此按下启动键并给自己
            # 盖了所有权戳，随后带着"这是我的局"的错觉抢控代打了六次。
            # 窗口在而桥不通：这个实例几乎必然是用户的——不启动、不盖戳，
            # 等桥恢复后由下面的事实观察器裁决归属。
            return {"activity": "sts2", "done": True,
                    "result": "unavailable", "why": "bridge_down",
                    "steps": 0}
        ok, why = pc_autonomy.can_launch(
            cfg, "sts2", present=ctx.get("pc_present"))
        if not ok:
            return {"activity": "sts2", "done": True,
                    "result": "unavailable", "why": why, "steps": 0}
        st["last_launch_try"] = time.time()
        launcher = ctx.get("sts2_launcher")       # 测试注入点
        if launcher is not None:
            ok2 = bool(launcher(ctx))
        else:
            ok2, lwhy = pc_autonomy.launch(cfg, "sts2")
            if not ok2:
                ok2 = False
        if not ok2:
            st["launch_fails"] = int(st.get("launch_fails", 0)) + 1
            return {"activity": "sts2", "done": True,
                    "result": "unavailable", "why": "launch_failed",
                    "steps": 0}
        # 等 mod 就绪（Steam 启动+主菜单加载）；后台档先让窗口露出
        # 来再最小化（找不到不强求，失败不拦主流程）
        deadline = time.time() + float(pa.get("boot_wait_s", 240))
        ready = False
        while time.time() < deadline:
            try:
                if tr.health():
                    ready = True
                    break
            except Exception:                     # noqa: BLE001
                pass
            time.sleep(2.0)
        if not ready:
            st["launch_fails"] = int(st.get("launch_fails", 0)) + 1
            # 观测（2026-10-16）：此前该路径零日志，深夜连开五次无从诊断
            logger.warning("[Act] sts2 已提交启动但 mod 在 boot_wait 内未就绪"
                           "（连续失败 %d 次，退避加倍）", st["launch_fails"])
            return {"activity": "sts2", "done": True,
                    "result": "unavailable", "why": "boot_timeout",
                    "steps": 0}
        # 姿态语义（2026-10-16 用户定）：attended=有人用电脑时**强制
        # 后台**（绝不抢焦点）；unattended=可前台；background 开关让
        # unattended 档也主动后台。
        if bool(pa.get("background", False)) or str(
                pa.get("level", "off")) == "attended":
            spec = (pa.get("apps") or {}).get("sts2") or {}
            pc_autonomy.minimize_window(
                str(spec.get("window_title") or "Slay the Spire 2"))
        st["launch_fails"] = 0
        # 归属标记：这份实例是她启动的（6h 窗口内的接管豁免凭据）。
        st["self_opened_ts"] = time.time()
        booted = True
    else:
        # 游戏已在运行且**不是她开的**：用户在操作电脑时这个实例是"他的"
        # ——不接管、不代打（2026-10-16 用户规则：防"我开游戏她来抢"）。
        # 所有权按**事实**判定，不用固定时间窗（2026-10-18 规范修订）：
        # 她启动过的局（self_opened_ts 是启动成功时盖的戳）在无人接管
        # 之前一直是她的——让渡发生过就盖 user_owns_ts，所有权即时翻转；
        # 用户当面邀请（want 新鲜）本身就是"你来打"的授权，不构成抢控。
        # —— 事实观察器（2026-10-18 抢控事故补账）：所有权翻转此前只靠
        # "她会话内检测到真人上手"，而她每次秒败弃权根本攒不够观察；
        # 用户在两次会话之间玩掉了三层（floor 1→5→13 是硬证据）却无人
        # 过户。现在逐拍比对局面签名：板子在她没动手的时候自己动了
        # =有人在玩，即时过户并让路——这一条**不受邀请豁免**（他邀请
        # 了却还占着鼠标，只能等她自己的局空出来，不授权当场抢控）。
        _cur_sig = ""
        try:
            _d0 = tr.state()
            _cur_sig = "%s|%s|%s" % (
                _d0.get("screen"),
                (_d0.get("run") or {}).get("floor"),
                (_d0.get("player") or {}).get("current_hp"))
        except Exception:                           # noqa: BLE001
            pass
        _prev_sig = str(st.get("last_sig") or "")
        _advanced = bool(_cur_sig and _prev_sig and _cur_sig != _prev_sig)
        st["last_sig"] = _cur_sig or _prev_sig      # 逐拍重定基线
        if _advanced:
            st["user_owns_ts"] = time.time()
        _user_at_game = False
        try:
            _fg = pc_autonomy.foreground_title()
            _user_at_game = bool(_title and _fg and pc_autonomy.user_present(pa)
                                 and _title.lower() in str(_fg).lower())
        except Exception:                           # noqa: BLE001
            pass
        if _advanced or _user_at_game:
            return {"activity": "sts2", "done": True,
                    "result": "unavailable", "why": "user_playing",
                    "steps": 0}
        # —— 以下维持既有所有权/邀请语义（2026-10-18 规范修订）：
        _opened = float(st.get("self_opened_ts", 0) or 0)
        _owns = float(st.get("user_owns_ts", 0) or 0)
        try:
            _rh = (time.time() - float(st.get("request_ts", 0) or 0)) / 3600.0
            _invited = math.exp(-max(0.0, _rh) / 2.0 * math.log(2)) > 0.5
        except Exception:                           # noqa: BLE001
            _invited = False
        if pc_autonomy.user_present(pa) and not (_opened > _owns) \
                and not _invited:
            return {"activity": "sts2", "done": True,
                    "result": "unavailable", "why": "user_playing",
                    "steps": 0}
    kg2, eng2 = _sts2_brain(ctx)
    # 经验装载（response 边 + 校准，宿主数据非生产图）
    try:
        from sts2_sim import kb as _kb
        exp_p = _sts2_exp_path()
        if exp_p and os.path.exists(exp_p):
            _kb.load_experience(kg2, exp_p)
    except Exception:                               # noqa: BLE001
        pass
    budget = float(ctx["config"].get("sts2_session_budget_s", 420))
    res = play_session(tr, kg2, eng2, budget_s=budget, log=logger.info,
                       gaming_probe=lambda: pc_autonomy.steam_games_running(
                           pa, exclude=[_title.lower()]))
    if booted:
        res["self_booted"] = True
    st = state.setdefault("sts2", {})
    # 归因更正（2026-10-18）：她刚玩完的离场局面是**她造成的**变化，
    # 把观察基线定在这里——下一拍的"板子自己动了"只剩一个解释：别人在玩。
    try:
        _dF = tr.state()
        st["last_sig"] = "%s|%s|%s" % (
            _dF.get("screen"),
            (_dF.get("run") or {}).get("floor"),
            (_dF.get("player") or {}).get("current_hp"))
    except Exception:                               # noqa: BLE001
        pass
    # 让渡即过户（2026-10-18）：会话里检测到真人上手（yielded）→ 这个
    # 实例从此归他，她不再回来抢——所有权翻转有事实依据，不靠时间窗猜。
    if res.get("result") == "yielded":
        st["user_owns_ts"] = time.time()
    # 新鲜度/计数只在真玩了一局才扣：unavailable/unknown 是环境不
    # 配合，惩罚渴望不成比例（一次菜单进不去 = 3 小时不想玩？）
    if res.get("result") in ("victory", "defeat", "aborted"):
        st["last_ts"] = time.time()
        day = time.strftime("%Y%m%d")
        if st.get("day") != day:
            st["day"], st["plays_today"] = day, 0
        st["plays_today"] = int(st.get("plays_today", 0)) + 1
    settle = _sts2_settle(ctx, state, res)
    try:                                            # 经验回写宿主文件
        from sts2_sim import kb as _kb
        _kb.persist_experience(kg2, _sts2_exp_path())
    except Exception:                               # noqa: BLE001
        pass
    return {"activity": "sts2", "done": True,
            "result": res.get("result"), "floor": res.get("floor"),
            "steps": res.get("steps"), **settle}


def _browse_appeal(ctx, st):
    """browse 欲望 =（种子/存货底）× 扫兴折扣，折扣带**时间衰减**
    （2026-10-18 修死锁）：旧设计里折扣只有"再逛一次且逛到新东西"才
    回升（+0.35），可它一沉下去 browse 就永远输掉选择、永远出不去、
    永远没有回升的机会——一次扫兴把出门通道永久焊死（违反 §三.5：
    一次偶然事件不得永久支配行为）。现在扫兴记忆按 ~6h 线性回基线，
    时间到了重新给 browse 出门的入场券；真逛到/没逛到新东西仍由
    +0.35/×0.5 两条实证反馈即时修正。"""
    base = (0.55 if _browse_seed(ctx)[0] else
            0.42 if ctx["config"].get("activity_forum_feeds", True) else 0.0)
    if base <= 0:
        return 0.0
    br = st.get("browse", {}) or {}
    nd = float(br.get("novelty_discount") or 1.0)
    if nd < 1.0:
        anchor = float(br.get("novelty_discount_ts")
                       or br.get("last_ts") or 0.0)
        if anchor:
            age_h = max(0.0, (time.time() - anchor) / 3600.0)
            nd = min(1.0, nd + (1.0 - nd) * min(1.0, age_h / 6.0))
    return round(base * nd, 4)


# ── 新增生活活动（2026-10-19 用户"都做"）：复盘/读本地/望桌面 ──────
# 共同纪律：只用既有机制（台账/聊天日志/规则抽取器/桥通道），零新库；
# 触发源都是"已经发生过的事的存量"，不造新欲望；都不抢用户前台。


def _life_data_dir():
    return os.environ.get("FAS_LIVING_DATA_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data")


def _ts_chat(e):
    import datetime as _dt2
    s = str(e.get("time") or "")[:26]
    for f in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
              "%Y-%m-%d %H:%M:%S"):
        try:
            return _dt2.datetime.strptime(s, f).timestamp()
        except ValueError:
            continue
    return 0.0


def _journal_send(text, tags):
    """向 Charon 日记/随手记通道送一条（桥不可达=静默 False）。"""
    try:
        from fas.companion.charon_bridge import CharonBridgeChannel
        return bool(CharonBridgeChannel().capture(text, tags))
    except Exception:                             # noqa: BLE001
        return False


def review_available(ctx):
    return (bool(ctx["config"].get("activity_review", True)), "复盘已关")


def _review_appeal(ctx, state):
    """复盘强度 ∝ 上次复盘以来沉淀的经历数（台账更新+发言往来）。
    没有新经历=0——不为了复盘制造事。"""
    import json as _json
    last = float((state.get("review") or {}).get("last_ts", 0) or 0)
    n = 0
    try:
        d = _json.load(open(os.path.join(_life_data_dir(),
                                         "living_ledger.json"),
                            encoding="utf-8"))
        acts = d.get("activities") or {}
        items = (list(acts.values()) if isinstance(acts, dict)
                 else list(acts))
        n += sum(1 for a in items
                 if float(a.get("updated") or 0) > last)
    except Exception:                             # noqa: BLE001
        pass
    try:
        chat = _json.load(open(os.path.join(_life_data_dir(),
                                            "chat_log.json"),
                               encoding="utf-8"))
        n += sum(1 for e in chat[-60:]
                 if (e.get("proactive") or (str(e.get("user_input") or "")
                                            .strip()
                                            and not str(e.get(
                                                "user_input")).startswith("(")))
                 and _ts_chat(e) > last)
    except Exception:                             # noqa: BLE001
        pass
    return round(min(0.6, 0.08 * n), 3)


def review_beat(ctx, state):
    """复盘：确定性组织当日经历成一条日记发往 Charon（零 LLM），
    标记消化点。产出既是她自己的沉淀，也是以后说话的原料。"""
    import json as _json
    st = state.setdefault("review", {})
    last = float(st.get("last_ts", 0) or 0)
    now = time.time()
    lines = []
    try:
        d = _json.load(open(os.path.join(_life_data_dir(),
                                         "living_ledger.json"),
                            encoding="utf-8"))
        acts = d.get("activities") or {}
        items = (list(acts.values()) if isinstance(acts, dict)
                 else list(acts))
        for a in sorted(items, key=lambda x: float(x.get("updated") or 0)):
            if float(a.get("updated") or 0) > last:
                lines.append("- 做了：「%s」（%s）" % (
                    str(a.get("topic") or "?")[:30], a.get("state")))
    except Exception:                             # noqa: BLE001
        pass
    try:
        chat = _json.load(open(os.path.join(_life_data_dir(),
                                            "chat_log.json"),
                               encoding="utf-8"))
        spoken = sum(1 for e in chat if e.get("proactive")
                     and _ts_chat(e) > last)
        asked = sum(1 for e in chat
                    if str(e.get("user_input") or "").strip()
                    and not str(e.get("user_input")).startswith("(")
                    and _ts_chat(e) > last)
        if spoken or asked:
            lines.append("- 往来：我主动说了 %d 次，接了用户 %d 句"
                         % (spoken, asked))
    except Exception:                             # noqa: BLE001
        pass
    if lines:
        import datetime as _dt3
        dig = "复盘 %s\n%s" % (_dt3.datetime.fromtimestamp(
            now).strftime("%m-%d %H:%M"), "\n".join(lines[:8]))
        sent = _journal_send(dig, ["复盘"])
        logger.info("[Act] 复盘消化 %d 行（日记%s）", len(lines),
                    "已送" if sent else "桥不通")
    st["last_ts"] = now
    st["lines"] = len(lines)
    return {"done": True, "activity": "review", "next": "continue",
            "result": "ok" if lines else "nothing_new", "steps": 0}


def _read_dirs(ctx):
    return [d for d in (ctx["config"].get("self_reading_dirs") or [])
            if isinstance(d, str) and os.path.isdir(d)]


def read_available(ctx):
    return (bool(_read_dirs(ctx)), "未配置自读目录（默认休眠）")


def _read_appeal(ctx, state):
    import json as _json
    seen = set((state.get("self_read") or {}).get("seen") or [])
    unread = 0
    for d in _read_dirs(ctx):
        try:
            unread += sum(1 for fn in sorted(os.listdir(d))[:60]
                          if fn.lower().endswith((".md", ".txt"))
                          and os.path.isfile(os.path.join(d, fn))
                          and os.path.join(d, fn) not in seen)
        except OSError:
            continue
    return round(min(0.5, 0.25 + 0.05 * min(5, unread)), 3) if unread \
        else 0.0


def read_beat(ctx, state):
    """读一个本地白名单目录里的文档：经历入图 + 规则级事实抽取
    （复用 browse_memory 同一硬化链路，零 LLM 零网络）。"""
    st = state.setdefault("self_read", {})
    seen = list(st.get("seen") or [])
    sen = set(seen)
    path = None
    for d in _read_dirs(ctx):
        try:
            for fn in sorted(os.listdir(d))[:60]:
                p = os.path.join(d, fn)
                if (fn.lower().endswith((".md", ".txt"))
                        and p not in sen and os.path.isfile(p)):
                    path = p
                    break
        except OSError:
            continue
        if path:
            break
    if not path:
        return {"done": True, "activity": "read", "result": "nothing_new"}
    try:
        raw = open(path, encoding="utf-8", errors="replace").read(1200)
    except OSError:
        raw = ""
    fname = os.path.splitext(os.path.basename(path))[0][:40]
    # 抽取标题用文档首行（规则抽取器从《》取主语；文件名常没有）
    _head = (raw.strip().splitlines() or [""])[0][:52] if raw.strip() else ""
    title = _head or fname
    exp = _note_experience(ctx, "我读了本地文档「%s」" % fname,
                           "self_read", value="medium", concept=fname)
    if exp and raw.strip():
        try:
            import browse_memory as _B
            _B.consolidate_browse_memory(
                ctx["kg"], ctx.get("engine"), exp, "file://" + path[:120],
                title, raw[:600], page_ok=True,
                fuzzy_match=ctx.get("fuzzy_match"))
        except Exception:                         # noqa: BLE001
            pass
    st["seen"] = (seen + [path])[-200:]
    logger.info("[Act] 读完了 %s", path[:70])
    return {"done": True, "activity": "read", "next": "continue",
            "result": "ok", "steps": 0}


def watch_available(ctx):
    return (bool(ctx["config"].get("screen_observe_enabled", False)),
            "屏幕观察未开启（隐私默认关，重启必关）")


def _watch_appeal(ctx, state):
    return 0.15          # 最低档：只在别无想望时"看看桌面"


def watch_beat(ctx, state):
    """望桌面=消费观察通道刚喂的新鲜帧（本活动自己不截图——采集只归
    既有开关驱动的管线管，权限模型不变）。无新鲜帧=让位。"""
    import screen_watch
    lr = (getattr(screen_watch, "_STATE", None) or {}).get("last_result") \
        or {}
    ts = float(lr.get("ts") or 0)
    if time.time() - ts > 600:
        return {"done": True, "activity": "watch", "result": "unavailable",
                "why": "no_fresh_frame"}
    state.setdefault("watch", {})["last_seen_ts"] = ts
    logger.info("[Act] 望了望桌面")
    return {"done": True, "activity": "watch", "next": "continue",
            "result": "ok", "steps": 0}


def tidy_available(ctx):
    return (bool(ctx["config"].get("activity_tidy", True)), "整理已关")


def _tidy_appeal(ctx, state):
    """整理欲望=账上有活才想起：悬空边>0，或距上次体检>12h 且有沉睡节点。
    图谱干净时是 0——她不会闲得慌去翻自己内脏。"""
    import json as _json
    kg = ctx.get("kg")
    if kg is None:
        return 0.0
    last = float((state.get("tidy") or {}).get("last_ts", 0) or 0)
    now = time.time()
    dangling = 0
    dormant = 0
    try:
        import datetime as _dt4
        with kg._lock:
            for e in kg.edges:
                if str(e.src) not in kg.nodes or str(e.dst) not in kg.nodes:
                    dangling += 1
            for n in kg.nodes.values():
                if str(getattr(n, "label", "") or "").startswith("declarative") \
                        and float(n.activation or 0) <= 0.05:
                    la = str(getattr(n, "last_access", "") or "")
                    try:
                        t = _dt4.datetime.strptime(la,
                                                   "%Y-%m-%d %H:%M:%S").timestamp()
                        if now - t > 14 * 86400:
                            dormant += 1
                    except ValueError:
                        pass
    except Exception:                             # noqa: BLE001
        return 0.0
    if dangling:
        return 0.42
    if dormant > 30 and now - last > 12 * 3600:
        return 0.2
    return 0.0


def tidy_beat(ctx, state):
    """图谱整理（安全版，2026-10-19 用户追问"怎么不搞"）：
    自动执行的只有**悬空边清理**——端点已不存在的边既传不动也画不出，
    删除只是把索引现实化，与启动自愈同型、零语义损失。其余一切
    （沉睡节点、无标假设腿、枢纽端点残留）只**写体检报告**送日记，
    删除永远是人工决定——自动改写的图不是她自己的图。"""
    kg = ctx.get("kg")
    st = state.setdefault("tidy", {})
    now = time.time()
    if kg is None:
        st["last_ts"] = now
        return {"done": True, "activity": "tidy", "result": "nothing_new"}
    rep = []
    with kg._lock:
        dead = [e for e in kg.edges
                if str(e.src) not in kg.nodes or str(e.dst) not in kg.nodes]
        targets = {(str(e.src), str(e.dst), str(e.relation)) for e in dead}
    pruned = 0
    for s, d, r in targets:
        try:
            if kg.remove_edge(s, d, r):
                pruned += 1
        except Exception:                         # noqa: BLE001
            continue
    dormant = 0
    try:
        import datetime as _dt5
        with kg._lock:
            for n in kg.nodes.values():
                if str(getattr(n, "label", "") or "").startswith("declarative") \
                        and float(n.activation or 0) <= 0.05:
                    try:
                        t = _dt5.datetime.strptime(
                            str(getattr(n, "last_access", "") or ""),
                            "%Y-%m-%d %H:%M:%S").timestamp()
                        if now - t > 14 * 86400:
                            dormant += 1
                    except ValueError:
                        pass
            hyp_no_leg = sum(
                1 for n in kg.nodes.values()
                if str((n.extra_attrs or {}).get("type") or "") == "hypothesis")
    except Exception:                             # noqa: BLE001
        hyp_no_leg = -1
    if pruned:
        rep.append("- 清了悬空边 %d 条" % pruned)
    rep.append("- 沉睡>14 天节点 %d 个（只报告，不动——删除需人工）" % dormant)
    if hyp_no_leg >= 0:
        rep.append("- 假设节点 %d 个在册" % hyp_no_leg)
    st["last_ts"] = now
    st["dormant"] = dormant
    if pruned or dormant > 100:
        _journal_send("图谱体检 %s\n%s" % (
            time.strftime("%m-%d %H:%M", time.localtime(now)),
            "\n".join(rep)), ["图谱体检"])
    logger.info("[Act] 整理：%s", "；".join(rep)[:120])
    if pruned:
        try:
            if ctx.get("save_fn"):
                ctx["save_fn"]()
        except Exception:                         # noqa: BLE001
            pass
    return {"done": True, "activity": "tidy", "next": "continue",
            "result": "ok" if pruned or dormant else "nothing_new",
            "steps": pruned}





ACTIVITIES = [
    ("music", music_available, _music_appeal, music_beat),
    ("review", review_available, _review_appeal, review_beat),
    ("tidy", tidy_available, _tidy_appeal, tidy_beat),
    ("read", read_available, _read_appeal, read_beat),
    ("watch", watch_available, _watch_appeal, watch_beat),
    ("browse",
     lambda ctx: ((bool(_browse_seed(ctx)[0]) or bool(
         ctx["config"].get("activity_forum_feeds", True)))
         and _web_budget_left(ctx) > 0, "无可逛之事或预算已尽"),
     _browse_appeal, browse_beat),
    ("research",
     lambda ctx: (bool(_graph_strength(ctx))
                  and _web_budget_left(ctx) > 0, "无事可想或预算已尽"),
     lambda ctx, st: (max((s for _c, s, _k, _e in _graph_strength(ctx)),
                          default=0.0)),
     research_beat),
    ("sts2", sts2_available, _sts2_appeal, sts2_beat),
]



def _sts2_put_down_if_unwanted(ctx, state):
    """不想打了就把桌**彻底**收拾掉（2026-10-17 用户规则，教过她的运存
    知识落到行为）：游戏还开着、但"想玩"的念头已凉透 → ①局内先
    save_and_quit（存档留磁盘、随时可续），结算屏先确认收掉；
    ②**再关闭游戏进程本身**（pc_autonomy.close_app）——退到主菜单
    进程还挂着=运存还在被占，那不算"退出"。
    10 分钟冷却：刚打完一局的回温期不收拾，念头真凉了才收。
    双拍确认（2026-10-18 规范修订）：单次读数下探不等于"不想玩了"——
    欲望要在**连续两拍**都低于凉透线才动手，中途回升则计数清零；
    避免瞬时波动触发退出这种不可逆操作。"""
    st = state.setdefault("sts2", {})
    if time.time() - float(st.get("last_quit_ts", 0) or 0) < 600:
        return
    try:
        low = float(_sts2_appeal(ctx, state)) < THRESHOLD * 0.5
    except Exception:                       # noqa: BLE001
        return
    streak = int(st.get("unwanted_streak") or 0)
    st["unwanted_streak"] = streak = (streak + 1) if low else 0
    if not low:
        return                              # 还想玩，别碰
    if streak < 2:
        logger.info("[Act] sts2 欲望走低（第 1 拍，待确认）")
        return                              # 一拍的冷却不足以决定退出
    try:
        from sts2_sim.live_session import ModTransport
        tr = ctx.get("sts2_transport") or ModTransport(base=str(
            (ctx.get("config") or {}).get(
                "sts2_api", "http://127.0.0.1:8080")))
        if not tr.health():
            return                          # mod 本来就没开
        d = tr.state()
        avail = d.get("available_actions") or []
        # 先收屏内残局：局未终→存档退出；结算屏→确认（否则挂在结果页）
        if d.get("screen") == "GAME_OVER" and "continue_game_over" in avail:
            tr.action({"action": "continue_game_over"})
        elif "save_and_quit" in avail:
            tr.action({"action": "save_and_quit"})
        # 再关进程：这步才真正释放运存（用户教的因果知识的行动落点）
        okc, _w = pc_autonomy.close_app(
            (ctx.get("config") or {}), "sts2",
            killer=ctx.get("app_killer"))
        st["last_quit_ts"] = time.time()
        st["unwanted_streak"] = 0
        logger.info("[Act] sts2 念头已凉 → %s（运存%s）",
                    "保存退出并关闭游戏" if okc else "已存档收屏（进程未关）",
                    "已释放" if okc else "仍被占用")
    except Exception:                       # noqa: BLE001
        logger.debug("[Act] sts2 收拾桌面失败", exc_info=True)


def _pl_activity_plugins():
    from plugin_loader import load_activity_plugins
    return load_activity_plugins()


ACTIVITIES += _pl_activity_plugins()


def beat(ctx, trigger: str = "sweep"):
    """living_loop daemon 的每拍入口（事件提前唤醒或安全网巡检）。

    trigger="event" 时受 REEVAL_MIN_GAP_S 冷却保护（风暴合并）；
    trigger="sweep" 为低频兜底巡检（恢复/超时/事件丢失兜底）。
    返回本拍执行摘要；无事可做返回 {"activity": None} —— 合法且常见。"""
    now = time.time()
    if trigger == "event":
        if now - _last_reeval_ts[0] < ctx["config"].get(
                "living_min_reeval_gap_s", REEVAL_MIN_GAP_S):
            return {"activity": None, "why": "cooldown_merged"}   # 合并处理
    _last_reeval_ts[0] = now
    if ctx["busy"]():
        return {"activity": None, "why": "user_interacting"}       # 用户优先
    with _STATE_LOCK:
        state = _load_state()
    prev = state.get("_last_activity") or {}
    best, best_score, prev_score = None, THRESHOLD, 0.0
    cands = []          # (name, score, beat_f) 全合格候选：首选被环境
    # 挡住（unavailable：user_playing/桥不通/预算…）时，同拍让位次优——
    # 想玩被占≠这一拍白活（2026-10-19 用户设计）。
    for name, avail_f, appeal_f, beat_f in ACTIVITIES:
        try:
            ok, _why = avail_f(ctx)
            if not ok:
                continue
            last = float(state.get(name, {}).get("last_ts", 0) or 0)
            if now - last < MIN_GAP_S:
                continue
            raw = float(appeal_f(ctx, state))
            score = raw * _drive_scale(ctx, name)
            if name == "sts2":
                logger.info("[Act] sts2 乘后：raw=%.2f score=%.2f "
                            "(prev=%s prev_score=%.2f)", raw, score,
                            prev.get("name"), prev_score)
            # 事件环境加成（2026-10-18 泛化）："发生了什么"接进既有比较，
            # 而非新状态机。browse 的顺风有两个真实来源——刚有新信息值得
            # 看、或研究刚撞墙（此路挖尽→出门找新料，设计2）。取单一乘子
            # 不叠乘（同一次竞争里 browse 只被"环境"抬一次），且必须 raw>0
            # （没内容可逛时不凭空造欲望，尊重 novelty_discount/预算硬闸）。
            if name == "browse" and raw > 0 and (
                    recent_event("new_info")
                    or recent_event("research_stalled")):
                score *= 1.25
            if name == prev.get("name") and now - float(prev.get("ts", 0)) < 3600:
                prev_score = score
            if score > best_score:
                best, best_score = name, score
            if score > THRESHOLD:
                cands.append((name, score, beat_f))
        except Exception:                         # noqa: BLE001
            continue
    # 连续性迟滞（2026-10-15 SN）：改道判定统一走 switch_gate——
    # 候选须明显（+margin）超出当前承诺才切；sn 关闭回退旧乘式迟滞。
    _sw = False
    try:
        import cognitive_field as _CF
        _sn2 = _CF.salience_network()
        if _sn2.enabled and best != prev.get("name"):
            _sw, _m = _sn2.switch_gate(prev_score, best_score)
            _sw = not _sw        # switch_gate 判"该切换"；此处要的是"该坚守"
        else:
            _sw = (best != prev.get("name") and prev.get("name")
                   and prev_score >= best_score * STICK_MARGIN)
    except Exception:             # noqa: BLE001
        _sw = (best != prev.get("name") and prev.get("name")
               and prev_score >= best_score * STICK_MARGIN)
    ranked = sorted(cands, key=lambda x: -x[1])
    if _sw:
        for i, row in enumerate(ACTIVITIES):
            if row[0] == prev.get("name"):
                best, best_score = prev["name"], prev_score
                # 坚守=把旧承诺放到尝试队首（不能只插进 cands 再被
                # sorted 拍平——D1 回归钉）；不在候选里的旧承诺也入队。
                ranked = [(prev["name"], prev_score, row[3])] + [
                    c for c in ranked if c[0] != prev["name"]]
                break
    else:
        pass  # ranked 已按分数降序
    if best is None:
        _set_presence(None)
        _sts2_put_down_if_unwanted(ctx, state)   # 无事可做≠留桌占运存
        with _STATE_LOCK:
            _save_state(state)
        return {"activity": None, "why": "nothing_worth_doing",
                "trigger": trigger}
    if best != "sts2":
        _sts2_put_down_if_unwanted(ctx, state)   # 选了别的活动且尖塔凉透
    logger.info("[Act] %s 唤醒重评估→想做：%s（程度 %.2f，上次 %s）",
                trigger, best, best_score, prev.get("name") or "无")
    result = {"activity": None, "why": "no_candidate"}
    executed = None
    for name, score, beat_f in ranked[:3]:       # 分级尝试，最多三名
        _set_presence(name)      # 可见性：她在过日子，UI 该知道
        result = beat_f(ctx, state)
        if result.get("result") == "unavailable":
            # 环境挡路≠她不想干——让路，同拍试下一个愿望
            logger.info("[Act] %s 被环境挡住(%s)→让位次优",
                        name, str(result.get("why") or "?")[:24])
            continue
        executed = (name, score)
        break
    if executed is None:
        executed = (ranked[0][0], ranked[0][1])   # 全被挡：记首选的让路
    if result.get("done") is not True:
        _set_presence(None)
    state["_last_activity"] = {"name": executed[0], "ts": now}
    with _STATE_LOCK:
        _save_state(state)
    result["appeal"] = round(executed[1], 3)
    result["trigger"] = trigger
    return result


def _set_presence(activity: str | None):
    """把生活动态映射到 avatar_state 协议（speaking 归话语，其余活动统一
    thinking——她在"忙一件事"；安静=idle）。Charon 徽标/ghost 渲染端共用。"""
    try:
        import avatar_state
        avatar_state.set_state("thinking" if activity else "idle",
                               source=f"activities:{activity or 'quiet'}")
    except Exception:                             # noqa: BLE001
        pass


def reset_state_for_test(path_override=None):
    """测试钩子：把状态文件指到临时路径（避免污染宿主）。"""
    global _STATE_PATH_OVERRIDE
    _STATE_PATH_OVERRIDE = path_override
