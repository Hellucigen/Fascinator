# -*- coding: utf-8 -*-
"""天气感知器 demo —— 感知/事件插件参考实现。

世界下雨了 → 告诉她。状态变化时才推送（不轮询刷屏）。
依赖：仅标准库 + wttr.in（免 key）。只写本机回环。
"""
import json
import time
import urllib.request

FAS = "http://127.0.0.1:5000"
POLL_S = 600          # 10 分钟看一次天
WEATHER_URL = "https://wttr.in/?format=j1"


def post_activate(nodes, energy=1.5):
    req = urllib.request.Request(
        FAS + "/api/activate",
        data=json.dumps({"nodes": nodes, "energy": energy}).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


def fetch_weather():
    with urllib.request.urlopen(WEATHER_URL, timeout=10) as r:
        d = json.load(r)
    cur = d["current_condition"][0]
    desc_cn = cur.get("lang_zh", [{}])[0].get("value") or cur["weatherDesc"][0]["value"]
    return {"desc": desc_cn, "tempC": int(cur["temp_C"]),
            "code": int(cur["weatherCode"])}


def describe(w):
    rain = ("雨" in w["desc"]) or ("雪" in w["desc"])
    nodes = [f"天气:{w['desc']}", f"气温:{w['tempC']}度"]
    if rain:
        nodes.append("下雨")
    if w["tempC"] <= 5:
        nodes.append("降温")
    return nodes, rain


def main():
    last_sig = None
    while True:
        try:
            w = fetch_weather()
            nodes, rain = describe(w)
            sig = (w["desc"], w["tempC"])
            if sig != last_sig:                      # 状态变化才推
                post_activate(nodes, 2.0 if rain else 1.2)
                print(time.strftime("%H:%M"), "推送:", nodes)
                last_sig = sig
        except Exception as e:
            print(time.strftime("%H:%M"), "err:", repr(e)[:80])
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
