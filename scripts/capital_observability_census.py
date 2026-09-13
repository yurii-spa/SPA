#!/usr/bin/env python3
"""Доля КАПИТАЛА, стоящего на НАБЛЮДЁННЫХ числах — приёмка G1 приказа владельца «Portfolio CIO».

Приказ `inbox-task-portfolio-cio-dynamic-capital-alloc` (13.08) требовал сперва установить
ФАКТИЧЕСКИ, почему книга выглядит замороженной. Диагностика (`docs/research/RS-portfolio-cio-diagnosis.md`)
назвала корнем не аллокатор, а наблюдаемость входов и записала приёмочную метрику §5:
**доля капитала, ранжированного по наблюдённым числам — было 25 %, цель 100 %**.

Дыру в коде закрыли 02.08 (`spa_core/adapters/status_reader.py`, ADR-063), но **метрику после
починки не сняли ни разу** — ни одного числа нет ни в одном документе. Пока её нет, SHADOW-вердикты
триггера ADR-060 меряют качество решений на входах неизвестного происхождения, и вопрос о взводе
триггера (ARM) задавать владельцу нельзя по его же решению 02.08 («сначала честные числа»).

## Что меряется — и почему ДВЕ оси, а не одна

Финансирование решают два РАЗНЫХ числа, и наблюдённость у них разная:

| ось | что решает | чем гейтится |
|---|---|---|
| APY | КТО получает капитал (ранжирование) | полоса 1…30 %, ADR-061 evidence gate |
| TVL | ДОПУСКАЕТСЯ ли пул вообще | пол $5M ТОЛЬКО по живому TVL (ADR-053) |

Артефакт `current_positions.json` уже печатает `feed_coverage.live_pct` — и это доля по оси
**APY и только APY**. Зелёные «100 %» там не говорят об оси TVL ничего: 12.09 обе оси сошлись,
а вопрос «а на чём стоит пол?» не задавал никто. Считать одну ось ответом за обе — ровно тот
класс, ради которого правило «зелёный ответ сторожа на СВОЙ вопрос не есть ответ на нужный»
и написано.

## Где меряется: у ПОВЕРХНОСТИ РЕШЕНИЯ, а не у самого свежего файла

Про один и тот же протокол в системе живут ДВА артефакта, и они спорят (замер 12.09):

* `data/current_positions.json` → `feed_coverage` — то, чем аллокатор РЕАЛЬНО ранжировал
  и гейтил в этом цикле (его вход — снимок оркестратора). `aave_v3`: TVL $206 107 174, `live`.
* `data/adapter_status.json` → `adapters` — второй снимок, который читают отчёты, телеграм и
  стратегии. Тот же `aave_v3` в тот же цикл: TVL $12 000 000 000, `static` — литерал в 58 раз
  больше наблюдения, лежавшего рядом.

Доля капитала меряется по ПЕРВОМУ: деньги стоят на том числе, которым их разложили. Второй
сверяется отдельно и его расхождения НАЗЫВАЮТСЯ — литерал, доезжающий до отчёта владельца
там, где наблюдение существовало, это находка, а не шум.

## Что НЕ считается наблюдением

Только объявленный производителем провенанс (`"live"`). Значение поля `apy`/`tvl_usd` само по
себе доказательством не является: при отсутствии наблюдения оно эхом повторяет `fallback_apy`
(см. шапку `status_reader.py`) — на этом и держался дефект 02.08. Протокол, у которого деньги
есть, а провенанс НЕ ОБЪЯВЛЕН вовсе, считается ненаблюдённым (fail-CLOSED) и называется
отдельной причиной: «не объявлен» и «объявлен литералом» — разные болезни с разным лечением.

## Третий исход (инвариант #17)

Нет каталога, файла, ключа `positions` или всей карты `feed_coverage` ⇒ **«НЕ ИЗМЕРЕНО»** с
названной причиной и кодом 2. Пустая книга — тоже НЕ ИЗМЕРЕНО: доли у нуля не существует, и
выдавать её за 0 % («всё плохо») или 100 % («всё хорошо») одинаково неверно. А вот книга, где
НИ ОДИН доллар не стоит на наблюдении, — это измеренный НОЛЬ, и он обязан быть отличим от
обоих. Отсутствие `data/` в git-worktree штатно и находкой не является.

Коды возврата: 0 — обе оси 100 % и второй артефакт не спорит · 1 — находки названы ·
2 — НЕ ИЗМЕРЕНО.

Только stdlib. Прибор ЧИТАЕТ и ничего не чинит: ни `data/`, ни адаптеры, ни пороги.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]

#: Провенанс, который считается наблюдением. Ровно одно слово: производители пишут `"live"`
#: (ADR-053/061/063). Регистр и пробелы нормализуются — писателей несколько; синонимов НЕТ
#: намеренно: «static», «fallback», «advisory», «hint» суть НЕ наблюдения, и мягкость здесь
#: означала бы ровно ту подмену, ради которой прибор написан.
OBSERVED_SOURCE = "live"

#: Ось → ключ карты провенанса в `feed_coverage`.
AXES = {"apy": "apy_sources", "tvl": "tvl_sources"}


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


def _second_artifact_claim(entry: Any) -> tuple[Optional[bool], Optional[bool]]:
    """(apy наблюдён?, tvl наблюдён?) по записи `adapter_status.json`.

    ``None`` — запись не разобрана (протокола нет / не словарь). У APY признаком служит
    ``live_apy``: ``null`` там означает, что производитель НЕ наблюдал, а соседнее ``apy``
    в этом случае эхом повторяет литерал.
    """
    if not isinstance(entry, dict):
        return None, None
    apy_obs = _observed(entry, "live_apy", (int, float)) is not None
    tvl_obs = _is_observed_source(entry.get("tvl_source"))
    return apy_obs, tvl_obs


def measure(explicit_dir: Optional[str] = None) -> dict:
    ddir = data_dir(explicit_dir)
    book = _load(ddir / "current_positions.json")

    positions = _observed(book, "positions", dict)
    if positions is None:
        raise NotMeasured("в снимке книги нет карты `positions` — какие деньги где стоят, "
                          "не сказано; доля от неизвестного знаменателя не считается")

    funded = {}
    for proto, usd in positions.items():
        if isinstance(usd, bool) or not isinstance(usd, (int, float)):
            raise NotMeasured(f"позиция `{proto}` не число ({usd!r}) — знаменатель НЕ ИЗМЕРЕН")
        if usd > 0:
            funded[str(proto)] = float(usd)

    deployed = sum(funded.values())
    if deployed <= 0:
        raise NotMeasured("книга пуста: развёрнуто $0. Доли у нуля не существует — это НЕ 0 % "
                          "(«всё стоит на литералах») и НЕ 100 % («всё наблюдено»)")

    coverage = _observed(book, "feed_coverage", dict)
    if coverage is None:
        raise NotMeasured("в снимке книги нет `feed_coverage` — провенанс входов не объявлен "
                          "ни для одного протокола")

    axes: dict[str, dict] = {}
    for axis, key in AXES.items():
        sources = _observed(coverage, key, dict)
        if sources is None:
            raise NotMeasured(f"в `feed_coverage` нет карты `{key}` — ось {axis.upper()} "
                              f"не измерена ни для одного доллара")
        observed_usd = 0.0
        literal, undeclared = [], []
        for proto, usd in sorted(funded.items()):
            if proto not in sources:
                undeclared.append({"protocol": proto, "usd": usd})
            elif _is_observed_source(sources.get(proto)):
                observed_usd += usd
            else:
                literal.append({"protocol": proto, "usd": usd,
                                "declared": sources.get(proto)})
        axes[axis] = {
            "observed_usd": round(observed_usd, 2),
            "observed_pct": round(100.0 * observed_usd / deployed, 4),
            "on_literal": literal,
            "provenance_undeclared": undeclared,
        }

    # Второй артефакт о тех же деньгах. Его отсутствие НЕ обнуляет главный замер и НЕ выдаётся
    # за согласие: сверка отдельно объявляется несостоявшейся.
    second: dict = {"read": False, "reason": None, "disagreements": []}
    try:
        status = _load(ddir / "adapter_status.json")
    except NotMeasured as exc:
        second["reason"] = str(exc)
    else:
        entries = _observed(status, "adapters", dict)
        if entries is None:
            second["reason"] = "в adapter_status.json нет секции `adapters`"
        else:
            second["read"] = True
            for proto, usd in sorted(funded.items()):
                if proto not in entries:
                    second["disagreements"].append({
                        "protocol": proto, "usd": usd, "axis": "-",
                        "kind": "absent_from_second_artifact",
                        "surface": "профинансирован", "second": "протокола нет вовсе"})
                    continue
                apy_obs, tvl_obs = _second_artifact_claim(entries[proto])
                for axis, obs in (("apy", apy_obs), ("tvl", tvl_obs)):
                    surface_obs = _is_observed_source(
                        (_observed(coverage, AXES[axis], dict) or {}).get(proto))
                    if obs is None or obs == surface_obs:
                        continue
                    kind = ("second_artifact_blind" if surface_obs
                            else "decision_surface_blind")
                    row = {"protocol": proto, "usd": usd, "axis": axis, "kind": kind,
                           "surface": "наблюдение" if surface_obs else "литерал",
                           "second": "наблюдение" if obs else "литерал"}
                    if axis == "tvl":
                        row["surface_value"] = (_observed(coverage, "tvl_usd", dict) or {}).get(proto)
                        row["second_value"] = _observed(entries[proto], "tvl_usd", (int, float))
                    second["disagreements"].append(row)

    # Третья копия провенанса живёт в ТОМ ЖЕ файле (`positions_detail.apy_source`). Спор двух
    # полей одного снимка — самая дешёвая улика, какая бывает, и молчать о нём нельзя.
    internal = []
    detail = _observed(book, "positions_detail", dict) or {}
    apy_map = _observed(coverage, "apy_sources", dict) or {}
    for proto in sorted(funded):
        d = detail.get(proto)
        if not isinstance(d, dict) or "apy_source" not in d:
            continue
        if _is_observed_source(d.get("apy_source")) != _is_observed_source(apy_map.get(proto)):
            internal.append({"protocol": proto, "usd": funded[proto],
                             "positions_detail": d.get("apy_source"),
                             "feed_coverage": apy_map.get(proto)})

    declared_deployed = _observed(book, "deployed_usd", (int, float))
    return {
        "data_dir": str(ddir),
        "as_of": book.get("generated_at"),
        "deployed_usd": round(deployed, 2),
        "declared_deployed_usd": declared_deployed,
        "deployed_matches_declaration": (declared_deployed is None
                                         or abs(declared_deployed - deployed) <= 0.01),
        "protocols": len(funded),
        "positions": {p: round(u, 2) for p, u in sorted(funded.items())},
        "axes": axes,
        "second_artifact": second,
        "internal_disagreements": internal,
    }


def _findings(r: dict) -> bool:
    return bool(
        any(a["observed_pct"] < 100.0 for a in r["axes"].values())
        or r["second_artifact"]["disagreements"]
        or r["internal_disagreements"]
        or not r["deployed_matches_declaration"]
        or not r["second_artifact"]["read"]
    )


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

    print(f"Доля капитала на НАБЛЮДЁННЫХ числах (каталог {r['data_dir']}, "
          f"снимок {str(r['as_of'])[:19]}):")
    print(f"  развёрнуто ${r['deployed_usd']:,.2f} в {r['protocols']} протокол(ах)")
    for axis in ("apy", "tvl"):
        a = r["axes"][axis]
        print(f"  ось {axis.upper():3}: {a['observed_pct']:6.2f} %  "
              f"(${a['observed_usd']:,.2f} из ${r['deployed_usd']:,.2f})")
        for row in a["on_literal"]:
            print(f"      НА ЛИТЕРАЛЕ  {row['protocol']} ${row['usd']:,.2f} — "
                  f"провенанс объявлен как `{row['declared']}`")
        for row in a["provenance_undeclared"]:
            print(f"      НЕ ОБЪЯВЛЕН  {row['protocol']} ${row['usd']:,.2f} — деньги стоят, "
                  f"провенанса нет в карте вовсе (считаем ненаблюдённым, fail-CLOSED)")
    if not r["deployed_matches_declaration"]:
        print(f"  ⚠️ сумма позиций ${r['deployed_usd']:,.2f} расходится с объявленным "
              f"deployed_usd ${r['declared_deployed_usd']:,.2f}")
    if not r["second_artifact"]["read"]:
        print(f"  ⚠️ сверка со вторым артефактом НЕ СОСТОЯЛАСЬ: {r['second_artifact']['reason']}")
    for row in r["second_artifact"]["disagreements"]:
        extra = ""
        if row.get("second_value") is not None and row.get("surface_value"):
            try:
                extra = (f" — ${row['second_value']:,.0f} против ${row['surface_value']:,.0f}, "
                         f"×{row['second_value'] / row['surface_value']:,.1f}")
            except ZeroDivisionError:
                extra = ""
        print(f"  СПОР АРТЕФАКТОВ {row['protocol']} (${row['usd']:,.2f}, ось {row['axis'].upper()}): "
              f"поверхность решения — {row['surface']}, adapter_status.json — {row['second']}{extra}")
    for row in r["internal_disagreements"]:
        print(f"  СПОР ВНУТРИ ФАЙЛА {row['protocol']} (${row['usd']:,.2f}): "
              f"positions_detail `{row['positions_detail']}` против "
              f"feed_coverage `{row['feed_coverage']}`")

    if not _findings(r):
        print("  ✅ обе оси 100 %, второй артефакт не спорит")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
