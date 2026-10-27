# -*- coding: utf-8 -*-
"""技能/活动插件加载器（2026-10-26，插件协议 v0）。

两个可选插件目录，FAS 启动时扫描：
  data/activities_plugins/*.py  生活活动（available/appeal/beat 三函数）
  data/skill_plugins/*.py       动作技能（CONCEPTS 定义 + Skill 子类）

安全模型（docs/PLUGINS.md §4）：
  · 活动插件：只读或写图（经既有漏斗），默认加载；
  · 技能插件：执行侧，需 config_overlay `"skill_plugins_enabled": true`
    才加载（默认关）。
失败隔离：单个插件异常记日志跳过，绝不影响主循环。

活动插件返回值与内置活动完全同构（见 activities.ACTIVITIES 表）；
技能插件挂进 skills.base.REGISTRY 与 action_concepts.ACTION_CONCEPTS，
经既有 resolve→propose→settle 管线执行，无旁路。
"""
import logging
import os

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓库根（本文件在 FAS-Cognitive/ 内）
ACTIVITY_PLUGIN_DIR = os.path.join(_ROOT, "data", "activities_plugins")
SKILL_PLUGIN_DIR = os.path.join(_ROOT, "data", "skill_plugins")


def _import_file(path: str, module_name: str):
    import importlib.util as ilu
    spec = ilu.spec_from_file_location(module_name, path)
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_activity_plugins():
    """返回 [(name, available, appeal, beat), ...]，与 ACTIVITIES 同构。
    模块级缓存；半成品插件（缺函数）拒载。"""
    out = []
    if not os.path.isdir(ACTIVITY_PLUGIN_DIR):
        return out
    for fn in sorted(os.listdir(ACTIVITY_PLUGIN_DIR)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        name = fn[:-3]
        try:
            mod = _import_file(os.path.join(ACTIVITY_PLUGIN_DIR, fn),
                               "activity_plugin_" + name)
            av = getattr(mod, "available", lambda ctx: True)
            ap = getattr(mod, "appeal", lambda ctx: 0.2)
            bt = getattr(mod, "beat", None)
            if bt is None:
                raise ValueError("missing beat(ctx, state)")
            out.append((name, av, ap, bt))
            logger.info("[Plugins] 活动插件加载: %s", name)
        except Exception as e:
            logger.warning("[Plugins] 活动插件加载失败(跳过) %s: %r", fn, e)
    return out


def load_skill_plugins(config: dict = None):
    """加载 data/skill_plugins/*.py：
      · 模块内 CONCEPTS = [dict]（action_concepts.ActionConcept 字段）
        → 注册进 action_concepts.ACTION_CONCEPTS（对话可触发）；
      · 模块内 Skill 子类（name/check/start/poll/cancel 契约）
        → @register 进 skills.base.REGISTRY（可执行）。
    开关：config_overlay `"skill_plugins_enabled": true`（默认关）。
    返回加载的插件名列表。"""
    if not (config or {}).get("skill_plugins_enabled", False):
        logger.info("[Plugins] 技能插件未启用（skill_plugins_enabled=false）")
        return []
    loaded = []
    if not os.path.isdir(SKILL_PLUGIN_DIR):
        return loaded
    # 延迟导入：skills/action_concepts 只在技能插件启用时才需要
    from skills import base as skill_base
    from action_concepts import ACTION_CONCEPTS, ActionConcept
    for fn in sorted(os.listdir(SKILL_PLUGIN_DIR)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        name = fn[:-3]
        try:
            mod = _import_file(os.path.join(SKILL_PLUGIN_DIR, fn),
                               "skill_plugin_" + name)
            n_concepts = 0
            for c in (getattr(mod, "CONCEPTS", None) or []):
                cc = ActionConcept(**c)
                ACTION_CONCEPTS[cc.concept_id] = cc
                n_concepts += 1
            n_skills = 0
            for obj in (getattr(mod, "SKILLS", None) or
                        [v for k, v in vars(mod).items()
                         if isinstance(v, type)
                         and getattr(v, "name", "")
                         and issubclass(v, skill_base.Skill)
                         and v is not skill_base.Skill]):
                skill_base.register(obj)
                n_skills += 1
            loaded.append(name)
            logger.info("[Plugins] 技能插件加载: %s（概念 %d, 技能 %d）",
                        name, n_concepts, n_skills)
        except Exception as e:
            logger.warning("[Plugins] 技能插件加载失败(跳过) %s: %r", fn, e)
    return loaded
