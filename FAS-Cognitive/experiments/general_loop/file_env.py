# file_env.py — 文件整理沙盒（**只能操作构造时给定的测试根目录**，
# 路径越界与未知算子一律硬拒；无删除算子——约束"不得删除"由算子
# 集合本身保证 + execute 白名单复核）
# 谓词：loc:<file>:<dir>  dir_exists:<d>  sandbox_root:<root>
import os
import shutil


class FileEnv:
    def __init__(self, root, dirs, files):
        """files: {name: dir}。root 外一切拒绝。"""
        self.root = os.path.abspath(root)
        self.dirs = list(dirs)
        self.files = dict(files)
        self.log = []
        os.makedirs(self.root, exist_ok=True)
        for d in self.dirs:
            os.makedirs(os.path.join(self.root, d), exist_ok=True)
        for name, d in self.files.items():
            p = os.path.join(self.root, d, name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            if not os.path.exists(p):
                with open(p, "w", encoding="utf-8") as f:
                    f.write(f"test file {name}")

    def universe(self):
        return {"file": sorted(self.files), "dir": self.dirs}

    def snapshot(self):
        s = {f"sandbox_root:{os.path.basename(self.root)}"}
        for d in self.dirs:
            s.add(f"dir_exists:{d}")
        for name, d in self.files.items():
            if d is not None:
                s.add(f"loc:{name}:{d}")
        return s

    def ops(self):
        out = []
        for name in self.files:
            for a in self.dirs:
                for b in self.dirs:
                    if a == b:
                        continue
                    out.append({"name": "mv", "args": {"file": name,
                                                       "from": a, "to": b},
                                "pre": [f"loc:{name}:{a}",
                                        f"dir_exists:{b}"],
                                "add": [f"loc:{name}:{b}"],
                                "del": [f"loc:{name}:{a}"],
                                "template": "mv"})
        return out

    def _in_root(self, *parts):
        p = os.path.abspath(os.path.join(self.root, *parts))
        return p if p.startswith(self.root + os.sep) or p == self.root \
            else None

    def execute(self, action):
        name = action["name"]
        args = action["args"]
        if name != "mv":
            self.log.append({"action": name, "ok": False,
                             "reason": "op_not_in_universe"})
            return {"ok": False, "reason": "op_not_in_universe"}
        src = self._in_root(args["from"], args["file"])
        dstdir = self._in_root(args["to"])
        dpath = self._in_root(args["to"], args["file"])
        if not src or not dpath:
            self.log.append({"action": "mv", "ok": False,
                             "reason": "path_escape_denied"})
            return {"ok": False, "reason": "path_escape_denied"}
        if self.files.get(args["file"]) != args["from"]:
            self.log.append({"action": "mv", "ok": False,
                             "reason": "not_where_env_thinks"})
            return {"ok": False, "reason": "not_where_env_thinks"}
        if not os.path.exists(src):
            self.log.append({"action": "mv", "ok": False,
                             "reason": "file_missing_on_disk"})
            return {"ok": False, "reason": "file_missing_on_disk"}
        if os.path.exists(dpath):
            self.log.append({"action": "mv", "ok": False,
                             "reason": "dst_conflict"})
            return {"ok": False, "reason": "dst_conflict"}
        shutil.move(src, dpath)
        self.files[args["file"]] = args["to"]
        self.log.append({"action": "mv", "args": args, "ok": True,
                         "reason": ""})
        return {"ok": True, "reason": ""}

    # ── 磁盘真实态构建 / 跨进程恢复（阶段 C）──
    @classmethod
    def from_disk(cls, root, dirs):
        root = os.path.abspath(root)
        os.makedirs(root, exist_ok=True)
        for d in dirs:
            os.makedirs(os.path.join(root, d), exist_ok=True)
        files = {}
        for d in dirs:
            for fn in sorted(os.listdir(os.path.join(root, d))):
                if os.path.isfile(os.path.join(root, d, fn)):
                    files[fn] = d
        e = cls(root, list(dirs), {})
        e.files = files
        return e

    def state(self):
        return {"root": self.root, "dirs": list(self.dirs),
                "files": dict(self.files)}

    @classmethod
    def restore(cls, st):
        e = cls(st["root"], st["dirs"], {})
        e.files = dict(st["files"])
        return e

    def full_state(self):
        return {"files": dict(self.files), "log": list(self.log),
                "on_disk": {d: sorted(os.listdir(os.path.join(
                    self.root, d))) for d in self.dirs}}
