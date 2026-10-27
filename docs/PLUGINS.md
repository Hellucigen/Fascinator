# 插件开发指南（v0）

三种插件，三种挂载方式。所有插件都是**可选的**——目录不存在时 FAS 行为
与从前完全一致。安全模型见 §4。

## 1. 感知/事件插件（往她的图里喂事实）

外部进程把"世界上发生的事"告诉 FAS。她的图谱是单一事实源：事件会经
episodic 写入成为经历节点，参与扩散、联想、课题选择。

**协议**：HTTP POST 到本机 FAS。

```
POST http://127.0.0.1:5000/api/activate
Content-Type: application/json

{"nodes": ["天气:下雨", "气温:12度"], "energy": 2.0}
```

- 节点 id 是**概念名**（她脑内的词，中文短词最佳，≤16 字符）；
  不存在的节点会自动创建（semantic 空间）。
- energy 是激活注入量（建议 1.0-3.0：太高会挤占真实事件的注意力）。
- 推荐节奏：事件发生时推一次即可；不要轮询式高频推送（会污染焦点）。

**参考实现**：`examples/plugins/weather_sensor.py`（天气感知器 demo——
调用 wttr.in 拿天气，状态变化时才推送）。运行：

```
python examples/plugins/weather_sensor.py
```

她会在下雨时"知道下雨了"，并可能主动跟你提。

## 2. 生活活动插件（给她的日子加一种"想做的事"）

放一个 `.py` 文件到 `data/activities_plugins/`，约定三个函数：

```python
# data/activities_plugins/my_activity.py
def available(ctx) -> bool:
    """现在能不能做这件事（不做会自动让位次优愿望）。"""
    return True

def appeal(ctx) -> float:
    """想做的程度 0~1。可以读 ctx['kg']/ctx['engine'] 自己算。"""
    return 0.3

def beat(ctx, state) -> dict:
    """做这件事。返回 {'done': bool, 'why': str, ...}。
    ctx: {'kg','engine','config','curiosity','drive','nlp',...}
    注意：网络访问要节制（共享每日预算）；写入图谱请走既有漏斗。"""
    return {"done": True, "what": "发呆欣赏落日"}
```

加载规则：目录内 `*.py` 全部加载（`_` 开头跳过）；`available` 为 False 或
appeal 低于候选阈值时自动让位；插件异常被捕获并记日志，不影响主循环。
内置活动（听歌/逛B站/调研…）优先级不变，插件与它们公平竞争。

## 3. 动作技能插件（让她"会做"一类新事）

放一个 `.py` 文件到 `data/skill_plugins/`，约定概念定义 + 执行函数：

```python
# data/skill_plugins/lights.py
CONCEPTS = [  # 注册为动作概念（进入 resolver，可被对话触发）
    {"action_type": "lights_off", "domain": "home",
     "fast_patterns": [r"关灯", r"把灯关"],
     "seed_expressions": ["关灯", "把灯关掉"]},
]

def execute(action: dict, params: dict) -> dict:
    """action_type 匹配时被调用。返回 {'success': bool, 'reason': str}。"""
    if action.get("action_type") == "lights_off":
        # ...你的实现（本地 API / 系统 命令 / 设备 SDK）
        return {"success": True, "result": "lights off"}
    return {"success": False, "reason": "unknown"}
```

安全模型（§4）默认限制见下。

## 4. 安全模型

- **只读本机回环**：感知插件应只推送到 `127.0.0.1:5000`；FAS 默认只监听
  回环，不为插件开放外部端口。
- **技能插件白名单开关**：`config_overlay.json` 加
  `"skill_plugins_enabled": true` 才会加载（默认关）——技能是"执行"侧，
  需要用户显式授权；感知/活动插件只读或写图，默认加载。
- **无网络提权**：插件进程与 FAS 同权限，FAS 不会为插件代理任何
  需要密钥的调用（LLM key 永不下发）。
- **失败隔离**：插件异常一律捕获记日志，绝不可能拖垮认知循环
  （与内置熔断器同一纪律）。
- **图谱纪律**：往图里写东西请用既有入口（/api/activate、episodic_buffer、
  knowledge packs 漏斗）；直接改图结构可能违反 schema 谓词族
  （见 graph_model.py 的 is_* 判定族）。

## 5. 事件下行（她 → 你的插件）

她主动表达/状态变化时，Charon 桥与网页队列收消息；你的插件也可以轮询：

```
GET http://127.0.0.1:5000/api/proactive/poll   # 取走她的主动话语（取走即删）
GET http://127.0.0.1:5000/api/avatar/state     # 她当前在干什么
GET http://127.0.0.1:5000/api/cognition/state  # 意图/阈值/场状态
```

轮询建议 ≥30s 间隔；proactive poll 是消费型接口（取走即删），只挂一个
消费者。
