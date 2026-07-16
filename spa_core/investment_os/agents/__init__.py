"""spa_core/investment_os/agents — the AI Investment OS analyst agents (docs/08).

Each analyst is a small module on `spa_core.investment_os.harness.ProductAgent`. Advisory only; reads
feeds fail-closed, evidence-tags (L0-L6), emits a namespaced artifact + proof. Never moves capital,
never touches RiskPolicy/kill-switch/live track. LLM (when a key exists) stays behind the harness gate.
"""
