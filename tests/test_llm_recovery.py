# -*- coding: utf-8 -*-
"""LLM 恢复路径测试（P0-3）：超时配置、failover 判定、换供应商、不掩盖真错误。

运行：python tests/test_llm_recovery.py（脚本式，全离线——网络路径用 monkeypatch）
"""
import httpx
import os
import sys
import tempfile

_r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _r)
# split_repos bootstrap: FAS-Cognitive sibling
_cog = os.environ.get("FAS_COG_ROOT") or os.path.join(
    os.path.dirname(_r), "FAS-Cognitive")
if os.path.isdir(_cog) and _cog not in sys.path:
    sys.path.insert(0, _cog)

import openai
from llm_provider import OpenAICompatBackend, _KNOWN_BACKEND_CLASSES

# 测试隔离（2026-10-13 实锤教训：本测试的假供应商调用曾写进生产
# data/usage_ledger.jsonl——"FakePrimary" 混进真实用量统计）。
import usage_ledger as _ul
_ul._PATH = os.path.join(tempfile.mkdtemp(), "usage.jsonl")

FAILURES = []
TOTAL = [0]


def check(name, cond):
    TOTAL[0] += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILURES.append(name)


# ── 客户端构造：显式超时 + 禁 SDK 静默重试 ──
os.environ.setdefault("MIMO_API_KEY", "test-key")
b = OpenAICompatBackend.__subclasses__()[0](api_key="k", base_url="http://x")
req = b._raw_client
check("应用级超时已设置（非 SDK 默认 600s）",
      getattr(req, "timeout", None) is not None
      and float(b._timeout_s) <= 180)
check("SDK 静默重试关闭（failover 显式接管）", req.max_retries == 0)

# ── _failoverable 分类 ──
conn = openai.APIConnectionError(request=httpx.Request("POST", "http://x"))
class _St(openai.APIError):
    def __init__(self, code):
        self.status_code = code
        super().__init__("x", request=None, body=None)
check("连接错误可 failover", OpenAICompatBackend._failoverable(conn))
check("429 可 failover", OpenAICompatBackend._failoverable(_St(429)))
check("503 可 failover", OpenAICompatBackend._failoverable(_St(503)))
check("400 不 failover（请求本身错误原样上抛）",
      not OpenAICompatBackend._failoverable(_St(400)))
check("普通代码异常不 failover",
      not OpenAICompatBackend._failoverable(ValueError("bug")))

# ── failover 成功路径（离线桩） ──
class FakeB(OpenAICompatBackend):
    _ENV_KEY = "PRIMARY_TEST_KEY"
    _LABEL = "FakePrimary"
    _DEFAULT_MODEL = "fake-p"


class FallbackSpec:
    _ENV_KEY = "SECONDARY_TEST_KEY"
    _ENV_URL = "SECONDARY_TEST_URL"
    _LABEL = "FakeSecondary"
    _DEFAULT_MODEL = "fake-s"
    _DEFAULT_BASE_URL = "http://secondary"
    _USE_MAX_COMPLETION_TOKENS = False


import llm_provider as LP
_orig_known = LP._KNOWN_BACKEND_CLASSES
orig_openai = openai.OpenAI
sentinel = object()
calls = []


class FakeCompletions:
    def create(self, **kw):
        calls.append(kw)
        if kw["model"] == "fake-p":
            raise conn
        return sentinel


class FakeChat:
    completions = FakeCompletions()


class FakeClient:
    def __init__(self, **kw):
        self.chat = FakeChat()


os.environ["SECONDARY_TEST_KEY"] = "sk-fake"
try:
    LP._KNOWN_BACKEND_CLASSES = [FakeB, FallbackSpec]
    openai.OpenAI = FakeClient
    fb_b = FakeB(api_key="k", base_url="http://primary")
    fb_b._raw_client = FakeClient()      # .chat.completions.create 抛 conn
    resp = fb_b._create([{"role": "user", "content": "hi"}])
    check("主链路瞬时故障后 failover 返回备用响应", resp is sentinel)
    check("备用请求使用备用模型", calls and calls[-1]["model"] == "fake-s")
    check("备用请求不带 response_format（最大兼容）",
          "response_format" not in calls[-1])
finally:
    openai.OpenAI = orig_openai
    LP._KNOWN_BACKEND_CLASSES = _orig_known
    os.environ.pop("SECONDARY_TEST_KEY", None)

# ── failover 全失败 → 原异常上抛（不掩盖） ──
class DeadFallback(FallbackSpec):
    pass


class FakeCompletions2:
    def create(self, **kw):
        raise conn


try:
    LP._KNOWN_BACKEND_CLASSES = [FakeB, DeadFallback]
    openai.OpenAI = lambda **kw: type("C", (), {"chat": type("H", (), {"completions": FakeCompletions2()})})()
    b2 = FakeB(api_key="k", base_url="http://p")
    b2._raw_client = type("C", (), {"chat": type("H", (), {"completions": FakeCompletions2()})})()
    try:
        b2._create([{"role": "user", "content": "hi"}])
        check("全失败仍上抛原异常", False)
    except openai.APIConnectionError:
        check("全失败仍上抛原异常", True)
finally:
    openai.OpenAI = orig_openai
    LP._KNOWN_BACKEND_CLASSES = _orig_known

# ── 注册表完整性（真实供应商） ──
check("failover 注册表含 MiMo/DeepSeek", len(_KNOWN_BACKEND_CLASSES) >= 2)

print(f"\nLLM 恢复：{TOTAL[0] - len(FAILURES)}/{TOTAL[0]} 通过")
sys.exit(1 if FAILURES else 0)
