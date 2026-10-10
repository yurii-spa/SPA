#!/usr/bin/env python3
"""Почему освобождение не сняло НИЧЕГО — заказ **G111 п. 2** (ADR-536).

Заказ, дословно:

    **111 освобождений не сняли ничего, и причина НЕ ИЗМЕРЕНА.** Это может быть и
    карточка, взятая не через журнал, и ``done`` без захвата, и ярлык, потерявший
    якорь. Разобрать по ПИСАТЕЛЮ, назвать доли, и не выдавать самую вероятную за
    измеренную.

Сосед ADR-536 (``claim_release_census.measure_writers``) НАЗВАЛ число — освобождения,
не снявшие ни одного прежнего захвата своей личности, — и сам сказал вслух, чего не
говорит: «освободило ничего» НЕ есть ошибка писателя. Здесь спрашивается ровно
пропущенное: **ПОЧЕМУ** каждое такое освобождение прошло впустую, и спрашивается у
ИСХОДА, а не у правдоподобия.

## Три причины заказа — три РАЗНЫХ двери, и спрашиваются они в объявленном порядке

====== ============================================ =====================================
шаг    вопрос                                        чем меряется (ИСХОД, не догадка)
====== ============================================ =====================================
1      ярлык потерял якорь?                          ПЕРЕКЛЮЧЕНИЕМ КЛЮЧА: тот же ярлык
                                                      ``session`` берётся вместо пары
                                                      (якорь|ярлык). Совпадение
                                                      ПОЯВИЛОСЬ ⇒ захват был, и его
                                                      спрятала личность, а не писатель
2      карточка взята не через журнал?               САМА КАРТОЧКА свидетельствует о
                                                      писателе: ``claimed_by`` или
                                                      ``status_trail``
3      захвата нет нигде?                            карточка ПРОЧИТАНА и о писателе
                                                      НЕ свидетельствует
====== ============================================ =====================================

Порядок закрыт и существен: шаг 1 отвечает ИЗ ЖУРНАЛА и потому не зависит от того,
читается ли карточка; шаги 2 и 3 различимы ТОЛЬКО когда файл карточки прочитан. Поменять
их местами значило бы отдать дрейфу личности исход «захвата нет нигде» на каждой
пропавшей карточке.

## Четвёртый, пятый и шестой исходы — НЕ причины, а признание, что причина НЕ ИЗМЕРЕНА (инв. #17)

* ``unmeasured_mention_only`` — карточка прочитана, в объявленных полях захвата
  писателя нет, но его ярлык ВСТРЕЧАЕТСЯ В КАРТОЧКЕ — в прозе тела либо в поле шапки,
  свидетелем НЕ объявленном (например в ``claim_takeover_reason``). Упоминание захватом
  не является и его отсутствием — тоже: про такую строку известно ровно то, что она
  есть. Сложить её со «захвата нет нигде» значило бы назвать измеренным самое
  вероятное — ровно то, что заказ запретил;
* ``unmeasured_card_unreadable`` — файла карточки нет (или значение поля ``card:``
  карточкой не является вовсе). Тогда шаги 2 и 3 НЕРАЗЛИЧИМЫ по построению, и выбрать
  между ними нельзя ничем;
* ``unmeasured_writer_unnamed`` — ярлык писателя ПУСТ. Пустой ярлык личностью не
  является, и спросить у него нельзя ничего: пустить его в ключ по ярлыку значило бы
  объявить дрейфом совпадение ДВУХ РАЗНЫХ безымянных писателей на одной карточке, то
  есть выдумать причину. Замер 10.10 — таких **0**, и это ИЗМЕРЕННЫЙ НУЛЬ.

**Цена четвёртого исхода измерена, а не объявлена.** Нестрогая проба («ярлык
где-нибудь в карточке») дала бы причине №2 **12** вместо **7** (замер 10.10 на живом
журнале) — то есть завысила бы её почти ВДВОЕ. Поэтому нестрогая проба считается
ОТДЕЛЬНО и в причину не входит.

## Поля-свидетели объявлены, и одно из них ИСКЛЮЧЕНО намеренно

Свидетельствуют ``claimed_by`` (нынешний держатель) и ``status_trail`` (писатель
перевода). ``claim_takeover_reason`` ИСКЛЮЧЕНО: оно называет сессии, чей захват
ПЕРЕБИТ, а не того, кто действовал, — включить его значило бы ИЗГОТОВИТЬ свидетелей
(одно поднятие приказа 10.10 назвало в своём основании 116 чужих ярлыков на ОДНОЙ
карточке). Цена исключения измерена и равна нулю СЕГОДНЯ (7 свидетелей с полем и 7 без
него): вред поля ЛАТЕНТЕН, а не отсутствует, и проявится, как только своё пустое
освобождение напишет сессия, чей захват уже перебит на той же карточке. Направление
ошибки известно (свидетели завышаются), поэтому поле не берётся.

## Разбор ПО ПИСАТЕЛЮ, как просил заказ

Доли считаются не только по причинам, но и по ПИСАТЕЛЮ (``by_writer``): сколько пустых
освобождений на каждом ярлыке и какие причины за ними стоят. Без этого «118 пустых
освобождений» остаётся свойством журнала, а заказ спрашивал про того, кто их пишет.

## Сверка состава с соседом — четвёртый вопрос, а не второе мнение

Население берётся у соседа ЦЕЛИКОМ (``split_population``, ``identity_of``), и число
пустых освобождений сверяется с его собственным (``measure_writers.released_nothing``).
Равенство ожидаемо ПО ПОСТРОЕНИЮ и независимым подтверждением НЕ является; ценность у
сверки обратная — расхождение означает, что один из двух приборов читает не то
население, и прибор его НАЗЫВАЕТ.

## Вердикт

* ``CAUSES_NAMED`` — у каждого пустого освобождения причина НАЗВАНА, неизмеренных нет
  (код 0);
* ``CAUSES_PARTLY_UNMEASURED`` — часть причин назвать НЕЧЕМ (код 1): это находка о
  ЗАПИСИ, а не о писателе — журнал и карточки сегодня не хранят того, чем эти случаи
  различаются;
* ``NO_EMPTY_RELEASES`` — пустых освобождений нет (код 0). Это ИЗМЕРЕННЫЙ НУЛЬ, а не
  отсутствие замера;
* ``UNMEASURED`` — код 2, перебивает всё.

Прибор ТОЛЬКО ЧИТАЕТ: правило освобождения не правит, карточек не трогает, ничего не
закрывает. Выбор, что делать с найденными долями, есть решение и идёт заказом, а не
следствием замера.

    python3 -m spa_core.monitoring.empty_release_causes
    python3 -m spa_core.monitoring.empty_release_causes --json --save
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

if __package__ in (None, ""):  # pragma: no cover — прямой запуск файла
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring.claim_release_census import (  # noqa: E402
    JOURNAL_REL,
    load_neighbours,
    measure_writers,
    read_journal,
    split_population,
)
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT_NAME = "empty_release_causes.json"
ORDER = ("G111 п. 2 (ADR-536) — почему освобождение не сняло НИЧЕГО, "
         "разбор по ПИСАТЕЛЮ")

TRACKER_REL = "nimbalyst-local/tracker"

STATUS_NAMED = "CAUSES_NAMED"
STATUS_PARTLY = "CAUSES_PARTLY_UNMEASURED"
STATUS_NONE = "NO_EMPTY_RELEASES"
STATUS_UNMEASURED = "UNMEASURED"

#: Причины заказа — ИМЕНА ИСХОДОВ. Перечень ЗАКРЫТ: пятая причина означала бы, что
#: заказ назвал не все двери, и это надо объявлять решением, а не дописывать молча.
CAUSE_DRIFT = "identity_drift"
CAUSE_OFF_JOURNAL = "claimed_off_journal"
CAUSE_NO_CLAIM = "no_claim_anywhere"
CAUSE_UNMEASURED_MENTION = "unmeasured_mention_only"
CAUSE_UNMEASURED_CARD = "unmeasured_card_unreadable"
CAUSE_UNMEASURED_WRITER = "unmeasured_writer_unnamed"

CAUSES = (CAUSE_DRIFT, CAUSE_OFF_JOURNAL, CAUSE_NO_CLAIM,
          CAUSE_UNMEASURED_MENTION, CAUSE_UNMEASURED_CARD,
          CAUSE_UNMEASURED_WRITER)

#: Исходы, которые причиной НЕ ЯВЛЯЮТСЯ: все три говорят «различить нечем» (инв. #17).
UNMEASURED_CAUSES = (CAUSE_UNMEASURED_MENTION, CAUSE_UNMEASURED_CARD,
                     CAUSE_UNMEASURED_WRITER)

#: Поля карточки, свидетельствующие о ПИСАТЕЛЕ. ``claim_takeover_reason`` ИСКЛЮЧЕНО
#: намеренно — оно называет перебитые сессии, а не действовавшую (см. модульную справку).
WITNESS_FIELDS = ("claimed_by", "status_trail")
WITNESS_FIELD_EXCLUDED = "claim_takeover_reason"


def label_of(row: Dict[str, Any]) -> str:
    """ЯРЛЫК писателя записи — то же поле, которым личность зовут все соседи."""
    return str(row["record"].get("session") or "")


def _claim_index(claims: Sequence[Dict[str, Any]]) -> Dict[str, Dict[Any, List[Any]]]:
    """Два ключа над ОДНИМ населением захватов: строгий (как у соседа) и по ярлыку.

    Строгий ключ — пара ``identity_of`` (якорь, если объявлен; иначе ярлык), то есть
    ровно тот, которым сосед считал ``released_nothing``. Ключ по ярлыку отличается
    РОВНО тем, что личность берётся без якоря: разница вердиктов между ними и ЕСТЬ
    замер дрейфа личности, а не его оценка.
    """
    strict: Dict[Any, List[Any]] = {}
    by_label: Dict[Any, List[Any]] = {}
    for row in claims:
        strict.setdefault((row["identity"], row["card"]), []).append(row)
        by_label.setdefault((label_of(row), row["card"]), []).append(row)
    return {"strict": strict, "by_label": by_label}


def _prior(index: Dict[Any, List[Any]], key: Any, stamp) -> List[Dict[str, Any]]:
    """Захваты по ключу, открытые НЕ ПОЗЖЕ ``stamp``.

    Правило «снял бы» взято у ДВЕРИ (``check_card_claim``, ось B соседа): ``>=``, то
    есть ``done`` раньше захвата повторное взятие не снимает. Своего правила здесь нет.
    """
    return [row for row in index.get(key, ()) if row["ts"] <= stamp]


def read_card_text(card: str, tracker_dir: Path, *, guard) -> Optional[str]:
    """Текст файла карточки или ``None`` — «карточка не прочитана» (третий исход).

    Путь строит СОСЕД (``guard.card_path``): своё правило имени разошлось бы с
    настоящим молча (ADR-220).
    """
    try:
        path = guard.card_path(card, tracker_dir=tracker_dir)
    except Exception:  # noqa: BLE001 — не имя карточки есть «не прочитана»
        return None
    if not path:
        return None
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return None


def trail_entries(text: str) -> List[str]:
    """Записи ``status_trail`` из шапки карточки.

    Читается ЗДЕСЬ, а не у соседа, и это НЕ второй экземпляр чужой мерки: разбор
    соседа (``guard.frontmatter``) ПЛОСКИЙ по построению — вложенные блоки он
    пропускает намеренно и отдаёт ``status_trail`` пустой строкой. Объявить его
    полем-свидетелем и спрашивать у плоского разбора значило бы объявить поле,
    которого читатель не видит ВОВСЕ: замер 10.10 — ``frontmatter`` вернул
    ``status_trail=''`` на карточке, чей трейл несёт писателя, то есть свидетель
    был бы МЁРТВЫМ, а доля причины — завышенно-нулевой.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    out: List[str] = []
    inside = False
    for raw in lines[1:]:
        if raw.strip() == "---":
            break
        if not inside:
            inside = raw.startswith("status_trail:")
            continue
        if raw.strip() and not raw[:1].isspace():
            break  # шапка пошла дальше — блок кончился
        if raw.strip().startswith("-"):
            out.append(raw.strip().lstrip("-").strip().strip("\"'"))
    return out


def witness_of(text: str, label: str, *, guard) -> Dict[str, bool]:
    """Свидетельствует ли КАРТОЧКА о писателе — строго и (отдельно) нестрого.

    ``declared`` — ярлык стоит в объявленных полях захвата (``WITNESS_FIELDS``):
    ``claimed_by`` берётся плоским разбором соседа, ``status_trail`` — своим
    читателем блока (см. ``trail_entries``).
    ``mention_only`` — в объявленных полях его нет, а где-нибудь в карточке он
    встречается (проза тела или поле шапки, свидетелем не объявленное): это НЕ захват
    и НЕ его отсутствие, поэтому исход считается отдельно и в причину не входит.
    """
    if not label:
        return {"declared": False, "mention_only": False}
    try:
        front = guard.frontmatter(text)
    except Exception:  # noqa: BLE001 — неразобранная шапка есть «не свидетельствует»
        front = {}
    witnesses = {"claimed_by": front.get("claimed_by"),
                 "status_trail": trail_entries(text)}
    blob = json.dumps(witnesses, ensure_ascii=False)
    declared = label in blob
    return {"declared": declared,
            "mention_only": bool(not declared and label in text)}


def classify(claims: Sequence[Dict[str, Any]],
             releases: Sequence[Dict[str, Any]],
             *, guard, tracker_dir: Path) -> Dict[str, Any]:
    """Причина КАЖДОГО пустого освобождения, доли и разбор по ПИСАТЕЛЮ."""
    index = _claim_index(claims)
    counts: Dict[str, int] = {cause: 0 for cause in CAUSES}
    #: Дрейф — с какой личности на какую: заказ просил разбор ПО ПИСАТЕЛЮ, а
    #: «якорь → якорь» (один ярлык, РАЗНЫЕ якоря) и «якорь → ярлык» (якорь
    #: потерян) есть две разные болезни одного имени.
    drift_shape: Dict[str, int] = {}
    by_writer: Dict[str, Dict[str, int]] = {}
    examples: Dict[str, List[Dict[str, Any]]] = {cause: [] for cause in CAUSES}
    mention_only_witnesses = 0

    empty: List[Dict[str, Any]] = []
    for row in releases:
        if _prior(index["strict"], (row["identity"], row["card"]), row["ts"]):
            continue
        empty.append(row)

    for row in empty:
        label = label_of(row)
        # Пустой ярлык личностью НЕ является, и спросить у него нельзя НИЧЕГО.
        # Пустить его в ключ `by_label` значило бы объявить дрейфом совпадение ДВУХ
        # РАЗНЫХ безымянных писателей на одной карточке — выдуманная причина там,
        # где честный ответ «писатель не назван» (инв. #17). Сегодня таких 0, и это
        # ИЗМЕРЕННЫЙ НУЛЬ, а не отсутствие случая.
        if not label:
            cause = CAUSE_UNMEASURED_WRITER
            counts[cause] += 1
            by_writer.setdefault("<ярлык пуст>", {})
            by_writer["<ярлык пуст>"][cause] = by_writer["<ярлык пуст>"].get(cause, 0) + 1
            if len(examples[cause]) < 5:
                examples[cause].append({
                    "card": row["card"], "writer": label,
                    "ts": row["ts"].isoformat().replace("+00:00", "Z"),
                    "identity_from": row["identity"][0]})
            continue
        drifted = _prior(index["by_label"], (label, row["card"]), row["ts"])
        if drifted:
            cause = CAUSE_DRIFT
            shape = (f"{','.join(sorted({c['identity'][0] for c in drifted}))}"
                     f"→{row['identity'][0]}")
            drift_shape[shape] = drift_shape.get(shape, 0) + 1
        else:
            text = read_card_text(row["card"], tracker_dir, guard=guard)
            if text is None:
                cause = CAUSE_UNMEASURED_CARD
            else:
                seen = witness_of(text, label, guard=guard)
                if seen["declared"]:
                    cause = CAUSE_OFF_JOURNAL
                elif seen["mention_only"]:
                    cause = CAUSE_UNMEASURED_MENTION
                    mention_only_witnesses += 1
                else:
                    cause = CAUSE_NO_CLAIM
        counts[cause] += 1
        by_writer.setdefault(label, {})
        by_writer[label][cause] = by_writer[label].get(cause, 0) + 1
        if len(examples[cause]) < 5:
            examples[cause].append({
                "card": row["card"],
                "writer": label,
                "ts": row["ts"].isoformat().replace("+00:00", "Z"),
                "identity_from": row["identity"][0]})

    total = len(empty)
    unmeasured = sum(counts[cause] for cause in UNMEASURED_CAUSES)
    shares = ({cause: round(100.0 * counts[cause] / total, 2) for cause in CAUSES}
              if total else None)
    writers_ranked = sorted(by_writer.items(),
                            key=lambda kv: (-sum(kv[1].values()), kv[0]))
    return {
        "empty_releases": total,
        "counts": counts,
        "shares_pct": shares,
        "unmeasured": unmeasured,
        "drift_shape": drift_shape or None,
        "mention_only_witnesses": mention_only_witnesses,
        "writers_total": len(by_writer),
        "by_writer_top": [{"writer": name, "empty_releases": sum(per.values()),
                           "causes": per} for name, per in writers_ranked[:10]],
        "examples": examples,
        "witness_fields": list(WITNESS_FIELDS),
        "witness_field_excluded": WITNESS_FIELD_EXCLUDED,
        "means": ("доли — замер ПРИЧИНЫ, а не правдоподобия: дрейф личности спрошен "
                  "переключением ключа, захват вне журнала — самой карточкой, и два "
                  "исхода объявлены НЕИЗМЕРЕННЫМИ вместо того, чтобы влиться в "
                  "самый вероятный"),
    }


def cross_check(classified: Dict[str, Any],
                neighbour_writers: Dict[str, Any]) -> Dict[str, Any]:
    """Сверка СОСТАВА с соседом: столько ли пустых освобождений видит он.

    Равенство ожидаемо ПО ПОСТРОЕНИЮ (население и ключ взяты у него же) и вторым
    мнением НЕ является. Расхождение есть дефект проводки — его прибор и называет.
    """
    if not neighbour_writers.get("measured"):
        return {"agrees": None,
                "reason": ("сосед не измерил писателей: "
                           f"{neighbour_writers.get('reason')}"),
                "neighbour_released_nothing": None,
                "own_empty_releases": classified["empty_releases"]}
    theirs = neighbour_writers.get("released_nothing")
    mine = classified["empty_releases"]
    agrees = theirs == mine
    return {
        "agrees": agrees,
        "reason": (None if agrees else
                   ("состав населений РАЗОШЁЛСЯ: один из двух приборов читает не то "
                    "население — это дефект проводки, а не два мнения")),
        "neighbour_released_nothing": theirs,
        "own_empty_releases": mine,
        "means": ("равенство ожидаемо по построению и подтверждением не является; "
                  "ценность сверки обратная — она ловит расхождение"),
    }


def build_report(repo_root: Path, *, now: Optional[datetime] = None,
                 journal_path: Optional[Path] = None,
                 tracker_dir: Optional[Path] = None,
                 neighbours: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Отчёт прибора. Форма ПОСТОЯННА: ключи объявлены всегда, «не вычислено» — ``None``."""
    stamp = now or datetime.now(timezone.utc)
    report: Dict[str, Any] = {
        "generated_at": stamp.isoformat().replace("+00:00", "Z"),
        "order": ORDER,
        "measured": False,
        "status": STATUS_UNMEASURED,
        "reason": None,
        "applied": False,
        "population": None,
        "causes": None,
        "cross_check": None,
    }
    kin = neighbours if neighbours is not None else load_neighbours(repo_root)
    if kin["missing"]:
        report["reason"] = ("не загружены соседние мерки: " + ", ".join(kin["missing"])
                            + " — правило освобождения, разбор личности и путь "
                              "карточки спрашиваются у них, своего экземпляра у "
                              "прибора нет намеренно")
        return report
    guard, sibling = kin["guard"], kin["sibling"]

    path = journal_path if journal_path is not None else repo_root / JOURNAL_REL
    journal = read_journal(Path(path))
    if journal["records"] is None:
        report["reason"] = journal["reason"]
        return report

    population = split_population(journal["records"], guard=guard, sibling=sibling)
    report["population"] = {
        "journal": str(path),
        "records": len(journal["records"]),
        "broken_lines": journal["broken_lines"],
        "claims": len(population["claims"]),
        "releases": len(population["releases"]),
        "records_without_card": population["records_without_card"],
        "records_with_card_unparsed_ts": population["records_with_card_unparsed_ts"],
    }
    if not population["releases"]:
        report["reason"] = ("освобождений в журнале нет — «ни одно не прошло впустую» "
                            "верно ПО ПОСТРОЕНИЮ и замером не является")
        return report

    tracker = tracker_dir if tracker_dir is not None else repo_root / TRACKER_REL
    classified = classify(population["claims"], population["releases"],
                          guard=guard, tracker_dir=Path(tracker))
    classified["tracker_dir"] = str(tracker)
    report["causes"] = classified
    report["cross_check"] = cross_check(
        classified, measure_writers(population["claims"], population["releases"]))

    report["measured"] = True
    if classified["empty_releases"] == 0:
        report["status"] = STATUS_NONE
    elif classified["unmeasured"] > 0:
        report["status"] = STATUS_PARTLY
    else:
        report["status"] = STATUS_NAMED
    return report


def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    path = data_dir / ARTIFACT_NAME
    atomic_save(report, str(path))
    return path


def format_report(report: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    if not report.get("measured"):
        lines.append("почему освобождение не сняло ничего (заказ G111 п. 2): "
                     f"НЕ ИЗМЕРЕНО — {report.get('reason')}")
        return lines
    pop = report["population"]
    causes = report["causes"]
    checked = report["cross_check"]
    counts = causes["counts"]
    # `... or {}` здесь склеило бы «раздела долей НЕТ» с «доли пусты» (инв. #17):
    # первое бывает при нуле пустых освобождений, второе не бывает вовсе, и
    # печатать для них одну строку значило бы выдать неизмеренное за измеренное.
    shares = observed(causes, "shares_pct", kind=dict)

    lines.append(f"почему освобождение не сняло ничего (заказ G111 п. 2): "
                 f"{report['status']} · освобождений {pop['releases']} · "
                 f"прошло впустую {causes['empty_releases']} · "
                 f"писателей {causes['writers_total']}")
    if causes["empty_releases"] == 0:
        lines.append("   ИЗМЕРЕННЫЙ НУЛЬ: ни одно освобождение не прошло впустую")
        return lines
    for cause in CAUSES:
        mark = "НЕ ИЗМЕРЕНО" if cause in UNMEASURED_CAUSES else "причина"
        share = None if shares is None else shares.get(cause)
        share_text = "доля НЕ ИЗМЕРЕНА" if share is None else f"{share} %"
        lines.append(f"   [{mark}] {cause}: {counts[cause]} ({share_text})")
    if causes["drift_shape"]:
        shape = " · ".join(f"{k} {v}" for k, v in sorted(causes["drift_shape"].items(),
                                                         key=lambda kv: -kv[1]))
        lines.append(f"   дрейф личности по форме: {shape}")
    if causes["mention_only_witnesses"]:
        lines.append(f"   нестрогая проба («ярлык где-нибудь в карточке») насчитала бы причине "
                     f"`{CAUSE_OFF_JOURNAL}` "
                     f"{counts[CAUSE_OFF_JOURNAL] + causes['mention_only_witnesses']} "
                     f"вместо {counts[CAUSE_OFF_JOURNAL]} — эти "
                     f"{causes['mention_only_witnesses']} считаются НЕИЗМЕРЕННЫМИ")
    for row in causes["by_writer_top"][:3]:
        lines.append(f"   писатель {row['writer']}: {row['empty_releases']} "
                     f"({', '.join(f'{k}={v}' for k, v in sorted(row['causes'].items()))})")
    if checked["agrees"] is None:
        lines.append(f"   [СВЕРКА] НЕ ИЗМЕРЕНО — {checked['reason']}")
    elif not checked["agrees"]:
        lines.append(f"   [СВЕРКА] {checked['reason']}: сосед "
                     f"{checked['neighbour_released_nothing']} против "
                     f"{checked['own_empty_releases']}")
    else:
        lines.append(f"   [СВЕРКА] состав сошёлся с соседом "
                     f"({checked['neighbour_released_nothing']}) — ожидаемо по "
                     f"построению, подтверждением не является")
    lines.append(f"   НЕ ДОКЛАДЫВАЕТ: какую запись чинить (это решение, идёт заказом) · "
                 f"поле `{causes['witness_field_excluded']}` в свидетели НЕ взято "
                 f"(называет перебитые сессии, а не действовавшую)")
    return lines


def run(root: Optional[str] = None, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Точка входа ступени моста (`findings_bridge`).

    Артефакт оставляется ВСЕГДА, включая третий исход: «не измерено» с названной
    причиной обязано доехать до шага 0-офис, иначе отсутствие файла неотличимо от
    «ступень не запускалась».
    """
    repo_root = Path(root) if root else Path(__file__).resolve().parents[2]
    report = build_report(repo_root, now=now)
    try:
        save_artifact(report, repo_root / "data")
    except Exception as exc:  # noqa: BLE001 — прибор не смеет валить мост
        report = dict(report)
        report["artifact_not_written"] = f"{type(exc).__name__}: {exc}"
    return {"measured": bool(report.get("measured")), "doc": report}


def exit_code_for(report: Dict[str, Any]) -> int:
    if not report.get("measured"):
        return 2
    return 1 if report["status"] == STATUS_PARTLY else 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=None, help="корень дерева (по умолчанию — своё)")
    ap.add_argument("--journal", default=None,
                    help=f"журнал объявлений (по умолчанию — {JOURNAL_REL} своего дерева)")
    ap.add_argument("--tracker-dir", default=None,
                    help=f"каталог карточек (по умолчанию — {TRACKER_REL} своего дерева)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", action="store_true", help=f"записать data/{ARTIFACT_NAME}")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[2]
    report = build_report(
        repo_root,
        journal_path=Path(args.journal) if args.journal else None,
        tracker_dir=Path(args.tracker_dir) if args.tracker_dir else None)
    if args.save:
        save_artifact(report, repo_root / "data")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for line in format_report(report):
            print(line)
    return exit_code_for(report)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
