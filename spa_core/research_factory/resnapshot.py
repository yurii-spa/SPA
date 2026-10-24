"""spa_core/research_factory/resnapshot.py — ежесуточная ПЕРЕСЪЁМКА свежайшего описания
кандидата: три недостающих писателя рецепта, открывающего окно усечения (ADR-798,
заказ G797 приказа Portfolio CIO).

Зачем этот писатель существует — измеренная причина, а не предпочтение в устройстве.

Лента ``data/research_factory/ledger.jsonl`` растёт 3.907 МБ/сут, и усечение по
ВОЗРАСТУ не имеет безопасного окна ни на одних сутках (ADR-793). ADR-794 оценил цену
названного лекарства — периодически ПЕРЕСНИМАТЬ свежайшее описание каждого живого
кандидата, — ADR-795 вылечил ФОРМУ накапливающих списков причин строкой уплотнения
(``history.KIND``), а ADR-797 попробовал ИСПОЛНИТЬ усечение и отказал, назвав причину
числом:

    рецепт, у которого прибор цены измерил окно 1 сут
    (``ledger_resnapshot_price_census`` ``"snapshot+evidence+compaction"``),
    состоит из ЧЕТЫРЁХ писателей, а построен был ОДИН.

Трое отсутствующих — это ровно одно действие, повторяемое каждый такт: взять свежайшую
запись вида ``candidate_snapshot`` / ``evidence_bundle`` / ``admission_decision`` каждого
кандидата и ЗАПИСАТЬ ЕЁ ЗАНОВО, чтобы описание кандидата всегда лежало внутри окна
хранения. Без этого ``read.latest`` зависит от записей, которым 20 суток (у 31 кандидата
из 100 единственное описание — со дня посева 04.10), и отрезать нельзя НИ ОДНОЙ записи.

Почему переснятая запись несёт ТОТ ЖЕ payload — бит в бит
---------------------------------------------------------
Пересъёмка не является наблюдением и не вправе выглядеть наблюдением (инв. #17: «не
измерено» обязано быть отличимо от «измерено»). Содержимое записи поэтому НЕ меняется
ни на байт: ``generated_at``/``as_of``/``recorded_at`` внутри payload остаются теми, что
были у наблюдения, и всякий читатель, судящий по ним, отвечает ровно то же, что отвечал
бы без пересъёмки. Замер этой нейтральности — не рассуждение: ``retention.view_answers``
сверяет ПОЛНЫЙ ответ обоих объявленных читающих видов этой ленты до и после прогона
писателя, и батарея требует побайтового равенства (``test_candidate_resnapshot.py``).

Пример, ради которого это важно: ``read._sherlock_block`` считает «решения за сегодня»
по ``payload["generated_at"]``, а не по ``at`` записи. Пересъёмка с ОБНОВЛЁННЫМ
``generated_at`` объявила бы вчерашние решения сегодняшними — то есть вылечила бы
усечение ценой вранья в ответе.

Чем тогда пересъёмка ОТЛИЧИМА от наблюдения
-------------------------------------------
КЛЮЧОМ записи, а не содержимым. Наблюдение кладёт ключ своего писателя
(``[kind, candidate_id, <отпечаток|digest|decision_id>]``), пересъёмка —
``[kind, candidate_id, "resnapshot", <момент>]``. Ключ входит в запись и в её хеш,
виден в ленте и в указателе ключей, и по нему перепись в любой момент отвечает, сколько
строк вида являются пересъёмками. Момент в ключе — он же третий исход: второй зов в ту
же секунду упирается в ключ, и это НЕ «уже свежо» (``key_collision``, как у
``history.compact``).

Чего писатель НЕ делает
-----------------------
* Не решает, можно ли резать. Разрешение даёт ЗАМЕР ответа (``retention.measure``), и
  писатель его не зовёт — иначе дневной прогон платил бы за полный прогон читающей
  модели ради чужого вопроса.
* Не чинит отсутствие описания. Кандидат, у которого вида нет вовсе (на 24.10 таких 21
  из 100 по ``evidence_bundle``/``admission_decision``), пересъёмкой не приобретает его:
  переснять нечего, и это НАЗВАННЫЙ исход (``absent``), а не тишина.
* Не трогает ``transition``: его форму вылечило уплотнение (ADR-795), а повтор его строк
  как раз НАКАПЛИВАЕТ причины — лекарство, делающее хуже то, что охраняет.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spa_core.research_factory import contract, registry
from spa_core.research_factory._common import iso, ledger_for
from spa_core.utils.hash_ledger import HashLedger

SCHEMA = "candidate-resnapshot/1"

#: Виды, свежайшая запись которых переснимается. Это НЕ свой список, а состав рецепта
#: ``"snapshot+evidence+compaction"`` из прибора цены (``newest_kinds``); вторая копия
#: состава разошлась бы с первой молча, и писатель начал бы строить рецепт, которого
#: никто не мерил. Четвёртая составляющая того же рецепта — строка уплотнения, и её
#: пишет ``history.compact``; здесь её нет намеренно.
RESNAPSHOT_KINDS: Tuple[str, ...] = ("candidate_snapshot", "evidence_bundle",
                                     "admission_decision")

#: Хвост ключа, по которому пересъёмка отличима от наблюдения.
MARK = "resnapshot"

#: Такт. Сутки — такт самого ``com.spa.research_factory``, который зовёт писателя, и он
#: же такт строки уплотнения (``history.COMPACTION_TACT_DAYS``): пересъёмка реже такта
#: усечения оставила бы пропущенный такт, то есть описание, уехавшее в архив вместе с
#: историей, которую оно должно было спасти.
TACT_DAYS = 1

OUTCOME_WRITTEN = "written"
OUTCOME_CURRENT = "already_current"
OUTCOME_ABSENT = "absent"
OUTCOME_COLLIDED = "key_collision"


def declared_kinds() -> Tuple[str, ...]:
    """Состав рецепта, который писатель ИСПОЛНЯЕТ, прочитанный у прибора цены.

    Расхождение :data:`RESNAPSHOT_KINDS` с ним — находка, а не мелочь: писатель,
    строящий другой рецепт, строит окно, которого никто не измерял. Сверку держит
    батарея; читать прибор на КАЖДОМ зове писателя незачем — он тянул бы
    ``monitoring`` в дневной прогон.
    """
    from spa_core.monitoring import ledger_resnapshot_price_census as price  # noqa: PLC0415
    for recipe in price.RECIPES:
        if recipe.compaction:
            return tuple(recipe.newest_kinds)
    return ()


# ── чтение ───────────────────────────────────────────────────────────────────────────


def _candidate_of(entry: dict, kind: str) -> Optional[str]:
    """``candidate_id`` записи — из КЛЮЧА, а не из payload.

    У трёх видов payload устроен по-разному (``candidate_snapshot`` держит кандидата
    во вложенном ``candidate``, двое других — полем ``candidate_id``), а ключ у всех
    трёх писателей — ``[kind, candidate_id, …]``. Читать одно место вместо трёх здесь
    не удобство: третий вид, добавленный в рецепт, иначе молча не нашёлся бы.
    """
    key = entry.get("key") or []
    if len(key) >= 2 and key[0] == kind and isinstance(key[1], str) and key[1]:
        return key[1]
    return None


def newest_rows(ledger: HashLedger,
                kinds: Sequence[str] = RESNAPSHOT_KINDS) -> Dict[Tuple[str, str], dict]:
    """``(вид, кандидат) -> свежайшая запись`` по порядку ленты.

    Порядок ленты, а не ``seq``: сцена, перестроенная из подмножества ленты,
    перенумерована с единицы (``retention``/``ledger_window_dependency_census.rechain``),
    поэтому ``seq`` не является личностью, переживающей усечение. Внутри одного файла
    оба порядка — одно и то же.
    """
    out: Dict[Tuple[str, str], dict] = {}
    wanted = set(kinds)
    for entry in ledger.read_all():
        kind = entry.get("kind")
        if kind not in wanted:
            continue
        cid = _candidate_of(entry, kind)
        if cid is None:
            continue
        out[(kind, cid)] = entry
    return out


def _is_due(entry: Optional[dict], now: datetime, tact_days: int) -> bool:
    """Пересъёмка нужна, когда свежайшей записи вида уже такт.

    Отметка берётся у ``at`` ЗАПИСИ, а не у payload: вопрос писателя — «сколько лет
    строке в ленте», а не «когда наблюдали». Неразборная отметка — не повод молчать:
    тогда переснять НУЖНО (иначе запись с битой датой жила бы вне такта вечно).
    """
    if entry is None:
        return False
    at = contract.parse_ts(entry.get("at"))
    if at is None:
        return True
    return (now - at) >= timedelta(days=tact_days)


def resnapshot_key(kind: str, candidate_id: str, at: str) -> List[str]:
    return [kind, candidate_id, MARK, at]


def is_resnapshot(entry: dict) -> bool:
    """Является ли запись ПЕРЕСЪЁМКОЙ — по ключу. Читает перепись, не писатель."""
    key = entry.get("key") or []
    return len(key) == 4 and key[2] == MARK


# ── запись ───────────────────────────────────────────────────────────────────────────


def resnapshot(data_dir: Path, *, now: Optional[datetime] = None,
               tact_days: int = TACT_DAYS,
               kinds: Sequence[str] = RESNAPSHOT_KINDS) -> dict:
    """Переснять свежайшую запись каждого вида у каждого кандидата, кому это нужно.

    Возвращает ЗАМЕР: кто записан, кто уже свеж, у кого вида нет вовсе, и у кого ключ
    столкнулся. «Никого не записали» и «писатель не смотрел» — разные ответы.
    """
    moment = now or datetime.now(timezone.utc)
    at = iso(moment)
    root = Path(data_dir)
    ledger = ledger_for(root)
    newest = newest_rows(ledger, kinds)
    candidates = registry.all_candidate_ids(ledger)

    written: List[dict] = []
    current: List[dict] = []
    absent: List[dict] = []
    collided: List[dict] = []
    for cid in candidates:
        for kind in kinds:
            entry = newest.get((kind, cid))
            if entry is None:
                absent.append({"candidate_id": cid, "kind": kind})
                continue
            if not _is_due(entry, moment, tact_days):
                current.append({"candidate_id": cid, "kind": kind})
                continue
            payload = entry.get("payload")
            if not isinstance(payload, dict):
                absent.append({"candidate_id": cid, "kind": kind,
                               "reason": "payload записи не является отображением"})
                continue
            _, created = ledger.append_idempotent(kind, resnapshot_key(kind, cid, at),
                                                  payload, at)
            (written if created else collided).append({"candidate_id": cid, "kind": kind})
    return {"schema": SCHEMA, "at": at, "tact_days": tact_days, "kinds": list(kinds),
            "candidates": len(candidates), OUTCOME_WRITTEN: written,
            OUTCOME_CURRENT: current, OUTCOME_ABSENT: absent, OUTCOME_COLLIDED: collided}


def due_report(data_dir: Path, *, now: Optional[datetime] = None,
               tact_days: int = TACT_DAYS,
               kinds: Sequence[str] = RESNAPSHOT_KINDS) -> dict:
    """Кому пересъёмка НУЖНА — тот же обход, но в ленту не пишет."""
    moment = now or datetime.now(timezone.utc)
    ledger = ledger_for(Path(data_dir))
    newest = newest_rows(ledger, kinds)
    due: List[dict] = []
    absent: List[dict] = []
    for cid in registry.all_candidate_ids(ledger):
        for kind in kinds:
            entry = newest.get((kind, cid))
            if entry is None:
                absent.append({"candidate_id": cid, "kind": kind})
            elif _is_due(entry, moment, tact_days):
                due.append({"candidate_id": cid, "kind": kind})
    return {"schema": SCHEMA, "dry_run": True, "at": iso(moment), "tact_days": tact_days,
            "kinds": list(kinds), "due": due, OUTCOME_ABSENT: absent}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=(
        "Ежесуточная пересъёмка свежайшего описания кандидата — три недостающих "
        "писателя рецепта усечения (ADR-798)."))
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="только показать, кому пересъёмка НУЖНА (в ленту не пишет)")
    args = parser.parse_args(argv)
    root = Path(args.data_dir)
    report = due_report(root) if args.dry_run else resnapshot(root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        if args.dry_run:
            print(f"пересъёмка описания ({root}): НУЖНА {len(report['due'])} · "
                  f"вида нет вовсе у {len(report[OUTCOME_ABSENT])}")
        else:
            print(f"пересъёмка описания ({root}): записано {len(report[OUTCOME_WRITTEN])} · "
                  f"уже свежих {len(report[OUTCOME_CURRENT])} · "
                  f"вида нет вовсе у {len(report[OUTCOME_ABSENT])} · "
                  f"столкновение ключа {len(report[OUTCOME_COLLIDED])}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
