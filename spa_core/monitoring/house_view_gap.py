"""house_view_gap.py — сверка «офис говорит X, книга делает Y» (ADR-066, Фаза 3, C1).

Детерминированная СВЕРКА (только сверка — никаких действий с капиталом):
берёт house_view инвест-офиса и фактическую аллокацию книги и НАЗЫВАЕТ
расхождения. Выход — data/house_view_gap.json; потребитель — мост
findings_bridge (карточки) и Шаг 0-офис оркестратора.

Типы расхождений:
  opportunity_unheld  офис называет возможность (evidence-level сохранён),
                      книга её не держит, и отказ НЕ назван нигде:
                        - held в positions                       → нет гэпа
                        - в below_median_cap / warnings rationale → explained (INFO)
                        - протокола нет в ADAPTER_REGISTRY        → explained (INFO:
                          входа технически нет — нужен адаптер + промоушен)
                        - иначе                                   → WARN (безымянный
                          простой возможности — нарушение духа ADR-055)
  posture_vs_book     постура офиса RED, книга развёрнута (cash < 50%) → WARN
                      (YELLOW — информационно, гэпом не является)
  analyst_red         аналитик с posture/status RED|CRITICAL → WARN

Честность: недоступный вход ⇒ запись в unchecked, гэпы НЕ выдумываются
(refusal-first). Реестр недоступен ⇒ классификация возможностей честно
опускается до INFO/unclassified — карточек из неизмеримого не рождается.
LLM_FORBIDDEN. Только stdlib. Время — вход (now=).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from spa_core.monitoring.architecture_conformance import REPO_ROOT

GAP_PATH = os.path.join(REPO_ROOT, "data", "house_view_gap.json")

_RED_TOKENS = ("RED", "CRITICAL")


def _norm(p) -> str:
    return str(p or "").strip().lower()


def compute_gaps(chief: dict | None,
                 positions: dict | None,
                 rationale: dict | None,
                 registry_keys: set[str] | None,
                 analysts: dict[str, dict],
                 now: dt.datetime) -> dict:
    gaps: list[dict] = []
    unchecked: list[dict] = []

    held: set[str] = set()
    cash_pct = None
    if positions:
        held = {_norm(k) for k in (positions.get("positions") or {})}
        cap = positions.get("capital_usd") or 0
        if cap:
            cash_pct = 100.0 * (positions.get("cash_usd") or 0) / cap
    else:
        unchecked.append({"input": "current_positions", "reason": "нет данных — гэпы по книге не измеримы"})

    explained_protocols: set[str] = set()
    if rationale:
        for e in rationale.get("below_median_cap") or []:
            explained_protocols.add(_norm(e.get("protocol")))
        shadow = rationale.get("decision_shadow") or {}
        blob = json.dumps(shadow.get("warnings") or [], ensure_ascii=False).lower()
    else:
        blob = ""
        unchecked.append({"input": "allocation_rationale", "reason": "нет данных — именованные отказы не видны"})

    if chief:
        hv = chief.get("house_view") or {}
        posture = str(hv.get("overall_posture") or "").upper()
        if posture in _RED_TOKENS:
            if positions and cash_pct is not None and cash_pct < 50.0:
                gaps.append({
                    "key": "gap:posture_vs_book",
                    "type": "posture_vs_book", "severity": "WARN",
                    "message": f"постура офиса {posture}, но книга развёрнута "
                               f"(cash {cash_pct:.1f}% < 50%) — офис кричит, книга не слышит",
                })
            elif positions is None:
                unchecked.append({"input": "posture_vs_book",
                                  "reason": f"постура {posture}, но книга не измерима"})
        for opp in (hv.get("top_opportunities") or []):
            v = opp.get("value") or {}
            proto = _norm(v.get("protocol"))
            if not proto:
                continue
            if positions is None:
                continue  # уже в unchecked — не выдумывать
            if proto in held:
                continue
            base = {"protocol": proto, "apy_pct": v.get("apy_pct"),
                    "evidence_level": opp.get("evidence_level"),
                    "source": opp.get("source")}
            if proto in explained_protocols or proto in blob:
                gaps.append({"key": f"gap:opportunity_explained:{proto}",
                             "type": "opportunity_unheld", "severity": "INFO",
                             "message": f"возможность {proto} {v.get('apy_pct')}% не в книге — "
                                        f"отказ НАЗВАН в rationale", **base})
            elif registry_keys is None:
                gaps.append({"key": f"gap:opportunity_unclassified:{proto}",
                             "type": "opportunity_unheld", "severity": "INFO",
                             "message": f"возможность {proto} не в книге; реестр адаптеров "
                                        f"недоступен — классификация не измерима", **base})
            elif proto not in registry_keys:
                gaps.append({"key": f"gap:opportunity_no_adapter:{proto}",
                             "type": "opportunity_unheld", "severity": "INFO",
                             "message": f"возможность {proto} {v.get('apy_pct')}% "
                                        f"(evidence {opp.get('evidence_level')}) вне реестра "
                                        f"адаптеров — входа технически нет (адаптер + промоушен)",
                             **base})
            else:
                gaps.append({"key": f"gap:opportunity_unnamed:{proto}",
                             "type": "opportunity_unheld", "severity": "WARN",
                             "message": f"возможность {proto} {v.get('apy_pct')}% "
                                        f"(evidence {opp.get('evidence_level')}) доступна книге, "
                                        f"не держится и отказ НЕ назван — безымянный простой "
                                        f"(дух ADR-055)", **base})
    else:
        unchecked.append({"input": "chief_investment", "reason": "house_view недоступен — сверка невозможна"})

    for name, data in sorted(analysts.items()):
        tokens = {str(data.get(k) or "").upper() for k in ("posture", "status", "combined_posture")}
        if tokens & set(_RED_TOKENS):
            gaps.append({"key": f"gap:analyst_red:{name}",
                         "type": "analyst_red", "severity": "WARN",
                         "message": f"аналитик {name}: {' / '.join(sorted(tokens & set(_RED_TOKENS)))} "
                                    f"— требует реакции (карточка/решение), не пролистывания"})

    return {"generated_at": now.isoformat(), "adr": "ADR-066",
            "gaps": gaps, "unchecked": unchecked,
            "counts": {"warn": sum(1 for g in gaps if g["severity"] == "WARN"),
                       "info": sum(1 for g in gaps if g["severity"] == "INFO"),
                       "unchecked": len(unchecked)}}


def _load(rel: str, root: str):
    try:
        return json.load(open(os.path.join(root, rel)))
    except Exception:
        return None


def run(root: str = REPO_ROOT, now: dt.datetime | None = None,
        write: bool = True, receipts: bool = True) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    chief = _load("data/investment_os/chief_investment.json", root)
    positions = _load("data/current_positions.json", root)
    rationale = _load("data/allocation_rationale.json", root)
    try:
        from spa_core.adapters import ADAPTER_REGISTRY
        registry_keys = {_norm(k) for k in ADAPTER_REGISTRY}
    except Exception:
        registry_keys = None
    analysts = {}
    io_dir = os.path.join(root, "data", "investment_os")
    if os.path.isdir(io_dir):
        for fn in sorted(os.listdir(io_dir)):
            if fn.endswith(".json") and not fn.startswith("_") and fn != "chief_investment.json":
                d = _load(f"data/investment_os/{fn}", root)
                if isinstance(d, dict):
                    analysts[fn[:-5]] = d

    report = compute_gaps(chief, positions, rationale, registry_keys, analysts, now)

    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(report, os.path.join(root, "data", "house_view_gap.json"))
    if receipts:
        from spa_core.monitoring.consumption_receipts import write_receipt
        for rel, loaded in [("data/investment_os/chief_investment.json", chief),
                            ("data/current_positions.json", positions),
                            ("data/allocation_rationale.json", rationale)]:
            if loaded is not None:
                write_receipt(rel, "house_view_gap", root=root)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--root", default=REPO_ROOT)
    args = ap.parse_args(argv)
    if not args.run:
        ap.print_help()
        return 0
    r = run(root=args.root)
    c = r["counts"]
    print(f"house_view_gap: warn={c['warn']} info={c['info']} unchecked={c['unchecked']}")
    for g in r["gaps"]:
        print(f"  [{g['severity']}] {g['message']}")
    for u in r["unchecked"]:
        print(f"  [UNCHECKED] {u['input']}: {u['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
