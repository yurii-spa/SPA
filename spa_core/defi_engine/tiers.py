"""spa_core/defi_engine/tiers.py — ONE tier authority and a census of every copy (ADR-532, P1-6).

**The authority** is ``spa_core.adapters.tier_map.tier_of`` — ``ADAPTER_REGISTRY`` first, then the
explicit alias table — and ``ADAPTER_REGISTRY`` is held equal to the protocol risk canon
(``risk.protocol_risk_map.PROTOCOL_RISK_SCORES``) by ``test_tier_declaration_agreement``. Every
tier this layer publishes is read from it. This module does NOT change a single tier value.

**The census** answers the audit's finding #53 («five tier copies disagree; the cap differs 2× by
which copy is read») with a measurement instead of a sentence. For every place a tier is written
it reports, per protocol, the copy's tier vs the authority's, the DIRECTION of the disagreement
(``looser`` = the copy grants a higher tier than the authority, ``stricter`` = a lower one), and
whether the copy is read on the money path. Resolving a disagreement changes a protocol's tier
label — that is an ADR and, since 2026-10-01, an explicit owner permission (ADR-532 §Owner
gate): this layer names it, it does not perform it.

Copies measured
---------------
``registry``           ``ADAPTER_REGISTRY`` tuples           (the authority's own source)
``canon``              ``PROTOCOL_RISK_SCORES``              (risk canon)
``polled``             ``POLLED_ADAPTERS`` literals          money path: orchestrator fallback
``orchestrator_live``  tier in the orchestrator snapshot     money path: RiskPolicy gate input
``policy_enforcer``    ``T1_ADAPTERS`` / ``T3_ADAPTERS``      money path: final book validation
``metadata``           ``ADAPTER_METADATA`` tier field       not on the money path
``data_registry``      ``data/adapter_registry.json``        money path: gate fallback, allocator merge
``adapter_class``      the adapter class ``TIER`` attribute  orchestrator record (self-report)

LLM_FORBIDDEN, stdlib only, read-only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_RANK = {"T1": 1, "T2": 2, "T3": 3}

MONEY_PATH = {
    "registry": True, "canon": False, "polled": True, "orchestrator_live": True,
    "policy_enforcer": True, "metadata": False, "data_registry": True, "adapter_class": True,
}


def authority(key: object) -> Optional[str]:
    """The ONE tier of a protocol, or ``None`` = not known (callers refuse — ADR-357 п. 3)."""
    from spa_core.adapters.tier_map import tier_of
    return tier_of(str(key)) if key else None


def _norm(raw: object) -> Optional[str]:
    from spa_core.risk.policy import tier_from_registry
    return tier_from_registry(raw)


def _copies(data_dir: Optional[Path]) -> dict[str, dict[str, Optional[str]]]:
    cols: dict[str, dict[str, Optional[str]]] = {}
    from spa_core.adapters import ADAPTER_REGISTRY
    cols["registry"] = {e[0]: _norm(e[1]) for e in ADAPTER_REGISTRY}
    cols["adapter_class"] = {e[0]: _norm(getattr(e[2], "TIER", None)) for e in ADAPTER_REGISTRY}
    from spa_core.risk.protocol_risk_map import PROTOCOL_RISK_SCORES
    cols["canon"] = {k: _norm(v.get("tier")) for k, v in PROTOCOL_RISK_SCORES.items()}
    from spa_core.orchestrator.adapter_orchestrator import POLLED_ADAPTERS
    cols["polled"] = {k: _norm(t) for k, t, _cls in POLLED_ADAPTERS}
    from spa_core.risk import policy_enforcer as pe
    enf: dict[str, Optional[str]] = {}
    for k in getattr(pe, "T1_ADAPTERS", ()) or ():
        enf[k] = "T1"
    for k in getattr(pe, "T3_ADAPTERS", ()) or ():
        enf[k] = "T3"
    cols["policy_enforcer"] = enf       # absent ⇒ the enforcer treats it as T2 by its default
    from spa_core.adapters.registry import ADAPTER_METADATA
    cols["metadata"] = {k: _norm(v.get("tier")) for k, v in ADAPTER_METADATA.items()
                        if isinstance(v, dict)}
    if data_dir is not None:
        reg = Path(data_dir) / "adapter_registry.json"
        try:
            doc = json.loads(reg.read_text(encoding="utf-8"))
            rows = doc.get("adapters", {}) if isinstance(doc, dict) else {}
            cols["data_registry"] = {k: _norm(v.get("tier")) for k, v in rows.items()
                                     if isinstance(v, dict) and v.get("tier") is not None}
        except Exception:  # noqa: BLE001 — absent in CI / worktree: the column is unmeasured
            pass
        snap = Path(data_dir) / "adapter_orchestrator_status.json"
        try:
            doc = json.loads(snap.read_text(encoding="utf-8"))
            cols["orchestrator_live"] = {a["protocol"]: _norm(a.get("tier"))
                                         for a in doc.get("adapters", []) if isinstance(a, dict)
                                         and a.get("protocol")}
        except Exception:  # noqa: BLE001
            pass
    return cols


def census(data_dir: "Path | str | None" = None) -> dict:
    """Every tier copy vs the authority. Read-only; changes nothing."""
    cols = _copies(Path(data_dir) if data_dir is not None else None)
    rows = []
    for copy, mapping in sorted(cols.items()):
        if copy == "policy_enforcer":
            # The enforcer has no T2 set: it resolves "not T1 and not T3" to T2. Judge it for
            # every protocol the authority knows, so a missing T3 member is a disagreement too.
            names = set(mapping) | set(cols.get("registry", {}))
        else:
            names = set(mapping)
        for k in sorted(names):
            auth = authority(k)
            got = mapping.get(k, "T2" if copy == "policy_enforcer" else None)
            if auth is None or got is None or got == auth:
                continue
            rows.append({
                "protocol": k, "copy": copy, "copy_tier": got, "authority_tier": auth,
                "direction": "looser" if _RANK[got] < _RANK[auth] else "stricter",
                "money_path": MONEY_PATH.get(copy, False),
            })
    measured = sorted(cols)
    unmeasured = sorted(set(MONEY_PATH) - set(cols))
    return {
        "authority": "spa_core.adapters.tier_map.tier_of (ADAPTER_REGISTRY ≡ protocol risk canon)",
        "copies_measured": measured,
        "copies_unmeasured": unmeasured,     # e.g. no data/ in CI — named, never read as agreement
        "disagreements": rows,
        "n_disagreements": len(rows),
        "n_money_path_looser": sum(1 for r in rows if r["money_path"] and r["direction"] == "looser"),
        "resolution": ("not performed here: changing a protocol tier label is an ADR plus the "
                       "owner's explicit permission (ADR-532 §Owner gate)"),
    }
