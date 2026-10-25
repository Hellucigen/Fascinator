# METADATA_AND_LICENSE_OPTIONS.md — 许可与元数据选项(供作者选择;未擅自选定)

## 1. 许可选项(二选一或组合)

| 选项 | 适用范围 | 与 PeerJ 的兼容性 | 适合本包的理由 | 不适合的理由 |
|---|---|---|---|---|
| **CC-BY 4.0** | 整包(数据+代码+文档) | PeerJ 论文默认 CC-BY;数据/代码用 CC-BY 完全合规,zenodo 通用 | 与论文许可一致;引用要求使使用者的论文可追溯 | 对代码而言 CC-BY 非 OSI 许可,部分开发者视为非标准 |
| **CC0 1.0** | 数据 + 元数据 | PeerJ 数据可用性声明接受 CC0;最大化再利用 | 数据归档(运行输出)无创造性表达,CC0 是 Zenodo 对数据的推荐 | 放弃署名要求 |
| **MIT** | 仅 code/ | PeerJ 接受任意开源许可的代码仓库 | 代码界标准;简短、宽松 | 不覆盖数据(需与 CC-BY/CC0 组合) |

**推荐组合(供参考,不替你决定)**:data/ 与 preregistration/ 用
CC-BY 4.0 或 CC0,code/ 用 MIT,README/文档用 CC-BY 4.0。
**动作项**:见 TODO_FOR_AUTHOR #3。

## 2. Zenodo 元数据(上传时填写)

- **Resource type**: Dataset(含 code 时可选 "Dataset" + 补充 "Software" 描述)
- **Title**: FAS (Fascinator) Reproducibility Package — persistent experience-derived state in an auditable unified-graph cognitive architecture
- **Creators**: 颜凯临(Kailin Yan), ORCID 待补
- **Description**: 复用包 README.md(可直接粘贴)
- **Keywords**: cognitive architecture; spreading activation; knowledge graph; embodied agents; preregistration
- **Related identifiers**:
  - isSupplementTo: [PEERJ-DOI-PLACEHOLDER](论文一旦接收由 PeerJ 分配)
  - references: 预注册记录(preregistration/ 目录)
- **License**: 见 §1 选择
- **Versions**: 首发 1.0.0;重大更正用新版本号(投稿后冻结)
- **Access**: open;若审稿期间需要受限访问,Zenodo 支持 restricted + 按请求开放,但 PeerJ 要求投稿时**可获取**——建议 open

## 3. CITATION.cff

包根已含 CITATION.cff;上传后把 `[ZENODO-DOI]`、`[ORCID-TO-BE-ADDED]`、
license 字段替换为实际值(Zenodo 可从 DOI 反向更新 cff)。

## 4. 论文 Data/Code Availability 声明草稿(EN,DOI 占位)

> **Data and code availability.** All experiments are deterministic and
> fully archived; the complete reproducibility package — raw run outputs,
> graph snapshots, statistics files, source code, preregistration
> records, and a one-command verifier that recomputes the paper's key
> numbers without an LLM — is openly available on Zenodo at
> [ZENODO-DOI] under [LICENSE-TO-BE-CHOSEN]. Preregistrations are
> included in the package and referenced in the paper (Supplementary
> Material S14–S16). LLM decision-head replications require an
> anonymized endpoint configuration that is not redistributed; they
> reproduce at the outcome level rather than bit-identical trajectories
> (paper §5.4).

## 5. 清理扫描记录(投稿包合规)

- 扫描工具:`scripts/scan_package_secrets.py`(只读)。
- **API key/token**:0 个真实密钥。`api_key = ""`(graph_expansion.py)为空串;
  扫描器曾报告的少数密钥前缀命中,逐条核实均为普通英文单词的子串误报,无真实密钥。
  `data/llm_config.json`(端点配置,原仓库存在)**未纳入包**。
- **个人用户名**:sanitized 副本 0 残留(原始包 2,810 处,位于 tests 与
  minecraft 会话快照;脱敏替换为 `player_main`)。
- **绝对路径**:sanitized 副本 0 残留(替换为 `<REPO_ROOT>` 等占位)。
- **第三方版权数据**:包内不含第三方数据集;嵌入模型(BGE)仅以名称引用,
  不随包分发。
- **大文件**:最大单文件 22.6 MB(`data/core_incremental_value/raw_results.jsonl`);
  总体积 235 MB(原始)/ 235 MB(sanitized)——无需分卷。

## 6. 决定记录(2026-10-06,作者选定)

**已选定:CC-BY 4.0(data/archives/docs)+ MIT(code)**——README 的
推荐组合。已执行:
- 两包根添加 `LICENSE`(双许可全文:MIT 全文 + CC BY 4.0 引用与归属);
- 两包根添加 `LICENSE_OPTIONS.md`(本文件副本);
- `CITATION.cff`:`version: 1.0.0+pkg.<新hash>`,
  `license: "CC-BY-4.0 (data, docs) & MIT (code) -- see LICENSE"`;
- README 的 License 段改为已选定措辞;
- 版本标识随 LICENSE 入包重算(payload 含 LICENSE):
  原始包 `sha256:d725e5e108bb8a1b`,脱敏包 `sha256:be68a9ddac9c0f53`
  (derived-from: d725e5e1)。
- Zenodo 表单:License 选 **CC BY 4.0**(整条记录的元数据许可);
  code 的 MIT 分包许可在 LICENSE 文件中说明。
