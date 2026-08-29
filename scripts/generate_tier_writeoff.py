#!/usr/bin/env python3
"""Генератор реестров «списано / заморожено» для любого тира аналитики.

ЗАЧЕМ. ADR-133 (решение владельца 2026-08-25) сделал это для Tier-C: девять
константных списаны, 162 «позвать нечем» заморожены, реестр
`spa_core/analytics/_tier_c_writeoff.py` СГЕНЕРИРОВАН из JSON аудита, а не набран
руками. Приём сработал: слой перестал публиковать число, которое к протоколу не
относится. Tier-B — та же болезнь и вчетверо больший масштаб: из 479 модулей 354
измеренно не дают протокол-зависимого сигнала, и с 2026-08-07 их не трогали.

Инструмент повторяет приём МАШИНОЙ, а не копипастой: один генератор, одна разметка,
один провенанс. Реестр Tier-C, доставленный руками, служит ему положительным
контролем — `--verify C` обязан воспроизвести его состав ПОЛНОСТЬЮ; не воспроизвёл ⇒
генератор врёт, и это видно до того, как он напишет реестр для Tier-B.

ЧТО ОН НЕ ДЕЛАЕТ. Не решает, списывать ли: списание — решение владельца (так было с
ADR-133 и так остаётся). Не правит `signal_aggregator`, не трогает `data/`, не двигает
капитал. Он превращает ЗАМЕР в файл, который можно прочитать и проверить.

КЛАССЫ И ЧТО ОНИ ЗНАЧАТ (все — измерения, не мнения):

* ``WRITTEN_OFF`` ← `blind_constant`: модуль отдаёт ОДНО И ТО ЖЕ число всем протоколам,
  включая НЕСУЩЕСТВУЮЩИЙ контрольный. Это доказательство, а не подозрение: протокол,
  которого нет, не может дать тот же осмысленный ответ, что настоящий. Ровно эта улика
  списала девять модулей Tier-C.
* ``BLIND_ACROSS_WIDE`` ← `blind_equal`: число одинаково у всей аудиторской тройки И на
  широкой вселенной (23–32 протокола, ни одного отличия). Улика СЛАБЕЕ, чем у
  `WRITTEN_OFF` — контрольный протокол не ответил, поэтому «константа» не доказана, —
  и поэтому набор ОТДЕЛЬНЫЙ. Смешать их значило бы выдать более слабое доказательство
  за более сильное.
* ``UNKNOWN_FROZEN`` ← `unchecked`: «позвать нечем» — у модуля нет точки входа,
  принимающей контекст. Это НЕ списание: списание было бы утверждением о
  бесполезности, а его у нас нет. Заморозка — честная запись «мы про них не знаем».
* ``DORMANT`` ← `dormant`: модуль позвался и вернул результат, который не приводится к
  score (в Tier-B: 47 вернули None, один — dict). Отдельный класс: чинить тут нечего
  до разбора КАЖДОГО.
* ``FAILED`` ← `failed`: вызов бросил исключение. Причина записана дословно.

ИСПОЛЬЗОВАНИЕ:

    python3 scripts/generate_tier_writeoff.py --verify C          # положительный контроль
    python3 scripts/generate_tier_writeoff.py --tier B --emit     # → _tier_b_writeoff.py
    python3 scripts/generate_tier_writeoff.py --tier B --from-report /tmp/rep_B.json --emit

КОДЫ ВОЗВРАТА: 0 — успех; 1 — `--verify` не сошёлся; 2 — инструмент отказал.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ANALYTICS_DIR = REPO_ROOT / "spa_core" / "analytics"

#: Класс аудита → имя набора в реестре. Порядок фиксирован: он же порядок секций
#: в сгенерированном файле, и от него зависит воспроизводимость вывода.
CLASS_TO_SET = (
    ("blind_constant", "WRITTEN_OFF"),
    ("blind_equal", "BLIND_ACROSS_WIDE"),
    ("unchecked", "UNKNOWN_FROZEN"),
    ("dormant", "DORMANT"),
    ("failed", "FAILED"),
)

#: Наборы, которые несут ПРИЧИНУ по каждому имени (dict), а не только имя (frozenset).
WITH_REASON = {"WRITTEN_OFF", "BLIND_ACROSS_WIDE", "DORMANT", "FAILED"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_audit():
    """Импортировать аудит ПО ПУТИ. Логика замера одна на всех — копий не заводим."""
    path = REPO_ROOT / "scripts" / "audit_protocol_blindness.py"
    spec = importlib.util.spec_from_file_location("_blindness_audit_for_gen", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"не удалось загрузить {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_blindness_audit_for_gen"] = mod
    spec.loader.exec_module(mod)
    return mod


def load_report(tier: str, from_report: Optional[str]) -> Dict[str, Any]:
    if from_report:
        report = json.loads(Path(from_report).read_text(encoding="utf-8"))
        if str(report.get("tier", "")).upper() != tier:
            raise RuntimeError(
                f"отчёт снят для тира {report.get('tier')!r}, а просят {tier!r} — "
                f"не тот замер, отказываю")
        return report
    return _load_audit().run_audit(tier)


def _reason_for(row: Dict[str, Any]) -> str:
    """Причина словами — ИЗ ЗАМЕРА этого модуля, без домысла."""
    cls = row["classification"]
    runs = row.get("runs", {}) or {}
    trio = (runs.get("aave_v3") or {})
    score = trio.get("score")
    if cls == "blind_constant":
        return (f"константа {score} на всех протоколах аудита И на несуществующем "
                f"контрольном — модуль не читает, о каком протоколе его спросили")
    if cls == "blind_equal":
        wide = row.get("wide") or {}
        n = wide.get("ok_runs")
        tail = (f"; широкая вселенная: {n} протокол(ов) ответили, ни один не дал "
                f"другого числа" if n is not None else "")
        return (f"одно и то же число {score} у всей аудиторской тройки{tail}; "
                f"контрольный протокол не ответил, поэтому «константа» НЕ доказана")
    if cls == "dormant":
        return trio.get("detail") or "результат не приводится к score"
    if cls == "failed":
        return trio.get("detail") or "вызов бросил исключение"
    return ""


def build_sets(report: Dict[str, Any]) -> Dict[str, Any]:
    """Классы замера → наборы реестра. Пересечения невозможны: класс у модуля один."""
    rows = report.get("results") or report.get("modules") or []
    by_class: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_class.setdefault(row["classification"], []).append(row)
    out: Dict[str, Any] = {}
    for cls, set_name in CLASS_TO_SET:
        members = sorted(by_class.get(cls, []), key=lambda r: r["module"])
        if set_name in WITH_REASON:
            out[set_name] = {m["module"]: _reason_for(m) for m in members}
        else:
            out[set_name] = [m["module"] for m in members]
    return out


def verify_against_existing(tier: str, sets: Dict[str, Any]) -> List[str]:
    """Положительный контроль: сверить с УЖЕ доставленным реестром тира.

    Существующий `_tier_c_writeoff.py` был доставлен по ADR-133 отдельным путём.
    Если генератор — правильный, он обязан воспроизвести его СОСТАВ поимённо.
    Расхождение здесь — отказ генератору, а не повод править реестр."""
    mod_name = f"spa_core.analytics._tier_{tier.lower()}_writeoff"
    try:
        existing = importlib.import_module(mod_name)
    except ImportError:
        return [f"реестра {mod_name} нет — сверять не с чем (это НЕ успех)"]

    # Исторические имена наборов Tier-C: у него `blind_equal` не было вовсе.
    pairs = [("WRITTEN_OFF", "WRITTEN_OFF"), ("UNKNOWN_FROZEN", "UNKNOWN_FROZEN"),
             ("DORMANT", "DORMANT"), ("FAILED", "FAILED")]
    problems: List[str] = []
    for gen_name, old_name in pairs:
        old = getattr(existing, old_name, None)
        if old is None:
            problems.append(f"{old_name}: в доставленном реестре нет такого набора")
            continue
        got, want = set(sets.get(gen_name) or ()), set(old)
        if got != want:
            problems.append(
                f"{old_name}: генератор {len(got)}, доставленный реестр {len(want)}; "
                f"только у генератора {sorted(got - want)[:4]}, "
                f"только в реестре {sorted(want - got)[:4]}")
    return problems


def _fmt_dict(d: Dict[str, str], indent: str = "    ") -> str:
    if not d:
        return ""
    return "\n".join(f"{indent}{k!r}:\n{indent}    {v!r}," for k, v in sorted(d.items()))


def _fmt_set(names: List[str], indent: str = "    ") -> str:
    if not names:
        return ""
    return "\n".join(f"{indent}{n!r}," for n in sorted(names))


def emit(tier: str, report: Dict[str, Any], sets: Dict[str, Any]) -> str:
    counts = report.get("counts", {})
    total = report.get("module_count", sum(counts.values()))
    n = {k: len(v) for k, v in sets.items()}
    return f'''"""_tier_{tier.lower()}_writeoff.py — реестр списанных и замороженных модулей Tier-{tier}.

СГЕНЕРИРОВАН ЗАМЕРОМ, руками не набран. Провенанс — две воспроизводимые команды:

    python3 scripts/audit_protocol_blindness.py --tier {tier} --out <файл>
    python3 scripts/generate_tier_writeoff.py --tier {tier} --from-report <файл> --emit

Замер: modules={total} counts={json.dumps(counts, sort_keys=True)}

Приём повторяет ADR-133 (Tier-C, решение владельца 2026-08-25 «все одобряю», 1А+2А).
Генератор проверен ПОЛОЖИТЕЛЬНЫМ КОНТРОЛЕМ: `--verify C` воспроизводит доставленный
руками `_tier_c_writeoff.py` поимённо; не воспроизвёл бы — реестра Tier-{tier} не было бы.

Файл НИЧЕГО не исполняет и ничего не отключает сам по себе. Он называет каждый модуль
и измеренную причину. Прекращение исполнения — отдельное решение владельца и отдельная
строка в `signal_aggregator`, как это было с Tier-C.

Tier-{tier} — советующий слой: капитал он не двигает, RiskPolicy и стоп-кран не касается.
"""
from typing import Dict, FrozenSet

#: Когда снят замер, из которого построен этот реестр.
AUDIT_GENERATED_AT = {report.get("generated_at", _utc_now_iso())!r}

#: Всего модулей в тире на момент замера.
TIER_SIZE = {total}

#: СПИСАНЫ ({n["WRITTEN_OFF"]}): одно и то же число всем протоколам, ВКЛЮЧАЯ несуществующий
#: контрольный. Протокол, которого нет, не может дать тот же осмысленный ответ, что
#: настоящий, — это доказательство слепоты, а не подозрение. Имя → измеренная причина.
WRITTEN_OFF: Dict[str, str] = {{
{_fmt_dict(sets["WRITTEN_OFF"])}
}}

#: СЛЕПЫ НА ШИРОКОЙ ВСЕЛЕННОЙ ({n["BLIND_ACROSS_WIDE"]}): одно и то же число у аудиторской
#: тройки И на 23–32 протоколах широкой вселенной — ни одного отличия. Улика СЛАБЕЕ, чем
#: у WRITTEN_OFF (контрольный протокол не ответил, «константа» не доказана), поэтому
#: набор отдельный: смешать значило бы выдать слабое доказательство за сильное.
BLIND_ACROSS_WIDE: Dict[str, str] = {{
{_fmt_dict(sets["BLIND_ACROSS_WIDE"])}
}}

#: «НЕ ЗНАЕМ», заморожены ({n["UNKNOWN_FROZEN"]}): позвать нечем — нет точки входа,
#: принимающей контекст. Это НЕ списание: списание было бы утверждением о
#: бесполезности, а его у нас нет. Честно идут в знаменатель как неработающие.
UNKNOWN_FROZEN: FrozenSet[str] = frozenset({{
{_fmt_set(sets["UNKNOWN_FROZEN"])}
}})

#: ОТВЕТИЛИ НЕЧИТАЕМЫМ ({n["DORMANT"]}): модуль позвался и вернул результат, который не
#: приводится к score. Имя → что именно вернулось.
DORMANT: Dict[str, str] = {{
{_fmt_dict(sets["DORMANT"])}
}}

#: УПАЛИ ({n["FAILED"]}): вызов бросил исключение. Имя → дословный диагноз.
FAILED: Dict[str, str] = {{
{_fmt_dict(sets["FAILED"])}
}}

#: Все имена реестра. Пересечений нет по построению: класс у модуля ровно один.
ALL_LISTED = (
    frozenset(WRITTEN_OFF) | frozenset(BLIND_ACROSS_WIDE) | UNKNOWN_FROZEN
    | frozenset(DORMANT) | frozenset(FAILED)
)
'''


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tier", choices=["A", "B", "C"], help="какой тир разметить")
    ap.add_argument("--verify", choices=["A", "B", "C"],
                    help="положительный контроль: сверить с доставленным реестром тира")
    ap.add_argument("--from-report", help="взять готовый JSON аудита, не гонять заново")
    ap.add_argument("--emit", action="store_true", help="записать реестр в пакет")
    ap.add_argument("--out", help="куда записать реестр (по умолчанию — в пакет)")
    args = ap.parse_args()

    tier = args.verify or args.tier
    if not tier:
        print("нужен --tier или --verify", file=sys.stderr)
        return 2

    try:
        report = load_report(tier, args.from_report)
        sets = build_sets(report)
    except Exception as exc:  # noqa: BLE001 — отказ инструмента громкий
        print(f"ОТКАЗ: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(f"Tier-{tier}: " + " · ".join(
        f"{name}={len(sets[name])}" for _cls, name in CLASS_TO_SET))

    if args.verify:
        problems = verify_against_existing(tier, sets)
        if problems:
            print(f"❌ положительный контроль НЕ сошёлся для Tier-{tier}:", file=sys.stderr)
            for p in problems:
                print("   " + p, file=sys.stderr)
            return 1
        print(f"✅ положительный контроль: генератор воспроизводит доставленный "
              f"_tier_{tier.lower()}_writeoff.py поимённо")
        return 0

    if args.emit or args.out:
        dest = Path(args.out) if args.out else (
            ANALYTICS_DIR / f"_tier_{tier.lower()}_writeoff.py")
        dest.write_text(emit(tier, report, sets), encoding="utf-8")
        print(f"реестр → {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
