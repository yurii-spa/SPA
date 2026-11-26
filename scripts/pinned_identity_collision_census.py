#!/usr/bin/env python3
"""Пол TVL судится по числу, у которого МОЖЕТ НЕ БЫТЬ закреплённого пула — и по одному пулу ДВАЖДЫ.

Остаток G1 приказа владельца «Portfolio CIO» (`inbox-task-portfolio-cio-dynamic-capital-alloc`).
ADR-1069 измерил корень симптома владельца («40 % капитала под низкой ставкой»): корень не в
аллокаторе и не в триме, а во **ВСЕЛЕННОЙ** — доходный хвост либо упёрт в потолок, либо не
допущен. Этот прибор спрашивает про саму допускающую ось ДВА вопроса, которых сегодня не
задаёт ни один живой сторож.

## Вопрос 1 — закреплён ли пул у числа, которым проверен ПОЛ

ADR-398 установил дисциплину словами теста `test_tvl_pinned_provenance`: **хинту ЗАПРЕЩЕНО
штамповать TVL `live`**. Причина названа там же — «побеждает больший TVL» есть тождество,
способное молча уехать; пин делает наблюдение предъявимым (UUID записан, аудитор
перекачивает и воспроизводит число).

Дисциплина применена к `adapter_status.json` — и ТОЛЬКО к нему. Замер 2026-11-25 на живом
каталоге: у второго артефакта 19 ключей `pinned/live/UUID`, 3 ключа `hint/static`, 12
`None/static` — контракт соблюдён дословно. А **поверхность решения**
(`current_positions.json.feed_coverage.tvl_sources`, та самая карта, по которой ADR-053
проверяет пол $5M) объявляет `live` у ВСЕХ 17 кандидатов, включая все три хинтовых:

    euler_v2     поверхность live $369,686      второй артефакт static $150,000,000   (hint)
    morpho_blue  поверхность live $114,724,290  второй артефакт static $2,000,000,000  (hint)
    yearn_v3     поверхность live $18,321,536   второй артефакт static $300,000,000    (hint)

Аллокатор берёт объявление у оркестратора как есть (`allocator.py`: «live only when the
orchestrator record DECLARES it»), оркестратор — у адаптера, адаптер ставит `live` по факту
«фид вернул число», не спрашивая, закреплён ли пул. Направление ошибки — В СТОРОНУ ДОПУСКА.

И собственное поле третьего исхода у поверхности при этом **ПУСТО**: `tvl_floor_unverified: []`
при трёх непроверяемых тождествах. Инвариант #17 требует, чтобы отсутствие наблюдения было
ОТДЕЛЬНЫМ значением; здесь оно представлено пустым списком, то есть «ничего не отсутствует».

## Вопрос 2 — сколько РАЗНЫХ ключей судят свой пол по ОДНОМУ пулу

Потолок концентрации считает ключи разными предметами риска. Замер 2026-11-25:

    morpho_blue        pool 931ea9be  hint (64 соперника, разрыв 0.0053 пп)  потолок 20 %
    morpho_steakhouse  pool 931ea9be  pinned                                 потолок 40 %

Один пул, два ключа, ОДИНАКОВЫЕ числа на поверхности ($114,724,290 / 2.5477 пп) — и
структурный предел пары 60 % книги при потолке корзины T2 50 %. То есть пара СПОСОБНА занять
всю корзину, стоя на одном пуле; а тождество первого из них решает порядок TVL среди 64
соперников с разрывом ставки 0.0053 пп, то есть может уехать к соседу завтра.

Ближайший сторож этого не видит ПО ПОСТРОЕНИЮ: `pool_identity_collision` берёт род
`declared`, а хинтовый ключ своего пула не ОБЪЯВЛЯЕТ — он его УГАДЫВАЕТ, и собственная
оговорка сторожа это говорит вслух («род `declared` этот ключ не берёт»).

## Что прибор НЕ делает

Ничего не чинит и ничего не двигает: ни порогов RiskPolicy, ни пинов, ни адаптеров, ни
`data/`, ни живого трека. Пороги он НЕ перепечатывает — берёт из `RiskConfig` (одно
определение; литерал здесь был бы ровно тем дефектом, про который правило
`.claude/rules/site-numbers.md`). Он НЕ судит, КАКОЙ пул правильный: «пин отсутствует» и
«пин неверен» — разные вопросы, и второй мерить нечем, кроме перекачки фида.

## Три исхода (инвариант #17)

* каталога/файла/секции нет, ключа нет во втором артефакте, пула не названо, потолок не
  объявлен ⇒ **НЕ ИЗМЕРЕНО** с названной причиной. «Пула не названо» НИКОГДА не считается
  «коллизий нет»: по безымянному пулу группировать нечего;
* находок нет ⇒ измеренный ноль, и он печатается как ноль С НАСЕЛЕНИЕМ (сколько ключей
  сверено), иначе «чисто» неотличимо от «сверять было нечего»;
* находки ⇒ названы поимённо, с последствием (проходит ли живое число пол, какой
  структурный предел у пары).

Коды возврата: 0 — сверено и чисто · 1 — находки названы · 2 — НЕ ИЗМЕРЕНО. Когда есть И
находки, И неизмеренные ключи, код **1**, а строка отчёта говорит вслух, что найденное есть
НИЖНЯЯ ГРАНИЦА: молчаливый код 2 похоронил бы названные находки, молчаливый код 0 — обратное.
Только stdlib (+ `RiskConfig` за порогами).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]

#: Провенанс, который производители пишут при наблюдении. Синонимов нет намеренно.
OBSERVED_SOURCE = "live"

#: Значение `pool_match`, которое ADR-398 признаёт закреплением. Ровно одно слово:
#: `hint` и отсутствие матча закреплением НЕ являются, и мягкость здесь означала бы
#: ровно ту подмену, ради которой прибор написан.
PINNED_MATCH = "pinned"


class NotMeasured(RuntimeError):
    """Замер не состоялся. Причина обязана быть названа."""


def data_dir(explicit: Optional[str] = None) -> Path:
    d = Path(explicit or os.environ.get("SPA_DATA_DIR") or (ROOT / "data"))
    if not d.is_dir():
        raise NotMeasured(f"каталога данных нет ({d}) — в git-worktree это ШТАТНО "
                          f"и находкой не является")
    return d


def _load(path: Path) -> Any:
    if not path.is_file():
        raise NotMeasured(f"файла нет: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NotMeasured(f"файл не разобран ({path}): {exc}") from exc


def _observed(doc: Any, key: str, kind: type | tuple[type, ...]) -> Any:
    """Наблюдение ключа или ``None``. Значение не того рода — тоже отсутствие."""
    if not isinstance(doc, dict) or key not in doc:
        return None
    value = doc[key]
    if value is None or isinstance(value, bool):
        return None
    return value if isinstance(value, kind) else None


def _is_observed_source(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() == OBSERVED_SOURCE


def _is_pinned(entry: Any) -> Optional[bool]:
    """Закреплён ли пул у записи второго артефакта.

    ``None`` — запись не разобрана или `pool_match` не объявлен вовсе: это НЕ «не закреплён»,
    а отсутствие ответа, и выше оно становится третьим исходом.
    """
    if not isinstance(entry, dict):
        return None
    match = entry.get("pool_match")
    if not isinstance(match, str) or not match.strip():
        return None
    return match.strip().lower() == PINNED_MATCH


def thresholds() -> tuple[float, float]:
    """(пол TVL, потолок корзины T2) из ЕДИНСТВЕННОГО определения — `RiskConfig`.

    Прибор их не перепечатывает: порог есть решение (ADR), а не замер, и вторая копия
    разошлась бы молча. Модуль недоступен ⇒ третий исход, а не подставленный литерал.
    """
    if str(ROOT) not in sys.path:
        # launchd и прямой зов по пути кладут в `sys.path[0]` КАТАЛОГ СКРИПТА, а не корень
        # репозитория (`.claude/rules/deployment.md`), поэтому корень называется здесь, а не
        # надеждой на `cd`. Без этого прибор честно отвечал «пороги НЕ ПРОЧИТАНЫ» — третий
        # исход верен, но на вопрос он не отвечает.
        sys.path.insert(0, str(ROOT))
    try:
        from spa_core.risk.policy import RiskConfig
    except Exception as exc:  # pragma: no cover - окружение без пакета
        raise NotMeasured(f"пороги НЕ ПРОЧИТАНЫ: `spa_core.risk.policy` не ввезён ({exc}) — "
                          f"перепечатать их литералом значило бы завести вторую копию") from exc
    cfg = RiskConfig()
    floor = getattr(cfg, "min_tvl_usd", None)
    t2 = getattr(cfg, "max_total_t2_allocation", None)
    if not isinstance(floor, (int, float)) or not isinstance(t2, (int, float)):
        raise NotMeasured("пороги НЕ ПРОЧИТАНЫ: у `RiskConfig` нет `min_tvl_usd` / "
                          "`max_total_t2_allocation` в ожидаемом роде")
    return float(floor), float(t2)


def measure(explicit_dir: Optional[str] = None) -> dict:
    ddir = data_dir(explicit_dir)
    floor_usd, t2_cap = thresholds()

    book = _load(ddir / "current_positions.json")
    coverage = _observed(book, "feed_coverage", dict)
    if coverage is None:
        raise NotMeasured("в снимке книги нет `feed_coverage` — поверхности решения, на которой "
                          "проверяется пол, не объявлено вовсе")
    tvl_sources = _observed(coverage, "tvl_sources", dict)
    if tvl_sources is None:
        raise NotMeasured("в `feed_coverage` нет карты `tvl_sources` — чем проверен пол, "
                          "не сказано ни для одного ключа")
    tvl_values = _observed(coverage, "tvl_usd", dict) or {}

    status = _load(ddir / "adapter_status.json")
    entries = _observed(status, "adapters", dict)
    if entries is None:
        raise NotMeasured("в adapter_status.json нет секции `adapters` — спросить о закреплении "
                          "пула некого")

    positions = _observed(book, "positions", dict) or {}
    funded = {str(p) for p, u in positions.items()
              if isinstance(u, (int, float)) and not isinstance(u, bool) and u > 0}

    # Ось 1: поверхность объявила наблюдение — закреплён ли пул у этого числа.
    surface_live = sorted(p for p in tvl_sources if _is_observed_source(tvl_sources.get(p)))
    live_by_hint: list[dict] = []
    unmeasured_pin: list[dict] = []
    for proto in surface_live:
        entry = entries.get(proto)
        pinned = _is_pinned(entry)
        if pinned is None:
            unmeasured_pin.append({
                "protocol": proto,
                "reason": ("ключа нет во втором артефакте" if not isinstance(entry, dict)
                           else "второй артефакт не объявил `pool_match`"),
            })
            continue
        if pinned:
            continue
        live_value = _observed({"v": tvl_values.get(proto)}, "v", (int, float))
        live_by_hint.append({
            "protocol": proto,
            "match": (entry.get("pool_match") if isinstance(entry, dict) else None),
            "pool_id": (entry.get("pool_id") if isinstance(entry, dict) else None),
            "surface_tvl_usd": live_value,
            "second_tvl_usd": _observed(entry, "tvl_usd", (int, float)),
            "second_source": (entry.get("tvl_source") if isinstance(entry, dict) else None),
            "passes_floor": (None if live_value is None else live_value >= floor_usd),
            "funded": proto in funded,
            "hint_rivals": _observed(entry, "hint_rivals", dict),
        })

    # Ось 2: сколько РАЗНЫХ ключей поверхности судят свой пол по ОДНОМУ пулу.
    by_pool: dict[str, list[str]] = {}
    unmeasured_pool: list[dict] = []
    for proto in surface_live:
        entry = entries.get(proto)
        pool = entry.get("pool_id") if isinstance(entry, dict) else None
        if not isinstance(pool, str) or not pool.strip():
            unmeasured_pool.append({
                "protocol": proto,
                "reason": ("ключа нет во втором артефакте" if not isinstance(entry, dict)
                           else "пул не назван — группировать по безымянному нечего"),
            })
            continue
        by_pool.setdefault(pool.strip(), []).append(proto)

    collisions: list[dict] = []
    for pool, protos in sorted(by_pool.items()):
        if len(protos) < 2:
            continue
        caps, caps_unmeasured = [], []
        for p in sorted(protos):
            cap = _observed(entries.get(p), "per_protocol_cap", (int, float))
            if cap is None:
                caps_unmeasured.append(p)
            else:
                caps.append((p, float(cap)))
        collisions.append({
            "pool_id": pool,
            "protocols": sorted(protos),
            "matches": {p: (entries.get(p) or {}).get("pool_match") for p in sorted(protos)},
            "caps": dict(caps),
            "caps_unmeasured": caps_unmeasured,
            # Структурный предел пары складывается ТОЛЬКО из объявленных потолков; при
            # неизмеренном потолке сумма НЕ выдаётся за полную.
            "structural_ceiling": (round(sum(c for _, c in caps), 6) if caps else None),
            "structural_ceiling_partial": bool(caps_unmeasured),
            "exceeds_t2_bucket": (None if not caps
                                  else sum(c for _, c in caps) > t2_cap),
            "funded": sorted(p for p in protos if p in funded),
        })

    declared_unverified = coverage.get("tvl_floor_unverified")
    return {
        "data_dir": str(ddir),
        "as_of": book.get("generated_at"),
        "second_artifact_as_of": status.get("generated_at"),
        "floor_usd": floor_usd,
        "t2_bucket_cap": t2_cap,
        "surface_live_keys": len(surface_live),
        "second_artifact_keys": len(entries),
        "funded_keys": sorted(funded),
        "live_by_hint": live_by_hint,
        "pin_unmeasured": unmeasured_pin,
        "pools_compared": len(by_pool),
        "pool_unmeasured": unmeasured_pool,
        "collisions": collisions,
        "surface_declares_unverified": declared_unverified,
        "surface_declares_unverified_count": (len(declared_unverified)
                                              if isinstance(declared_unverified, list) else None),
    }


def _findings(r: dict) -> bool:
    return bool(r["live_by_hint"] or r["collisions"])


def _unmeasured(r: dict) -> bool:
    return bool(r["pin_unmeasured"] or r["pool_unmeasured"])


def format_report(r: dict) -> list[str]:
    out = [
        f"Закрепление пула у числа, которым проверен пол, и коллизии тождества "
        f"(каталог {r['data_dir']}, снимок {str(r['as_of'])[:19]}):",
        f"  поверхность решения объявила наблюдение TVL у {r['surface_live_keys']} ключ(а/ей); "
        f"второй артефакт знает {r['second_artifact_keys']}; "
        f"пол ${r['floor_usd']:,.0f}, потолок корзины T2 {r['t2_bucket_cap']:.0%}",
    ]
    for row in r["live_by_hint"]:
        tail = ""
        if row["surface_tvl_usd"] is not None:
            tail = (f" — живое ${row['surface_tvl_usd']:,.0f}, пол "
                    f"{'ПРОХОДИТ' if row['passes_floor'] else 'НЕ ПРОХОДИТ'}")
        rivals = row.get("hint_rivals") or {}
        if rivals.get("count"):
            tail += (f"; соперников {rivals['count']}, разрыв ставки "
                     f"{rivals.get('apy_spread_pp')} пп")
        out.append(f"  ЖИВОЕ БЕЗ ПИНА  {row['protocol']} (`{row['match']}`, пул "
                   f"{str(row['pool_id'])[:8]}, второй артефакт `{row['second_source']}`)"
                   f"{' [В КНИГЕ]' if row['funded'] else ''}{tail}")
    for row in r["collisions"]:
        ceil = row["structural_ceiling"]
        ceil_s = ("НЕ ИЗМЕРЕН" if ceil is None
                  else f"{ceil:.0%}{' (ЧАСТИЧНО)' if row['structural_ceiling_partial'] else ''}")
        # Вложенная строка ТОЙ ЖЕ кавычкой внутри поля f-string разбирается только
        # Python 3.12+, а контрольный прогон идёт на 3.11 (сторож
        # `spa_core/tests/test_fstring_ci_python_compat.py`): на origin этот файл в
        # CI НЕ РАЗБИРАЛСЯ вовсе. Выражение вынесено наружу; ни один знак вывода не
        # изменён — сверено прогоном прибора до и после.
        matches = row["matches"]
        pairs = ", ".join("%s=`%s`" % (p, matches.get(p)) for p in row["protocols"])
        out.append(f"  ОДИН ПУЛ, {len(row['protocols'])} КЛЮЧА  {row['pool_id'][:8]}: "
                   f"{pairs} — "
                   f"структурный предел {ceil_s}, потолок корзины T2 {r['t2_bucket_cap']:.0%}"
                   f"{' — ПРЕВЫШЕН' if row['exceeds_t2_bucket'] else ''}"
                   f"{' [В КНИГЕ: ' + ', '.join(row['funded']) + ']' if row['funded'] else ''}")
    for row in r["pin_unmeasured"]:
        out.append(f"  НЕ ИЗМЕРЕНО (пин)  {row['protocol']}: {row['reason']}")
    for row in r["pool_unmeasured"]:
        out.append(f"  НЕ ИЗМЕРЕНО (пул)  {row['protocol']}: {row['reason']}")
    n = r["surface_declares_unverified_count"]
    if n is not None:
        out.append(f"  поверхность объявляет непроверенным пол у {n} ключ(а/ей) "
                   f"(`tvl_floor_unverified`), прибор нашёл {len(r['live_by_hint'])} "
                   f"без пина")
    else:
        out.append("  НЕ ИЗМЕРЕНО: поверхность не объявила `tvl_floor_unverified` ни одним родом")
    if _findings(r) and _unmeasured(r):
        out.append(f"  ⚠️ население НЕ ПОЛНО: {len(r['pin_unmeasured'])} ключ(а/ей) без ответа о "
                   f"пине и {len(r['pool_unmeasured'])} без названного пула — найденное есть "
                   f"НИЖНЯЯ ГРАНИЦА, а не итог")
    if not _findings(r):
        out.append(f"  ✅ измеренный НОЛЬ: сверено {r['surface_live_keys']} ключ(а/ей) "
                   f"и {r['pools_compared']} пул(а/ов) — каждое живое число закреплено, "
                   f"одного пула на два ключа нет")
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default=None,
                    help="каталог данных (умолчание — SPA_DATA_DIR или data/)")
    ap.add_argument("--json", action="store_true", help="печатать замер как JSON")
    args = ap.parse_args(argv)

    try:
        r = measure(args.data_dir)
    except NotMeasured as exc:
        print(f"НЕ ИЗМЕРЕНО — {exc}")
        return 2

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    for line in format_report(r):
        print(line)

    if _findings(r):
        return 1
    if _unmeasured(r):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
