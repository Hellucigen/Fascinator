# -*- coding: utf-8 -*-
"""graph_bridges — 跨包/跨存量节点的定点桥边（startup 后补，幂等）。

为什么不放进 pack：pack 在 runtime 之上合并前加载，引用 runtime 节点的边
会以悬空边被丢。这里在 kg 完整构建后统一补，**每对端点都经代码验证存在于
当时图谱才落边**；全部走既有 add_edge（端点校验、schema hub 检查照常）。

关系词取 graph_schema 规范本体。certainty=likely 的统计倾向绝不用"导致"。
"""
import logging

logger = logging.getLogger("graph_bridges")

# (src, relation, dst, certainty)
BRIDGES = [
    # 用户世界的具体物 ↔ 通用音乐结构（实例/使用层）
    ("网易云音乐", "使用", "搜索歌曲", "general"),
    ("歌曲《吸吐》", "实例属于", "歌曲", "general"),
    ("听歌—对象—吸吐", "使用", "歌词", "general"),
    ("音乐唱片", "是", "音乐作品", "general"),        # MC 实体桥（id 存在才落）
    ("专辑", "包含", "音乐作品", "general"),
    # 感知/情绪对齐既有节点
    ("能力_听觉感知", "相关", "听觉体验", "general"),
    ("消极情绪", "相关", "悲伤", "general"),
    ("消极情绪", "相关", "孤独感", "general"),
    ("情绪低落", "相关", "悲伤", "general"),
    # 时段桶（temporal 体系既有节点）↔ 活动
    ("听音乐", "发生于", "晚上", "likely"),
    ("听音乐", "发生于", "深夜", "likely"),
    ("提神", "发生于", "上午", "likely"),
    # 两知识包之间的跨域桥
    ("整理房间", "影响", "专注提升", "likely"),
    ("休息", "可实现为", "听音乐", "likely"),
    ("锻炼", "诱发", "振奋", "likely"),
    # 记忆/个人层与既有 episodic 生态
    ("个人音乐记忆", "属于", "经历记忆", "general"),
    ("老歌", "关于", "怀旧效应", "general"),
    ("习惯养成_音乐", "先于", "喜欢的歌", "likely"),
]


def ensure_bridges(kg, engine=None, save=False):
    """kg 上幂等补桥。返回 {'added': [...], 'skipped_missing': [...]}。"""
    from graph_model import Edge
    added, missing, dup = [], [], 0
    with kg._lock:
        for src, rel, dst, cert in BRIDGES:
            if src not in kg.nodes or dst not in kg.nodes:
                missing.append((src, rel, dst))
                continue
            if kg.get_edge(src, dst, rel):
                dup += 1
                continue
            kg.add_edge(Edge(src=src, dst=dst, relation=rel,
                             weight=0.5 if cert == "general" else 0.35,
                             extra_attrs={"certainty": cert,
                                          "source": "graph_bridges@2026-10-13"}))
            added.append((src, rel, dst))
        if save and added and engine is not None:
            pass
    logger.info("[Bridges] +%d 条桥边（重复跳过 %d，端点缺席 %d）",
                len(added), dup, len(missing))
    return {"added": added, "skipped_missing": missing, "dup": dup}
