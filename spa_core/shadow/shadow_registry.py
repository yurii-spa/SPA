"""
shadow_registry — the canonical MP-106 panel of shadow strategies S0–S5.

Pure data, no logic. Allocation rules live in ``shadow_allocator.py``.
"""

STRATEGIES = {
    "S0": {"name": "MaxYield",     "description": "100% в протокол с max APY"},
    "S1": {"name": "MaxSharpe",    "description": "аллокация по max Sharpe (историческая)"},
    "S2": {"name": "EqualWeight",  "description": "равные веса по всем активным адаптерам"},
    "S3": {"name": "T1Only",       "description": "только T1 адаптеры, равные веса"},
    "S4": {"name": "Conservative", "description": "40% Aave + 40% Compound + 20% cash"},
    "S5": {"name": "CurrentSPA",   "description": "зеркало реального аллокатора — baseline"},
}
