# Zenodo Deposition Metadata (draft)

title: "Fascinator: An Auditable Unified-Graph Cognitive Architecture with a Preregistered Boundary Analysis of Activation-Based Access — Full Experiment Archive"
creators:
  - name: "Yan, Kailin"
    affiliation: "Department of Computer Science"   # 作者需核对正式英文单位名
    orcid: ""                                        # 待作者填写
description: "Complete archived run outputs for the Fascinator (FAS) paper: deterministic zero-LLM subject experiments (494 runs), the preregistered core incremental-value mechanism campaign (34,016 runs), the 663-run falsification campaign, the beacon campaign (80 runs), the routing campaign (520 valid runs; v1 archived as INVALID), the relation-direction diagnosis (60 runs), the shared-hub parameter sweep (2,550 runs), the embedding accessibility check, and the determinism re-run. Includes raw run records, graph snapshots, statistics files, preregistration records, figure-generation scripts, and the claim-to-evidence mapping."
upload_type: dataset
keywords:
  - cognitive architecture
  - knowledge graph
  - spreading activation
  - experience consolidation
  - preregistration
  - reproducible research
access_right: open
license: CC-BY-4.0 (data); code under repository LICENSE
related_identifiers:
  - identifier: "(DOI of the companion code repository)"
    relation: isSupplementTo
  - identifier: "(DOI of the paper, if minted)"
    relation: isReferencedBy
communities: []
notes: >
  Zero-LLM experiments are bit-reproducible from the archived seeds. LLM decision-head
  experiments (beacon/routing) require an anonymized endpoint configuration and reproduce
  outcome-level, not trajectory-level, results (paper Supplementary Material S10).
  The first routing campaign is archived under an INVALID marker and is not a source of
  any claim. Potential sensitive content: none (synthetic sandbox data; live Minecraft
  observations contain no personal data).
files:
  - experiments/            (campaign archives)
  - FAS_Research_Experiments/ (subject-experiment families)
  - paper_audit/            (PAPER_FACT_DATABASE.json, figure generators)
  - deliverables/experiments_new/ (shared-hub sweep, embedding check, determinism re-run)
  - FAS_Paper_I/figures/    (figure sources)
preregistration: "experiments/core_incremental_value/manifest.json (hypotheses, topologies, seed reservoir, metrics, and testing scheme committed before execution); deliverables/experiments_new/*/DESIGN.md (sweep and re-run designs frozen before execution)"
