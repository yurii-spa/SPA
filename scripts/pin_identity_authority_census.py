#!/usr/bin/env python3
# LLM_FORBIDDEN
"""pin_identity_authority_census — судит ли гейт финансирования ЗАПИНЁННЫЙ пул.

ВОПРОС. Сосед ADR-236 (`measure_pin_placement_effect.pins_invisible_to_the_gate`)
спрашивает, ВИДЕН ли запинённый ключ производителю, по которому решается
финансирование, и отвечает присутствием имени в снимке оркестратора. Это верный
ответ на СВОЙ вопрос — и он ничего не говорит о нужном: присутствие имени не
означает, что снимок наблюдал ТОТ САМЫЙ пул, который пин объявил. Ключ виден,
пин на месте, а гейт судит другой инструмент — и оба артефакта при этом зелены.

Здесь задан второй вопрос и только он: **для каждого запинённого ключа — какой
пул назвал производитель, по которому ADR-053 решает о деньгах, и тот ли это пул,
что объявлен пином.**

ЗАЧЕМ ЭТО НЕ АКАДЕМИЯ (замер 2026-09-30, живой каталог `data/`):

  aave_v3           пин aa70268e… · снимок гейта 6f00d46b… — РАЗНЫЕ пулы
  morpho_blue_base  пин ba68527f… · снимок гейта 8276be38… — РАЗНЫЕ пулы
  compound_v3       пин 7da72d09… · снимок гейта не назвал пул ВОВСЕ

Комментарий у самой таблицы пинов говорит прямо: «Only a pinned match may stamp
``tvl_source: "live"``, because the $5M TVL floor is a policy gate and a gate must
not rest on a match that can drift». Именно это и происходит: снимок оркестратора
штампует ``tvl_source: "live"`` на пуле, которого пин не объявлял, и порог $5M
проверяется по нему. На 30.09 под тремя такими ключами лежит $55 000 из $95 000
развёрнутых — 57.9 % книги.

ЧТО ЭТОТ ПРИБОР НЕ ДЕЛАЕТ. Он не выбирает, какой пул верен, не правит пины, не
трогает ``POLLED_ADAPTERS``, адаптеры, аллокатор, RiskPolicy v1.0, стоп-кран и
живой трек. Он ТОЛЬКО ЧИТАЕТ два файла и объявленную таблицу пинов. Починка
(«закрепить пул за ключом у того производителя, который решает о деньгах») —
money-path и отдельное решение, а не следствие замера.

ФОРМА ИСХОДА ЗАКРЫТА, и третий исход обязателен (инв. #17):

  honours              снимок гейта назвал РОВНО запинённый пул
  identity_mismatch    снимок назвал ДРУГОЙ пул — громко
  identity_unmeasured  ключ в снимке есть, пул не назван (null/пусто) — громко;
                       это НЕ «пул тот же», иначе молчание зачлось бы как согласие
  absent_from_gate     ключа в снимке нет вовсе — предмет соседа ADR-236, здесь
                       только считается, чтобы сумма исходов равнялась населению

ДЕНЬГИ. Доллары книги разложены по тем же исходам плюс ведро ``unpinned`` (у
позиции нет пина вовсе — объявленной личности не существует, и честь ей оказывать
нечему). Знаменатель — развёрнутый капитал; ``unpinned``-доллары входят в
знаменатель и НЕ входят в числитель власти: недоказанное тождество властью не
является. Книга не прочитана ⇒ деньги ``unmeasured`` с причиной, а не $0.

КОДЫ ВОЗВРАТА:
  0 — измерено, громких находок нет;
  1 — измерено, есть громкая находка (mismatch / identity_unmeasured);
  2 — НЕ ИЗМЕРЕНО с названной причиной (снимок не прочитан, снимок пуст, таблица
      пинов не прочитана). Ноль находок отсюда не выводится никогда.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

#: Исходы в объявленном порядке. Форма ЗАКРЫТА: сумма ведёр обязана равняться
#: населению, и отдельный тест это требует.
OUTCOMES = ("honours", "identity_mismatch", "identity_unmeasured", "absent_from_gate")

#: Какие исходы громкие. Присутствие/отсутствие ключа — предмет соседа ADR-236;
#: считать его громким и здесь значило бы изобразить рост находок.
LOUD = ("identity_mismatch", "identity_unmeasured")

_UNMEASURED = "НЕ ИЗМЕРЕНО"


def _load_pins() -> tuple[Optional[dict[str, str]], Optional[str]]:
    """Объявленная таблица пинов, либо причина, по которой её нет.

    Имя приватное намеренно: канон один, и второй копии таблицы в репозитории
    быть не должно (`.claude/rules/adapters.md`, «одно имя — один объект»).
    Сосед ADR-236 читает её тем же способом.
    """
    try:
        from spa_core.monitoring.adapter_status_generator import _POOL_ID_LOOKUP
    except Exception as exc:  # noqa: BLE001 — молчание здесь = fail-OPEN
        return None, f"таблица пинов не прочитана: {type(exc).__name__}: {exc}"
    if not isinstance(_POOL_ID_LOOKUP, dict) or not _POOL_ID_LOOKUP:
        return None, ("таблица пинов пуста — «нарушений нет» и «сверять было "
                      "нечего» это разные факты")
    return {str(k): str(v) for k, v in _POOL_ID_LOOKUP.items()}, None


def _read_json(path: Path) -> tuple[Optional[Any], Optional[str]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, f"{path.name}: {type(exc).__name__}: {exc}"


def _gate_rows(data_dir: Path) -> tuple[Optional[dict[str, dict]], Optional[str]]:
    """Строки производителя, по которому ADR-053 решает о финансировании."""
    doc, why = _read_json(data_dir / "adapter_orchestrator_status.json")
    if doc is None:
        return None, f"снимок оркестратора не прочитан: {why}"
    rows = doc.get("adapters") if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not rows:
        return None, ("в снимке оркестратора нет ни одной строки — «пин уважён» "
                      "и «сверять было нечего» это разные факты")
    out: dict[str, dict] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("protocol"):
            out[str(row["protocol"])] = row
    if not out:
        return None, ("ни одна строка снимка не назвала протокол — население "
                      "сверки пусто, и это не ноль нарушений")
    return out, None


def _pool_of(row: dict) -> Optional[str]:
    """Пул, НАЗВАННЫЙ снимком, либо ``None`` = «личность не измерена»."""
    raw = row.get("pool_id")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


def _book(data_dir: Path) -> tuple[Optional[dict[str, float]], Optional[float], Optional[str]]:
    """(позиции, развёрнутый капитал, причина-отказ)."""
    doc, why = _read_json(data_dir / "current_positions.json")
    if doc is None:
        return None, None, f"книга не прочитана: {why}"
    if not isinstance(doc, dict):
        return None, None, "книга не является объектом"
    pos = doc.get("positions")
    if not isinstance(pos, dict):
        return None, None, ("в книге нет раздела `positions` — доллары НЕ "
                            "ИЗМЕРЕНЫ, а не равны нулю")
    held: dict[str, float] = {}
    for key, val in pos.items():
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            held[str(key)] = float(val)
    deployed = doc.get("deployed_usd")
    if not isinstance(deployed, (int, float)) or isinstance(deployed, bool):
        # Знаменатель восполняется суммой позиций, и это сказано вслух.
        deployed = sum(held.values())
    return held, float(deployed), None


def census(data_dir: Path, now_fn: Optional[Callable[[], datetime]] = None) -> dict:
    """Перепись власти пина у производителя, решающего о деньгах."""
    now_fn = now_fn or (lambda: datetime.now(timezone.utc))
    out: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": now_fn().isoformat(),
        "generated_by": "pin_identity_authority_census",
        "unmeasured": None,
        "population": 0,
        "outcomes": {name: [] for name in OUTCOMES},
        "findings": [],
        "money": {"unmeasured": "не считались: сверка не дошла до денег"},
    }

    pins, why = _load_pins()
    if pins is None:
        out["unmeasured"] = why
        return out
    out["population"] = len(pins)

    rows, why = _gate_rows(Path(data_dir))
    if rows is None:
        out["unmeasured"] = why
        return out
    out["gate_rows"] = len(rows)

    for key in sorted(pins):
        declared = pins[key]
        row = rows.get(key)
        if row is None:
            out["outcomes"]["absent_from_gate"].append(key)
            continue
        seen = _pool_of(row)
        if seen is None:
            kind = "identity_unmeasured"
        elif seen == declared:
            kind = "honours"
        else:
            kind = "identity_mismatch"
        out["outcomes"][kind].append(key)
        if kind in LOUD:
            out["findings"].append({
                "key": key,
                "kind": kind,
                "declared_pool": declared,
                "gate_pool": seen,
                "tvl_usd": row.get("tvl_usd"),
                "tvl_source": row.get("tvl_source"),
                "apy_pct": row.get("apy_pct"),
                "message": _message(key, kind, declared, seen, row),
            })

    counted = sum(len(v) for v in out["outcomes"].values())
    if counted != out["population"]:  # pragma: no cover — держит тест
        out["unmeasured"] = (f"сумма исходов {counted} не равна населению "
                             f"{out['population']} — форма исхода разъехалась")
        return out

    out["money"] = _money(Path(data_dir), out["outcomes"])
    return out


def _message(key: str, kind: str, declared: str, seen: Optional[str], row: dict) -> str:
    tvl = row.get("tvl_usd")
    src = row.get("tvl_source")
    tail = (f"снимок штампует `tvl_source: {src!r}` и TVL {tvl} на этом пуле — "
            f"порог $5M (ADR-053) проверяется ИМЕННО по нему")
    if kind == "identity_mismatch":
        return (f"{key}: гейт финансирования судит пул {seen}, а пин объявляет "
                f"{declared} — это РАЗНЫЕ инструменты, и {tail}. Починка — "
                f"закрепить пул за ключом у ЭТОГО производителя, а не выбрать "
                f"число; выбор числа здесь ничего не лечит")
    return (f"{key}: гейт финансирования не назвал пул ВОВСЕ (`pool_id` пуст), "
            f"хотя пин объявляет {declared} — молчание о личности не есть "
            f"согласие с пином, и {tail}")


def _money(data_dir: Path, outcomes: dict[str, list[str]]) -> dict:
    held, deployed, why = _book(data_dir)
    if held is None:
        return {"unmeasured": why}
    where = {k: name for name, keys in outcomes.items() for k in keys}
    buckets: dict[str, float] = {name: 0.0 for name in OUTCOMES}
    buckets["unpinned"] = 0.0
    for key, usd in held.items():
        buckets[where.get(key, "unpinned")] += usd
    total = sum(buckets.values())
    share = (buckets["honours"] / deployed) if deployed else None
    return {
        "unmeasured": None,
        "deployed_usd": deployed,
        "held_by_outcome": buckets,
        "held_total_usd": total,
        "authority_share": share,
        # Остаток называется вслух: книга и знаменатель — два разных числа, и
        # молча подогнать их значило бы спрятать расхождение.
        "book_vs_deployed_gap_usd": round(total - deployed, 2),
    }


def report_lines(result: dict) -> list[str]:
    """Строки для обязательного шага 0-офис."""
    head = "— власть пина у гейта финансирования (ADR-520) —"
    if result.get("unmeasured"):
        return [head, f"   [{_UNMEASURED}] {result['unmeasured']}"]

    oc = result["outcomes"]
    lines = [head, (
        f"   запинённых ключей {result['population']}: уважено {len(oc['honours'])} · "
        f"ДРУГОЙ ПУЛ {len(oc['identity_mismatch'])} · пул не назван "
        f"{len(oc['identity_unmeasured'])} · нет в снимке "
        f"{len(oc['absent_from_gate'])} (предмет ADR-236)"
    )]
    for f in result["findings"]:
        lines.append(f"   [CRITICAL] {f['message']}")
    if not result["findings"]:
        lines.append("   ✅ каждый запинённый ключ, который снимок гейта вообще "
                     "назвал, назван ЗАПИНЁННЫМ пулом")

    money = result.get("money") or {}
    if money.get("unmeasured"):
        lines.append(f"      [{_UNMEASURED}] деньги: {money['unmeasured']}")
        return lines
    b = money["held_by_outcome"]
    dep = money["deployed_usd"]
    not_authoritative = dep - b["honours"]
    lines.append(
        f"      ДЕНЬГИ: из ${dep:,.2f} развёрнутых на объявленной личности стои́т "
        f"${b['honours']:,.2f} ({(money['authority_share'] or 0) * 100:.1f} %); "
        f"НЕ стои́т ${not_authoritative:,.2f} — другой пул ${b['identity_mismatch']:,.2f} · "
        f"пул не назван ${b['identity_unmeasured']:,.2f} · нет в снимке "
        f"${b['absent_from_gate']:,.2f} · пина нет вовсе ${b['unpinned']:,.2f}"
    )
    lines.append("      доллары без пина входят в знаменатель и НЕ входят в "
                 "числитель: недоказанное тождество властью не является")
    if money["book_vs_deployed_gap_usd"]:
        lines.append(f"      [{_UNMEASURED}] книга и знаменатель расходятся на "
                     f"${money['book_vs_deployed_gap_usd']:,.2f} — доли считаны "
                     f"по объявленному развёрнутому капиталу")
    lines.append("      ADVISORY: прибор только ЧИТАЕТ. Пины, POLLED_ADAPTERS, "
                 "адаптеры, аллокатор, пороги RiskPolicy v1.0, стоп-кран, живой "
                 "трек и landing/ НЕ трогаются")
    return lines


def exit_code(result: dict) -> int:
    if result.get("unmeasured"):
        return 2
    return 1 if result.get("findings") else 0


def main(argv: Optional[list[str]] = None) -> int:  # noqa: D103
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default=str(_REPO_ROOT / "data"),
                    help="каталог data/ прод-дерева (из worktree живого нет)")
    ap.add_argument("--json", action="store_true", help="печатать сырой результат")
    args = ap.parse_args(argv)

    result = census(Path(args.data_dir))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for line in report_lines(result):
            print(line)
    return exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
