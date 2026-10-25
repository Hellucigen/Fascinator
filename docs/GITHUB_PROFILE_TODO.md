# GitHub 个人主页更新指南

你用的是 **fine-grained PAT**（`github_pat_…`），它没有改个人资料（bio/blog）的权限
（403 Resource not accessible）——仓库管理权限是有的（改名/删除/归档都成功了），
唯独 profile 的 bio 属于需要 `user` 类权限的 classic 范围。

## 两个选项

### A. 手动 30 秒改 bio（最快）
打开 https://github.com/settings/profile → Bio 粘贴：

```
构建一个会自己过日子的 AI 伙伴 —— 扩散激活知识图谱 × 情境记忆 × 自主表达 | Fascinator & Charon
```

Website 填：`https://github.com/<USER>/Fascinator`

### B. 给 PAT 补权限（如果你以后想让我代管 profile）
Settings → Developer settings → Personal access tokens →
编辑你现在的 fine-grained token → Account permissions →
勾选 **Profile (read & write)** → 保存。然后跟我说一声，我就能 API 写入。

## PROFILE.md（已推送）

新增了 `PROFILE.md`——虽然你的 username（<USER>）没有同名仓库，
这个文件**不会**自动显示在主页上（只有与 username 同名的仓库的 README.md
才会成为个人主页）。两个用法：

1. **建一个 `<USER>/<USER>` 仓**，把这个文件内容贴进去成 README.md
   —— 它就会渲染成你的 GitHub 主页门面。
2. 或者忽略它，纯当资料留档（也行，内容已经写好）。

要我帮你把 PROFILE.md 内容变成 `<USER>/<USER>` 仓的 README，说一声即可（repo 创建 + 推送全程可自动化）。
