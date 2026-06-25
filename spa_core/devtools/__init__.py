"""spa_core.devtools — developer/ops tooling. NOT runtime risk/execution/monitoring.
Lives outside the LLM-forbidden scan dirs: tools here MAY use LLM SDKs (e.g. auto_fixer
uses Claude for autonomous code repair). Never imported by deterministic risk/execution paths.
"""
