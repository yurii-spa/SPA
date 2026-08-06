#!/usr/bin/env python3
"""
audit_protocol_blindness.py — дифференциальный аудит протокол-слепоты
аналитических модулей (Tier A / B / C — флаг --tier, по умолчанию B).

Контекст (audit 2026-08-02): после удаления no-arg fallback в
`_ModuleAdapter._invoke` часть Tier-B модулей всё ещё возвращает "ok" —
они принимают context-аргумент, но внутри игнорируют ctx["protocol"]
(читают собственные внутренние/demo-данные) → composite_risk_0_100
байт-в-байт одинаковый для любого протокола. Слепота ушла с уровня
адаптера, но осталась внутри модулей.

Метод (дифференциальный):
  каждый модуль выбранного тира прогоняется через тот же `_ModuleAdapter`,
  что и в проде, для набора прогонов:
    * реальные протоколы: aave_v3, maple, pendle;
    * повтор aave_v3 — ловит недетерминированные модули (различие score
      при ОДНОМ протоколе ≠ протокол-чувствительность);
    * контрольный несуществующий протокол — модуль, отдающий тот же score
      для заведомо несуществующего протокола, гарантированно не читает
      ctx["protocol"].

Классификация ok-модулей:
  sensitive        — score различается между реальными протоколами
                     (и повтор aave_v3 стабилен);
  nondeterministic — повтор aave_v3 дал другой score: сигнал нестабилен,
                     различия между протоколами недоказуемы;
  blind_constant   — одинаковый score на всех реальных протоколах И на
                     контрольном несуществующем;
  blind_equal      — одинаковый score на реальных протоколах, но контроль
                     повёл себя иначе (код читает протокол, а данные —
                     нет: практически слепой сегодня, data-starved).

Волна 2 (2026-08-05, задача A2) — широкая вселенная. Аудиторская тройка
(aave_v3/maple/pendle) вся живёт на ethereum: модуль, честно различающий
протоколы по chain/kind/fee-структуре, на тройке даёт равные score и ложно
попадает в «слепые». Поэтому каждый trio-слепой модуль дополнительно
прогоняется по ВСЕЙ вселенной _protocol_facts (35 протоколов, ранний выход
при первом различии):
  blind_equal_wide_ok — на тройке равен, но на широкой вселенной различает
                     протоколы: ЧЕСТНЫЙ coarse-модуль, НЕ слепой эквивалент,
                     в PROTOCOL_BLIND_MODULES не попадает (исполняется).

Для weight-политики blind_constant / blind_equal / nondeterministic —
все «слепой эквивалент» (не несут протокол-специфичной информации);
blind_equal_wide_ok несёт (грубую) протокол-специфичную информацию.

Tier-C (2026-08-06): метод тот же и работает для C с самого начала —
`--tier C` принимался всегда, а `run_tier_c` гоняет модули через ТОТ ЖЕ
`_ModuleAdapter`, что и Tier-B, поэтому прогон воспроизводит прод. Замер на
`origin/main` 11abfaf1c: 180 модулей → 9 ok / 103 unchecked / 64 failed /
4 dormant, и все 9 ok — `blind_constant` (одинаковый score на тройке, на
повторе, на всей широкой вселенной и на несуществующем контрольном), sensitive
= 0. Разметка (`--emit-markup`) остаётся Tier-B-only: Tier-C её не потребляет,
у него честный вердикт считается in-situ каждый прогон
(`_meta.protocol_differentiation`, см. signal_aggregator.run_tier_c).

Запуск ТОЛЬКО в sandbox (не из живой ~/Documents/SPA_Claude — модули пишут
свои data/*-логи относительно корня репо):

    python3 scripts/audit_protocol_blindness.py --out /path/to/report.json
    python3 scripts/audit_protocol_blindness.py --tier C --out /path/report.json

Опционально `--emit-markup` генерирует spa_core/analytics/_protocol_blindness.py
(машиночитаемая разметка, потребляется signal_aggregator.run_tier_b).
stdlib-only, детерминированный порядок обхода, advisory-слой.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from spa_core.analytics import _module_registry as registry          # noqa: E402
from spa_core.analytics.signal_aggregator import _ModuleAdapter      # noqa: E402

REAL_PROTOCOLS = ["aave_v3", "maple", "pendle"]
REPEAT_PROTOCOL = "aave_v3"          # повторный прогон — ловим недетерминизм
CONTROL_PROTOCOL = "__nonexistent_control_protocol__"


def _wide_universe():
    """Протоколы широкой вселенной для wide-прогона (без аудиторской тройки,
    детерминированный порядок)."""
    from spa_core.analytics._protocol_facts import known_protocols
    return [p for p in known_protocols() if p not in REAL_PROTOCOLS]
MODULE_TIMEOUT = 3.0                 # как в проде (signal_aggregator)
MAX_WORKERS = 8

BLIND_EQUIVALENT = ("blind_constant", "blind_equal", "nondeterministic")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_once(module_info: Dict[str, Any], protocol: str
              ) -> Tuple[Optional[float], str, str]:
    """Один прогон модуля для протокола с прод-таймаутом. → (score, status, detail)."""
    adapter = _ModuleAdapter(module_info)
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(adapter.run, protocol, {"source": "blindness_audit"})
        try:
            return fut.result(timeout=MODULE_TIMEOUT)
        except FuturesTimeout:
            return None, "timeout", ""
        except Exception as exc:  # noqa: BLE001 — fail-open, как в проде
            return None, "failed", f"{type(exc).__name__}: {exc}"


def _audit_module(module_info: Dict[str, Any]) -> Dict[str, Any]:
    """Полный дифференциальный прогон одного модуля."""
    name = module_info.get("module", "")
    runs: Dict[str, Dict[str, Any]] = {}
    for label, proto in (
        [(p, p) for p in REAL_PROTOCOLS]
        + [(REPEAT_PROTOCOL + "#2", REPEAT_PROTOCOL), ("control", CONTROL_PROTOCOL)]
    ):
        score, status, detail = _run_once(module_info, proto)
        runs[label] = {"score": score, "status": status}
        if detail:
            runs[label]["detail"] = detail

    real = [runs[p] for p in REAL_PROTOCOLS]
    real_ok = [r for r in real if r["status"] == "ok"]
    # Статус модуля = худший «первичный» статус (для не-ok модулей аудит
    # лишь подтверждает разбивку unchecked/failed/dormant/timeout).
    if len(real_ok) == 0:
        primary = real[0]["status"]
        return {"module": name, "classification": primary, "runs": runs}
    if len(real_ok) < len(real):
        # ok не на всех реальных протоколах — уже протокол-зависимое поведение
        return {"module": name, "classification": "sensitive",
                "subtype": "partial_ok", "runs": runs}

    scores = [r["score"] for r in real_ok]
    repeat = runs[REPEAT_PROTOCOL + "#2"]
    control = runs["control"]

    if repeat["status"] == "ok" and repeat["score"] != runs[REPEAT_PROTOCOL]["score"]:
        cls = "nondeterministic"
    elif len(set(scores)) > 1:
        cls = "sensitive"
    elif control["status"] == "ok" and control["score"] == scores[0]:
        cls = "blind_constant"
    else:
        cls = "blind_equal"

    out = {"module": name, "classification": cls, "runs": runs,
           "weight": module_info.get("weight"),
           "category": module_info.get("category")}

    # Волна 2: trio-слепой ≠ слепой. Прогон по широкой вселенной
    # _protocol_facts (ранний выход при первом отличающемся ok-score).
    if cls in ("blind_constant", "blind_equal"):
        trio_score = scores[0]
        wide_ok_runs = 0
        for proto in _wide_universe():
            score, status, _detail = _run_once(module_info, proto)
            if status != "ok" or score is None:
                continue
            wide_ok_runs += 1
            if score != trio_score:
                out["classification"] = "blind_equal_wide_ok"
                out["wide"] = {
                    "differs_at": proto,
                    "trio_score": trio_score,
                    "wide_score": score,
                    "ok_runs_until_differ": wide_ok_runs,
                }
                break
        else:
            out["wide"] = {"differs_at": None,
                           "ok_runs": wide_ok_runs}
    return out


def run_audit(tier: str = "B") -> Dict[str, Any]:
    modules = registry.get_tier_modules(tier)
    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for res in ex.map(_audit_module, modules):
            results.append(res)
    results.sort(key=lambda r: r["module"])

    counts: Dict[str, int] = {}
    for r in results:
        counts[r["classification"]] = counts.get(r["classification"], 0) + 1
    blind = sorted(r["module"] for r in results
                   if r["classification"] in BLIND_EQUIVALENT)
    sensitive = sorted(r["module"] for r in results
                       if r["classification"] == "sensitive")
    wide_ok = sorted(r["module"] for r in results
                     if r["classification"] == "blind_equal_wide_ok")
    return {
        "generated_at": _utc_now_iso(),
        "tier": tier,
        "method": {
            "real_protocols": REAL_PROTOCOLS,
            "repeat_protocol": REPEAT_PROTOCOL,
            "control_protocol": CONTROL_PROTOCOL,
            "module_timeout_s": MODULE_TIMEOUT,
            "wide_universe_size": len(_wide_universe()),
        },
        "module_count": len(modules),
        "counts": counts,
        "blind_equivalent": blind,
        "sensitive": sensitive,
        "wide_ok": wide_ok,
        "results": results,
    }


_MARKUP_TEMPLATE = '''"""
_protocol_blindness.py — эмпирическая разметка протокол-слепых Tier-B модулей.

СГЕНЕРИРОВАНО scripts/audit_protocol_blindness.py — НЕ редактировать вручную;
перегенерация: python3 scripts/audit_protocol_blindness.py --emit-markup
(в sandbox-чекауте, не в живом репо — модули пишут data/*-логи).

Дифференциальный аудит {generated_at}: каждый Tier-B модуль прогнан для
{real_protocols} + повтор {repeat} (недетерминизм) + контрольный
несуществующий протокол; trio-слепые дополнительно прогнаны по ВСЕЙ
вселенной _protocol_facts (волна 2, задача A2). Модули PROTOCOL_BLIND_DETAIL
вернули «ok», но их score НЕ зависит от протокола (или недетерминирован) →
протокол-специфичной информации не несут. signal_aggregator.run_tier_b
исключает их из composite и из confidence (громкий статус "blind"),
advisory-слой; Tier-A не трогаем.

WIDE_OK_MODULES — модули, равные на аудиторской тройке (весь ethereum), но
РАЗЛИЧАЮЩИЕ протоколы на широкой вселенной (chain/kind/fee-структура):
честные coarse-модули, НЕ слепые, из исполнения НЕ исключаются.
"""
from typing import Dict, FrozenSet

AUDIT_GENERATED_AT = "{generated_at}"

# module_name -> подтип (blind_constant | blind_equal | nondeterministic)
PROTOCOL_BLIND_DETAIL: Dict[str, str] = {{
{detail_lines}
}}

PROTOCOL_BLIND_MODULES: FrozenSet[str] = frozenset(PROTOCOL_BLIND_DETAIL)

# Честные coarse-модули (trio-равные, wide-различающие) — исполняются.
WIDE_OK_MODULES: FrozenSet[str] = frozenset({{
{wide_ok_lines}
}})
'''


def emit_markup(report: Dict[str, Any], path: Path) -> None:
    detail = {
        r["module"]: r["classification"]
        for r in report["results"]
        if r["classification"] in BLIND_EQUIVALENT
    }
    lines = "\n".join(
        f'    "{name}": "{detail[name]}",' for name in sorted(detail)
    )
    wide_ok = sorted(
        r["module"] for r in report["results"]
        if r["classification"] == "blind_equal_wide_ok"
    )
    wide_ok_lines = "\n".join(f'    "{name}",' for name in wide_ok)
    text = _MARKUP_TEMPLATE.format(
        generated_at=report["generated_at"],
        real_protocols=REAL_PROTOCOLS,
        repeat=REPEAT_PROTOCOL,
        detail_lines=lines,
        wide_ok_lines=wide_ok_lines,
    )
    path.write_text(text, encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--out", required=True,
                    help="Путь для JSON-отчёта (sandbox, НЕ живая data/).")
    ap.add_argument("--tier", default="B", choices=["A", "B", "C"])
    ap.add_argument("--emit-markup", action="store_true",
                    help="Перегенерировать spa_core/analytics/_protocol_blindness.py")
    args = ap.parse_args(argv)

    report = run_audit(args.tier)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                   encoding="utf-8")

    if args.emit_markup:
        if args.tier != "B":
            print("--emit-markup поддержан только для Tier B", file=sys.stderr)
            return 2
        emit_markup(report, REPO_ROOT / "spa_core" / "analytics"
                    / "_protocol_blindness.py")

    c = report["counts"]
    print(f"modules={report['module_count']} counts={c}")
    print(f"blind_equivalent={len(report['blind_equivalent'])} "
          f"sensitive={len(report['sensitive'])}")
    print(f"report → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
