# LLM_FORBIDDEN
"""Переживают ли ИМЕНА упавших тестов раннер (заказ G87 п. 1, ADR-528).

Заказ ADR-491 поставлен дословно так:

    **Имена упавших тестов `main` обязаны переживать раннер.** ``reports/`` не
    выгружается, ``_NAMES_SHOWN`` режет 61 до 20. Спросить надо не «поднять ли
    предел печати», а **у кого из читателей вердикта CI есть доступ к ПОЛНОЙ
    записи** — и мерить это у ПИСАТЕЛЯ (кто сохраняет запись), а не по имени
    поля. Три исхода обязательны.

## Почему вопрос задаётся ПИСАТЕЛЮ, и почему порядок ног есть часть утверждения

Соблазн здесь ровно один: поднять ``ci_verdict._NAMES_SHOWN`` с 20 до 200 и
считать дело сделанным. Это лечит не тот орган. Замер 28.09 (прогон ``test.yml``
36350773679 о ``351c84162``): шаг ``spa_core/tests/`` снят по
``timeout-minutes`` на ``[ 94%]``, junit-записи нет вовсе, потоковая запись
говорит «начато 101 206 · упало 61 · сессия дошла до конца: НЕТ». Полный
перечень из 61 имени **существовал** — он лежал в
``reports/stream-spa_core.jsonl`` внутри раннера, — и был уничтожен вместе с
раннером. В логе осталось 20.

Поэтому ноги спрашиваются в объявленном порядке, и порядок не оформление:

1. **ПИСАТЕЛЬ.** Пишет ли шаг запись имён на диск и ПОКИДАЕТ ли эта запись
   раннер. Если ни одна запись раннер не покидает, то доступа к полному
   перечню нет **ни у одного** читателя — и этот вывод не зависит ни от того,
   как написан читатель, ни от предела печати.
2. **ЧИТАТЕЛЬ.** Только после первой ноги осмысленно спрашивать, каким КАНАЛОМ
   читатель вердикта получает имена. Канал может нести все имена, часть
   (лог шага, усечённый ``_NAMES_SHOWN``) или ни одного (``conclusion`` прогона).

Обратный порядок дал бы ровно ту ошибку, против которой написан заказ: перепись
читателей на мёртвой записи выглядела бы вопросом о читателях.

## «Не по имени поля» — это про ПОКРЫТИЕ ПУТИ, а не про название шага

Шаг с ``name: Upload test results`` не доказывает, что он выгружает нужную
запись: решает, покрывает ли его ``with.path`` тот путь, который объявил
писатель. И решает это **в той же джобе** — выгрузка в джобе ``lint`` не спасает
запись джобы ``test``. Оба вопроса меряются у разбора воркфлоу, а не у слов.

## Условие шага выгрузки — отдельный вопрос, и его молчание есть ОТКАЗ

Запись об упавших тестах нужна ИМЕННО тогда, когда шаг упал. Шаг выгрузки без
``if:`` после упавшего шага GitHub **пропускает**, то есть объявленная выгрузка
не исполняется никогда в том единственном случае, ради которого она нужна. Это
не то же самое, что «выгрузки нет», и исход поэтому свой:
``upload_declared_but_not_on_failure``. Второй путь к тому же результату —
``continue-on-error: true`` у самого писателя: тогда джоба не падает и шаг
выгрузки исполняется обычным порядком. Он измеряется и НАЗЫВАЕТСЯ в причине, а
не домысливается.

## Три исхода обязательны (инв. #17)

Перечень исходов ЗАКРЫТ, сумма равна населению, каждый ноль объявлен:

====================================== ========================================
``record_survives_as_artifact``        запись пишется, покрывающая выгрузка в
                                       той же джобе есть и исполняется при
                                       отказе — имена покидают раннер
``upload_declared_but_not_on_failure`` покрывающая выгрузка есть, но на пути
                                       отказа не исполняется
``record_dies_with_the_runner``        запись пишется, покрывающей выгрузки нет
``no_record_written``                  шаг не объявляет пути записи вовсе: имена
                                       живут только в логе, а у ОБОРВАННОЙ
                                       сессии не живут нигде
``unmeasured``                         не разобрано, с названной причиной
====================================== ========================================

``no_record_written`` — не «мягче» смерти записи, а другой вред: там запись
уничтожают, здесь её не делают. Склеить их значило бы потерять разницу между
«лекарство есть и не доставлено» и «лекарства нет».

## Разбор YAML здесь НАСТОЯЩИЙ, и его отсутствие — третий исход

``yaml.safe_load``, а не второй самодельный разборщик: самодельный и есть тот
дефект, который ловит ADR-522, и соседи по набору
(``test_ci_covers_every_test_dir``, ``test_pytest_timeout_method_reports``) уже
решили этот вопрос так же. Ввоз сделан ВНУТРИ функции: модуль живёт в
``spa_core/monitoring`` (рантайм-домен, инв. #4), и верхнеуровневый ``import
yaml`` уронил бы сборкой весь шаг 0-офис на хосте без PyYAML. Отсутствие
библиотеки — **НЕ ИЗМЕРЕНО** с названной причиной, а не скип и не ноль
(урок ``pyflakes``, ``.claude/rules/deployment.md``).

## Число печати ИЗМЕРЯЕТСЯ, а не перепечатывается

``_NAMES_SHOWN`` читается у ``scripts/ci_verdict.py`` разбором AST. Не нашли —
печатается «не измерено», а не 20: перепечатать чужое число из текста правила и
есть тот дефект, на котором ``.claude/rules/site-numbers.md`` поймала саму себя.

## Односторонность названа ЗАРАНЕЕ и числом

* Писатель виден по ``run``, содержащему ``pytest``. Шаг, зовущий pytest из
  скрипта-обёртки, в население не попадёт — мера ошибается в сторону
  ЗАНИЖЕНИЯ населения.
* Пути записи распознаются в трёх формах: ``--junitxml``, переменная
  ``SPA_PYTEST_STREAM`` и ``tee <файл>``. Четвёртая форма дала бы
  ``no_record_written`` там, где запись есть, — ошибка в сторону ЗАВЫШЕНИЯ
  вреда, и число распознанных форм печатается рядом с вердиктом.
* Покрытие пути решается только на литералах. Путь или ``path:`` с
  ``${{ … }}`` ⇒ ``unmeasured``, а не «покрыто» и не «не покрыто».
* Ось читателей (вторая, в сумму НЕ входит) измеряется по УПОМИНАНИЮ в
  ``scripts/`` и ``spa_core/`` вне тестов. Упоминание не есть чтение, и число
  просмотренных файлов печатается — чтобы «ни один читатель» было числом, а не
  словом.

Прибор только ЧИТАЕТ: ни один тест не запускается, не правится и не ослабляется
(инв. #16); RiskPolicy, стоп-кран, аллокатор, живой трек и ``landing/`` не
трогаются. LLM запрещён. Модульные ввозы — только stdlib (инв. #4).
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import sys

# ── исходы оси ПИСАТЕЛЯ. Перечень ЗАКРЫТ: сумма обязана равняться населению ──
SURVIVES = "record_survives_as_artifact"
NOT_ON_FAILURE = "upload_declared_but_not_on_failure"
DIES = "record_dies_with_the_runner"
NO_RECORD = "no_record_written"
UNMEASURED = "unmeasured"

OUTCOMES: tuple[str, ...] = (SURVIVES, NOT_ON_FAILURE, DIES, NO_RECORD, UNMEASURED)

#: Лестница строгости для шага, объявившего НЕСКОЛЬКО записей: вердикт шага есть
#: вердикт его ХУДШЕЙ записи (fail-CLOSED — «часть имён уцелела» не есть «имена
#: уцелели»). Порядок объявлен, а не унаследован от порядка перечисления:
#: ``unmeasured`` стоит ВЫШЕ ``survives`` (не можем сказать, что уцелели все) и
#: НИЖЕ определённых находок — спрятать названный вред за словом «не знаю» было
#: бы той же подменой, против которой написан инв. #17.
_SEVERITY: tuple[str, ...] = (SURVIVES, UNMEASURED, NOT_ON_FAILURE, DIES, NO_RECORD)

# ── исходы оси ЧИТАТЕЛЯ. Отдельная ось, в сумму населения НЕ входит ──────────
CH_API = "channel_api_conclusion"
CH_STEP_LOG = "channel_step_log_truncated"
CH_LOCAL_RECORD = "channel_local_record_given_as_input"
CH_UNMEASURED = "channel_unmeasured"

READER_CHANNELS: tuple[str, ...] = (CH_API, CH_STEP_LOG, CH_LOCAL_RECORD, CH_UNMEASURED)

#: Формы, которыми шаг объявляет путь записи имён. Число форм печатается рядом
#: с вердиктом: мера видит ровно их, и это её объявленная односторонность.
RECORD_FORMS: tuple[str, ...] = ("junitxml", "stream_env", "tee")

#: Токены условия, при которых шаг исполняется ПОСЛЕ упавшего шага.
_RUNS_ON_FAILURE = ("always()", "!cancelled()", "! cancelled()", "failure()")

_EXPRESSION = re.compile(r"\$\{\{")
_JUNITXML = re.compile(r"--junitxml[=\s]+([^\s\\]+)")
_TEE = re.compile(r"\btee\s+(?:-a\s+)?([^\s|&;]+)")


class Unmeasured(Exception):
    """Предпосылка замера не обеспечена. Причина обязательна."""


# ── вход: разобранные воркфлоу ───────────────────────────────────────────────

def load_workflows(root: str) -> dict[str, dict]:
    """Воркфлоу как РАЗОБРАННЫЕ документы. Отсутствие PyYAML — третий исход.

    Ввоз внутри функции намеренно (см. шапку модуля): рантайм-домен обязан
    оставаться importable на stdlib-only хосте.
    """
    try:
        import yaml  # noqa: PLC0415
    except ImportError as exc:
        raise Unmeasured(f"PyYAML отсутствует, разобрать воркфлоу нечем ({exc})") from exc

    wf_dir = os.path.join(root, ".github", "workflows")
    if not os.path.isdir(wf_dir):
        raise Unmeasured(f"каталога воркфлоу нет: {wf_dir}")
    names = sorted(n for n in os.listdir(wf_dir) if n.endswith((".yml", ".yaml")))
    if not names:
        raise Unmeasured(f"в {wf_dir} нет ни одного воркфлоу")

    docs: dict[str, dict] = {}
    for name in names:
        path = os.path.join(wf_dir, name)
        try:
            doc = yaml.safe_load(open(path, encoding="utf-8").read())
        except Exception as exc:  # noqa: BLE001 — молчание здесь = fail-OPEN
            raise Unmeasured(
                f"воркфлоу не разобран: {name}: {type(exc).__name__}: {exc}") from exc
        docs[name] = doc if isinstance(doc, dict) else {}
    return docs


def names_shown(root: str):
    """``ci_verdict._NAMES_SHOWN`` разбором AST. ``None`` = не измерено.

    Перепечатать «20» из текста заказа значило бы повторить дефект, против
    которого заказ и написан.
    """
    path = os.path.join(root, "scripts", "ci_verdict.py")
    try:
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    except Exception:  # noqa: BLE001 — не измерено, а не умолчание
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (isinstance(target, ast.Name) and target.id == "_NAMES_SHOWN"
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, int)):
                return node.value.value
    return None


# ── разбор шагов ─────────────────────────────────────────────────────────────

def _steps_of(doc: dict):
    """Пары «имя джобы → список шагов». Джоба без списка шагов — не находка."""
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        return []
    out = []
    for job_name, job in sorted(jobs.items()):
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if isinstance(steps, list):
            out.append((str(job_name), [s for s in steps if isinstance(s, dict)]))
    return out


#: Разделители команд внутри одного ``run``. Писателем шаг делает ВЫЗОВ pytest,
#: а не упоминание слова: ``pip install pytest`` ставит библиотеку и ничего не
#: пишет. Соседний сторож (``test_declared_git_environment``) судит по
#: подстроке, и для ЕГО вопроса это верно — он обязан ошибаться в сторону
#: находки. Здесь ошибка в ту же сторону ЗАВЫШАЕТ вред: шаг установки попал бы
#: в ``no_record_written``, которого он не заслужил.
_SEGMENT = re.compile(r"[\n;|&]+|&&|\|\|")


def _invokes_pytest(command: str) -> bool:
    """Вызывает ли ОДНА команда pytest (а не ставит его)."""
    tokens = command.replace("\\\n", " ").split()
    if not tokens:
        return False
    if "install" in tokens:
        return False
    for index, token in enumerate(tokens):
        bare = token.rsplit("/", 1)[-1]
        if bare in ("pytest", "pytest.exe"):
            if index == 0 or tokens[index - 1] == "-m":
                return True
    return False


def _is_pytest_step(step: dict) -> bool:
    run = step.get("run")
    if not isinstance(run, str):
        return False
    return any(_invokes_pytest(seg) for seg in _SEGMENT.split(run))


def record_paths(step: dict) -> list[tuple[str, str]]:
    """Пути записи имён, объявленные шагом, с ФОРМОЙ объявления каждого.

    Форма — часть замера, а не украшение: она называет, чем именно мера видит
    запись, и тем самым объявляет, чего она не видит.
    """
    found: list[tuple[str, str]] = []
    run = step.get("run") if isinstance(step.get("run"), str) else ""
    for match in _JUNITXML.finditer(run):
        found.append(("junitxml", match.group(1).strip().strip("'\"")))
    for match in _TEE.finditer(run):
        found.append(("tee", match.group(1).strip().strip("'\"")))
    env = step.get("env")
    if isinstance(env, dict):
        value = env.get("SPA_PYTEST_STREAM")
        if isinstance(value, str) and value.strip():
            found.append(("stream_env", value.strip()))
    # Порядок стабилен и не зависит от обхода словаря: вердикт обязан быть
    # одинаковым на любом хосте (PYTHONHASHSEED — часть предписанного прогона).
    return sorted(set(found))


def _upload_paths(step: dict) -> list[str]:
    """Литеральные пути шага выгрузки. Строка с ``${{ … }}`` не литерал."""
    with_ = step.get("with")
    if not isinstance(with_, dict):
        return []
    raw = with_.get("path")
    if not isinstance(raw, str):
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _is_upload_step(step: dict) -> bool:
    uses = step.get("uses")
    return isinstance(uses, str) and uses.startswith("actions/upload-artifact")


def _covers(upload_path: str, record_path: str):
    """Покрывает ли объявленный путь выгрузки путь записи.

    ``None`` = решить нельзя (выражение подстановки). Это третий исход пары, а
    не «покрыто» и не «не покрыто».
    """
    if _EXPRESSION.search(upload_path) or _EXPRESSION.search(record_path):
        return None
    up = upload_path.strip().lstrip("./").rstrip("/")
    rec = record_path.strip().lstrip("./")
    if not up or not rec:
        return None
    if up == rec:
        return True
    if rec.startswith(up + "/"):
        return True
    if any(ch in up for ch in "*?[") and fnmatch.fnmatch(rec, up):
        return True
    return False


def _runs_on_failure(step: dict):
    """Исполнится ли шаг ПОСЛЕ упавшего шага.

    ``None`` = условие есть, но ни одного известного токена в нём нет ⇒ решать
    нельзя (fail-CLOSED). Отсутствие ``if:`` вовсе — определённое «нет»: GitHub
    пропускает последующие шаги упавшей джобы.
    """
    cond = step.get("if")
    if cond is None:
        return False
    text = str(cond)
    if any(token in text for token in _RUNS_ON_FAILURE):
        return True
    return None


# ── замер ────────────────────────────────────────────────────────────────────

def measure(root: str, workflows: dict | None = None) -> dict:
    """Перепись «переживают ли имена упавших тестов раннер».

    ``workflows`` — ВХОД (разобранные документы). Так прибор проверяется
    фикстурой, а не живым GitHub, и остаётся read-only: тот же порядок, что у
    часов, pid и сети в ``.claude/rules/deployment.md``.
    """
    unmeasured_reason = ""
    if workflows is None:
        try:
            workflows = load_workflows(root)
        except Unmeasured as exc:
            return {
                "population": 0,
                "rows": [],
                "counts": {name: 0 for name in OUTCOMES},
                "readers": [],
                "reader_counts": {name: 0 for name in READER_CHANNELS},
                "reader_files_scanned": None,
                "names_shown": names_shown(root),
                "record_forms": list(RECORD_FORMS),
                "unmeasured_reason": str(exc),
            }

    rows: list[dict] = []
    for wf_name, doc in sorted(workflows.items()):
        for job_name, steps in _steps_of(doc):
            uploads = [s for s in steps if _is_upload_step(s)]
            for index, step in enumerate(steps):
                if not _is_pytest_step(step):
                    continue
                rows.append(_judge(wf_name, job_name, index, step, uploads))

    counts = {name: 0 for name in OUTCOMES}
    for row in rows:
        counts[row["outcome"]] += 1

    readers, reader_counts, scanned = _reader_axis(root)
    return {
        "population": len(rows),
        "rows": rows,
        "counts": counts,
        "readers": readers,
        "reader_counts": reader_counts,
        "reader_files_scanned": scanned,
        "names_shown": names_shown(root),
        "record_forms": list(RECORD_FORMS),
        "unmeasured_reason": unmeasured_reason,
    }


def _judge(wf_name: str, job_name: str, index: int, step: dict,
           uploads: list[dict]) -> dict:
    """Вердикт одного писателя. Выгрузки берутся ТОЛЬКО из его джобы."""
    row = {
        "workflow": wf_name,
        "job": job_name,
        "step": str(step.get("name") or f"#{index}"),
        "records": [],
        "outcome": UNMEASURED,
        "why": "",
    }
    records = record_paths(step)
    row["records"] = [{"form": form, "path": path} for form, path in records]
    if not records:
        row["outcome"] = NO_RECORD
        row["why"] = ("шаг не объявляет пути записи ни одной из "
                      f"{len(RECORD_FORMS)} распознаваемых форм "
                      f"({', '.join(RECORD_FORMS)}) — имена живут только в логе")
        return row

    # Писатель, которому разрешено падать, не роняет джобу, поэтому обычный
    # шаг выгрузки после него ИСПОЛНЯЕТСЯ. Это второй путь к тому же исходу,
    # и он НАЗЫВАЕТСЯ, а не домысливается.
    tolerated = step.get("continue-on-error") is True

    best: tuple[int, str, str] | None = None
    for form, path in records:
        verdict, why = _one_record(path, uploads, tolerated)
        rank = _SEVERITY.index(verdict)
        tag = f"{form} {path}: {why}"
        if best is None or rank > best[0]:
            best = (rank, verdict, tag)
    assert best is not None
    row["outcome"] = best[1]
    row["why"] = best[2]
    return row


def _one_record(path: str, uploads: list[dict], tolerated: bool) -> tuple[str, str]:
    """Исход ОДНОЙ записи: покрыта ли выгрузкой и исполнится ли та при отказе."""
    undecided = ""
    for upload in uploads:
        decided_any = False
        for declared in _upload_paths(upload):
            covered = _covers(declared, path)
            if covered is None:
                undecided = undecided or (
                    f"путь выгрузки «{declared}» содержит подстановку — "
                    "покрытие решить нельзя")
                continue
            if covered:
                decided_any = True
                break
        if not decided_any:
            continue
        on_failure = _runs_on_failure(upload)
        if on_failure is True:
            return SURVIVES, (f"выгрузка «{upload.get('name') or upload.get('uses')}» "
                              f"покрывает путь и исполняется при отказе "
                              f"(if: {upload.get('if')})")
        if on_failure is None:
            return UNMEASURED, (
                f"выгрузка покрывает путь, но её условие «{upload.get('if')}» "
                "не содержит ни одного известного токена — решить нельзя")
        if tolerated:
            return SURVIVES, ("выгрузка покрывает путь и исполняется потому, что "
                              "писателю разрешено падать (continue-on-error: true)")
        return NOT_ON_FAILURE, ("выгрузка покрывает путь, но у неё нет условия: "
                                "после упавшего шага GitHub её ПРОПУСКАЕТ — "
                                "ровно в том случае, ради которого она нужна")
    if undecided:
        return UNMEASURED, undecided
    return DIES, (f"ни одна выгрузка джобы не покрывает «{path}» — запись "
                  "уничтожается вместе с раннером")


# ── ось читателей ────────────────────────────────────────────────────────────

#: Чем читатель берёт вердикт. Порядок проверки — от самого узкого признака.
#: Признак-ВОРОТА («этот файл вообще читает вердикт CI?») НЕ объявляется
#: отдельно: он есть объединение этих же меток по построению. Отдельный список
#: ворот однажды разошёлся бы с этим — и файл, чей канал мера знает, выпал бы из
#: населения молча. Это та же ошибка, что два дома у одного порога (ADR-513).
_READER_MARKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (CH_LOCAL_RECORD, ("junitxml", "SPA_PYTEST_STREAM", "<testsuite")),
    (CH_API, ("/actions/runs", "gh run ", "actions/workflows/")),
    (CH_STEP_LOG, ("ci_verdict",)),
)

#: Исключения оси читателей — с НАЗВАННОЙ причиной у каждого. Оба файла
#: содержат метки канала и читателями вердикта не являются: первый его ПИШЕТ,
#: второй — ЭТОТ прибор, и он читает воркфлоу, а не вердикт. Считать прибор
#: собственным населением значило бы сверять его сам с собой (ADR-504).
READER_EXCLUSIONS: dict[str, str] = {
    "scripts/ci_verdict.py": "сам писатель вердикта, не его читатель",
    "spa_core/monitoring/failed_name_survival_census.py":
        "сам прибор: читает воркфлоу, а не вердикт",
}


def _reader_axis(root: str):
    """Читатели вердикта CI и КАНАЛ каждого.

    Ось вторая и в сумму населения НЕ входит: она существует затем, чтобы
    вывод «доступа нет ни у одного читателя» был ЧИСЛОМ, а не словом.
    """
    readers: list[dict] = []
    counts = {name: 0 for name in READER_CHANNELS}
    scanned = 0
    for rel_root in ("scripts", os.path.join("spa_core", "monitoring")):
        base = os.path.join(root, rel_root)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in sorted(dirnames) if d != "tests"]
            for filename in sorted(filenames):
                if not filename.endswith(".py"):
                    continue
                scanned += 1
                path = os.path.join(dirpath, filename)
                try:
                    text = open(path, encoding="utf-8").read()
                except OSError:
                    continue
                rel = os.path.relpath(path, root).replace(os.sep, "/")
                if rel in READER_EXCLUSIONS:
                    continue
                channel = _channel_of(text)
                if channel is None:
                    continue
                readers.append({"reader": rel, "channel": channel})
                counts[channel] += 1
    return readers, counts, scanned


def _channel_of(text: str):
    """Канал по признаку в тексте. ``None`` = ни одной метки ⇒ не читатель."""
    for channel, marks in _READER_MARKS:
        if any(mark in text for mark in marks):
            return channel
    return None


# ── вердикт и отчёт ──────────────────────────────────────────────────────────

def verdict(doc: dict) -> str:
    """``unmeasured`` · ``names_outlive_the_runner`` · ``names_die_with_the_runner``."""
    if doc.get("unmeasured_reason"):
        return "unmeasured"
    if not doc.get("population"):
        return "unmeasured"
    counts = doc["counts"]
    if counts[SURVIVES] == doc["population"]:
        return "names_outlive_the_runner"
    return "names_die_with_the_runner"


def format_report(doc: dict) -> str:
    """Отчёт для шага 0-офис. Каждый ноль объявлен (инв. #17)."""
    if doc.get("unmeasured_reason"):
        return ("НЕ ИЗМЕРЕНО: имена упавших тестов — "
                f"{doc['unmeasured_reason']}")
    if not doc.get("population"):
        # Пустое население печаталось бы как «все нули», то есть как ЧИСТО —
        # это класс `vacuous_guard_census`, и он fail-OPEN тише красного.
        return ("НЕ ИЗМЕРЕНО: имена упавших тестов — ни одного шага, "
                "запускающего pytest, не найдено; ноль исходов на пустом "
                "населении не есть «чисто»")
    counts = doc["counts"]
    lines = [f"имена упавших тестов переживают раннер (заказ G87 п. 1): "
             f"население {doc['population']} шаг(ов), запускающих pytest"]
    lines.append("  " + " · ".join(f"{name} {counts[name]}" for name in OUTCOMES))
    shown = doc.get("names_shown")
    shown_text = (f"{shown}" if isinstance(shown, int) else "НЕ ИЗМЕРЕНО")
    lines.append(f"  предел печати имён у ci_verdict (_NAMES_SHOWN, замером): {shown_text}"
                 f"; форм записи мера видит {len(doc.get('record_forms') or ())}")
    for row in doc["rows"]:
        if row["outcome"] == SURVIVES:
            continue
        lines.append(f"  [{row['outcome']}] {row['workflow']}::{row['job']} :: "
                     f"{row['step']} — {row['why']}")
    counts_r = doc.get("reader_counts") or {}
    scanned = doc.get("reader_files_scanned")
    lines.append("  ось читателей (в сумму НЕ входит; упоминание не есть чтение, "
                 f"просмотрено файлов {scanned if scanned is not None else 'НЕ ИЗМЕРЕНО'}): "
                 + " · ".join(f"{name} {counts_r.get(name, 0)}" for name in READER_CHANNELS))
    if counts[SURVIVES] == 0 and doc["population"]:
        lines.append("  ВЫВОД: раннер не покидает НИ ОДНА запись имён ⇒ доступа к "
                     f"полному перечню нет ни у одного из {len(doc.get('readers') or ())} "
                     "измеренных читателей, и от предела печати это не зависит")
    lines.append("  НЕ ДОКЛАДЫВАЕТ: читает ли названный читатель канал на самом деле · "
                 "pytest, позванный из скрипта-обёртки · четвёртую форму записи · "
                 "сохранность самого артефакта после retention-days")
    lines.append("  ADVISORY: прибор только ЧИТАЕТ (applied=False)")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    doc = measure(args.root)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_report(doc))
    label = verdict(doc)
    return {"unmeasured": 2, "names_die_with_the_runner": 1,
            "names_outlive_the_runner": 0}[label]


if __name__ == "__main__":
    sys.exit(main())
