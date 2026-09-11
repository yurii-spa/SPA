"""ЕСТЬ ЛИ ЧЕМ закрыть дыру переписи задним числом — и той ли это пробы (заказ #544).

Заказ цикла #544 ([ADR-302]) звучал так:

> Собрать карточку владельцу по предмету границы ADR-285: «расширить ли
> ``apy_evidenced_pct`` до полного живого набора дня». Все три числа уже
> измерены и берутся ССЫЛКОЙ, не пересчётом.
>
> **Ловушка названа заранее.** Соблазн — подать это как «дешёвую однострочную
> починку». У писателя она и правда одна строка, но запись, которую он пишет, —
> та самая, по которой судят перекладки капитала.

Карточка, собранная строго по трём ссылочным числам, называла бы владельцу ДВА
исхода: «расширить писателя» (действует только ВПЕРЁД) и «оставить как есть».
Прибор существует ровно потому, что у вопроса есть третий исход, и без замера
карточка была бы верным вопросом с неполным входом — тем самым дефектом, от
которого заказ предостерегал.

## Вопрос, на который прибор отвечает

ADR-302 измерил, что 41 блокирующая пара «forward-день × нога» из 44 — это класс
``absent_from_forward_books``: ноги не было в книгах того дня, и запись не могла
нести её ставку **ни при каком состоянии фида**. Правка писателя расширит записи
БУДУЩИХ дней; уже написанные 35 строк журнала она не трогает.

Отсюда вопрос: **сохранился ли где-нибудь СЛЕД ставки того дня для той ноги** —
то есть существует ли материал, которым отсечённую пару можно закрыть задним
числом, не выдумывая значение?

## Что прибор считает материалом — и чем материал НЕ является

Материал — точка в ``data/apy_series_daily.json``: накопитель
``spa_core/analytics/apy_series_accumulator.py`` кладёт туда одну точку на
протокол в день и **никогда не интерполирует** (пропуск дня остаётся пропуском,
это его собственная конвенция).

**Материал ≠ эвиденс, и прибор их не смешивает.** Журнал решений признаёт ставку
только при ``apy_sources[p] == "live"`` — провенанс ЗНАЧЕНИЯ. Ряд не несёт
провенанса вовсе: накопитель выбирает ``live_apy``, а при его отсутствии — ``apy``,
и пропускает значение единственной проверкой на конечность. Поэтому «точка есть»
означает «есть чем закрыть», а НЕ «закрытое будет той же пробы».

Отсюда две величины докладываются ОТДЕЛЬНО и ни одна не выводится из другой:

* ``material`` — покрытие отсечённых пар точками ряда (по парам, поимённо);
* ``series_provenance_exposure`` — сколько адаптеров СЕГОДНЯ не несут ``live_apy``
  вовсе и прошли бы в ряд по ``apy``, и сколько из них в ряду действительно есть.

Второе — снимок ДОРОГИ на сегодня, и прибор говорит это вслух: он **не**
утверждает, какие точки прошлого были живыми. Провенанс принадлежит значению, а
не дороге ([ADR-302], та же ловушка) — а значит вопрос «была ли живой точка ряда
за 2026-08-12» не решается ничем, что сегодня лежит на диске, и получает третий
исход, а не правдоподобную корзину.

## Третий исход

Журнал не прочитан · паритет ADR-302 не прошёл · ряд не прочитан или не той формы
⇒ ``UNMEASURED`` с названной причиной. Ноль пар с материалом при исправном ряде и
ноль пар вообще — РАЗНЫЕ исходы, и второй не выдаётся за первый.

## ADVISORY

Писатель журнала, ``POLLED_ADAPTERS``, пины, ``MIN_HIT_RATE``, ``TriggerParams``,
пороги RiskPolicy v1.0, kill-switch и живой трек НЕ трогаются. Прибор только
называет, чем ЗАКРЫВАЕМА дыра и какой пробы будет закрытое; расширение записи и
любое обратное заполнение — предмет границы ADR-285 и решение владельца.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.utils.observation import observed

VERSION = "1.0"
OUTPUT_FILENAME = "journal_backfill_material.json"

STATUS_OK = "OK"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

SERIES_FILENAME = "apy_series_daily.json"
ADAPTER_STATUS_FILENAME = "adapter_status.json"

#: пара отсечена переписью входов — именно её и спрашиваем о материале
CLASS_ABSENT = "absent_from_forward_books"

#: исходы по паре
MATERIAL_PRESENT = "material_present"
MATERIAL_ABSENT_DAY = "material_absent_that_day"
MATERIAL_NO_SERIES = "protocol_not_in_series"

WHAT_IT_DOES_NOT_PROVE = (
    "какой пробы была точка ряда в КОНКРЕТНЫЙ день прошлого: ряд не несёт "
    "провенанса значения ни в каком виде, а adapter_status.json несёт состояние "
    "дороги на сегодня, а не происхождение значения за 2026-08-12. Прибор "
    "докладывает НАЛИЧИЕ материала и ФОРМУ правила отбора, и НЕ докладывает "
    "эвиденс-класс обратного заполнения")


def _is_finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _read_json(path: Path):
    import json
    return json.loads(path.read_text())


def series_points(series: dict) -> Dict[str, Dict[str, float]]:
    """``{протокол: {дата: значение}}`` — форма ряда разбирается ОДНИМ местом.

    Строка не той формы отбрасывается молча по протоколу, но протокол, у которого
    не осталось НИ ОДНОЙ разобранной даты, остаётся с пустым словарём, а не
    исчезает: «протокола нет в ряду» и «ряд по протоколу нечитаем» — разные
    ответы, и схлопывать их значило бы изготовить третий исход из второго.

    Значение проходит тем же фильтром конечности, каким его пропускал накопитель;
    точка с нечисловым значением датой НЕ становится — иначе «дата есть, а числа
    нет» читалось бы как материал (ADR-309: обратное заполнение берёт ЗНАЧЕНИЕ,
    а не отметку о том, что день упоминался).
    """
    out: Dict[str, Dict[str, float]] = {}
    for name, rows in (series or {}).items():
        pts: Dict[str, float] = {}
        for r in rows or []:
            if isinstance(r, (list, tuple)) and len(r) >= 2 \
                    and isinstance(r[0], str) and _is_finite(r[1]):
                pts[r[0]] = float(r[1])
        out[str(name)] = pts
    return out


def series_dates(series: dict) -> Dict[str, set]:
    """``{протокол: {дата, …}}`` — множество дат, выведенное из :func:`series_points`.

    Отдельного разбора здесь НЕТ намеренно: две копии правила «что такое точка
    ряда» разошлись бы молча, и одна из них назвала бы материалом то, что второй
    не является.
    """
    return {name: set(pts) for name, pts in series_points(series).items()}


def classify_pair(pair: dict, by_protocol: Dict[str, set]) -> str:
    """Исход по одной отсечённой паре. Читает ТОЛЬКО ряд, ничего не достраивая."""
    proto = str(pair.get("protocol"))
    day = str(pair.get("forward_date"))
    if proto not in by_protocol:
        return MATERIAL_NO_SERIES
    return MATERIAL_PRESENT if day in by_protocol[proto] else MATERIAL_ABSENT_DAY


def provenance_exposure(adapters: dict, by_protocol: Dict[str, set]) -> dict:
    """Форма правила отбора накопителя на СЕГОДНЯШНЕМ снимке дороги.

    Накопитель берёт ``live_apy``, а при его отсутствии ``apy``, и пропускает по
    конечности. Значит адаптер без ``live_apy`` с конечным ``apy`` проходит в ряд
    под файлом, чья подпись говорит «live APY percent points». Меряем ровно это —
    и НЕ выдаём за утверждение о прошлом.
    """
    live_ok: List[str] = []
    static_only: List[str] = []
    for name, info in (adapters or {}).items():
        if not isinstance(info, dict):
            continue
        if _is_finite(info.get("live_apy")):
            live_ok.append(str(name))
        elif _is_finite(info.get("apy")):
            static_only.append(str(name))
    in_series = sorted(n for n in static_only if n in by_protocol)
    return {
        "adapters_seen": len(live_ok) + len(static_only),
        "with_live_apy": len(live_ok),
        "without_live_apy_but_finite_apy": len(static_only),
        "of_those_present_in_series": in_series,
        "rule": "live_apy → иначе apy → фильтр только на конечность",
        "note": ("снимок ДОРОГИ на сегодня; о происхождении точек прошлого "
                 "не говорит ничего"),
    }


def measure(data_dir, *, now: Optional[datetime] = None,
            book_id: Optional[str] = None,
            horizon_days: Optional[int] = None,
            causes: Optional[dict] = None) -> dict:
    """Чем закрываема дыра переписи и какой пробы будет закрытое.

    ``causes`` — уже посчитанный отчёт ADR-302 (инъекция для тестов и для
    повторного использования внутри одного прогона моста). По умолчанию прибор
    зовёт НАСТОЯЩИЙ ``unevidenced_leg_causes.measure``: своей копии правила
    отнесения пары к классу у него нет и быть не должно.
    """
    data_dir = Path(data_dir)
    now = now or datetime.now(timezone.utc)
    findings: List[str] = []
    doc: dict = {
        "version": VERSION,
        "generated_at": now.isoformat(),
        "status": STATUS_UNMEASURED,
        "findings": findings,
        "what_it_does_not_prove": WHAT_IT_DOES_NOT_PROVE,
        "advisory": ("писатель журнала, POLLED_ADAPTERS, пины, MIN_HIT_RATE, "
                     "TriggerParams, пороги RiskPolicy v1.0 и живой трек НЕ "
                     "трогаются — прибор только называет материал и его пробу"),
    }

    if causes is None:
        from spa_core.monitoring import unevidenced_leg_causes
        try:
            causes = unevidenced_leg_causes.measure(
                data_dir, now=now, book_id=book_id, horizon_days=horizon_days)
        except Exception as exc:  # noqa: BLE001 — третий исход, а не ноль
            findings.append(f"[НЕ ИЗМЕРЕНО] отчёт причин (ADR-302) не построен: {exc}")
            return doc

    doc["causes_status"] = causes.get("status")
    if causes.get("status") == STATUS_UNMEASURED:
        findings.append("[НЕ ИЗМЕРЕНО] отчёт причин (ADR-302) сам не измерен — "
                        "спрашивать о материале не для чего")
        return doc
    parity = causes.get("parity_control") or {}
    if parity and not parity.get("passed"):
        findings.append("[НЕ ИЗМЕРЕНО] паритет ADR-302 с оценщиком не прошёл — "
                        "население отсечённых пар брать неоткуда")
        return doc

    pairs = [p for p in (causes.get("attribution") or [])
             if p.get("class") == CLASS_ABSENT]
    doc["pairs_cut_by_transcription"] = len(pairs)

    try:
        series_doc = _read_json(data_dir / SERIES_FILENAME) or {}
        series_raw = series_doc.get("series")
        if series_raw is not None and not isinstance(series_raw, dict):
            # Поле ЕСТЬ, но не того рода: это не «материала нет», а «прочитать
            # не смогли» (инвариант #17) — третий исход с названной причиной.
            findings.append(
                f"[НЕ ИЗМЕРЕНО] ряд {SERIES_FILENAME} имеет форму "
                f"{type(series_raw).__name__}, ожидался словарь — «материала нет» "
                "из этого НЕ следует")
            doc["status"] = STATUS_UNMEASURED
            return doc
        # Поля нет вовсе — ряда не существует, и материала действительно нет.
        series = series_raw or {}
    except Exception as exc:  # noqa: BLE001
        findings.append(f"[НЕ ИЗМЕРЕНО] ряд {SERIES_FILENAME} не прочитан: {exc} — "
                        "«материала нет» из этого НЕ следует")
        return doc
    if not isinstance(series, dict):
        findings.append(f"[НЕ ИЗМЕРЕНО] ряд {SERIES_FILENAME} не той формы "
                        f"({type(series).__name__}) — разобрать нечем")
        return doc

    by_protocol = series_dates(series)
    doc["series_protocols"] = len(by_protocol)

    per_class: Dict[str, int] = {MATERIAL_PRESENT: 0, MATERIAL_ABSENT_DAY: 0,
                                 MATERIAL_NO_SERIES: 0}
    rows: List[dict] = []
    for p in pairs:
        cls = classify_pair(p, by_protocol)
        per_class[cls] += 1
        rows.append({"decision_date": p.get("decision_date"),
                     "forward_date": p.get("forward_date"),
                     "protocol": p.get("protocol"), "outcome": cls})
    doc["material"] = per_class
    doc["per_pair"] = rows
    doc["protocols_without_material"] = sorted(
        {str(r["protocol"]) for r in rows if r["outcome"] != MATERIAL_PRESENT})

    try:
        adapters = (_read_json(data_dir / ADAPTER_STATUS_FILENAME)
                    or {}).get("adapters") or {}
    except Exception as exc:  # noqa: BLE001
        adapters = {}
        findings.append(f"[НЕ ИЗМЕРЕНО] {ADAPTER_STATUS_FILENAME} не прочитан "
                        f"({exc}) — форма правила отбора накопителя не измерена")
    doc["series_provenance_exposure"] = provenance_exposure(adapters, by_protocol)

    if not pairs:
        doc["status"] = STATUS_OK
        findings.append("[ОТВЕТ] отсечённых переписью пар нет — закрывать нечего")
        return doc

    covered = per_class[MATERIAL_PRESENT]
    findings.append(
        f"[ОТВЕТ] материал для обратного заполнения есть у {covered} из "
        f"{len(pairs)} отсечённых пар: точка ряда за ТОТ день по ТОЙ ноге "
        f"существует. Без материала — {len(pairs) - covered} "
        f"({', '.join(doc['protocols_without_material']) or '—'})")

    exp = doc["series_provenance_exposure"]
    if exp.get("without_live_apy_but_finite_apy"):
        findings.append(
            "[CRITICAL] материал НЕ той же пробы, что эвиденс журнала: правило "
            f"отбора накопителя — {exp['rule']}, и сегодня "
            f"{exp['without_live_apy_but_finite_apy']} адаптер(ов) из "
            f"{exp['adapters_seen']} не несут `live_apy` вовсе; "
            f"{len(exp['of_those_present_in_series'])} из них в ряду ЕСТЬ"
            + (f" ({', '.join(exp['of_those_present_in_series'])})"
               if exp["of_those_present_in_series"] else "")
            + ". Обратное заполнение из ряда даст записи ставку, о живости "
              "которой в тот день не свидетельствует ничто — это ослабление "
              "пробы контрфакта (ADR-061/063), а не восстановление истории")
        doc["status"] = STATUS_CRITICAL
    else:
        doc["status"] = STATUS_OK
    return doc


def format_report(doc: dict) -> List[str]:
    out: List[str] = [
        f"   чем закрываема дыра переписи (заказ #544): {doc.get('status')} · "
        f"отсечённых пар {doc.get('pairs_cut_by_transcription')} · "
        f"протоколов в ряду {doc.get('series_protocols')}"]
    mat = doc.get("material") or {}
    if mat:
        out.append("   материал: " + " · ".join(f"{k}={v}" for k, v in mat.items()))
    for line in doc.get("findings") or []:
        out.append(f"   {line}")
    if doc.get("what_it_does_not_prove"):
        out.append(f"   НЕ ДОКАЗЫВАЕТ: {doc['what_it_does_not_prove']}")
    if doc.get("advisory"):
        out.append(f"   ADVISORY: {doc['advisory']}")
    return out


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        write: bool = True, **kwargs) -> dict:
    """Форма, которую ждут ступень переписей `findings_bridge` и шаг 0-офис."""
    from spa_core.utils.atomic import atomic_save

    root = root or str(Path(__file__).resolve().parents[2])
    data_dir = Path(root) / "data"
    doc = measure(data_dir, now=now, **kwargs)
    findings = list(doc.get("findings") or [])
    doc["overall"] = doc["status"]
    doc["counts"] = {
        "critical": sum(1 for x in findings if x.startswith("[CRITICAL]")),
        "warn": 0,
        "info": sum(1 for x in findings if x.startswith("[ОТВЕТ]")),
        # «не измерено» считается ОТДЕЛЬНО от нулей: растворив его, мы сделали бы
        # молчание прибора неотличимым от чистого прогона.
        "unchecked": (1 if doc["status"] == STATUS_UNMEASURED else 0)
                     + sum(1 for x in findings if x.startswith("[НЕ ИЗМЕРЕНО]")),
    }
    if write:
        atomic_save(doc, str(data_dir / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="чем закрываема дыра переписи журнала решений (заказ #544)")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    data_dir = (Path(args.data_dir) if args.data_dir
                else Path(os.environ.get("SPA_DATA_DIR")
                          or (Path(__file__).resolve().parents[2] / "data")))
    doc = measure(data_dir)
    if not args.no_write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(Path(data_dir) / OUTPUT_FILENAME))
    for line in format_report(doc):
        print(line)
    return 0 if doc["status"] == STATUS_OK else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
