#!/usr/bin/env python3
"""Кто окажется ЧИТАТЕЛЕМ квитанции read-only проверки захвата — заказ **G88 п. 1** (ADR-498).

Заказ поставлен 28.09 и перевыставлялся двадцатью одним заказом (G89…G109) дословно:

    **Квитанция у read-only проверки.** ``check`` следа не оставляет, и из-за этого
    неизмеримы ОБА вопроса: «спрашивали ли сторожа» и «было ли столкновение».
    Спросить надо не «дописать ли лог», а **у кого квитанция окажется ЧИТАТЕЛЕМ** —
    сегодня вердикт ``check`` не читает никто, кроме человека в терминале. Три исхода
    обязательны; гейт «нельзя взять занятое» до этого не заводить.

Прибор отвечает на вопрос заказа и **поправляет его посылку**: читатель вердикта
существует, и это шаг 0a-ГОЛОД. Разница между «читать вердикт» и «читать квитанцию»
и есть ответ, потому что читатель вердикта его **ПЕРЕСЧИТЫВАЕТ**, а пересчётом нельзя
узнать, что сторожа СПРАШИВАЛИ: пересчёт даёт ответ, а не факт вопроса.

## Четыре замера, и ни один не заменяет другой

===== ====================================== =========================================
ось   вопрос                                 чем меряется
===== ====================================== =========================================
A     оставляет ли ``check`` след?           ОДНОРАЗОВАЯ сцена: слепок каталога до и
                                             после настоящего вызова двери (sha256
                                             каждого файла), вердикт обязан быть
                                             произведён — иначе «следа нет» верно
                                             потому, что дверь не открывали
B     кто читает ВЕРДИКТ?                    форма ПОТРЕБЛЕНИЯ у тех, кто сторожа
                                             ГРУЗИТ (перечень загрузивших берётся у
                                             соседа — одно правило, одна копия)
C     есть ли у квитанции ЧИТАТЕЛЬ?          ДИФФЕРЕНЦИАЛЬНО: один и тот же читатель
                                             на двух наборах записей, отличающихся
                                             ровно одной квитанцией; поле отчёта
                                             изменилось ⇒ читатель доказан ИСХОДОМ
D     что стоит наивный канал?               ДИФФЕРЕНЦИАЛЬНО: квитанция, вписанная в
                                             общий журнал единственным разрешённым
                                             видом записи, переворачивает вердикт
                                             ``free`` → ``claimed`` — то есть ВОПРОС
                                             становится ЗАХВАТОМ
===== ====================================== =========================================

Ось B без оси C назвала бы читателя вердикта и промолчала про квитанцию — ровно та
подмена, на которой заказ и стоял. Ось C без оси D предложила бы «дописать лог» —
то, от чего заказ предостерегал дословно. Ось A нужна обеим: без неё «квитанции нет»
есть догадка о коде, а не замер.

## Третий исход обязателен (инв. #17), и здесь он у каждой оси свой

* ось A — ``unmeasured``, если сцена не собралась, дверь не открылась или вердикт не
  произведён. «Следа нет» при неоткрытой двери — самое успокоительное из прочтений;
* ось B — ``unmeasured``, если файл не разобран (``SyntaxError``) или перечень
  загрузивших не измерен у соседа. Отдельно и ВСЛУХ: форма потребления — не
  исполнение. Прибор не утверждает, что ветка с вердиктом когда-либо исполнялась;
* ось C — ``unmeasured``, если читатель не загрузился: «поле не изменилось» у
  незагруженного читателя неотличимо от «читателя нет»;
* ось D — ``unmeasured``, если базовый вердикт не ``free``: на занятой карточке
  переворот нечем увидеть.

## Одностороннее названо заранее

* **«Читает вердикт» измеряется ФОРМОЙ, а не исполнением.** Это та же граница, на
  которой остановился сосед (``duplicate_subject_census.measure_guard_wiring``:
  «чего этот замер НЕ утверждает — что загрузивший ЧИТАЕТ ВЕРДИКТ»). Прибор идёт
  на один шаг дальше соседа и там же честно останавливается.
* **Население оси B — только те, кто сторожа ГРУЗИТ.** Упоминание в прозе читателем
  не становится, и перечень загрузивших прибор НЕ пересчитывает своим кодом: второй
  экземпляр мерки разошёлся бы с первым молча (урок ADR-220).
* **Ось C доказывает ЧИТАТЕЛЯ, а не пользу.** Поле читателя изменилось — значит
  квитанция до него доходит; стало ли от этого лучше решение, прибор не измеряет.
* **Ось D говорит про ОДИН канал — общий журнал.** Что наивный канал вредит, не есть
  утверждение, что вредит любой; про отдельный канал прибор молчит.
* **Личность процесса в сцене — не литерал.** Номер берётся живым по построению
  (``os.getpid()``), а вердикт оси D от его живости не зависит: свежий сильный захват
  блокирует независимо от ``ps`` (``.claude/rules/deployment.md``, личность процесса).

## Вердикт

* ``RECEIPT_READER_WITHOUT_WRITER`` — у квитанции ЕСТЬ читатель, а писателя нет
  (``check`` следа не оставляет). Код возврата 1: это находка, а не норма;
* ``RECEIPT_WITHOUT_READER`` — писателя нет И читателя нет. Код 1: заводить канал
  рано, сначала читатель;
* ``RECEIPT_WIRED`` — след есть и читатель есть. Код 0;
* ``UNMEASURED`` — код 2, перебивает всё.

Гейт «нельзя взять занятое» прибор НЕ заводит и не предлагает: причина названа замером
в п. 4 решения ADR-498 (на 12 375 парах живость держателя неизмерима), а не вкусом.

    python3 -m spa_core.monitoring.claim_guard_receipt_readers
    python3 -m spa_core.monitoring.claim_guard_receipt_readers --json --save
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

if __package__ in (None, ""):  # pragma: no cover — прямой запуск файла
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed

ARTIFACT_NAME = "claim_guard_receipt_readers.json"
ORDER = "G88 п. 1 (ADR-498) — у кого квитанция read-only проверки окажется ЧИТАТЕЛЕМ"

STATUS_READER_WITHOUT_WRITER = "RECEIPT_READER_WITHOUT_WRITER"
STATUS_WITHOUT_READER = "RECEIPT_WITHOUT_READER"
STATUS_WIRED = "RECEIPT_WIRED"
STATUS_UNMEASURED = "UNMEASURED"

#: Словарь вердиктов сторожа захвата. Перечень ЗАКРЫТ и взят из докстринга
#: `scripts/check_card_claim.py`: `free` · `claimed` · `stale` · `unchecked`.
#: Закрытость существенна — «похоже на вердикт» измерением не является.
VERDICTS = ("free", "claimed", "stale", "unchecked")

#: Имена сторожа, чей ВОЗВРАТ несёт вердикт. Тоже закрыто: `gather`/`build_report`
#: отдают отчёт, `exit_code` — число, выведенное из вердикта, `main` — то же число
#: через CLI. Прочие имена сторожа (`read_card`, `_CLAIM_KEYS`) вердикта не несут.
VERDICT_PRODUCERS = ("gather", "build_report", "exit_code", "main")

#: Ключ, под которым вердикт лежит в отчёте сторожа.
VERDICT_KEY = "verdict"

#: Классы оси B.
READER_VERDICT = "verdict_consumed"
READER_CONSTANT = "constant_only"
READER_CALL_ONLY = "invokes_without_reading"
READER_UNMEASURED = "unmeasured"

_SANDBOX_CARD = "inbox-proba-kvitantsii-storozha-zahvata"


# ─────────────────────── ось A: оставляет ли `check` след ───────────────────────

def _load_guard(repo_root: Path):
    """Сторож захвата, загруженный ПО ПУТИ (как его грузит шаг 0a-ГОЛОД)."""
    path = repo_root / "scripts" / "check_card_claim.py"
    if not path.is_file():
        raise FileNotFoundError(f"сторожа захвата нет по пути {path}")
    spec = importlib.util.spec_from_file_location("_ccc_for_receipt_readers", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"не собран спек модуля для {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest_tree(root: Path) -> Dict[str, str]:
    """sha256 каждого файла сцены. Ключ — путь относительно сцены."""
    out: Dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        out[path.relative_to(root).as_posix()] = hashlib.sha256(
            path.read_bytes()).hexdigest()
    return out


def live_other_anchor(*, ps=None, pid: Optional[int] = None) -> Dict[str, Any]:
    """Личность ЧУЖОЙ, но ЖИВОЙ ПО ПОСТРОЕНИЮ сессии для сцены оси D.

    Порядок предпочтения из ``.claude/rules/deployment.md`` (личность процесса),
    п. 2: номер с ИЗВЕСТНОЙ живостью. ``os.getppid()`` жив на любой машине всегда и
    при этом не является моим собственным якорём, то есть сторож не спутает сцену с
    самозахватом. Отметка старта снимается **у той же двери**, которой потом ответит
    проверяемый код (``ps -p <pid> -o lstart=``); не снялась ⇒ третий исход
    ``measured=False`` и ГРОМКИЙ отказ, а не «кажется, подойдёт».
    """
    import subprocess  # локально: модуль прибора остаётся читателем, не исполнителем
    pid = pid if pid is not None else os.getppid()
    runner = ps or (lambda argv: subprocess.run(argv, capture_output=True, text=True,
                                                timeout=20))
    try:
        done = runner(["ps", "-p", str(pid), "-o", "lstart="])
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "pid": pid, "start": None,
                "reason": f"`ps` не отработал: {type(exc).__name__}: {exc}"}
    start = (getattr(done, "stdout", "") or "").strip()
    if getattr(done, "returncode", 1) != 0 or not start:
        return {"measured": False, "pid": pid, "start": None,
                "reason": f"`ps -p {pid}` не назвал отметку старта — живость номера "
                          "НЕ ИЗМЕРЕНА, и судить о сцене нечем"}
    return {"measured": True, "pid": pid, "start": start, "reason": None}


#: Формат отметки времени ЕДИНСТВЕННОГО писателя журнала
#: (``log_session_change.record``): секундная точность, без микросекунд. Литерал
#: здесь — не вкус: сторож разбирает ровно эту форму, и сцена, написавшая
#: микросекунды, получила бы «метка времени не разобрана» — то есть прибор
#: измерил бы СВОЮ сцену, а не дверь. Поэтому сцены, идущие ЧЕРЕЗ сторожа, пишет
#: сам писатель (:func:`_write_sandbox`), и формат не может разойтись с ним вовсе.
_WRITER_STAMP = "%Y-%m-%dT%H:%M:%SZ"


def _write_sandbox(root: Path, subject: str, *, announcer,
                   receipt_anchor: Optional[Dict[str, Any]] = None,
                   receipt_state: str = "claim",
                   receipt_log: Optional[Path] = None) -> Tuple[Path, Path]:
    """Одноразовая сцена: карточка + журнал, НАПИСАННЫЙ НАСТОЯЩИМ ПИСАТЕЛЕМ.

    Журнал не собирается строками: его пишет ``log_session_change.record`` — тот самый
    единственный писатель, которого потом читает сторож. Так форма записи не может
    разойтись со сценой ни по одному полю, и прибор остаётся замером двери, а не
    замером собственного представления о ней.

    ``receipt_anchor`` задан ⇒ в журнал добавляется КВИТАНЦИЯ, и добавляется она в
    единственном виде, который писатель пропускает: состояний у записи ровно два
    (``claim`` / ``done``), поэтому квитанция неизбежно принимает форму ВЗЯТИЯ. Это и
    есть цена наивного канала, которую меряет ось D.

    Свежесть записи здесь — ПО ПОСТРОЕНИЮ (её только что написали), а не литеральная
    дата: тот же приём, что ``os.getpid()`` у личности процесса.

    ``receipt_state`` и ``receipt_log`` добавлены заказом **G110 п. 1** (ADR-684) и
    УМОЛЧАНИЕМ сохраняют поведение оси D байт в байт. Они существуют потому, что
    заказ спрашивает цену ДВУХ кандидатов канала, а не одного: третье состояние
    записи (``receipt_state="asked"``) и второй файл (``receipt_log=<путь>``). Копию
    этой сцены заводить было нельзя — второй экземпляр мерки расходится с первым
    молча (ADR-220), и расхождение пришлось бы на форму записи, то есть ровно на то,
    что сцена и обязана воспроизводить точно.

    Про ``receipt_state`` важно, что валидации у писателя НЕТ: ``card_state``
    записывается как пришёл (``log_session_change.record``), а ограничение
    ``{claim,done}`` живёт только в разборе аргументов CLI. Поэтому «третье состояние»
    здесь не выдумано сценой — оно ИЗМЕРИМО настоящим вызовом настоящего писателя.
    """
    tracker = root / "tracker"
    tracker.mkdir(parents=True, exist_ok=True)
    (tracker / f"{subject}.md").write_text(
        "---\ntrackerStatus:\n  type: inbox\n"
        "title: \"проба квитанции\"\nstatus: new\n---\n\nсцена прибора.\n",
        encoding="utf-8")
    log = root / "session_changes.jsonl"
    log.touch()
    announcer.record("сцена пробы: посторонняя запись без предмета",
                     [str(root / "scene.py")], "сцена", log=str(log))
    if receipt_anchor is not None:
        announcer.record(
            f"[check_card_claim] проверка захвата карточки {subject} — вердикт free",
            [], "квитанция read-only проверки", card=subject,
            card_state=receipt_state,
            log=str(receipt_log or log), session=f"pid{receipt_anchor['pid']}",
            process=({"session_pid": receipt_anchor["pid"],
                      "session_pid_start": receipt_anchor["start"]},
                     "личность чужой живой сессии, измеренная у двери `ps`"))
    return tracker, log


def _ask_guard(guard, tracker: Path, log: Path, subject: str) -> Dict[str, Any]:
    """Настоящий вызов двери ``check`` через CLI сторожа. → разобранный отчёт."""
    buf, err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        code = guard.main(["--tracker-dir", str(tracker), "--log", str(log), "--json",
                           "check", subject])
    return {"code": int(code), "report": json.loads(buf.getvalue())}


def measure_trace(repo_root: Path, *, guard_loader=None) -> Dict[str, Any]:
    """Ось A. Оставляет ли read-only проверка след — замер ИСХОДОМ, не чтением кода.

    Сцена одноразовая (``mkdtemp``), живое дерево не трогается ни на байт. Слепок
    берётся до и после настоящего вызова ``check``; «следа нет» объявляется только
    при ПРОИЗВЕДЁННОМ вердикте — иначе утверждение относилось бы к неоткрытой двери.

    **Часов этот замер не принимает намеренно.** Журнал сцены пишет настоящий
    писатель, то есть отметка берётся у реальных часов и запись свежа ПО
    ПОСТРОЕНИЮ. Параметр ``now=`` здесь был бы распиской без инъекции — ровно тот
    класс, против которого написан ADR-479 (``_injected_clock``): записка не есть
    инъекция. Вердикт сцены от календаря не зависит: карточка свободна при любой дате.
    """
    out: Dict[str, Any] = {"measured": False, "reason": None, "outcome": None,
                           "verdict": None, "exit_code": None,
                           "files_before": None, "files_changed": [], "files_added": []}
    scene = Path(tempfile.mkdtemp(prefix="spa_receipt_probe_"))
    try:
        guard = (guard_loader or _load_guard)(repo_root)
        tracker, log = _write_sandbox(scene, _SANDBOX_CARD,
                                      announcer=guard.load_announcer())
        before = _digest_tree(scene)
        answer = _ask_guard(guard, tracker, log, _SANDBOX_CARD)
        after = _digest_tree(scene)
    except Exception as exc:  # noqa: BLE001 — сцена могла не собраться как угодно
        out["reason"] = f"сцена пробы не отработала: {type(exc).__name__}: {exc}"
        return out
    finally:
        shutil.rmtree(scene, ignore_errors=True)

    verdict = observed(answer["report"], VERDICT_KEY, kind=str)
    if verdict is None:
        out["reason"] = "вердикт не произведён — о неоткрытой двери прибор не судит"
        return out
    out["verdict"] = verdict
    out["exit_code"] = answer["code"]
    out["files_before"] = len(before)
    out["files_added"] = sorted(set(after) - set(before))
    out["files_changed"] = sorted(k for k in set(after) & set(before) if after[k] != before[k])
    out["measured"] = True
    out["outcome"] = ("no_trace" if not out["files_added"] and not out["files_changed"]
                      else "trace_written")
    return out


# ─────────────────────── ось B: кто читает ВЕРДИКТ ───────────────────────

def _verdict_vocabularies(tree: ast.AST) -> set:
    """Имена модуля, чьё значение — набор вердиктов (``CLAIM_ABSENT = ("free", "stale")``).

    Без этого шага читатель, сравнивающий вердикт со ИМЕНЕМ набора, а не с литералом,
    был бы объявлен нечитающим — а это ровно форма шага 0a-ГОЛОД.
    """
    names: set = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if not isinstance(value, (ast.Tuple, ast.List, ast.Set)):
            continue
        items = [e.value for e in value.elts
                 if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if not items or len(items) != len(value.elts):
            continue
        if not set(items).issubset(set(VERDICTS)):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


#: Вызовы, чей возврат ЕСТЬ загруженный модуль сторожа. Перечень ЗАКРЫТ: имя,
#: вычисленное в рантайме, не гадается.
_MODULE_PRODUCING_CALLS = frozenset({"module_from_spec", "import_module", "load_module"})

#: Имя модуля сторожа — так его называют и `import`, и `spec_from_file_location`.
_GUARD_MODULE = "check_card_claim"


def _guard_bindings(tree: ast.AST) -> Tuple[set, set]:
    """Имена, за которыми в этом файле стоит сторож. → (модульные имена, прямые имена).

    **Зачем именно так.** Первая редакция считала вызовом сторожа ЛЮБОЙ вызов функции
    с подходящим именем — и собственный ``main()`` файла сошёл за чтение вердикта
    сторожа: ``check_tracker_drift``, который берёт у сторожа ровно одну константу,
    был объявлен «вызывает, но не читает». Тот же класс, на котором сосед уже
    спотыкался (``lines.append("… check_card_claim …")`` сходило за проводку, ADR-498),
    только с другой стороны: не литерал за вызов, а чужое имя за свой вызов.
    """
    module_names: set = {_GUARD_MODULE}
    direct_names: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == _GUARD_MODULE:
            direct_names.update(a.asname or a.name for a in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _GUARD_MODULE:
                    module_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            callee = node.value.func
            name = (callee.attr if isinstance(callee, ast.Attribute)
                    else callee.id if isinstance(callee, ast.Name) else "")
            if name not in _MODULE_PRODUCING_CALLS:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    module_names.add(target.id)
    return module_names, direct_names


def _classify_reader(text: str) -> Tuple[str, Dict[str, Any]]:
    """Класс одного загрузившего по ФОРМЕ потребления вердикта. → (класс, детали)."""
    detail: Dict[str, Any] = {"producers_called": [], "verdict_key_read": False,
                              "compared_against": [], "vocabularies": []}
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return READER_UNMEASURED, {"reason": f"файл не разобран: {exc.__class__.__name__}"}

    vocab = _verdict_vocabularies(tree)
    detail["vocabularies"] = sorted(vocab)
    module_names, direct_names = _guard_bindings(tree)
    detail["guard_bindings"] = sorted(module_names | direct_names)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = node.func
            # Вызов СТОРОЖА, а не одноимённой своей функции: либо атрибут у имени,
            # за которым стоит загруженный модуль, либо имя, внесённое `from … import`.
            if isinstance(callee, ast.Attribute) and callee.attr in VERDICT_PRODUCERS \
                    and isinstance(callee.value, ast.Name) and callee.value.id in module_names:
                detail["producers_called"].append(f"{callee.value.id}.{callee.attr}")
            elif isinstance(callee, ast.Name) and callee.id in direct_names \
                    and callee.id in VERDICT_PRODUCERS:
                detail["producers_called"].append(callee.id)
        elif isinstance(node, ast.Subscript):
            index = node.slice
            if isinstance(index, ast.Constant) and index.value == VERDICT_KEY:
                detail["verdict_key_read"] = True
        elif isinstance(node, ast.Compare):
            for side in [node.left, *node.comparators]:
                if isinstance(side, ast.Constant) and side.value in VERDICTS:
                    detail["compared_against"].append(str(side.value))
                elif isinstance(side, ast.Name) and side.id in vocab:
                    detail["compared_against"].append(side.id)
    detail["producers_called"] = sorted(set(detail["producers_called"]))
    detail["compared_against"] = sorted(set(detail["compared_against"]))

    if detail["verdict_key_read"] and detail["compared_against"]:
        return READER_VERDICT, detail
    if detail["producers_called"]:
        return READER_CALL_ONLY, detail
    return READER_CONSTANT, detail


def measure_verdict_readers(repo_root: Path, *, wiring=None) -> Dict[str, Any]:
    """Ось B. Кто ЧИТАЕТ вердикт среди тех, кто сторожа ГРУЗИТ.

    Перечень загрузивших берётся у соседа (``duplicate_subject_census``), а не
    пересчитывается: второй экземпляр одной мерки расходится с первым молча
    (ADR-220, проект платил за это трижды).
    """
    out: Dict[str, Any] = {"measured": False, "reason": None, "by_class": {},
                           "readers": [], "loaders_measured": None, "doors": []}
    if wiring is None:
        try:
            from spa_core.monitoring.duplicate_subject_census import measure_guard_wiring
            wiring = measure_guard_wiring(repo_root)
        except Exception as exc:  # noqa: BLE001
            out["reason"] = f"перечень загрузивших не получен: {type(exc).__name__}: {exc}"
            return out
    if not wiring.get("measured"):
        out["reason"] = f"перечень загрузивших НЕ ИЗМЕРЕН у соседа: {wiring.get('reason')}"
        return out

    loaders = list(wiring.get("loads") or [])
    out["loaders_measured"] = len(loaders)
    if not loaders:
        # Ноль загрузивших — не «читателей нет», а «нечего классифицировать»:
        # сосед уже измерил, что их двое, и ноль здесь означал бы поломку чтения.
        out["reason"] = "ни одного загрузившего сторожа — классифицировать нечего"
        return out

    counts: Dict[str, int] = {READER_VERDICT: 0, READER_CONSTANT: 0,
                             READER_CALL_ONLY: 0, READER_UNMEASURED: 0}
    doors: List[Dict[str, Any]] = []
    for rel in loaders:
        path = repo_root / rel
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            counts[READER_UNMEASURED] += 1
            doors.append({"door": rel, "class": READER_UNMEASURED,
                          "detail": {"reason": f"не прочитан: {type(exc).__name__}"}})
            continue
        klass, detail = _classify_reader(text)
        counts[klass] += 1
        doors.append({"door": rel, "class": klass, "detail": detail})
    out["by_class"] = counts
    out["doors"] = doors
    out["readers"] = [d["door"] for d in doors if d["class"] == READER_VERDICT]
    out["measured"] = True
    # Вслух: форма потребления — не исполнение. Прибор не утверждает, что ветка
    # с вердиктом когда-либо исполнялась; он утверждает, что она написана.
    out["form_not_execution"] = ("класс измерен по ФОРМЕ потребления; исполнялась ли "
                                 "ветка с вердиктом — прибор не докладывает")
    return out


# ─────────────── ось C: есть ли у квитанции читатель (дифференциально) ───────────────

def measure_receipt_reader(*, now: Optional[datetime] = None,
                           reader=None, pid: Optional[int] = None) -> Dict[str, Any]:
    """Ось C. Доказательство ИСХОДОМ: меняет ли квитанция отчёт названного читателя.

    Кандидат один и назван: ось B переписи дублей
    (``duplicate_subject_census.measure_receipts``) — единственное место, которое
    спрашивает «у взятия есть квитанция?». Два набора записей отличаются РОВНО одной
    квитанцией; изменилось поле ⇒ читатель доказан. Не изменилось ⇒ читателя нет, и
    заводить канал рано.
    """
    now = now or datetime.now(timezone.utc)
    pid = pid or os.getpid()
    out: Dict[str, Any] = {"measured": False, "reason": None, "outcome": None,
                           "reader": None, "field": "window_takings_without_receipt",
                           "without_receipt": None, "with_receipt": None}
    if reader is None:
        try:
            from spa_core.monitoring.duplicate_subject_census import measure_receipts
            reader = measure_receipts
        except Exception as exc:  # noqa: BLE001
            out["reason"] = f"кандидат-читатель не загружен: {type(exc).__name__}: {exc}"
            return out
    out["reader"] = ("spa_core/monitoring/duplicate_subject_census.py"
                     "::measure_receipts (ось B переписи дублей)")

    taking = {"ts": (now - timedelta(minutes=30)).strftime(_WRITER_STAMP),
              "session": f"pid{pid}", "summary": "сцена оси C: взятие предмета",
              "files": [], "verified": "сцена",
              "card": _SANDBOX_CARD, "card_state": "claim",
              "session_pid": pid, "session_pid_start": "Thu Oct  1 00:00:00 2026"}
    receipt = dict(taking)
    receipt["ts"] = (now - timedelta(minutes=31)).strftime(_WRITER_STAMP)
    receipt["summary"] = f"[check_card_claim] проверка захвата карточки {_SANDBOX_CARD}"

    try:
        without = reader([taking], now=now)
        with_one = reader([receipt, taking], now=now)
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"кандидат-читатель не отработал: {type(exc).__name__}: {exc}"
        return out

    key = out["field"]
    left = observed(without, key, kind=int)
    right = observed(with_one, key, kind=int)
    if left is None or right is None:
        out["reason"] = f"у читателя нет поля `{key}` — сравнивать нечего"
        return out
    out["without_receipt"] = left
    out["with_receipt"] = right
    out["measured"] = True
    out["outcome"] = "reader_proven" if left != right else "reader_absent"
    return out


# ─────────────── ось D: цена наивного канала (дифференциально) ───────────────

def measure_naive_channel(repo_root: Path, *, guard_loader=None, anchor=None) -> Dict[str, Any]:
    """Ось D. Во что обходится квитанция, вписанная в ОБЩИЙ журнал объявлений.

    У единственного писателя журнала состояний ровно два (``claim`` / ``done``),
    поэтому квитанция неизбежно принимает форму ВЗЯТИЯ — и сторож читает её как
    сильный признак. Замер показывает, что от этого вердикт переворачивается:
    вопрос («занято?») становится ответом («занято мной же, потому что я спросил»).

    **От живости номера процесса вердикт не зависит** по построению: свежий сильный
    захват блокирует независимо от ``ps`` (``.claude/rules/deployment.md``, личность
    процесса). Поэтому номер берётся живым (``os.getppid()``), а не литералом.

    Часов замер не принимает — по той же причине, что ось A: обе записи сцены пишет
    настоящий писатель, и свежесть у них ПО ПОСТРОЕНИЮ.
    """
    out: Dict[str, Any] = {"measured": False, "reason": None, "outcome": None,
                           "verdict_without": None, "verdict_with": None,
                           "code_without": None, "code_with": None, "anchor": None}
    anchor = anchor if anchor is not None else live_other_anchor()
    out["anchor"] = {"pid": anchor.get("pid"), "measured": bool(anchor.get("measured"))}
    if not anchor.get("measured"):
        out["reason"] = (f"личность чужой живой сессии НЕ ИЗМЕРЕНА — {anchor.get('reason')}; "
                         "судить о перевороте вердикта по неизмеренному номеру запрещено")
        return out
    scene = Path(tempfile.mkdtemp(prefix="spa_naive_channel_"))
    try:
        guard = (guard_loader or _load_guard)(repo_root)
        announcer = guard.load_announcer()
        tracker_a, log_a = _write_sandbox(scene / "base", _SANDBOX_CARD,
                                          announcer=announcer)
        tracker_b, log_b = _write_sandbox(scene / "with", _SANDBOX_CARD,
                                          announcer=announcer, receipt_anchor=anchor)
        answer_a = _ask_guard(guard, tracker_a, log_a, _SANDBOX_CARD)
        answer_b = _ask_guard(guard, tracker_b, log_b, _SANDBOX_CARD)
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"сцена пробы не отработала: {type(exc).__name__}: {exc}"
        return out
    finally:
        shutil.rmtree(scene, ignore_errors=True)

    left = observed(answer_a["report"], VERDICT_KEY, kind=str)
    right = observed(answer_b["report"], VERDICT_KEY, kind=str)
    if left is None or right is None:
        out["reason"] = "вердикт не произведён на одной из двух сцен"
        return out
    out["verdict_without"] = left
    out["verdict_with"] = right
    out["code_without"] = answer_a["code"]
    out["code_with"] = answer_b["code"]
    # Якорь сцены обязан быть ЧУЖИМ, и это проверяется ИСХОДОМ, а не доверием к
    # `os.getppid()`. Сторож узнаёт свою сессию по подтверждённой паре (pid, старт) и
    # СВОЙ захват не считает блокирующим — значит, попади в сцену мой собственный
    # якорь, замер объявил бы наивный канал безвредным, померив самозахват. Замерено
    # на этой же правке: с `pid=os.getpid()` исход `harmless`, с чужим живым —
    # `question_becomes_claim`. Отсюда и ВАЖНОЕ свойство самого вреда: он
    # АСИММЕТРИЧЕН — сессия, оставившая квитанцию, своего замка не видит НИКОГДА,
    # видят его только остальные.
    if observed(answer_b["report"], "self_claims", kind=list):
        out["reason"] = ("якорь сцены опознан сторожем как МОЙ — переворот мерился бы "
                         "на самозахвате, а своего захвата сторож не считает "
                         "блокирующим; чужая живая личность не получена")
        return out
    if left != "free":
        # Карточка сцены не свободна — переворот нечем увидеть. Это НЕ «вреда нет».
        out["reason"] = (f"базовый вердикт сцены `{left}`, а не `free` — "
                         "переворот вопроса в захват нечем измерить")
        return out
    out["measured"] = True
    # Вред имеет ДВА лица, и сворачивать их в одно нельзя: `claimed` запирает карточку
    # для других, `unchecked` — fail-CLOSED «не измерено», от которого отказывается и
    # берущая сессия (код 2), и шаг 0a-ГОЛОД (разбирает отдельно). Третье лицо —
    # `harmless`: вердикт не сдвинулся, и тогда наивный канал ничего не стоит.
    out["outcome"] = {"claimed": "question_becomes_claim",
                      "unchecked": "question_becomes_unchecked",
                      "stale": "question_becomes_stale"}.get(right, "harmless")
    return out


# ─────────────────────────────── сборка ──────────────────────────────────

def build_report(repo_root: Path, *, now: Optional[datetime] = None,
                 trace=None, readers=None, receipt=None, naive=None) -> Dict[str, Any]:
    """Отчёт прибора. Форма ПОСТОЯННА: ключи объявлены всегда, «не вычислено» — ``None``."""
    stamp = (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    report: Dict[str, Any] = {
        "generated_at": stamp,
        "order": ORDER,
        "measured": False,
        "status": STATUS_UNMEASURED,
        "reason": None,
        "applied": False,
        "trace": None,
        "verdict_readers": None,
        "receipt_reader": None,
        "naive_channel": None,
    }
    report["trace"] = trace if trace is not None else measure_trace(repo_root)
    report["verdict_readers"] = (readers if readers is not None
                                 else measure_verdict_readers(repo_root))
    report["receipt_reader"] = (receipt if receipt is not None
                                else measure_receipt_reader(now=now))
    report["naive_channel"] = (naive if naive is not None
                               else measure_naive_channel(repo_root))

    unmeasured = [name for name in ("trace", "verdict_readers", "receipt_reader",
                                    "naive_channel")
                  if not (report[name] or {}).get("measured")]
    if unmeasured:
        reasons = "; ".join(f"{name}: {(report[name] or {}).get('reason')}"
                            for name in unmeasured)
        report["reason"] = f"не измерено {len(unmeasured)} из 4 осей — {reasons}"
        return report

    report["measured"] = True
    has_writer = report["trace"]["outcome"] == "trace_written"
    has_reader = report["receipt_reader"]["outcome"] == "reader_proven"
    if has_writer and has_reader:
        report["status"] = STATUS_WIRED
    elif has_reader:
        report["status"] = STATUS_READER_WITHOUT_WRITER
    else:
        report["status"] = STATUS_WITHOUT_READER
    return report


def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    path = data_dir / ARTIFACT_NAME
    atomic_save(report, str(path))
    return path


def format_report(report: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    if not report.get("measured"):
        lines.append("квитанция read-only проверки захвата (заказ G88 п. 1): "
                     f"НЕ ИЗМЕРЕНО — {report.get('reason')}")
        return lines
    trace = report["trace"]
    readers = report["verdict_readers"]
    receipt = report["receipt_reader"]
    naive = report["naive_channel"]
    lines.append(
        f"квитанция read-only проверки захвата (заказ G88 п. 1): {report['status']}")
    lines.append(
        f"[ОСЬ A] `check` на одноразовой сцене: {trace['outcome']} — вердикт "
        f"`{trace['verdict']}` произведён (код {trace['exit_code']}), файлов в сцене "
        f"{trace['files_before']}, изменено {len(trace['files_changed'])}, "
        f"добавлено {len(trace['files_added'])}")
    lines.append(
        f"[ОСЬ B] загрузивших сторожа {readers['loaders_measured']}; "
        + " · ".join(f"{k} {v}" for k, v in readers["by_class"].items()))
    for door in readers["doors"]:
        extra = ""
        detail = door.get("detail") or {}
        if detail.get("compared_against"):
            extra = f" — сравнивает с {', '.join(detail['compared_against'])}"
        elif detail.get("reason"):
            extra = f" — {detail['reason']}"
        lines.append(f"[ОСЬ B] {door['class']}: {door['door']}{extra}")
    lines.append(f"[ОСЬ B] {readers['form_not_execution']}")
    lines.append(
        f"[ОСЬ C] читатель квитанции: {receipt['outcome']} — {receipt['reader']}, "
        f"поле `{receipt['field']}` {receipt['without_receipt']} → "
        f"{receipt['with_receipt']} от ОДНОЙ добавленной квитанции")
    lines.append(
        f"[ОСЬ D] наивный канал (общий журнал): {naive['outcome']} — вердикт "
        f"`{naive['verdict_without']}` → `{naive['verdict_with']}` "
        f"(коды {naive['code_without']} → {naive['code_with']})")
    if report["status"] == STATUS_READER_WITHOUT_WRITER:
        lines.append("ВЫВОД: у квитанции ЕСТЬ читатель, доказанный исходом, а писателя "
                     "нет — и наивный канал заводить нельзя, он превращает ВОПРОС в "
                     "ЗАХВАТ. Канал нужен отдельный, и это решение, а не следствие замера")
    lines.append("НЕ ДОКЛАДЫВАЕТ: исполняется ли ветка с вердиктом · спрашивали ли "
                 "сторожа в прошлом (задним числом это неизмеримо по построению) · "
                 "вреден ли ОТДЕЛЬНЫЙ канал · полезна ли квитанция читателю")
    lines.append("ADVISORY: прибор только ЧИТАЕТ (applied=False) — RiskPolicy v1.0, "
                 "стоп-кран, аллокатор, живой трек и landing/ не трогаются; сцены "
                 "одноразовые (mkdtemp), гейт «нельзя взять занятое» НЕ заводится")
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
    return 0 if report["status"] == STATUS_WIRED else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=None, help="корень дерева (по умолчанию — своё)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", action="store_true", help=f"записать data/{ARTIFACT_NAME}")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[2]
    report = build_report(repo_root)
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
