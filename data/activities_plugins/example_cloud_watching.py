# -*- coding: utf-8 -*-
"""示例活动插件：看云。

一个最小的外部活动插件样板——available/appeal/beat 三函数。
行为：晴天时偶尔"看云发呆"，产生一条轻量体验入图（经既有
episodic 通道由 beat 返回后由宿主登记——这里只做网络禁用示范，
实际用不到网络）。
"""


def available(ctx):
    return True


def appeal(ctx):
    # 晴天加成：白天且场不忙时略高
    return 0.18


def beat(ctx, state):
    return {"done": True, "what": "看着窗外的云发了一会儿呆",
            "result": "done"}
