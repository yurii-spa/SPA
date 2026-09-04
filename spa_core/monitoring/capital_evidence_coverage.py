"""capital_evidence_coverage.py — какая доля НАШИХ ДЕНЕГ стои́т на наблюдении, а не на литерале.

Приёмка, у которой не было производителя
========================================
ТЗ владельца «Portfolio CIO» (`nimbalyst-local/tracker/inbox-task-portfolio-cio-dynamic-capital-alloc`,
13.08) требует мерить, «стало ли лучше», четырьмя числами. Диагностика §5
(`docs/research/RS-portfolio-cio-diagnosis.md`) записала одно из них так:

    Доля капитала, ранжированного по наблюдённым числам: было $20k из $80k (25 %) —
    цель 100 % (или явный fail-closed отказ).

Замер 04.09 (цикл #485): **это число не производит НИЧТО.** Оно было посчитано руками
02.08, руками же повторено диагностикой 19.08 — и с тех пор отвечать на вопрос
приёмки можно только новым разбором вручную. Метрика, которую надо каждый раз
выводить заново, приёмкой не является: она не краснеет, не растёт и не показывает,
что гэп G1 закрыт.

Почему `feed_coverage.live_pct` НЕ является этим числом
======================================================
Рядом лежит поле, которое читается как ответ и им не является. Это два разных
вопроса, и совпадение их значений — не тождество, а совпадение:

| поле | вопрос | единица | множество |
|---|---|---|---|
| `feed_coverage.live_pct` | сколько ФИДОВ живо | адаптер | вся вселенная кандидатов |
| это число | сколько НАШИХ ДЕНЕГ ранжировано наблюдением | доллар | развёрнутая книга |

Разойтись они могут произвольно далеко в ОБЕ стороны, и оба направления —
настоящие аварии, а не арифметика:

* книга держит все деньги в одном протоколе без провенанса, а 19 из 20 адаптеров
  живы ⇒ `live_pct` 95 %, покрытие капитала 0 %;
* и наоборот — половина фидов молчит, но вся книга стои́т в наблюдаемых ⇒
  `live_pct` 50 % при покрытии 100 %, и красный `live_pct` зовёт чинить то, что
  деньгам сейчас не мешает.

ЧЕГО ЭТОТ МОДУЛЬ НЕ ПРОВЕРЯЕТ, и это надо сказать первым
========================================================
Провенанс он не добывает, а ЧИТАЕТ — `feed_coverage.apy_sources`, который
аллокатор ставит сам себе. Значит, правдивость ответа целиком заимствована у
правдивости штампа, и **своей цены ошибки у этого измерителя нет**.

Проверьте это на самом дорогом дне: 02.08 верное покрытие равнялось 25 %
($20k из $80k), а `apy_source` докладывал `live` почти обо всём — двенадцать
адаптеров читали `data/adapter_status.json` по устаревшей схеме, получали `None`
и подставляли зашитый `DEFAULT_APY_PCT`, который WS1.1 штамповал как живой
(дефект D1, карточка `agent-apy-evidence-provenance`). **Существуй этот модуль
тогда, он ответил бы «100 %» вместе со всеми** — и 25 % посчитал бы не он, а
человек, который ЗНАЛ, что штамп врёт.

Поэтому здесь названы обе опоры, на которых стои́т сегодняшний ответ, и обе
проверены замером 04.09, а не приняты на веру:

* **штамп сделан правдивым** — ADR-063 снял подстановку `DEFAULT_APY_PCT`.
  Замер 04.09 ПОВЕДЕНЧЕСКИЙ, а не по тексту: каждому из 12 названных D1
  адаптеров подсунут `adapter_status.json` современной схемы, и спрошен
  `get_apy()`. С наблюдением все 12 вернули ИМЕННО наблюдённое число; без
  наблюдения все 12 вернули `None`, а не свою константу. (Грепом это мерить
  нельзя: `morpho_steakhouse` читает файл своим кодом, а `fluid_fusdc` метода
  `_read_apy_from_status` не имеет вовсе — по тексту оба выглядели бы
  исключениями, которыми не являются.) D2 — `morpho_steakhouse` в
  `ADAPTER_REGISTRY` (36) и в `POLLED_ADAPTERS`;
* **штамп сверяется извне** — `adapter_feed_divergence` спрашивает у ВТОРОГО
  артефакта, литерал там или наблюдение (род `literal_vs_live`).

Сломается любая из двух — это число замолчит вместе с ними, и звать его
независимой проверкой провенанса НЕЛЬЗЯ. Оно отвечает на свой вопрос: сколько
долларов книги стои́т на том, что система САМА называет наблюдением.

Что этот модуль НЕ делает
=========================
Не выбирает APY, не ранжирует, не двигает капитал, не гейтит исполнение, не
трогает RiskPolicy и не пишет ни в один чужой артефакт. **Только меряет и
называет.** Read-only: единственный вход — `data/current_positions.json`
(его пишет дневной цикл), единственный выход — собственный отчёт и собственный
журнал.

Три исхода на доллар, а не два
==============================
Провенанс держит `feed_coverage.apy_sources` — тот самый, что аллокатор ставит
сам себе (ADR-061/063 сделали его правдивым). Доллар попадает ровно в одну
корзину:

* **`evidenced`** — `apy_source == "live"`: протокол ранжирован наблюдением;
* **`literal`** — `apy_source == "fallback_stale"`: литерал, но ЧЕСТНО помеченный;
  деньги на нём стоят, и это обязано звучать (WARN), а не растворяться в «не 100 %»;
* **`unmeasured`** — позиция в книге ЕСТЬ, а записи о провенансе нет вовсе.

Третья корзина существует отдельно намеренно. Свалить её к `literal` значило бы
утверждать про доллар то, чего мы не мерили, а к `evidenced` — ровно тот fail-OPEN,
против которого написан весь контур. «Не измерено» имеет своё значение
(инвариант #17): любой такой доллар поднимает вердикт до `UNCHECKED` и код 2, и
про него печатается ПРИЧИНА, а не число.

Пустая книга — тоже НЕ 100 %
============================
0 наблюдаемых долларов из 0 развёрнутых арифметически даёт что угодно, и заманчиво
округлить это до «полное покрытие». Тогда книга-всё-в-кэше (например, после
HARD_KILL) выдавала бы самый зелёный отчёт за всю историю. Пустой знаменатель ⇒
`coverage_pct: None` и `UNCHECKED` с названной причиной.

Единица памяти — СНИМОК КНИГИ, а не прогон
==========================================
Книгу пишет дневной цикл (раз в сутки), а сторожа зовёт `com.spa.decision_loop`
(часто). Ключ журнала — `generated_at` самой книги, поэтому «покрытие держится N
суток» отвечает на вопрос о книге, а не о том, сколько раз мы на неё посмотрели.
Окно `history()` обрезается возрастом журнала и говорит об этом вслух: «100 % за
30 суток» по двухдневному журналу — не хорошая новость, а ненаблюдение.

Свежесть входа — вход, а не окружение
=====================================
Время передаётся параметром `now` (`.claude/rules/deployment.md`). Книга старше
`MAX_AGE_S` ⇒ `UNCHECKED`: сторож не имеет права говорить в настоящем времени о
вчерашней книге.

Коды возврата: 0 — покрытие полное · 1 — есть капитал на помеченных литералах ·
2 — есть неизмеренный капитал, вход не прочитан или книга пуста (fail-CLOSED).
LLM_FORBIDDEN. Только stdlib.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from spa_core.monitoring.architecture_conformance import REPO_ROOT, _parse_iso
from spa_core.utils.atomic import atomic_save

REPORT_REL = os.path.join("data", "capital_evidence_coverage.json")
LOG_REL = os.path.join("data", "capital_evidence_coverage_log.jsonl")
POSITIONS_REL = os.path.join("data", "current_positions.json")

# 26 ч: книгу пишет дневной цикл раз в сутки, поэтому сутки + запас на сдвиг запуска.
MAX_AGE_S = 93600.0
HISTORY_WINDOW_DAYS = 30.0
LOG_MAX_LINES = 5000

OK = "OK"
WARN = "WARN"
UNCHECKED = "UNCHECKED"

# Метки провенанса, которые аллокатор ставит сам себе (ADR-061/063).
SRC_LIVE = "live"
SRC_STALE = "fallback_stale"


def _num(value):
    """Число или ``None``. ``bool`` — НЕ число: ``True`` не является одним долларом."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f == f and f not in (float("inf"), float("-inf")):
        return f
    return None


def _pct(part: float, whole: float):
    if whole:
        return round(100.0 * part / whole, 2)
    return None


def measure(doc, *, now):
    """Разобрать книгу в отчёт. Чистая функция: ни файлов, ни часов внутри.

    Отделена от :func:`run` намеренно — так тест кормит книгу словарём и не
    зависит ни от живого ``data/`` хоста, ни от календаря.
    """
    unchecked = []
    if not isinstance(doc, dict):
        return _report(now, unchecked=["книга не является объектом JSON"])

    stamp = _parse_iso(doc.get("generated_at"))
    age_s = round((now - stamp).total_seconds(), 1) if stamp else None
    if stamp is None:
        unchecked.append(
            "у книги не прочитана отметка `generated_at` — сказать, о СЕГОДНЯШНЕЙ ли книге идёт речь, нечем"
        )
    elif age_s > MAX_AGE_S:
        unchecked.append(
            f"книге {round(age_s / 3600, 1)} ч при потолке {round(MAX_AGE_S / 3600, 1)}"
            " ч — сторож не говорит в настоящем времени о вчерашней книге (stale_input)"
        )

    positions = doc.get("positions")
    coverage = doc.get("feed_coverage")
    if not isinstance(positions, dict):
        unchecked.append(
            "в книге нет раздела `positions` — из чего состоит капитал, не сказано"
        )
    if not isinstance(coverage, dict):
        unchecked.append(
            "в книге нет раздела `feed_coverage` — провенанс ранжирования не сказан"
        )
    if unchecked:
        return _report(now, unchecked=unchecked, stamp=stamp, age_s=age_s)

    sources = coverage.get("apy_sources")
    if not isinstance(sources, dict):
        return _report(
            now,
            stamp=stamp,
            age_s=age_s,
            unchecked=[
                "`feed_coverage.apy_sources` отсутствует или не объект — провенанс КАЖДОГО"
                " доллара неизвестен; это не «нет живых», а «не измерено»"
            ],
        )

    buckets = {"evidenced": 0.0, "literal": 0.0, "unmeasured": 0.0}
    by_protocol = []
    bad_amounts = []
    deployed = 0.0
    for protocol in sorted(positions):
        usd = _num(positions[protocol])
        if usd is None:
            bad_amounts.append(str(protocol))
            continue
        if usd <= 0:
            continue
        deployed += usd
        src = sources.get(protocol)
        if src == SRC_LIVE:
            bucket, why = "evidenced", None
        elif src == SRC_STALE:
            bucket, why = "literal", (
                f"{protocol}: ${usd:,.0f} ранжированы ПОМЕЧЕННЫМ литералом"
                f" (`{SRC_STALE}`) — число честно названо старым, но деньги на нём стоят"
            )
        elif src is None:
            bucket, why = "unmeasured", (
                f"{protocol}: ${usd:,.0f} в книге, а записи о провенансе нет вовсе —"
                " чем ранжирован этот доллар, НЕ ИЗМЕРЕНО (в `apy_sources` протокола нет)"
            )
        else:
            bucket, why = "unmeasured", (
                f"{protocol}: ${usd:,.0f} — провенанс `{src}` сторожу неизвестен;"
                " назвать доллар наблюдённым по незнакомой метке значило бы угадать"
            )
        buckets[bucket] += usd
        row = {
            "protocol": protocol,
            "usd": round(usd, 2),
            "bucket": bucket,
            "apy_source": src,
        }
        apy = _num((coverage.get("apy_used_pct") or {}).get(protocol))
        if apy is not None:
            row["apy_used_pct"] = apy
        if why:
            row["message"] = why
        by_protocol.append(row)

    if bad_amounts:
        unchecked.append(
            "размер позиции не является числом у: "
            + ", ".join(sorted(bad_amounts))
            + " — доля капитала не считается по нечисловому знаменателю"
        )
        return _report(now, unchecked=unchecked, stamp=stamp, age_s=age_s)

    if deployed <= 0:
        return _report(
            now,
            stamp=stamp,
            age_s=age_s,
            unchecked=[
                "книга пуста: развёрнуто $0, и доля наблюдённого капитала НЕ ОПРЕДЕЛЕНА"
                " (0 из 0). Это не 100 % — округлив пустой знаменатель вверх, отчёт"
                " объявил бы книгу-всё-в-кэше самой здоровой за всю историю"
            ],
        )

    adapters_live_pct = _num(coverage.get("live_pct"))
    capital_pct = _pct(buckets["evidenced"], deployed)
    verdict = OK
    if buckets["unmeasured"] > 0:
        verdict = UNCHECKED
    elif buckets["literal"] > 0:
        verdict = WARN

    return _report(
        now,
        stamp=stamp,
        age_s=age_s,
        verdict=verdict,
        deployed_usd=round(deployed, 2),
        cash_usd=_num(doc.get("cash_usd")),
        capital_coverage_pct=capital_pct,
        usd={k: round(v, 2) for k, v in buckets.items()},
        by_protocol=by_protocol,
        adapters_live_pct=adapters_live_pct,
        divergence_pp=(
            round(adapters_live_pct - capital_pct, 2)
            if adapters_live_pct is not None and capital_pct is not None
            else None
        ),
        blocked=dict(coverage.get("blocked") or {}),
    )


def _report(now: dt.datetime, *, unchecked=None, verdict=None, stamp=None, age_s=None, **fields) -> dict:
    rep = {
        "generated_at": now.isoformat(),
        "generated_by": "spa_core/monitoring/capital_evidence_coverage.py",
        "schema_version": 1,
        "verdict": verdict or (UNCHECKED if unchecked else OK),
        "book_generated_at": stamp.isoformat() if stamp else None,
        "book_age_s": age_s,
        "capital_coverage_pct": None,
        "deployed_usd": None,
        "cash_usd": None,
        "usd": {"evidenced": None, "literal": None, "unmeasured": None},
        "by_protocol": [],
        "adapters_live_pct": None,
        "divergence_pp": None,
        "blocked": {},
        "unchecked": list(unchecked or []),
        # Цель приёмки едет В отчёте: читатель не ходит за ней в документ.
        "target_pct": 100.0,
        "baseline_pct": 25.0,
        "baseline_note": "02.08: $20k из $80k ранжированы наблюдением (docs/research/RS-portfolio-cio-diagnosis.md §5)",
    }
    rep.update(fields)
    return rep


def log_path(base: str) -> str:
    return os.path.join(base, os.path.basename(LOG_REL))


def _snapshot_key(report: dict, now: dt.datetime) -> str:
    """Отпечаток КНИГИ, а не прогона.

    Книгу пишет дневной цикл, сторожа зовёт часовой агент. Ключ по
    ``book_generated_at`` делает единицей счёта книгу: двадцать взглядов на одну
    книгу — одна запись. Отметку, которую прочитать не удалось, подменяют сутки
    ``now`` — тогда слепота не размножается построчно, но и не исчезает.
    """
    stamp = report.get("book_generated_at")
    if stamp:
        return str(stamp)
    return f"?{now.date().isoformat()}"


def read_journal(base: str) -> tuple[list[dict], str]:
    """``(записи, причина_нечитаемости)``. Битые строки считаются, а не проглатываются."""
    path = log_path(base)
    records: list[dict] = []
    bad = 0
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if isinstance(rec, dict):
                    records.append(rec)
                else:
                    bad += 1
    except FileNotFoundError:
        return [], f"журнала нет на диске: {path}"
    except OSError as e:
        return [], f"журнал не прочитан: {e}"
    return records, (f"пропущено нечитаемых строк: {bad}" if bad else "")


def append_history(report: dict, base: str, now: dt.datetime) -> list[dict]:
    """Дописать замер ЭТОЙ книги. Возвращает реально записанные строки.

    Здесь пишется КАЖДЫЙ снимок, включая полное покрытие, — в отличие от журнала
    расхождений, где согласие строки не оставляет. Причина: там предмет — редкое
    событие, здесь — ТРЕНД, и ряд без зелёных точек не отвечает на вопрос ТЗ
    «стало ли лучше и держится ли».
    """
    key = _snapshot_key(report, now)
    known, _ = read_journal(base)
    path = log_path(base)
    if not os.path.exists(path):
        # Открывающая строка отделяет «журнал пуст» от «журнала нет»: без неё
        # окно истории считалось бы от первого замера, а не от начала наблюдения.
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "observed_at": now.isoformat(),
                        "snapshot_key": "-",
                        "kind": "journal_opened",
                        "message": "журнал покрытия капитала открыт — с этой отметки считается покрытие окна",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        known, _ = read_journal(base)
    if any(r.get("snapshot_key") == key and r.get("kind") == "measurement" for r in known):
        return []
    rec = {
        "observed_at": now.isoformat(),
        "snapshot_key": key,
        "kind": "measurement",
        "verdict": report.get("verdict"),
        "capital_coverage_pct": report.get("capital_coverage_pct"),
        "adapters_live_pct": report.get("adapters_live_pct"),
        "deployed_usd": report.get("deployed_usd"),
        "usd": report.get("usd"),
        "unchecked": list(report.get("unchecked") or []),
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    total = len(known) + 1
    if total > LOG_MAX_LINES:
        kept = (known + [rec])[-LOG_MAX_LINES:]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for r in kept:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    return [rec]


def history(base: str, *, days: float = HISTORY_WINDOW_DAYS, now: dt.datetime | None = None) -> dict:
    """Ряд покрытия за окно. Считаются РАЗНЫЕ книги, а не строки журнала."""
    now = now or dt.datetime.now(dt.timezone.utc)
    records, bad = read_journal(base)
    if not records:
        return {
            "status": UNCHECKED,
            "reason": bad or "журнал пуст — это НЕ «покрытие держалось»",
            "window_days": days,
        }
    cutoff = now - dt.timedelta(days=days)
    opened = None
    seen: dict = {}
    for rec in records:
        ts = _parse_iso(rec.get("observed_at"))
        if ts is None:
            continue
        if opened is None or ts < opened:
            opened = ts
        if rec.get("kind") != "measurement" or ts < cutoff:
            continue
        seen.setdefault(str(rec.get("snapshot_key")), rec)
    if opened is None:
        return {
            "status": UNCHECKED,
            "reason": "ни одной читаемой отметки времени в журнале",
            "window_days": days,
        }
    covered = round(min((now - opened).total_seconds() / 86400.0, days), 2)
    pcts = [
        r["capital_coverage_pct"]
        for r in seen.values()
        if _num(r.get("capital_coverage_pct")) is not None
    ]
    return {
        "status": OK,
        "window_days": days,
        "covered_days": covered,
        "window_truncated": covered < days,
        "books_measured": len(seen),
        "books_unmeasured": sum(
            1 for r in seen.values() if _num(r.get("capital_coverage_pct")) is None
        ),
        "coverage_pct_min": min(pcts) if pcts else None,
        "coverage_pct_max": max(pcts) if pcts else None,
        "coverage_pct_last": (
            max(seen.values(), key=lambda r: str(r.get("observed_at"))).get("capital_coverage_pct")
            if seen
            else None
        ),
        "journal_note": bad,
    }


def run(
    root: str = REPO_ROOT,
    now: dt.datetime | None = None,
    write: bool = True,
    data_dir: str | None = None,
) -> dict:
    """Померить книгу и вернуть отчёт (он же пишется в ``REPORT_REL``)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    base = data_dir or os.path.join(root, "data")
    path = os.path.join(base, os.path.basename(POSITIONS_REL))
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        report = _report(
            now,
            unchecked=[f"книги нет на диске ({path}) — доля наблюдённого капитала не измерена"],
        )
    except (OSError, ValueError) as e:
        report = _report(now, unchecked=[f"книга не прочитана — {e}"])
    else:
        report = measure(doc, now=now)

    report["input"] = {"path": os.path.basename(POSITIONS_REL)}
    report["history_appended"] = len(append_history(report, base, now)) if write else 0
    report["history"] = history(base, days=HISTORY_WINDOW_DAYS, now=now)
    if write:
        atomic_save(report, os.path.join(base, os.path.basename(REPORT_REL)))
    return report


def exit_code(report: dict) -> int:
    """0 — покрытие полное · 1 — капитал на помеченных литералах · 2 — fail-CLOSED.

    Вердикта без отчёта быть не должно, и потому именно здесь удобнее всего
    соврать: привычное ``report.get("verdict") or OK`` превратило бы «отчёта нет»
    в зачёт. Нет вердикта ⇒ 2.
    """
    verdict = report.get("verdict")
    if verdict == OK:
        return 0
    if verdict == WARN:
        return 1
    return 2


def _lines(report: dict) -> list[str]:
    out = [
        f"доля КАПИТАЛА, ранжированного по наблюдённым числам: {report.get('capital_coverage_pct')}%"
        f" (цель {report.get('target_pct')}%, было {report.get('baseline_pct')}% на 02.08)"
        f" — вердикт {report.get('verdict')}"
    ]
    usd = report.get("usd") or {}
    if report.get("deployed_usd"):
        out.append(
            f"  развёрнуто ${report.get('deployed_usd'):,.0f}:"
            f" наблюдением ${usd.get('evidenced') or 0:,.0f}"
            f" · помеченным литералом ${usd.get('literal') or 0:,.0f}"
            f" · НЕ ИЗМЕРЕНО ${usd.get('unmeasured') or 0:,.0f}"
        )
    alp = report.get("adapters_live_pct")
    if alp is not None:
        out.append(
            f"  рядом: живых АДАПТЕРОВ вселенной {alp}% — это ДРУГОЙ вопрос"
            f" (расхождение {report.get('divergence_pp')} пп)"
        )
    for row in report.get("by_protocol") or []:
        if row.get("message"):
            tag = "НЕ ИЗМЕРЕНО" if row.get("bucket") == "unmeasured" else "WARN"
            out.append(f"  [{tag}] {row.get('message')}")
    for reason in report.get("unchecked") or []:
        out.append(f"  [НЕ ИЗМЕРЕНО] {reason}")
    return out


def main(argv=None, *, now: dt.datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument(
        "--data-dir",
        default=None,
        help="читать книгу и писать отчёт в ЧУЖОЙ каталог (обычно <прод>/data)",
    )
    ap.add_argument("--no-write", action="store_true", help="только печать, без артефакта")
    ap.add_argument("--json", action="store_true", help="печатать отчёт как JSON")
    args = ap.parse_args(argv)
    report = run(root=args.root, now=now, write=not args.no_write, data_dir=args.data_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for line in _lines(report):
            print(line)
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
