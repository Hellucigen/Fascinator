# -*- coding: utf-8 -*-
"""build_knowledge_packs.py — 通用知识包生成器（2026-10-13 图谱扩展）。

产出 FAS-Cognitive/knowledge_packs/{music_emotion,life_causality}/：
  · knowledge_graph.json + metadata.json（既有 PackManager 格式）
  · 幂等可重跑；对齐：读取 data/runtime_graph.json——**已存在的节点不重建**
    （实体对齐=命名一致优先；仅相似的不同实体绝不误并）。
  · 跨域桥边**不放包里**（pack 加载顺序在 runtime 前，引用 runtime 节点会被
    当悬空边丢）——由 companion 启动后 ensure_bridges() 定点补，见
    graph_bridges.py。

关系词全部取 graph_schema 规范本体表（否则会被同义表吞成"关联"）：
  是/属于/包含/具有/实例/使用/需要/发生于/诱发/影响/调节/针对/关于/经历/记得…
认识论标注在 extra_attrs：epistemic=general（世界常识）| likely（统计倾向，
绝不冒充因果）；source/version 可追溯。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COG = os.environ.get("FAS_COG_ROOT") or os.path.join(
    os.path.dirname(HERE), "FAS-Cognitive")
OUT_ROOT = os.path.join(COG, "knowledge_packs")
SOURCE = "knowledge_pack_v1:2026-10-13"
RUNTIME = os.path.join(HERE, "data", "runtime_graph.json")


def _n(id_, weight=0.5, conf=0.6, epistemic="general", note="",
       label="declarative-semantic", space="semantic"):
    return {"id": id_, "weight": weight, "activation": 0.0, "label": label,
            "graph_space": space, "execution": None, "confidence": conf,
            "extra_attrs": {"type": "prior_concept", "source": SOURCE,
                            "epistemic": epistemic,
                            **({"note": note} if note else {})}}


def _e(src, rel, dst, certainty="general", w=None):
    """调用习惯：_e(源, 关系词, 目标) —— 关系词全部取 graph_schema 规范本体。"""
    return {"src": src, "dst": dst, "relation": rel,
            "weight": w if w is not None else (
                0.5 if certainty == "general" else 0.35),
            "extra_attrs": {"certainty": certainty, "source": SOURCE}}


# ══════════════════════ music_emotion ══════════════════════
ME_NODES = [
    # 作品结构（本体层级）
    _n("歌曲", note="音乐的人声短篇作品"), _n("歌词"), _n("旋律"), _n("和声"),
    _n("音色"), _n("力度", note="音量强弱变化"), _n("速度_音乐", note="快慢( BPM )",
       epistemic="general"), _n("演唱"), _n("乐器"), _n("专辑"),
    _n("背景音乐", note="伴随其他活动的非注意中心音乐"),
    _n("慢歌"), _n("快歌"), _n("纯音乐", note="无人声"), _n("民谣"), _n("摇滚"),
    _n("说唱"), _n("抒情歌"),
    # 听觉属性与感知
    _n("听觉体验"), _n("音量"), _n("音高"), _n("柔和", epistemic="general"),
    _n("刺耳"), _n("动感", note="节奏激起的身体反应"), _n("听觉疲劳"),
    _n("能量感", note="音乐传达的强弱兴醒度"),
    # 主题（歌词/作品所表达）
    _n("离别"), _n("爱情"), _n("失恋"), _n("成长"), _n("梦想"), _n("自由"),
    _n("自然_主题"), _n("城市生活"), _n("故乡"), _n("青春"),
    # 情绪（作品表达 vs 听者感受分层）
    _n("怀念"), _n("思念"), _n("希望"), _n("平静"), _n("感伤"), _n("温暖"),
    _n("振奋"), _n("孤独感"),
    # 行为
    _n("听音乐"), _n("唱歌"), _n("搜索歌曲"), _n("分享歌曲"), _n("收藏歌曲"),
    _n("单曲循环"), _n("现场演出"), _n("放音乐当背景"),
    # 作用/机制（全部 likely=统计倾向，非必然）
    _n("情绪调节", note="改变情绪状态的一般过程"), _n("放松"), _n("专注提升"),
    _n("提神"), _n("记忆唤起"), _n("怀旧效应", note="老歌触发当年情境记忆"),
    _n("背景音效应", note="音乐对任务表现的影响视任务与人而定"),
    _n("入睡困难缓解"), _n("情绪传染_音乐", note="作品情绪向听者传递的现象"),
    # 场景
    _n("通勤"), _n("睡前"), _n("运动中"), _n("工作时"), _n("学习时"),
    _n("雨天"), _n("聚会"), _n("咖啡馆场景"), _n("夜晚独处"),
    # 个人经历槽位（与运行时事件层桥接点）
    _n("个人音乐记忆", weight=0.6, note="某人在某时某地听某歌的经历之总类",
       space="episodic", label="declarative-episodic"),
    _n("喜欢的歌", weight=0.6), _n("习惯养成_音乐"),
]

ME_EDGES = [
    # 作品结构
    _e("歌曲", "是", "音乐作品"),
]
# "音乐作品"未在现有概念中——补节点并在包内成层级
ME_NODES.append(_n("音乐作品", note="创作出的音乐实体总称"))
ME_EDGES = [
    _e("歌曲", "是", "音乐作品"), _e("纯音乐", "是", "音乐作品"),
    _e("背景音乐", "是", "音乐作品"),
    _e("音乐作品", "属于", "音乐"),
    _e("歌词", "组成部分", "歌曲"), _e("旋律", "组成部分", "歌曲"),
    _e("和声", "组成部分", "歌曲"), _e("演唱", "组成部分", "歌曲"),
    _e("音色", "组成部分", "音乐"), _e("力度", "组成部分", "音乐"),
    _e("速度_音乐", "组成部分", "音乐"), _e("节奏", "组成部分", "音乐"),
    _e("旋律", "具有", "音高"), _e("旋律", "具有", "和声"),
    _e("乐器", "产生", "音色"), _e("演唱", "产生", "音色"),
    _e("专辑", "包含", "音乐作品"),
    _e("民谣", "属于", "音乐风格"), _e("摇滚", "属于", "音乐风格"),
    _e("说唱", "属于", "音乐风格"), _e("抒情歌", "属于", "音乐风格"),
    _e("流行音乐", "属于", "音乐风格"), _e("电子音乐", "属于", "音乐风格"),
    _e("慢歌", "具有", "速度_音乐"), _e("快歌", "具有", "速度_音乐"),
    # 听觉
    _e("音乐", "作用于", "听觉体验"),
    _e("听觉体验", "属于", "听觉"),   # 既有节点在包外，包内自锚
    _e("音量", "具有", "力度"),
    _e("刺耳", "是", "音色"), _e("柔和", "是", "音色"),
    _e("动感", "诱发", "快歌"), _e("快歌", "具有", "动感"),
    _e("音量", "影响", "听觉疲劳"),
    _e("能量感", "具有", "快歌"), _e("抒情歌", "具有", "能量感"),
    # 主题：作品表达层（一般知识，"针对"=内容所指）
    _e("歌词", "针对", "离别"), _e("歌词", "针对", "爱情"),
    _e("歌词", "针对", "成长"), _e("歌词", "针对", "故乡"),
    _e("民谣", "针对", "故乡"), _e("民谣", "针对", "青春"),
    _e("抒情歌", "针对", "爱情"), _e("失恋歌曲占多", "关于", "失恋"),
    _e("摇滚", "针对", "自由"), _e("说唱", "针对", "城市生活"),
    # 情绪：作品表达 ≠ 听者感受（两层分开，感受全用"诱发"+likely）
    _e("离别", "针对", "思念"), _e("离别", "针对", "感伤"),
    _e("故乡", "针对", "怀念"), _e("青春", "针对", "怀念"),
    _e("梦想", "针对", "希望"), _e("爱情", "针对", "温暖"),
    _e("失恋", "针对", "孤独感"), _e("慢歌", "诱发", "平静", certainty="likely"),
    _e("慢歌", "诱发", "感伤", certainty="likely"),
    _e("快歌", "诱发", "振奋", certainty="likely"),
    _e("摇滚", "诱发", "振奋", certainty="likely"),
    _e("悲伤的音乐", "诱发", "难过", certainty="likely",
       ) if False else _e("抒情歌", "诱发", "感伤", certainty="likely"),
    # 行为
    _e("听音乐", "需要", "播放设备"),
    _e("听音乐", "作用于", "情绪调节"),
    _e("听音乐", "发生于", "通勤"), _e("听音乐", "发生于", "睡前"),
    _e("听音乐", "发生于", "运动中"), _e("听音乐", "发生于", "工作时"),
    _e("背景音乐", "发生于", "工作时"), _e("背景音乐", "发生于", "学习时"),
    _e("搜索歌曲", "使用", "音乐平台"), _e("分享歌曲", "属于", "表达行为"),
    _e("单曲循环", "影响", "听觉疲劳", certainty="likely"),
    _e("唱歌", "使用", "演唱"),
    # 作用（一律 likely：统计倾向，允许因人而异）
    _e("情绪调节", "可实现为", "听音乐"),
    _e("听音乐", "影响", "放松", certainty="likely"),
    _e("慢歌", "影响", "入睡困难缓解", certainty="likely"),
    _e("背景音乐", "影响", "专注提升", certainty="likely"),
    _e("快歌", "影响", "提神", certainty="likely"),
    _e("怀旧效应", "关于", "老歌"), _e("老歌", "诱发", "记忆唤起",
                                    certainty="likely"),
    _e("音乐作品", "诱发", "怀旧效应", certainty="likely"),
    _e("情绪传染_音乐", "关于", "能量感"),
    _e("背景音效应", "关于", "工作时"),
    # 个人经历层（模板节点——具体经历由运行时事件写入，这里给锚）
    _e("个人音乐记忆", "属于", "经历记忆"),
    _e("喜欢的歌", "关于", "个人音乐记忆"),
    _e("怀旧效应", "关于", "个人音乐记忆"),
    _e("老歌", "影响", "喜欢的歌", certainty="likely"),
    _e("习惯养成_音乐", "影响", "喜欢的歌", certainty="likely"),
    _e("歌词", "针对", "自然_主题"),
    _e("收藏歌曲", "需要", "音乐平台"),
    _e("现场演出", "使用", "演唱"),
    _e("放音乐当背景", "产生", "背景音乐"),
    _e("悲伤的音乐", "诱发", "感伤", certainty="likely"),
    _e("悲伤的音乐", "诱发", "难过", certainty="likely"),
    _e("大声_持续", "是", "音量"),
    _e("大声_持续", "影响", "听觉疲劳", certainty="likely"),
    _e("难过", "相关", "感伤"),
    # 场景细化
    _e("夜晚独处", "属于", "场景"), _e("雨天", "属于", "场景"),
    _e("睡前", "属于", "场景"), _e("通勤", "属于", "场景"),
    _e("雨天", "诱发", "平静", certainty="likely"), _e("雨天", "诱发", "感伤",
                                                    certainty="likely"),
    _e("聚会", "需要", "快歌", certainty="likely"),
    _e("咖啡馆场景", "需要", "背景音乐", certainty="likely"),
]
ME_NODES += [
    _n("音乐"),          # 包内锚点（与 runtime 同名=merge 时以先加载的 pack 为底，
                          # runtime 值随后覆盖；边仍指向它）
    _n("音乐风格"), _n("听觉"), _n("节奏"), _n("流行音乐"), _n("电子音乐"),
    _n("播放设备"), _n("音乐平台"), _n("表达行为"), _n("场景"),
    _n("老歌", note="与某人某段岁月绑定过的作品"),
    _n("经历记忆"), _n("难过"), _n("大声_持续"), _n("失恋歌曲占多"),
    _n("悲伤的音乐"),
]

# ══════════════════════ life_causality ══════════════════════
LC_NODES = [
    # 事件与行动结构骨架
    _n("事件"), _n("参与者"), _n("场所"), _n("前提条件"), _n("后果"),
    _n("障碍"), _n("应对方式"), _n("策略"), _n("证据"), _n("例外"),
    _n("经验总结", note="行动结果沉淀成的可复用知识"),
    # 日常
    _n("锻炼"), _n("休息"), _n("做饭"), _n("整理房间"), _n("喝水"),
    _n("道歉"), _n("和解"), _n("冲突"), _n("合作"), _n("计划"), _n("行动"),
    _n("结果"), _n("学习_个体", note="从经验获得持久变化", label="declarative-semantic"),
    _n("挫折感"), _n("目标受阻"), _n("策略调整"),
]
LC_EDGES = [
    _e("事件", "包含", "参与者"), _e("事件", "具有", "场所"),
    _e("事件", "具有", "前提条件"), _e("事件", "产生", "后果"),
    _e("行动", "属于", "事件"), _e("计划", "先于", "行动"),
    _e("行动", "针对", "目标" if False else "策略"),
    _e("障碍", "阻碍", "行动"),
    _e("行动", "产生", "结果"), _e("结果", "先于", "经验总结"),
    _e("应对方式", "可实现为", "策略"),
    _e("睡眠不足", "影响", "注意力", certainty="likely"),
    _e("锻炼", "影响", "情绪低落", certainty="likely"),
    _e("锻炼", "属于", "应对方式"),
    _e("休息", "属于", "应对方式"), _e("休息", "影响", "疲劳", certainty="likely"),
    _e("喝水", "影响", "身体状态", certainty="likely"),
    _e("整理房间", "影响", "专注提升", certainty="likely"),
    _e("做饭", "属于", "日常行为"), _e("做饭", "需要", "食材"),
    _e("冲突", "可修复于", "道歉"), _e("道歉", "可达成", "和解"),
    _e("冲突", "产生", "关系压力", certainty="likely"),
    _e("合作", "产生", "信任", certainty="likely"),
    # 失败→情绪→调整（游戏与通用双栖）
    _e("失败", "导致" if False else "诱发", "目标受阻"),
    _e("目标受阻", "诱发", "挫折感", certainty="likely"),
    _e("应对方式", "可实现为", "策略调整"),
    _e("因果关系", "具有", "证据"),
    _e("因果关系", "具有", "例外"),
    _e("经验总结", "属于", "学习_个体"),
    _e("失败", "先于", "经验总结", certainty="likely"),
    # 因果 vs 倾向的元规范（给下游消费的提醒节点）
    _e("统计倾向", "区别于", "因果关系"),
    _e("冲突", "产生", "关系压力", certainty="likely"),
    _e("合作", "产生", "信任", certainty="likely"),
    _e("睡眠不足", "影响", "注意力", certainty="likely"),
    _e("锻炼", "影响", "情绪低落", certainty="likely"),
    _e("休息", "影响", "疲劳", certainty="likely"),
    _e("喝水", "影响", "身体状态", certainty="likely"),
    _e("做饭", "属于", "日常行为"), _e("做饭", "需要", "食材"),
    _e("冲突", "可修复于", "道歉"), _e("道歉", "可达成", "和解"),
]
LC_NODES += [
    _n("统计倾向", note="A常伴B ≠ A必然导致B"), _n("因果关系"),
    _n("日常行为"), _n("注意力"), _n("睡眠不足"), _n("身体状态"), _n("疲劳"),
    _n("食材"), _n("关系压力"), _n("信任"), _n("失败"), _n("情绪低落"),
]

PACKS = {
    "music_emotion": {
        "desc": "音乐-情绪-感官-个人经历跨领域骨架（作品结构/听觉属性/主题/情绪分层/行为场景/作用机制 likely 标注）",
        "nodes": ME_NODES, "edges": ME_EDGES},
    "life_causality": {
        "desc": "事件-行动-因果骨架与日常生活（参与者/前提/后果/应对；统计倾向≠因果；音乐 pack 经 休息/放松/专注提升 共享枢纽桥接）",
        "nodes": LC_NODES, "edges": LC_EDGES},
}


def existing_ids():
    ids = set()
    if os.path.isfile(RUNTIME):
        try:
            raw = json.load(open(RUNTIME, encoding="utf-8"))
            ns = raw["nodes"]
            ids |= {(n["id"] if isinstance(n, dict) else n) for n in ns}
        except (OSError, ValueError, KeyError):
            pass
    for pkg in ("common", "computer", "minecraft"):
        gp = os.path.join(OUT_ROOT, pkg, "knowledge_graph.json")
        if os.path.isfile(gp):
            try:
                raw = json.load(open(gp, encoding="utf-8"))
                ids |= {(n["id"] if isinstance(n, dict) else n)
                        for n in raw.get("nodes", [])}
            except Exception:
                pass
    return ids


def build(dry=False):
    have = existing_ids()
    report = {}
    for name, spec in PACKS.items():
        # 实体对齐策略（2026-10-13 修正）：pack **全量携带**自身节点定义——
        # 与 runtime 重名的锚点（平静/失败/行动…）由 merge→overlay 机制以
        # runtime 值覆盖（pack 先、runtime 后），既不重复建点又保证
        # 包内边端点完整（此前"跳过已有节点"导致这些边在 pack 加载期
        # 作为悬空边被丢——实测 5+ 条跨域边丢失）。
        nodes = spec["nodes"]
        overlapped = sorted({x["id"] for x in nodes} & have)
        idents = {x["id"] for x in nodes}
        spec["edges"] = [e for e in spec["edges"]
                         if isinstance(e, dict) and "src" in e and "dst" in e]
        edges = [e for e in spec["edges"]
                 if e["src"] in idents and e["dst"] in idents]
        drop_edges = [(e["src"], e["dst"], e["relation"]) for e in spec["edges"]
                      if e not in edges]
        report[name] = {"nodes": len(nodes), "anchors_overlaid_with_runtime": overlapped,
                        "edges": len(edges), "edges_dropped": drop_edges[:8]}
        if dry:
            continue
        d = os.path.join(OUT_ROOT, name)
        os.makedirs(d, exist_ok=True)
        json.dump({"nodes": nodes, "edges": edges},
                  open(os.path.join(d, "knowledge_graph.json"), "w",
                       encoding="utf-8"), ensure_ascii=False, indent=1)
        json.dump({"name": name, "type": "semantic", "enabled": True,
                   "priority": 6, "description": spec["desc"],
                   "created": "2026-10-13", "version": 1},
                  open(os.path.join(d, "metadata.json"), "w",
                       encoding="utf-8"), ensure_ascii=False, indent=1)
    return report


if __name__ == "__main__":
    rep = build(dry="--dry" in sys.argv)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
