# -*- coding: utf-8 -*-
"""技能插件示例：家里灯光（demo 用——execute 打印而非真控设备）。

CONCEPTS：注册动作概念（对话可触发：她说"关灯"即解析为 LIGHTS_OFF）。
SKILLS：注册可执行技能（name=LIGHTS_OFF，ActionManager 派发到 execute）。

放置位置：data/skill_plugins/lights.py
启用：config_overlay.json 加 "skill_plugins_enabled": true，重启 FAS。
"""

CONCEPTS = [
    {"concept_id": "LIGHTS_OFF", "name_zh": "关灯", "domain": "web",
     "executor": "LIGHTS_OFF",
     "description": "关掉家里的灯（示例技能）",
     "fast_patterns": [r"关灯", r"把灯关[掉上]"],
     "seed_expressions": ["关灯", "把灯关掉", "帮我关灯"],
     "negation": "none"},
]

from skills.base import Skill, register


@register
class LightsOffSkill(Skill):
    name = "LIGHTS_OFF"
    category = "home"
    description = "关掉家里的灯（技能插件示例）"

    def check(self, ctx, params):
        return True, ""

    def start(self, ctx, params):
        # 真实实现处：本地 HomeAssistant API / 硬件 SDK 等
        print("[lights plugin] lights off (demo)")
        return {"status": "done", "describe": "灯已关"}
