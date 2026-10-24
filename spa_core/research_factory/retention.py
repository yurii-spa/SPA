"""spa_core/research_factory/retention.py — ОТРЕЗАНИЕ хвоста ленты как ПЕРЕНОС, и точка
отрезания как ЗАМЕР (ADR-797, заказ G795 п. 1).

Зачем этот модуль, и почему он почти всегда ОТКАЗЫВАЕТ
------------------------------------------------------

Лента ``data/research_factory/ledger.jsonl`` росла 3.907 МБ/сут (замер ADR-794) и к 23.10
весит 72.5 МБ. Пять решений подряд называли лекарством усечение по возрасту, и каждое
закрывалось замером: ADR-793 — безопасного окна НЕТ вовсе; ADR-794 — пересъёмка описания
окна не открывает, а остаток 3.72 % держится на НАКАПЛИВАЮЩИХ списках причин, которые
повтор только удлиняет; ADR-795 — завёл строку уплотнения ``candidate_history`` и измерил
на ней рецепт ``snapshot+evidence+compaction``: зависимость ответа от записей старше суток
**0.00 %**, безопасное окно **1 сут**, лента устаканится на 5.95 МБ.

Заказ G795 п. 1 просил **исполнить** это решение. Первое, что сделал исполняющий цикл, —
перемерил предпосылку, и она не подтвердилась:

* рецепт, у которого окно 1 сут, несёт **ЧЕТЫРЕ** составляющих — ежесуточную пересъёмку
  свежайших ``candidate_snapshot``, ``evidence_bundle``, ``admission_decision`` ПЛЮС строку
  уплотнения (``ledger_resnapshot_price_census.RECIPES``, поле ``newest_kinds`` рядом с
  ``synthesised_kinds``);
* построена из них **ОДНА** — строка уплотнения. Писателя, который переснимал бы описание
  кандидата каждые сутки, не существует: ``registry.upsert`` пишет новый снимок ТОЛЬКО при
  смене отпечатка;
* замер живой ленты 24.10 (24 305 записей, 100 кандидатов): у **39** кандидатов свежайший
  ``candidate_snapshot`` старше суток, у **31** — старше семи, и у них он ОДИН, со дня
  посева 04.10; ``evidence_bundle``/``admission_decision`` отсутствуют у **21** вовсе;
  строк ``candidate_history`` в живой ленте **НОЛЬ** — дневной писатель ADR-795 ещё не
  отработал ни разу.

Отсюда устройство модуля. Срок хранения — РЕШЕНИЕ (:data:`KEEP_DAYS`), но оно не является
разрешением резать: разрешение даёт ЗАМЕР — ответ объявленных читающих видов, снятый ДО и
ПОСЛЕ предполагаемого отрезания и сверенный ПОЛИСТНО. Прибор не спрашивает у себя, какие
виды записей читателю нужны (ровно это предположение и обрушило пять предыдущих решений);
он спрашивает у ОТВЕТА. Замер 24.10 на живой ленте: наибольшее безопасное отрезание —
**0 записей из 24 305**, и даже снятие ОДНОЙ самой старой строки меняет ответ.

Отрезание есть ПЕРЕНОС, а не удаление
-------------------------------------

Отрезанный префикс уезжает в ``research_factory/archive/ledger.<первая>-<последняя>.jsonl``
дословными байтами, и склейка архивов с горячим файлом даёт исходную ленту бит в бит.
Это не вежливость, а граница ADR-285: удаление данных — предмет №3, остающийся за
владельцем; перенос обратим и предметом не является. Цена, которую отрезание снимает, —
ВРЕМЯ РАЗБОРА горячего файла (ADR-785: ``parse_s`` есть время), а оно платится только за
горячий файл.

Что остаётся верным после переноса, и чем это держится
-----------------------------------------------------

* **цепь хешей** — ``hash_ledger.verify`` учится ОБЪЯВЛЕННОЙ точке усечения
  (``ledger.truncation.json``) и сверяет первую горячую запись со своим якорем; файл
  якорей (2.98 МБ против 72.5) не режется НИКОГДА и остаётся доказательством префикса;
* **обнаружение дублей ключа** — ``find`` после переноса не видел бы ключей архива и
  ``append_idempotent`` молча создал бы второй ряд с тем же ключом. Поэтому перенос пишет
  указатель ``ledger.truncation.keys.json``: сверка ключа → ``(архив, смещение, длина)``,
  и попадание читает ОДНУ строку архива по смещению, а не разбирает его целиком;
* **восстановление** — склейка ``archive/*.jsonl`` (в порядке имён, они несут ``seq``) с
  горячим файлом. Поле ``archive`` в объявлении называет ПОСЛЕДНИЙ перенос, а не все: полный
  перечень архивов живёт в указателе ключей и в самом каталоге, и это сказано здесь вслух,
  чтобы «одно имя» не читалось как «один архив»;
* **три исхода** (инв. #17): отрезание ИЗМЕРЕНО и возможно · ИЗМЕРЕНО и равно нулю
  (``nothing_older_than_window`` / ``measured_zero``) · НЕ ИЗМЕРЕНО (вид не вычислился,
  цепь порвана до начала работы) — и последнее никогда не выдаётся за «резать нечего».

# LLM_FORBIDDEN
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spa_core.research_factory import contract, history, registry
from spa_core.research_factory._common import iso, ledger_for
from spa_core.utils.hash_ledger import HashLedger

#: Лента, о которой этот модуль. Имя то же, под которым её знает прибор цены разбора.
LEDGER_ID = "research_factory"

#: СРОК ХРАНЕНИЯ горячего файла — РЕШЕНИЕ цикла #920, и вот его причина. Такт писателя
#: уплотнения (``history.COMPACTION_TACT_DAYS``) — сутки; окно, равное такту, не оставляет
#: ни одного пропущенного такта: строка уплотнения, не переписанная ОДИН раз, уезжает в
#: архив вместе с историей, которую должна была сохранить. Трое суток дают ДВА пропущенных
#: такта запаса и всё ещё держат горячий файл на порядок меньше нынешнего.
#:
#: Это потолок, а не разрешение: резать разрешает только :func:`measure`.
KEEP_DAYS = 3

#: Что прибор цены измерил безопасным ДЛЯ СВОЕГО РЕЦЕПТА (ADR-795). Здесь — не для
#: подстановки, а чтобы расхождение «1 сут по прибору против 0 записей по замеру ответа»
#: было видно в отчёте, а не исчезало между двумя документами.
MEASURED_FLOOR_DAYS = 1

#: Виды записей, свежесть которых прибор ДОКЛАДЫВАЕТ, когда отрезание оказалось небезопасным.
#: Это ДИАГНОСТИКА, а не гейт: гейт — ответ читающих видов. Состав взят из рецепта, который
#: измерил окно (``ledger_resnapshot_price_census.RECIPES``, ``snapshot+evidence+compaction``).
DIAGNOSED_KINDS: Tuple[str, ...] = ("candidate_snapshot", "evidence_bundle",
                                    "admission_decision", "admission_v2_report",
                                    history.KIND)

TRUNCATION_SCHEMA = "ledger-truncation/1"


class CutRefused(Exception):
    """Отрезание отказано: ответ читающего вида изменился бы, либо не измерен.

    Отчёт приложен к исключению НАМЕРЕННО: отказ без диагностики сообщает, что резать
    нельзя, и не сообщает ПОЧЕМУ, — а именно «почему» и есть то, из-за чего пять
    предыдущих решений называли лекарством не то.
    """

    def __init__(self, message: str, report: Optional[dict] = None) -> None:
        super().__init__(message)
        self.report = report or {}


# ── объявленные читающие виды ────────────────────────────────────────────────────────────────


def declared_views(ledger_id: str = LEDGER_ID) -> tuple:
    """Читающие виды ЭТОЙ ленты — из того же объявления, которым их знает прибор цены
    разбора (``ledger_parse_census.LEDGERS``). Своей копии перечня здесь нет намеренно:
    второй перечень видов разошёлся бы с первым молча, и гейт начал бы сверять ответ,
    которого никто не читает (класс «одно имя — один объект»)."""
    from spa_core.monitoring import ledger_parse_census as census
    return tuple(m for m in census.LEDGERS if m.ledger_id == ledger_id)


def view_answers(data_dir: Path, now: datetime,
                 ledger_id: str = LEDGER_ID) -> Tuple[Dict[str, str], List[dict]]:
    """``({вид: канонический ответ}, [не измеренные])``.

    Оба объявленных вида этой ленты ДЕТЕРМИНИРОВАНЫ при фиксированном ``now`` (замер 24.10:
    два прогона подряд дают байт в байт одно и то же), поэтому сверка идёт по ПОЛНОМУ ответу
    без единой проекции. Проекция здесь была бы дырой: поле, вынутое из сверки «как
    изменчивое», и есть поле, по которому отрезание прошло бы незамеченным.
    """
    from spa_core.monitoring import ledger_parse_census as census
    answers: Dict[str, str] = {}
    unmeasured: List[dict] = []
    members = declared_views(ledger_id)
    if not members:
        return {}, [{"view": ledger_id, "reason": "НЕ ИЗМЕРЕНО: у этой ленты не объявлено "
                                                  "ни одного читающего вида"}]
    for member in members:
        fn, reason = census.resolve_view(member)
        if fn is None:
            unmeasured.append({"view": member.id, "reason": reason})
            continue
        try:
            answer = member.invoke(fn, Path(data_dir), now) if member.invoke \
                else fn(Path(data_dir))
        except Exception as exc:                      # noqa: BLE001 — исход, а не глушение
            unmeasured.append({"view": member.id, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        answers[member.id] = canonical(answer)
    return answers, unmeasured


def canonical(value) -> str:
    """Канонический вид ответа — СВОЙ, а не ``json.dumps(sort_keys=True)``.

    Причина измерена, а не предположена: на УСЕЧЁННОЙ ленте ответ ``read.latest`` содержит
    отображение, у которого ключи ``str`` и ``None`` одновременно (кандидат, потерявший своё
    единственное описание, теряет и домен, по которому его группируют), и штатный
    сериализатор на таком словаре падает ``TypeError: '<' not supported between instances of
    'str' and 'NoneType'``. Падение сериализатора неотличимо от «ответ изменился», если не
    различать их НАМЕРЕННО: первое есть НЕ ИЗМЕРЕНО, второе — находка. Поэтому ключи
    приводятся к строке с сохранением вида (``None`` ≠ ``"None"``), и сверка остаётся
    сверкой ПОЛНОГО ответа без единой проекции.
    """
    if isinstance(value, dict):
        items = sorted((f"{type(k).__name__}:{k!r}", v) for k, v in value.items())
        return "{" + ",".join(f"{json.dumps(k)}:{canonical(v)}" for k, v in items) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical(v) for v in value) + "]"
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return json.dumps(f"{type(value).__name__}:{value!r}", ensure_ascii=False)


# ── диагностика: ПОЧЕМУ отрезание небезопасно ────────────────────────────────────────────────


def freshness_diagnosis(data_dir: Path, now: datetime, keep_days: int = KEEP_DAYS) -> dict:
    """Возраст СВЕЖАЙШЕЙ записи каждого диагностируемого вида у каждого кандидата.

    Отвечает на один вопрос: сколько кандидатов потеряли бы своё единственное описание,
    если резать по возрасту. Гейтом не является и вердикта не ставит.
    """
    ledger = ledger_for(Path(data_dir))
    rows = ledger.read_all()
    cutoff = now - timedelta(days=keep_days)
    cands = list(registry.all_candidate_ids(ledger))
    newest: Dict[str, Dict[str, dict]] = {cid: {} for cid in cands}
    for entry in rows:
        kind = entry.get("kind")
        if kind not in DIAGNOSED_KINDS:
            continue
        payload = entry.get("payload") or {}
        cid = ((payload.get("candidate") or {}).get("candidate_id")
               or payload.get("candidate_id"))
        if cid not in newest:
            continue
        prior = newest[cid].get(kind)
        if prior is None or entry.get("seq", 0) > prior.get("seq", 0):
            newest[cid][kind] = entry
    out: Dict[str, dict] = {}
    for kind in DIAGNOSED_KINDS:
        absent = [cid for cid in cands if kind not in newest[cid]]
        stale = []
        for cid in cands:
            entry = newest[cid].get(kind)
            if entry is None:
                continue
            stamp = contract.parse_ts(entry.get("at"))
            if stamp is None or stamp < cutoff:
                stale.append(cid)
        out[kind] = {"candidates": len(cands), "absent": len(absent),
                     "newest_older_than_window": len(stale),
                     "absent_ids": absent[:10], "stale_ids": stale[:10]}
    return {"keep_days": keep_days, "candidates": len(cands), "by_kind": out}


# ── предложение точки отрезания ──────────────────────────────────────────────────────────────


def propose(data_dir: Path, now: datetime, keep_days: int = KEEP_DAYS) -> dict:
    """Сколько ВЕДУЩИХ записей старше окна. Это ПРЕДЛОЖЕНИЕ, а не вердикт.

    Предложение намеренно не рассуждает о том, какие виды записей читателю нужны: ровно это
    рассуждение пять решений подряд оказывалось неверным. Оно отвечает на арифметический
    вопрос «что старше окна», а разрешение даёт :func:`measure`.
    """
    ledger = ledger_for(Path(data_dir))
    rows = ledger.read_all()
    if not rows:
        return {"rows": 0, "cut_rows": 0, "through_seq": 0, "reason": "ledger is empty"}
    cutoff = now - timedelta(days=keep_days)
    cut_rows = 0
    unparsed: List[int] = []
    for entry in rows:
        stamp = contract.parse_ts(entry.get("at"))
        if stamp is None:
            unparsed.append(entry.get("seq"))
            break
        if stamp >= cutoff:
            break
        cut_rows += 1
    through = rows[cut_rows - 1]["seq"] if cut_rows else 0
    return {"rows": len(rows), "cut_rows": cut_rows, "through_seq": through,
            "through_entry_hash": rows[cut_rows - 1]["entry_hash"] if cut_rows else None,
            "keep_days": keep_days, "cutoff": iso(cutoff),
            "unparsable_stamp_at_seq": unparsed,
            "reason": ("nothing_older_than_window" if not cut_rows else "proposed")}


# ── ЗАМЕР: разрешение резать ─────────────────────────────────────────────────────────────────


def measure(data_dir: Path, cut_rows: int, now: datetime,
            ledger_id: str = LEDGER_ID) -> dict:
    """Изменится ли ответ объявленных читающих видов, если снять ``cut_rows`` ведущих строк.

    Сцена — ОТДЕЛЬНЫЙ каталог: горячий файл там уже усечён, а живой ``data/`` не трогается
    ни на байт. ``verify`` на сцене опирается на объявление усечения, которое сцена несёт.
    """
    before, unmeasured_before = view_answers(Path(data_dir), now, ledger_id)
    if unmeasured_before:
        return {"safe": False, "measured": False, "reason": "НЕ ИЗМЕРЕНО до отрезания",
                "unmeasured": unmeasured_before}
    if cut_rows <= 0:
        return {"safe": False, "measured": True, "reason": "measured_zero: резать нечего",
                "cut_rows": 0, "differs": [], "unmeasured": []}
    scene = Path(tempfile.mkdtemp(prefix="spa_retention_scene_"))
    try:
        _stage_scene(Path(data_dir), scene, cut_rows)
        after, unmeasured_after = view_answers(scene / "data", now, ledger_id)
    finally:
        shutil.rmtree(scene, ignore_errors=True)
    if unmeasured_after:
        return {"safe": False, "measured": False, "cut_rows": cut_rows,
                "reason": "НЕ ИЗМЕРЕНО после отрезания", "unmeasured": unmeasured_after}
    differs = [vid for vid in sorted(before) if before.get(vid) != after.get(vid)]
    return {"safe": not differs, "measured": True, "cut_rows": cut_rows,
            "views": sorted(before), "differs": differs, "unmeasured": []}


def _stage_scene(data_dir: Path, scene: Path, cut_rows: int) -> Path:
    """Собрать сцену: тот же состав файлов, горячая лента усечена, объявление написано."""
    src = ledger_for(Path(data_dir))
    dst_root = scene / "data"
    (dst_root / src.subdir).mkdir(parents=True, exist_ok=True)
    (dst_root / src.anchors_subdir).mkdir(parents=True, exist_ok=True)
    for extra in sorted(src.root().glob("*.json")):
        shutil.copy2(extra, dst_root / src.subdir / extra.name)
    shutil.copy2(src.anchors_path(), dst_root / src.anchors_subdir / src.anchors_path().name)
    lines = src.ledger_path().read_text(encoding="utf-8").splitlines(keepends=True)
    hot = lines[cut_rows:]
    (dst_root / src.subdir / src.ledger_name).write_text("".join(hot), encoding="utf-8")
    prefix = [json.loads(line) for line in lines[:cut_rows]]
    _write_declaration(dst_root, src, prefix, archive_name="(scene — archive not staged)")
    return dst_root


def _write_declaration(data_root: Path, src: HashLedger, prefix: Sequence[dict],
                       archive_name: str) -> Path:
    led = HashLedger(data_root, src.subdir, src.anchors_subdir, src.ledger_name)
    doc = {"schema": TRUNCATION_SCHEMA,
           "through_seq": prefix[-1]["seq"],
           "through_entry_hash": prefix[-1]["entry_hash"],
           "through_at": prefix[-1]["at"],
           "rows_archived": len(prefix),
           "archive": archive_name}
    path = led.truncation_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    #: Через ту же дверь, что архив и горячий файл (инв. #5, атомарная запись), и ПОТОМУ
    #: ЖЕ наблюдаем порядок шагов переноса: утверждение «объявление пишется ПЕРВЫМ»
    #: проверяется тестом, который смотрит на последовательность записей, а не на текст.
    _atomic_bytes(path, (json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
    return path


# ── ОТРЕЗАНИЕ = перенос ──────────────────────────────────────────────────────────────────────


def cut(data_dir: Path, *, now: Optional[datetime] = None, keep_days: int = KEEP_DAYS,
        apply: bool = False, ledger_id: str = LEDGER_ID) -> dict:
    """Перенести в архив всё, что СТАРШЕ окна И доказуемо не меняет ответ ни одного вида.

    Без ``apply=True`` ничего не пишет и возвращает тот же отчёт — «что было бы».
    """
    moment = now or datetime.now(timezone.utc)
    root = Path(data_dir)
    led = ledger_for(root)
    verdict = led.verify()
    if not verdict["ok"]:
        raise CutRefused(f"цепь ленты порвана до начала работы: seq={verdict['break_at']} "
                         f"reason={verdict.get('reason')} — НЕ ИЗМЕРЕНО, а не «резать нечего»")
    plan = propose(root, moment, keep_days)
    report = {"schema": "ledger-retention/1", "at": iso(moment), "keep_days": keep_days,
              "measured_floor_days": MEASURED_FLOOR_DAYS, "ledger_id": ledger_id,
              "bytes_before": led.ledger_path().stat().st_size, "propose": plan,
              "applied": False}
    if plan["cut_rows"] <= 0:
        report["measurement"] = {"safe": False, "measured": True,
                                 "reason": "nothing_older_than_window"}
        return report
    measurement = measure(root, plan["cut_rows"], moment, ledger_id)
    report["measurement"] = measurement
    if not measurement["safe"]:
        report["diagnosis"] = freshness_diagnosis(root, moment, keep_days)
        if not measurement.get("measured"):
            raise CutRefused("ОТРЕЗАНИЕ НЕ ИЗМЕРЕНО: " + json.dumps(
                measurement.get("unmeasured"), ensure_ascii=False), report)
        raise CutRefused(
            f"ответ читающих видов ИЗМЕНИЛСЯ бы: {measurement['differs']} — отрезание "
            f"{plan['cut_rows']} записей отказано", report)
    if not apply:
        return report
    report.update(_apply(led, plan, moment))
    after, unmeasured = view_answers(root, moment, ledger_id)
    report["acceptance"] = {"views_identical_after_apply": not unmeasured,
                            "unmeasured": unmeasured,
                            "verify": led.verify(),
                            "bytes_after": led.ledger_path().stat().st_size}
    return report


def _apply(led: HashLedger, plan: dict, moment: datetime) -> dict:
    """Перенос. Порядок шагов выбран так, что КАЖДОЕ промежуточное состояние проверяемо.

    Объявление пишется ПЕРВЫМ и терпимо: пока горячий файл ещё полон,
    ``hash_ledger.verify`` читает цепь от начала и докладывает объявление как `pending`.
    Смерть процесса на любом шаге оставляет ленту, которую verify называет ИСПРАВНОЙ, —
    чего не дал бы обратный порядок (усечённый файл без объявления есть молчаливое
    усечение, и это обязано ломать verify).
    """
    cut_rows = plan["cut_rows"]
    with led.file_lock(timeout_s=30.0):
        led.invalidate_cache()
        lines = led.ledger_path().read_text(encoding="utf-8").splitlines(keepends=True)
        prefix = [json.loads(line) for line in lines[:cut_rows]]
        if prefix[-1]["seq"] != plan["through_seq"]:
            raise CutRefused("лента изменилась между замером и переносом: "
                             f"ожидали seq={plan['through_seq']}, нашли {prefix[-1]['seq']}")
        archive_dir = led.root() / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        name = f"ledger.{prefix[0]['seq']:08d}-{prefix[-1]['seq']:08d}.jsonl"
        archive = archive_dir / name
        if archive.exists():
            raise CutRefused(f"архив {name} уже существует — перенос не затирает архивы")
        _write_declaration(led.data_dir, led, prefix, archive_name=f"archive/{name}")
        payload = "".join(lines[:cut_rows]).encode("utf-8")
        _atomic_bytes(archive, payload)
        _write_key_index(led, prefix, lines[:cut_rows], f"archive/{name}")
        _atomic_bytes(led.ledger_path(), "".join(lines[cut_rows:]).encode("utf-8"))
        _write_declaration(led.data_dir, led, prefix, archive_name=f"archive/{name}")
        led.invalidate_cache()
    return {"applied": True, "archive": f"archive/{name}", "rows_archived": cut_rows,
            "through_seq": plan["through_seq"]}


def _atomic_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _write_key_index(led: HashLedger, prefix: Sequence[dict], raw: Sequence[str],
                     archive_rel: str) -> Path:
    """Указатель ключей архива: сверка ключа → ``[архив, смещение, длина]``.

    Без него ``HashLedger.find`` после переноса не увидел бы ключей архива, и
    ``append_idempotent`` молча создал бы ВТОРОЙ ряд с тем же ключом — тихая порча
    контракта идемпотентности, которую не заметил бы ни один сторож.
    """
    path = led.truncation_keys_path()
    existing = {}
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8")).get("keys") or {}
    offset = 0
    for entry, line in zip(prefix, raw):
        blob = line.encode("utf-8")
        digest = HashLedger.key_digest(entry["kind"], entry["key"])
        existing[digest] = [archive_rel, offset, len(blob)]
        offset += len(blob)
    doc = {"schema": "ledger-truncation-keys/1", "keys": existing}
    _atomic_bytes(path, (json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
    return path


def largest_safe_cut(data_dir: Path, now: datetime, ledger_id: str = LEDGER_ID) -> dict:
    """Наибольшее отрезание, которое ЗАМЕР называет безопасным. Диагностический режим.

    Двоичный поиск по числу ведущих строк: ``lo`` всегда измерен безопасным, ``hi`` —
    небезопасным либо не измеренным. Оба конца названы в отчёте, поэтому «0 безопасно,
    1 уже нет» читается как ЗАМЕР, а не как отказ прибора работать.
    """
    ledger = ledger_for(Path(data_dir))
    total = len(ledger.read_all())
    lo, hi, probes = 0, total, []
    while hi - lo > 1:
        mid = (lo + hi) // 2
        verdict = measure(Path(data_dir), mid, now, ledger_id)
        probes.append({"cut_rows": mid, "safe": verdict["safe"],
                       "measured": verdict["measured"],
                       "differs": verdict.get("differs"),
                       "unmeasured": verdict.get("unmeasured")})
        if verdict["safe"]:
            lo = mid
        else:
            hi = mid
    return {"rows": total, "largest_safe_cut_rows": lo, "first_unsafe_cut_rows": hi,
            "probes": probes}


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=(
        "Срок хранения ленты research_factory: перенос префикса в архив, если ЗАМЕР "
        "ответа читающих видов разрешает (ADR-797)."))
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--keep-days", type=int, default=KEEP_DAYS)
    parser.add_argument("--apply", action="store_true", help="перенести (иначе только замер)")
    parser.add_argument("--diagnose", action="store_true",
                        help="печатать свежесть диагностируемых видов, не трогая ленту")
    parser.add_argument("--bisect", action="store_true",
                        help="искать НАИБОЛЬШЕЕ безопасное отрезание (замер, не действие)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.data_dir)
    now = datetime.now(timezone.utc)
    if args.diagnose:
        report = freshness_diagnosis(root, now, args.keep_days)
        code = 0
    elif args.bisect:
        report = largest_safe_cut(root, now)
        code = 0 if report["largest_safe_cut_rows"] else 3
    else:
        try:
            report = cut(root, now=now, keep_days=args.keep_days, apply=args.apply)
            code = 0 if report.get("applied") or report["measurement"].get("safe") else 3
        except CutRefused as exc:
            report = dict(exc.report)
            report["refused"] = str(exc)
            code = 4
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, default=str))
    else:
        _print_human(report, args)
    return code


def _print_human(report: dict, args) -> None:
    if "refused" in report:
        print(f"ОТКАЗ: {report['refused']}")
        diagnosis = report.get("diagnosis")
        if diagnosis:
            print(f"  ПОЧЕМУ (окно {diagnosis['keep_days']} сут, кандидатов "
                  f"{diagnosis['candidates']}):")
            for kind, row in diagnosis["by_kind"].items():
                print(f"    {kind:24s} отсутствует у {row['absent']:3d} · свежайшая старше "
                      f"окна у {row['newest_older_than_window']:3d}")
        return
    if "largest_safe_cut_rows" in report:
        print(f"НАИБОЛЬШЕЕ безопасное отрезание: {report['largest_safe_cut_rows']} из "
              f"{report['rows']} записей (первое небезопасное — "
              f"{report['first_unsafe_cut_rows']}); проб {len(report['probes'])}")
        return
    if args.diagnose:
        print(f"свежесть при окне {report['keep_days']} сут "
              f"(кандидатов {report['candidates']}):")
        for kind, row in report["by_kind"].items():
            print(f"  {kind:24s} отсутствует у {row['absent']:3d} · свежайшая старше окна "
                  f"у {row['newest_older_than_window']:3d}")
        return
    plan = report["propose"]
    print(f"срок хранения {report['keep_days']} сут · записей {plan['rows']} · "
          f"старше окна {plan['cut_rows']} · горячий файл {report['bytes_before']:,} Б")
    m = report["measurement"]
    if m.get("safe"):
        print(f"  ЗАМЕР: безопасно — ответ всех видов {m['views']} полистно тот же")
        if report.get("applied"):
            print(f"  ПЕРЕНЕСЕНО {report['rows_archived']} записей → {report['archive']}")
    else:
        print(f"  ЗАМЕР: {m.get('reason') or 'ответ изменился: ' + str(m.get('differs'))}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
