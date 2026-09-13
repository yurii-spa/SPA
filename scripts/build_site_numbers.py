#!/usr/bin/env python3
"""Витрина чисел сайта: ОДИН адрес, откуда страница берёт любое число.

Установка владельца 12.09 ([ADR-357](../docs/decisions/ADR-357-owner-decisions-2026-09-12.md)
п. 5), дословно по смыслу: «все цифры на сайте должны браться консолидированно с одного и
того же места… и тогда вы мне не будете каждый раз спрашивать одно и то же по этим цифрам».
Плюс: обновлять **раз в неделю**, показывать **годовую в среднем**, а не результат за период.

## Почему это НЕ третье место для чисел

`.claude/rules/site-numbers.md` делит числа на **замер** (устаревает за сутки) и **решение**
(меняется только ADR) и запрещает заводить третий ИСТОЧНИК. Запрет остаётся в силе: здесь
не заводится источник, здесь собирается **витрина** — проекция двух источников в один адрес
чтения. Различие существенно:

| | сколько | почему |
|---|---|---|
| источников правды | **два** (`track_snapshot.json`, `constitution.json`) | делит их ПРИРОДА числа: замер стареет, порог — нет |
| адресов, откуда читает страница | **один** (этот файл) | требование владельца; автору страницы больше не надо знать, замер перед ним или порог |

Витрина ничего не вычисляет заново: она берёт уже посчитанное, называет РОД каждого числа и
пересчитывает ставки в годовые единым способом. Своего числа у неё нет ни одного — иначе она
и была бы третьим источником.

## Недельный такт и честность даты

Наблюдение остаётся ЕЖЕДНЕВНЫМ, меняется частота ПУБЛИКАЦИИ. Поэтому у витрины две даты, и
обе видны читателю:

* ``measured_at`` — день, когда снят замер (из снимка трека);
* ``published_at`` — неделя публикации.

Смешать их значило бы выдать недельной давности замер за сегодняшний.

## Третий исход (инв. #17)

Источник не найден, не разобран, или в нём нет обязательного поля ⇒ витрина **НЕ пишется**
целиком и код возврата 2 («НЕ ИЗМЕРЕНО» с названной причиной). Половинчатая витрина хуже
отсутствующей: страница отрендерила бы часть чисел свежими, часть — прошлыми, и никто бы не
сказал, где какие. Отдельные ЗНАЧЕНИЯ, которых нет в замере, остаются ``None`` с названной
причиной — страница обязана напечатать «данные недоступны», а не последнее известное число.

Коды возврата: 0 — витрина собрана · 2 — НЕ ИЗМЕРЕНО.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "landing" / "src" / "data" / "track_snapshot.json"
CONSTITUTION = ROOT / "landing" / "src" / "lib" / "constitution.json"
OUT = ROOT / "landing" / "src" / "data" / "site_numbers.json"

#: Род числа. Третьего не бывает — это и есть правило `site-numbers.md`.
MEASUREMENT = "замер"
DECISION = "решение"

#: Как считается годовая ставка. Названо строкой, потому что «годовая» без метода —
#: не число, а намерение: простая экстраполяция и сложный процент дают разное.
ANNUALISATION = ("сложный процент от якоря доказанного трека: "
                 "(NAV_сегодня / NAV_якоря) ^ (365 / дней) − 1")

#: Поля снимка, без которых витрина бессмысленна. Их отсутствие — отказ, а не `None`.
REQUIRED_SNAPSHOT = ("as_of", "real_track_days", "evidenced_anchor")


class NotMeasured(RuntimeError):
    """Витрина не собрана. Причина обязана быть названа."""


def _load(path: Path) -> dict:
    if not path.is_file():
        raise NotMeasured(f"{path.name} не найден ({path}) — собирать не из чего")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise NotMeasured(f"{path.name} не разобран ({exc})") from exc
    if not isinstance(doc, dict):
        raise NotMeasured(f"{path.name} не объект")
    return doc


def _num(value: object) -> "float | None":
    """Число или ``None``. Булево числом НЕ является (инв. #17, `observation.py`)."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


def figure(value: object, *, unit: str, kind: str, source: str,
           annualised: bool = False, evidence: "str | None" = None,
           unavailable_reason: "str | None" = None) -> dict:
    """Одно число витрины со всем, что о нём обязан знать автор страницы."""
    v = _num(value)
    out = {
        "value": v,
        "unit": unit,
        "kind": kind,
        "source": source,
    }
    if annualised:
        out["annualised"] = True
        out["annualisation"] = ANNUALISATION
    if evidence:
        out["evidence"] = evidence
    if v is None:
        out["unavailable_reason"] = (
            unavailable_reason or "значения нет в источнике — печатать «данные недоступны»")
    return out


def _evidence_split(days: "float | None", observed_since: object,
                    measured_at: object) -> dict:
    """Сколько дней книги начислены по НАБЛЮДЕНИЯМ, а сколько по литералам.

    Обязательство, идущее вместе с решением владельца 12.09 (ADR-357 п. 4): трек
    советательных книг остаётся с 23 августа, и потому рядом с числом обязана стоять
    доля дней, начисленных по ставкам, которых никто не наблюдал. У Aggressive это
    почти весь период, и без такой пометки число читается как заработанное.

    Все три исхода различимы (инв. #17): посчитано · посчитано и литеральных дней
    ноль · НЕ ИЗМЕРЕНО (даты перехода нет — журнала не было или он не прочитан).
    """
    out: dict = {"observed_days": None, "literal_days": None, "caveat": None}
    if days is None or not isinstance(observed_since, str) or not isinstance(measured_at, str):
        out["unmeasured_reason"] = (
            "дата перехода на наблюдённые ставки не измерена — доля литеральных "
            "дней НЕ ИЗВЕСТНА (это не «их ноль»)")
        return out
    try:
        since = date.fromisoformat(observed_since)
        upto = date.fromisoformat(measured_at)
    except ValueError:
        out["unmeasured_reason"] = "дата перехода или дата замера не разобраны"
        return out
    observed = max(0, (upto - since).days + 1)
    observed = min(observed, int(days))
    literal = max(0, int(days) - observed)
    out["observed_days"] = observed
    out["literal_days"] = literal
    out["observed_since"] = observed_since
    if literal > 0:
        out["caveat"] = (
            f"{literal} из {int(days)} дней начислены по ставкам, которых никто не "
            f"наблюдал (до {observed_since}); наблюдения идут с {observed_since}")
    return out


def _book(track: dict, key: str, label: str, measured_at: object = None) -> dict:
    b = track.get(key) if isinstance(track, dict) else None
    b = b if isinstance(b, dict) else {}
    days = _num(b.get("days_with_positions"))
    return {
        "label": label,
        "status": b.get("status"),
        "days": days,
        "evidence_split": _evidence_split(days, b.get("observed_accrual_since"), measured_at),
        "apy": figure(b.get("apy_pct"), unit="%", kind=MEASUREMENT, annualised=True,
                      source="landing/src/data/track_snapshot.json → paper_tracks",
                      evidence=b.get("evidence"),
                      unavailable_reason="книга ещё не дала годовой ставки — "
                                         "печатать «идёт paper-тест», не число"),
        # Хвост публикуется РЯДОМ со ставкой намеренно: инвариант #8 и
        # `.claude/rules/site-copy.md` требуют показывать просадку вместе с доходностью.
        # Разнести их по разным местам страницы — то же, что не показать.
        "drawdown": figure(b.get("dd_pct"), unit="%", kind=MEASUREMENT,
                           source="landing/src/data/track_snapshot.json → paper_tracks"),
        "nav": figure(b.get("nav_usd"), unit="USD", kind=MEASUREMENT,
                      source="landing/src/data/track_snapshot.json → paper_tracks"),
    }


def build(*, published_at: "str | None" = None) -> dict:
    snap = _load(SNAPSHOT)
    const = _load(CONSTITUTION)

    missing = [k for k in REQUIRED_SNAPSHOT if snap.get(k) in (None, "")]
    if missing:
        raise NotMeasured(f"в снимке нет обязательных полей: {missing} — "
                          f"витрина не собирается частично")

    ks = const.get("kill_switch") if isinstance(const.get("kill_switch"), dict) else {}
    caps = const.get("chain_caps") if isinstance(const.get("chain_caps"), dict) else {}
    track = snap.get("paper_tracks") if isinstance(snap.get("paper_tracks"), dict) else {}

    pub = published_at or date.today().isoformat()
    return {
        "_note": ("ВИТРИНА, а не источник: собрана из двух источников правды. Править руками "
                  "запрещено — пересобирается scripts/build_site_numbers.py."),
        "_generator": "scripts/build_site_numbers.py",
        "_sources": {
            "замер": "landing/src/data/track_snapshot.json",
            "решение": "landing/src/lib/constitution.json",
        },
        # ДВЕ даты, и обе видны читателю: наблюдение ежедневное, публикация недельная.
        "measured_at": snap.get("as_of"),
        "published_at": pub,
        "cadence": "weekly",
        "next_publication": (date.fromisoformat(pub) + timedelta(days=7)).isoformat(),
        "rates_are_annualised": True,
        "annualisation": ANNUALISATION,

        "headline": {
            "apy": figure(snap.get("paper_apy_pct"), unit="%", kind=MEASUREMENT,
                          annualised=True, evidence="paper",
                          source="landing/src/data/track_snapshot.json → paper_apy_pct"),
            "drawdown": figure(snap.get("max_drawdown_pct"), unit="%", kind=MEASUREMENT,
                               source="landing/src/data/track_snapshot.json"),
            "nav": figure(snap.get("nav_usd"), unit="USD", kind=MEASUREMENT,
                          source="landing/src/data/track_snapshot.json"),
            "evidenced_days": figure(snap.get("real_track_days"), unit="дней",
                                     kind=MEASUREMENT,
                                     source="landing/src/data/track_snapshot.json"),
            "evidenced_anchor": snap.get("evidenced_anchor"),
            "gates": {"passed": _num(snap.get("gates_passed")),
                      "total": _num(snap.get("gates_total")),
                      "state": snap.get("go_live_state")},
        },

        "books": {
            "conservative": _book(track, "conservative", "Conservative", snap.get("as_of")),
            "balanced": _book(track, "balanced", "Balanced", snap.get("as_of")),
            "aggressive": _book(track, "aggressive", "Aggressive", snap.get("as_of")),
        },

        "thresholds": {
            "kill_switch_soft": figure(ks.get("soft_derisk_pct"), unit="%", kind=DECISION,
                                       source="constitution.json → kill_switch (ADR-034/048)"),
            "kill_switch_hard": figure(ks.get("hard_kill_pct"), unit="%", kind=DECISION,
                                       source="constitution.json → kill_switch (ADR-034/048)"),
            "start_capital": figure(const.get("start_capital_usd"), unit="USD", kind=DECISION,
                                    source="constitution.json"),
            "min_cash_buffer": figure(const.get("min_cash_buffer_pct"), unit="%", kind=DECISION,
                                      source="constitution.json"),
            "max_per_protocol_t1": figure(const.get("max_per_protocol_t1_pct"), unit="%",
                                          kind=DECISION, source="constitution.json"),
            "max_per_protocol_t2": figure(const.get("max_per_protocol_t2_pct"), unit="%",
                                          kind=DECISION, source="constitution.json"),
            "max_t2_total": figure(const.get("max_t2_total_pct"), unit="%", kind=DECISION,
                                   source="constitution.json"),
            "tvl_floor": figure(const.get("tvl_floor_usd"), unit="USD", kind=DECISION,
                                source="constitution.json"),
            "apy_floor": figure(const.get("apy_floor_pct"), unit="%", kind=DECISION,
                                source="constitution.json"),
            "apy_ceiling": figure(const.get("apy_ceiling_pct"), unit="%", kind=DECISION,
                                  source="constitution.json"),
            "min_paper_days": figure(const.get("min_paper_days_before_live"), unit="дней",
                                     kind=DECISION, source="constitution.json"),
            "single_chain_cap": figure(caps.get("single_chain_pct"), unit="%", kind=DECISION,
                                       source="constitution.json → chain_caps (ADR-025/136)"),
            "l2_total_cap": figure(caps.get("l2_total_pct"), unit="%", kind=DECISION,
                                   source="constitution.json → chain_caps (ADR-025/136)"),
            "base_chain_cap": figure(caps.get("base_chain_pct"), unit="%", kind=DECISION,
                                     source="constitution.json → chain_caps (ADR-025/136)"),
        },
    }


def publication_due(*, today: "str | None" = None,
                    out: "Path | None" = None) -> "tuple[bool, str]":
    """Пора ли публиковать: прошла ли неделя со дня прошлой публикации.

    Такт недельный ПО РЕШЕНИЮ владельца, поэтому решение о сроке принимает файл, а
    не расписание запуска: агент может быть запущен чаще или реже, а неделя от этого
    не меняется. Витрины нет ⇒ пора (первая публикация). Дата в ней не разобрана ⇒
    тоже пора: «не смогли прочитать, когда публиковали» не имеет права означать
    «публиковали недавно» (инв. #17 — тише молчать, чем показать прошлое за
    настоящее).
    """
    path = out or OUT
    if not path.is_file():
        return True, "витрины ещё нет — первая публикация"
    try:
        prev = json.loads(path.read_text(encoding="utf-8")).get("published_at")
        last = date.fromisoformat(str(prev))
    except Exception as exc:  # noqa: BLE001
        return True, f"дата прошлой публикации не прочитана ({exc}) — публикуем"
    now = date.fromisoformat(today) if today else date.today()
    age = (now - last).days
    if age >= 7:
        return True, f"со дня публикации {last.isoformat()} прошло {age} дн"
    return False, f"со дня публикации {last.isoformat()} прошло {age} дн из 7"


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--published-at", default=None,
                    help="дата публикации (ISO); умолчание — сегодня")
    ap.add_argument("--check", action="store_true",
                    help="собрать и сравнить с файлом, не записывая (для CI)")
    ap.add_argument("--if-due", action="store_true",
                    help="пересобрать, только если со дня публикации прошла НЕДЕЛЯ")
    args = ap.parse_args(argv)

    if args.if_due:
        due, why = publication_due(today=args.published_at)
        if not due:
            print(f"публикация не назначена: {why}")
            return 0
    try:
        doc = build(published_at=args.published_at)
    except NotMeasured as exc:
        print(f"НЕ ИЗМЕРЕНО — {exc}")
        return 2
    text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        cur = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        same = cur == text
        print("витрина совпадает с источниками" if same else
              "витрина РАСХОДИТСЯ с источниками — пересобрать "
              "scripts/build_site_numbers.py")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8")
    head = doc["headline"]["apy"]
    print(f"собрано {OUT.relative_to(ROOT)}: замер {doc['measured_at']}, "
          f"публикация {doc['published_at']}, годовая ставка "
          f"{head['value'] if head['value'] is not None else '— (' + head['unavailable_reason'] + ')'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
