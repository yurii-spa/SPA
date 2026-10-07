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

Коды возврата: 0 — витрина собрана (или срок не пришёл) · 2 — НЕ ИЗМЕРЕНО · 3 — гейт последовательности · 4 — собранная витрина ждёт одобрения владельца · 5 — одобренная витрина готова к доставке (ADR-630).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # launched as a script by path (ADR-148 class) — make spa_core importable
    sys.path.insert(0, str(ROOT))
from spa_core.publication import cadence as _cadence  # noqa: E402
from spa_core.publication import metric_types as _mt  # noqa: E402
from spa_core.publication import product_map as _pmap  # noqa: E402
from spa_core.defi_engine.package_status import REPORTABLE_AFTER  # noqa: E402

#: ADR-630 (PRODUCT-TRUTH-02): the shelf carries its own provenance; bumped on every shape change.
SCHEMA_VERSION = "site_numbers/2"
SNAPSHOT = ROOT / "landing" / "src" / "data" / "track_snapshot.json"
CONSTITUTION = ROOT / "landing" / "src" / "lib" / "constitution.json"
OUT = ROOT / "landing" / "src" / "data" / "site_numbers.json"
#: ADR-630: the exact input bytes of every written shelf, content-addressed (sha256 → file). A shelf
#: approved days after its build verifies against THESE, not against today's regenerated snapshot.
INPUTS_STORE = ROOT / "data" / "publication_inputs"

#: Род числа. ADR-580 (RM-TRUTH-01, C2) РАСШИРЯЕТ, а не отменяет правило `site-numbers.md`:
#: третьего МЕСТА для чисел всё ещё нет, но честных РОДОВ теперь пять, не два. BACKTEST —
#: число из исторического/бэктест-прогона (а не из живого трека: ``tier1_packages.json``,
#: s61/s27/s62/s77 — см. `docs/rm_truth/A3_product.md` §2.1, претензия 19/claim 11
#: `REVIEW_1.md`), TARGET — объявленная цель/ладдер (не результат), MODELLED — выведено
#: моделью, а не наблюдено напрямую. BACKTEST никогда не несёт метку «замер»/«realized».
MEASUREMENT = "замер"
DECISION = "решение"
BACKTEST = "backtest"
TARGET = "target"
MODELLED = "modelled"

#: Полный словарь родов — используется там, где нужно перечислить ВСЕ допустимые значения
#: (храповик `test_site_numbers_shelf.py`), а не как магическое число "2" или "5".
KINDS = (MEASUREMENT, DECISION, BACKTEST, TARGET, MODELLED)

#: Как считается годовая ставка. Названо строкой, потому что «годовая» без метода —
#: не число, а намерение: простая экстраполяция и сложный процент дают разное.
ANNUALISATION = ("сложный процент от якоря доказанного трека: "
                 "(NAV_сегодня / NAV_якоря) ^ (365 / дней) − 1")

#: Провенанс-маркеры (подстроки в ``source``), ОБЯЗАННЫЕ сопровождаться родом
#: BACKTEST/TARGET/MODELLED — никогда MEASUREMENT/DECISION. Список называет КОНКРЕТНЫЕ
#: находки, а не угадывает по форме: единственная сегодня — `tier1_packages.json`
#: (D5/claim-11, `docs/rm_truth/A3_product.md` §5 / `REVIEW_1.md`). Расширяется по мере
#: находок, тем же порядком, что остальные списки-исключения этого дома.
_BACKTEST_SOURCE_MARKERS = ("tier1_packages",)



def _package_field(snap: dict, name: str, field: str):
    """A package aggregate, or None when the snapshot does not carry it — absence stays absence
    (inv. #17): ``figure`` then publishes «unavailable», never a number read off an empty dict."""
    from spa_core.utils.observation import observed
    packages = observed(snap, "packages", kind=dict)
    row = observed(packages, name, kind=dict) if packages is not None else None
    return observed(row, field) if row is not None else None

def validate_shelf(doc: dict) -> "list[str]":
    """Гейт последовательности публикации (C12, ADR-580). Пустой список ⇒ витрину
    МОЖНО доставлять; непустой — КАЖДАЯ строка сама по себе достаточная причина отказать.

    Два инварианта:

    1. **Бэктест не выдаёт себя за замер.** Число, чей ``source`` несёт один из
       `_BACKTEST_SOURCE_MARKERS`, не имеет права нести род MEASUREMENT/DECISION —
       ровно дефект D5/claim-11, который жил в `packages.*` до C2 («3.7, kind=замер»
       на самом деле `tier1_packages.blended_net_apy_pct`, бэктест-блендер
       s61/s27/s62/s77).
    2. **Нерепортабельная ставка — всегда ``None``.** `reportable is False` и
       одновременно ненулевое ``value`` — дефект D6 (генератор публиковал ставку с
       2 баров, страница сама гасила её до 30; прод-полка 04.10 несла «Balanced
       −11.5 %» на трёх барах ровно так). `figure()` уже гасит это сам при сборке —
       гейт здесь ВТОРОЙ рубеж (защита в глубину): ловит данные, собранные МИМО
       `figure()` (ручная правка, другой код путь), не только регресс в этом файле.

    Зовётся и тестом (регресс кода), и перед доставкой (регресс ДАННЫХ конкретного
    прогона — напр. файл подложен в обход генератора).
    """
    problems: list[str] = []

    def walk(node, path):
        if isinstance(node, dict):
            if "value" in node and "unit" in node and "kind" in node:
                kind = node.get("kind")
                source = str(node.get("source") or "")
                if kind in (MEASUREMENT, DECISION) and any(
                        m in source for m in _BACKTEST_SOURCE_MARKERS):
                    problems.append(
                        f"{path}: источник бэктеста ({source!r}) несёт род {kind!r} — "
                        f"BACKTEST не может называться «замер»/«решение» (ADR-580 C2)")
                if node.get("reportable") is False and node.get("value") is not None:
                    problems.append(
                        f"{path}: reportable=False, но value={node.get('value')!r} — "
                        f"нерепортабельная ставка обязана быть None (ADR-580 C2, инв. #17)")
                return
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(doc, "shelf")
    return problems


#: Поля снимка, без которых витрина бессмысленна. Их отсутствие — отказ, а не `None`.
REQUIRED_SNAPSHOT = ("as_of", "real_track_days", "evidenced_anchor")


class NotMeasured(RuntimeError):
    """Витрина не собрана. Причина обязана быть названа."""


class SequencingViolation(RuntimeError):
    """C12 (ADR-580): собранная витрина не проходит гейт последовательности публикации.

    Отличается от ``NotMeasured`` ПРЕДМЕТОМ: там источника нет или он не разбирается,
    здесь источник прочитан и разобран, но ВЫДАЁТ СЕБЯ не за то, что он есть (бэктест
    под меткой «замер») или несёт число, которого по правилу зрелости быть не должно.
    Публиковать ТАКОЕ опаснее, чем не публиковать вовсе.
    """


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
           unavailable_reason: "str | None" = None,
           window_days: "float | None" = None, window_days_reason: "str | None" = None,
           reportable: "bool | None" = None, reportable_after: "float | None" = None,
           basis: "str | None" = None) -> dict:
    """Одно число витрины со всем, что о нём обязан знать автор страницы.

    C2 (ADR-580) — обязательные поля для КАЖДОЙ СТАВКИ (``annualised=True``):
    ``window_days`` (окно, по которому ставка посчитана — явный ``None`` с причиной, если
    источник его не публикует, а не молчаливое отсутствие ключа), ``annualisation`` (уже
    было) и ``reportable`` (прошла ли ставка порог зрелости; ниже порога — значение
    обязано быть ``None``, инв. #17). ``reportable_after`` — сам порог, когда он назван.

    Сравнение/упорядочивание ставок разных родов или разной ``reportable`` ADR-580 C2
    запрещает — это проверяется на странице, не здесь; здесь обязанность — НЕ СКРЫТЬ
    эти два свойства у числа.
    """
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
        out["window_days"] = _num(window_days)
        if out["window_days"] is None:
            out["window_days_reason"] = (
                window_days_reason or "продолжительность окна не опубликована источником")
        # По умолчанию ставка «репортабельна», если у неё есть значение — явное
        # переопределение (напр. рукав-книга ниже порога зрелости) обязано перекрыть это.
        out["reportable"] = bool(reportable) if reportable is not None else (v is not None)
        if reportable_after is not None:
            out["reportable_after"] = _num(reportable_after)
        if not out["reportable"] and v is not None:
            # Инв. #17 / C2: нерепортабельная ставка не имеет права нести значение —
            # это ровно дефект D6 (REVIEW_1, claim про ≥2-бар-гейт против 30-дневного
            # правила страницы). Значение гасится ЗДЕСЬ, на входе в витрину, даже если
            # вызывающий код забыл погасить его сам.
            v = None
            out["value"] = None
            unavailable_reason = unavailable_reason or (
                f"ставка ниже порога зрелости"
                f"{f' ({reportable_after} дн.)' if reportable_after is not None else ''} — "
                f"печатать «идёт paper-тест», не число")
    # ADR-630: every RETURN carries its typed name; every drawdown carries its basis. Derived from the
    # kind and the maturity verdict above — never chosen by the page, never left implicit.
    if annualised:
        out["metric_type"] = _metric_type(kind, out["reportable"])
    if basis is not None:
        out["basis"] = basis
    if evidence:
        out["evidence"] = evidence
    if v is None:
        out["unavailable_reason"] = (
            unavailable_reason or "значения нет в источнике — печатать «данные недоступны»")
    return out


def _metric_type(kind: str, reportable: bool) -> str:
    """kind (+ maturity) ⇒ typed return. A measurement below maturity is an OBSERVATION, not a result."""
    if kind == BACKTEST:
        return _mt.BACKTEST_RETURN
    if kind == TARGET:
        return _mt.TARGET_RETURN
    if kind == MODELLED:
        return _mt.MODELLED_RETURN
    if kind == MEASUREMENT:
        return _mt.REALIZED_PAPER_RETURN if reportable else _mt.OBSERVED_RETURN
    raise SequencingViolation(f"род {kind!r} не может нести доходность (ADR-630): тип не определён")


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
        # Число позиций — не ставка и не порог, но страница его печатает; без него
        # витрина не покрывает показатель, и страница печатала бы `undefined`
        # (поймано дифференциалом собранного HTML, а не глазами).
        "positions": _num(b.get("positions_count")),
        # ADR-531 / вариант A владельца: прежний период искажён дефектом учёта — пометка БЕЗ числа.
        "pre_fix_period": (b.get("pre_fix_period") if isinstance(b.get("pre_fix_period"), dict) else None),
        "apy": figure(b.get("apy_pct"), unit="%", kind=MEASUREMENT, annualised=True,
                      source="landing/src/data/track_snapshot.json → paper_tracks",
                      evidence=b.get("evidence"),
                      # C2 (ADR-580): окно и зрелость идут из того же генератора, что и
                      # сама ставка (`_sleeve_paper_track`, ADR-531/548) — не пересчитываются
                      # здесь заново. Главная (conservative) книга не несёт эти поля, витрина
                      # честно выводит их как None/производное — её гейт за пределами этой
                      # задачи (см. отчёт сессии).
                      window_days=days,
                      # ADR-630: a short history is never reportable by default. The snapshot's own
                      # verdict wins when present; absent ⇒ the canonical maturity rule, not «has a value».
                      reportable=(b.get("reportable") if isinstance(b.get("reportable"), bool)
                                  else (days is not None and days >= REPORTABLE_AFTER)),
                      reportable_after=(b.get("reportable_after")
                                        if b.get("reportable_after") is not None else REPORTABLE_AFTER),
                      unavailable_reason="книга ещё не дала годовой ставки — "
                                         "печатать «идёт paper-тест», не число"),
        # Хвост публикуется РЯДОМ со ставкой намеренно: инвариант #8 и
        # `.claude/rules/site-copy.md` требуют показывать просадку вместе с доходностью.
        # Разнести их по разным местам страницы — то же, что не показать.
        "drawdown": figure(b.get("dd_pct"), unit="%", kind=MEASUREMENT, basis=_mt.PAPER,
                           source="landing/src/data/track_snapshot.json → paper_tracks"),
        "nav": figure(b.get("nav_usd"), unit="USD", kind=MEASUREMENT,
                      source="landing/src/data/track_snapshot.json → paper_tracks"),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(*, published_at: "str | None" = None, source_commit: "str | None" = None) -> dict:
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
    try:
        profiles = _pmap.checked(snap.get("package_status"), evidenced_anchor=snap.get("evidenced_anchor"))
    except _pmap.MappingConflict as exc:
        raise SequencingViolation(f"сопоставление профилей противоречиво: {exc}") from exc
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
        "cadence": _cadence.CADENCE,
        "next_publication": _cadence.next_publication(pub),
        # ADR-630: provenance of THIS artifact. Deterministic from its inputs (no wall clock): the
        # generation time is the snapshot's own; the commit is recorded only when the publisher passes it.
        "_provenance": {
            "schema_version": SCHEMA_VERSION,
            "generated_at": snap.get("generated_at"),
            "measurement_as_of": snap.get("as_of"),
            "source_commit": source_commit,
            "source_commit_reason": (None if source_commit else
                                     "not passed by the builder — bind by source_hashes"),
            "source_hashes": {
                "landing/src/data/track_snapshot.json": _sha256(SNAPSHOT),
                "landing/src/lib/constitution.json": _sha256(CONSTITUTION),
            },
            "cadence_rule": "spa_core/publication/cadence.py (weekly from the PUBLISHED shelf)",
            "product_map_rule": "spa_core/publication/product_map.py (ADR-OWN-2026-07, ADR-593, ADR-533)",
        },
        "profiles": profiles,
        "rates_are_annualised": True,
        "annualisation": ANNUALISATION,

        "headline": {
            "apy": figure(snap.get("paper_apy_pct"), unit="%", kind=MEASUREMENT,
                          annualised=True, evidence="paper",
                          window_days=snap.get("real_track_days"),
                          reportable=(_num(snap.get("real_track_days")) or 0) >= REPORTABLE_AFTER,
                          reportable_after=REPORTABLE_AFTER,
                          source="landing/src/data/track_snapshot.json → paper_apy_pct"),
            "drawdown": figure(snap.get("max_drawdown_pct"), unit="%", kind=MEASUREMENT, basis=_mt.PAPER,
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

        # Остальное, что страницы показывают читателю. Без этих полей витрина
        # покрывала семь показателей из пятнадцати, и страница выходила бы
        # ПОЛОСАТОЙ — половина чисел недельные, половина дневные, и по виду не
        # отличить. Такая страница хуже обоих чистых вариантов.
        "track": {
            "days_needed": figure(snap.get("days_needed"), unit="дней", kind=DECISION,
                                  source="track_snapshot.json → days_needed (порог 30 дней, "
                                         "ADR-002; в снимок приходит из гейта)"),
            "end_equity": figure(snap.get("end_equity"), unit="USD", kind=MEASUREMENT,
                                 source="track_snapshot.json → end_equity"),
            "go_live_target": snap.get("go_live_target"),
            "degraded": bool(snap.get("degraded")),
            # Отметка генератора снимка — НЕ число и не показатель: она говорит,
            # когда снят замер, и живёт рядом с `measured_at` как его источник.
            "snapshot_generated_at": snap.get("generated_at"),
        },

        # Публикуемые ставки пакетов. Идут ВМЕСТЕ с просадкой по той же причине,
        # что и у книг (инв. #8): доходность без хвоста читается как обещание.
        #
        # C2 (ADR-580): это БЭКТЕСТ, не замер. `track_snapshot.json → packages` сам пришёл
        # из `data/tier1_packages.json` (`blended_net_apy_pct`/`worst_dd_pct`, смесь
        # s61/s27/s62/s77 — `spa_core/backtesting/tier1/packages.py`), а НЕ из живого
        # paper-трека. Раньше это несло `kind="замер"`: ровно дефект D5/claim-11
        # (`docs/rm_truth/A3_product.md` §5, `REVIEW_1.md` claim 11) — число реальный
        # paper-трек обойти не может, а ярлык говорил, что это он. ``window_days`` явный
        # ``None``: длина бэктест-окна не публикуется источником (`tier1_packages.json`
        # несёт только итоговые агрегаты, не границы периода) — третий исход (инв. #17),
        # не выдуманное число.
        "packages": {
            name: {
                "apy": figure(_package_field(snap, name, "apy_pct"),
                              unit="%", kind=BACKTEST, annualised=True,
                              source="track_snapshot.json → packages (← data/tier1_packages.json, "
                                     "blended_net_apy_pct — s61/s27/s62/s77, "
                                     "spa_core/backtesting/tier1/packages.py)",
                              window_days_reason="окно бэктеста не публикуется "
                                                "tier1_packages.json (только итоговые агрегаты)",
                              unavailable_reason="ставка пакета не измерена — печатать "
                                                 "«идёт paper-тест», не число"),
                "drawdown": figure(_package_field(snap, name, "dd_pct"),
                                   unit="%", kind=BACKTEST, basis=_mt.BACKTEST,
                                   source="track_snapshot.json → packages (← data/tier1_packages.json, "
                                          "worst_dd_pct)"),
            }
            for name in ("conservative", "balanced", "aggressive")
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


def _verifier():
    import importlib.util as _u
    spec = _u.spec_from_file_location("_verify_publication_from_bsn", ROOT / "scripts" / "verify_publication.py")
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _ThisModule:
    """This module as an object, whatever name it was loaded under (scripts are loaded by path, not
    registered in ``sys.modules``): the verifier reads and temporarily swaps its globals."""

    def __getattr__(self, k):
        try:
            return globals()[k]
        except KeyError as exc:
            raise AttributeError(k) from exc

    def __setattr__(self, k, v):
        globals()[k] = v


def _judge_candidate(target: Path, published: Path, today: "str | None") -> dict:
    """READY (passes the gate with an owner approval) · WAITING (only the approval is missing) ·
    SUPERSEDE (fails for a reason no approval can clear, or cannot be verified at all)."""
    vp = _verifier()
    me = _ThisModule()
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"state": "SUPERSEDE", "reason": "candidate unreadable"}
    approval = vp.find_approval(doc, _sha256(target))
    res = vp.verify(shelf=target, published=published, today=today or date.today().isoformat(),
                    approval=approval, bsn=me)
    if res["outcome"] == vp.PASS:
        return {"state": "READY", "approval": approval}
    if vp.approval_only(res):
        return {"state": "WAITING", "findings": res["findings"]}
    return {"state": "SUPERSEDE", "reason": res.get("reason"), "findings": res.get("findings")}


def inputs_store_for(target: Path) -> Path:
    """The canonical shelf keeps its inputs in ``data/publication_inputs``; a shelf elsewhere (scenes,
    sandboxes) keeps them beside itself — tests never write into the repository's data/."""
    try:
        canonical = Path(target).resolve() == OUT.resolve()
    except OSError:
        canonical = False
    return INPUTS_STORE if canonical else Path(target).parent / ".publication_inputs"


#: superseded candidates (and the inputs they reference) kept for forensics; older ones are pruned
KEEP_SUPERSEDED = 8


def _atomic_text(path: Path, text: str) -> None:
    from spa_core.utils.atomic import atomic_save_text
    atomic_save_text(text, str(path))


def _supersede(target: Path, verdict: dict, published: "Path | None" = None) -> None:
    """Keep the old candidate as a named superseded record (never silently overwritten). Atomic writes;
    the log is rewritten whole (atomic), one line per superseded sha — a re-run adds no duplicate."""
    store = inputs_store_for(target)
    store.mkdir(parents=True, exist_ok=True)
    text = target.read_text(encoding="utf-8")
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    rec = store / f"superseded-shelf-{sha}.json"
    if not rec.is_file():
        _atomic_text(rec, text)
    log = store / "superseded.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines() if log.is_file() else []
    if not any(f'"sha256": "{sha}"' in ln for ln in lines):
        lines.append(json.dumps({"sha256": sha, "reason": verdict.get("reason"),
                                 "findings": (verdict.get("findings") or [])[:10]}, ensure_ascii=False))
        _atomic_text(log, "\n".join(lines) + "\n")
    _prune_store(store, target, published)


def _preserve_inputs(target: Path) -> None:
    """Content-addressed copy of the inputs of a shelf being written (ADR-630), atomically."""
    store = inputs_store_for(target)
    store.mkdir(parents=True, exist_ok=True)
    for src in (SNAPSHOT, CONSTITUTION):
        dst = store / f"{_sha256(src)}.json"
        if not dst.is_file():
            _atomic_text(dst, src.read_text(encoding="utf-8"))


def _hashes_of(doc) -> set:
    prov = doc.get("_provenance") if isinstance(doc, dict) else None
    return set(((prov or {}).get("source_hashes") or {}).values()) if isinstance(prov, dict) else set()


def _prune_store(store: Path, target: Path, published: "Path | None" = None) -> None:
    """Bound the store: keep the inputs referenced by the PUBLISHED shelf, the current candidate and the
    last ``KEEP_SUPERSEDED`` superseded candidates; drop the rest. The published shelf must be NAMED by the
    caller; unknown ⇒ keep every input (never delete what might still verify the public copy)."""
    def _doc(p: Path):
        try:
            return json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
    log = store / "superseded.jsonl"
    shas = []
    if log.is_file():
        for ln in log.read_text(encoding="utf-8").splitlines():
            try:
                shas.append(json.loads(ln)["sha256"])
            except Exception:  # noqa: BLE001
                continue
    keep_sup = set(shas[-KEEP_SUPERSEDED:])
    for p in store.glob("superseded-shelf-*.json"):
        if p.stem.replace("superseded-shelf-", "") not in keep_sup:
            p.unlink(missing_ok=True)
    if len(shas) > KEEP_SUPERSEDED:
        kept = [ln for ln in log.read_text(encoding="utf-8").splitlines()
                if any(f'"sha256": "{h}"' in ln for h in keep_sup)]
        _atomic_text(log, "\n".join(kept) + "\n")
    pub_doc = _doc(published) if published else None
    if pub_doc is None:
        return
    keep = _hashes_of(pub_doc) | _hashes_of(_doc(target))
    for h in keep_sup:
        keep |= _hashes_of(_doc(store / f"superseded-shelf-{h}.json"))
    for p in store.glob("*.json"):
        if p.name.startswith("superseded-shelf-"):
            continue
        if len(p.stem) == 64 and p.stem not in keep:
            p.unlink(missing_ok=True)


def publication_due(*, today: "str | None" = None,
                    out: "Path | None" = None, published: "Path | None" = None) -> "tuple[bool, str]":
    """Пора ли публиковать — по ЕДИНОМУ правилу `spa_core/publication/cadence.py` (ADR-630).

    Срок считается от ОПУБЛИКОВАННОЙ витрины (``published`` — копия на origin/зеркале), а не от
    локально собранной: витрина, собранная на Маке и не доехавшая до origin, не публикация
    (аудит 07.10: локальная 10-05 давала «следующая 10-12», сайт и Director — «10-08»).
    ``published`` не передан ⇒ читается ``out``/``OUT`` (сцены тестов и CLI без зеркала).
    Витрины нет ⇒ пора. Дата не разобрана ⇒ тоже пора (инв. #17).
    """
    path = published or out or OUT
    if not path.is_file():
        return True, "витрины ещё нет — первая публикация"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return True, f"дата прошлой публикации не прочитана ({exc}) — публикуем"
    st = _cadence.status(doc if isinstance(doc, dict) else None, today=today)
    if not st["measured"]:
        return True, "дата прошлой публикации не прочитана — публикуем"
    last, age = st["published_at"], st["age_days"]
    if st["due"]:
        return True, f"со дня публикации {last} прошло {age} дн"
    return False, f"со дня публикации {last} прошло {age} дн из 7"


def run(*, published_at: "str | None" = None, if_due: bool = False,
        write: bool = True, out: "Path | None" = None, published: "Path | None" = None,
        source_commit: "str | None" = None) -> dict:
    """Один ТАКТ публикации витрины: собрать и записать, если срок пришёл.

    Гейт такта живёт ЗДЕСЬ, а не в ``main`` (заказ **G40 п. 1** приказа
    «Portfolio CIO» — единственная находка переписи гейтов такта, ADR-415).
    Разница не косметическая: пока звавший один — рука цикла на шаге (1е), —
    открытый производитель вреда не несёт, но ВТОРОЙ звавший (ступень моста,
    будущий агент) обязан был бы завести свою копию правила недели, и
    разошлись бы копии молча — класс ADR-220.

    «Не публиковали» и «опубликовано» — РАЗНЫЕ исходы (инв. #17): внутри такта
    возвращается ``{"published": False, "reason": …}``, а файл не трогается
    вовсе. Срок решает ФАЙЛ (``publication_due``), а не расписание запуска.

    ``published`` отвечает на вопрос «прошёл ли такт и собрана ли витрина», а
    НЕ «записаны ли байты»: запись — отдельный вход ``write`` (сцена ``--check``
    сравнивает, не публикуя). Слить их значило бы дать сравнению в CI право
    двигать числа витрины — предмет №2 границы ADR-285.

    ``build`` остаётся негейтированной НАМЕРЕННО, и это не недосмотр: она
    ничего не пишет, это чистая проекция двух источников. Производитель здесь
    — тот, кто кладёт байты в ``site_numbers.json``, и он ровно один.
    """
    target = Path(out) if out is not None else OUT
    if if_due:
        # ADR-630: the operand is the PUBLISHED shelf. An explicit ``out`` names its own operand (scenes);
        # otherwise the one shared resolver — and no location ⇒ NOT MEASURED, never the local copy.
        if published is None and out is None:
            published = _cadence.published_shelf_path()
            if published is None:
                raise NotMeasured("опубликованная витрина не найдена (нет зеркала origin и "
                                  "$SPA_PUBLISHED_SHELF) — срок публикации НЕ ИЗМЕРЕН, локальная "
                                  "копия операндом не служит (ADR-630)")
        if published is not None and Path(published).resolve() != target.resolve() and target.is_file():
            try:
                local_doc = json.loads(target.read_text(encoding="utf-8"))
                pub_doc = json.loads(Path(published).read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — unreadable ⇒ the due-check below decides
                local_doc = pub_doc = None
            if _cadence.built_not_delivered(local_doc, pub_doc):
                # Built, not delivered. Judge the candidate by the gate itself: approved ⇒ ready to ship;
                # only the approval missing ⇒ wait (no daily rebuild loop); anything approval cannot
                # clear (stale, inputs lost, rebuild differs) ⇒ supersede it ONCE and build anew.
                verdict = _judge_candidate(target, Path(published), published_at)
                if verdict["state"] == "READY":
                    return {"published": False, "ready": True, "artifact": str(target),
                            "approval": verdict.get("approval"),
                            "reason": f"витрина от {local_doc.get('published_at')} одобрена владельцем — к доставке"}
                if verdict["state"] == "WAITING":
                    return {"published": False, "not_delivered": True, "artifact": str(target),
                            "reason": (f"SHELF_NOT_DELIVERED: собрана витрина от {local_doc.get('published_at')}, "
                                       f"на публике {pub_doc.get('published_at')} — ждёт ворот владельца, "
                                       f"не пересобираем")}
                _supersede(target, verdict, Path(published))
        due, why = publication_due(today=published_at, out=target, published=published)
        if not due:
            return {"published": False, "reason": why, "artifact": str(target)}
    doc = build(published_at=published_at, source_commit=source_commit)
    # C12 (ADR-580): гейт последовательности публикации — ПЕРЕД записью байт, не после.
    # «Собрали» и «можно показывать посетителю» — разные вопросы; если второй отвечен
    # «нет», файл не трогаем вовсе (то же disciplина, что у `if_due` выше).
    problems = validate_shelf(doc)
    if problems:
        raise SequencingViolation(
            "витрина не прошла гейт последовательности (" + str(len(problems)) +
            " наруш.): " + "; ".join(problems))
    text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    if write:
        _preserve_inputs(target)
        _atomic_text(target, text)
        _prune_store(inputs_store_for(target), target, published)
    return {"published": True, "doc": doc, "text": text, "artifact": str(target)}


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--published-at", default=None,
                    help="дата публикации (ISO); умолчание — сегодня")
    ap.add_argument("--check", action="store_true",
                    help="собрать и сравнить с файлом, не записывая (для CI)")
    ap.add_argument("--if-due", action="store_true",
                    help="пересобрать, только если со дня публикации прошла НЕДЕЛЯ")
    ap.add_argument("--published", default=None,
                    help="путь к ОПУБЛИКОВАННОЙ витрине (умолчание: $SPA_PUBLISHED_SHELF или зеркало origin)")
    ap.add_argument("--source-commit", default=None,
                    help="коммит origin, из которого взяты входы (записывается в _provenance)")
    args = ap.parse_args(argv)
    published = _cadence.published_shelf_path(args.published) if args.published else None

    # Гейт такта живёт в ОДНОМ месте (`run`) — вторая его копия здесь означала
    # бы, что рука цикла и любой будущий звавший судят о неделе по разным
    # правилам, а расходились бы они молча.
    try:
        outcome = run(published_at=args.published_at, if_due=args.if_due,
                      write=not args.check, published=published, source_commit=args.source_commit)
    except NotMeasured as exc:
        print(f"НЕ ИЗМЕРЕНО — {exc}")
        return 2
    except SequencingViolation as exc:
        # C12: отдельный код от «НЕ ИЗМЕРЕНО» (2) — источник прочитан и разобран, но
        # то, что он выдаёт, нарушает гейт последовательности, а не отсутствует.
        print(f"ГЕЙТ ПОСЛЕДОВАТЕЛЬНОСТИ ОТКАЗАЛ (C12, ADR-580) — {exc}")
        return 3
    if not outcome["published"]:
        print(f"публикация не назначена: {outcome['reason']}")
        if outcome.get("ready"):
            return 5
        return 4 if outcome.get("not_delivered") else 0
    doc, text = outcome["doc"], outcome["text"]
    if args.check:
        cur = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        same = cur == text
        print("витрина совпадает с источниками" if same else
              "витрина РАСХОДИТСЯ с источниками — пересобрать "
              "scripts/build_site_numbers.py")
        return 0 if same else 1
    head = doc["headline"]["apy"]
    print(f"собрано {OUT.relative_to(ROOT)}: замер {doc['measured_at']}, "
          f"публикация {doc['published_at']}, годовая ставка "
          f"{head['value'] if head['value'] is not None else '— (' + head['unavailable_reason'] + ')'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
