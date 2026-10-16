# reading_env.py — 把既有 ReadingLedger 包装为 taskloop 环境（不复制其逻辑）
# 谓词：read:u{n}（confirmed）、next:u{n}、reading_done。算子 read_unit_n:
# pre next:u{n} → add read:u{n}, next:u{n+1}。execute 委派
# ledger.read_unit —— 进度/证据/恢复仍由 ReadingLedger 持有（复用原则）。
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import reading as RD                                     # noqa: E402


class ReadingEnv:
    def __init__(self, ledger, extractor):
        self.ledger = ledger
        self.extractor = extractor
        self.n = int(ledger.source["total_units"])
        self.exec_log = []

    def universe(self):
        return {"u": [f"u{k}" for k in range(1, self.n + 1)]}

    def snapshot(self):
        s = set()
        d = self.ledger.data[self.ledger.sid]["units"]
        nxt = None
        for k in range(1, self.n + 1):
            st = (d.get(str(k)) or {}).get("status")
            if st == "confirmed":
                s.add(f"read:u{k}")
            elif nxt is None:
                nxt = k
        if nxt is not None:
            s.add(f"next:u{nxt}")
        if nxt is None:
            s.add("reading_done")
        return s

    def ops(self):
        out = []
        for k in range(1, self.n + 1):
            nxt = ["next:u1"] if k == 1 else [f"next:u{k}"]
            add = [f"read:u{k}"] + ([f"next:u{k + 1}"]
                                     if k < self.n else ["reading_done"])
            out.append({"name": f"read_u{k}", "args": {"u": f"u{k}"},
                        "pre": [f"next:u{k}"],
                        "add": add,
                        "del": [f"next:u{k}"],
                        "template": "read_unit"})
        return out

    def execute(self, action):
        k = int(action["args"]["u"][1:])
        snap = self.snapshot()
        if f"next:u{k}" not in snap:
            self.exec_log.append({"action": action, "ok": False,
                                  "reason": "out_of_order"})
            return {"ok": False, "reason": "out_of_order"}
        r = self.ledger.read_unit(k, self.extractor, self._kg(),
                          tl=getattr(self, "tl", None))
        ok = r["status"] == "confirmed"
        self.exec_log.append({"action": action, "ok": ok,
                              "reason": r.get("reason", "")})
        return {"ok": ok, "reason": "" if ok else r.get("reason", "failed")}

    def _kg(self):
        return getattr(self, "kg", None)

    def full_state(self):
        return {"progress": self.ledger.progress_report(),
                "log": list(self.exec_log)}


def make_default_extractor(triples_per_unit=2):
    """离线假抽取器（确定性）：为每单元产出 entities + 少量三元组，
    并留一条可查询事实（供"已读证据回答"验证）。"""
    def ex(text):
        first = " ".join(str(text).split()[:3])
        return {"entities": [f"topic_{first[:20]}"],
                "relations": [{"src": first[:20], "rel": "相关",
                               "dst": "unit_content",
                               "kind": "text", "quote": first[:40]}]}
    return ex
