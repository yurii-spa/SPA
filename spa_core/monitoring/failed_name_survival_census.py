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
* Ось читателей (вторая, в сумму НЕ входит) измеряется по УПОМИНАНИЮ, и
  население её УЗКОЕ: ровно ``*.py`` каталогов ``scripts/`` и
  ``spa_core/monitoring/`` вне тестов. Упоминание не есть чтение, и число
  просмотренных файлов печатается — чтобы «ни один читатель» было числом, а не
  словом.
* **Ноль узкой оси есть НИЖНЯЯ ГРАНИЦА, и с ADR-650 это печатает сам прибор.**
  Заказ G106 п. 3 потребовал спросить с другой стороны, и вторая половина оси
  (ниже, ``_wide_reader_axis``) ходит по четырём родам площадок ВНЕ узкого
  населения: python вне двух каталогов · ``*.sh`` (их фильтр ``.py`` не видит
  даже в объявленных каталогах) · воркфлоу · документы ПРОТОКОЛА. У каждой
  площадки объявлено, ГДЕ лежит метка (исполняемый текст против прозы) и какова
  РОЛЬ (читает лог против зовёт писателя) — иначе слово в комментарии и команда
  в протоколе считались бы одним и тем же. Цены оставшейся односторонности
  названы заранее (``LOWER_BOUND_PRICES``).

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
            # Воркфлоу не разобраны ⇒ писательская ось НЕ ИЗМЕРЕНА. Вторая ось
            # от этого не умирает: она ходит по дереву, а не по воркфлоу, и
            # отдать её нулями значило бы выдать «не измерено» за «читателя
            # нет» у ОСТАЛЬНЫХ трёх родов (инв. #17).
            wide, wide_scanned, wide_sites_unmeasured, wide_kinds = \
                _wide_reader_axis(root, workflows={})
            wide_kinds[KIND_WORKFLOW] = str(exc)
            # Ось возраста ходит по ДЕРЕВУ (скачивающие площадки) и по
            # ЧИТАТЕЛЯМ, а не по воркфлоу: отдать её нулями значило бы выдать
            # «не измерено» у предложения за «спроса нет» у читателей.
            # Предложение при этом честно пусто — сроки живут в воркфлоу.
            fetch, fetch_scanned, fetch_unmeasured = _fetch_axis(root, {})
            age_rows, age_counts, age_excluded, age_outside = _age_demand_axis(
                [], wide, fetch)
            return {
                "population": 0,
                "rows": [],
                "counts": {name: 0 for name in OUTCOMES},
                "readers": [],
                "reader_counts": {name: 0 for name in READER_CHANNELS},
                "reader_files_scanned": None,
                "retention_rows": [],
                "retention_counts": {name: 0 for name in RETENTIONS},
                "age_demand_rows": age_rows,
                "age_demand_counts": age_counts,
                "age_excluded": age_excluded,
                "fetch_sites": fetch,
                "fetch_scanned": fetch_scanned,
                "fetch_unmeasured": fetch_unmeasured,
                "fetch_outside_population": age_outside,
                "wide_sites": wide,
                "wide_counts": wide_counts(wide),
                "wide_scanned": wide_scanned,
                "wide_site_unmeasured": wide_sites_unmeasured,
                "wide_kind_unmeasured": wide_kinds,
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
    # Те же воркфлоу подаются и второй оси: один вход — один операнд, иначе
    # тест, подавший сцену писателю, мерил бы у читателя ЖИВОЕ `.github/`.
    wide, wide_scanned, wide_sites_unmeasured, wide_kinds = \
        _wide_reader_axis(root, workflows=workflows)
    # Ось ВОЗРАСТА (заказ G106 п. 1). Порядок ног объявлен: предложение — у
    # воркфлоу (там живёт `retention-days`), спрос — у читателей, уже
    # измеренных двумя осями выше. Обратный порядок прочитался бы как вопрос
    # о настройке, а заказ запретил спрашивать настройку.
    retention_rows, retention_counts = _retention_axis(workflows)
    fetch, fetch_scanned, fetch_unmeasured = _fetch_axis(root, workflows)
    age_rows, age_counts, age_excluded, age_outside = _age_demand_axis(
        readers, wide, fetch)
    return {
        "population": len(rows),
        "rows": rows,
        "counts": counts,
        "readers": readers,
        "reader_counts": reader_counts,
        "reader_files_scanned": scanned,
        "retention_rows": retention_rows,
        "retention_counts": retention_counts,
        "age_demand_rows": age_rows,
        "age_demand_counts": age_counts,
        "age_excluded": age_excluded,
        "fetch_sites": fetch,
        "fetch_scanned": fetch_scanned,
        "fetch_unmeasured": fetch_unmeasured,
        "fetch_outside_population": age_outside,
        "wide_sites": wide,
        "wide_counts": wide_counts(wide),
        "wide_scanned": wide_scanned,
        "wide_site_unmeasured": wide_sites_unmeasured,
        "wide_kind_unmeasured": wide_kinds,
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


# ── ось читателей ВНЕ узкого населения: ноль есть НИЖНЯЯ ГРАНИЦА (G106 п. 3) ─
#
# Узкая ось выше ходит ровно по ``*.py`` двух каталогов (``scripts/`` и
# ``spa_core/monitoring/``) и про всё остальное дерево не говорит НИЧЕГО. Её
# ноль поэтому есть НИЖНЯЯ ГРАНИЦА, а не ответ «читателя нет»: за населением
# остаются воркфлоу, shell (каталог ``scripts/`` объявлен, но фильтр ``.py``
# половины его не видит), python вне двух каталогов и — то, что заказ назвал
# прямо, — сам человек в ПРОТОКОЛЕ. Заказ G106 п. 3 требует спросить с другой
# стороны и назвать ноль нижней границей.

#: Род площадки, на которой читателя искали. Перечень ЗАКРЫТ.
KIND_CODE = "code_py_outside"
KIND_SHELL = "shell"
KIND_WORKFLOW = "workflow_run"
KIND_DOC = "protocol_doc"
WIDE_KINDS: tuple[str, ...] = (KIND_CODE, KIND_SHELL, KIND_WORKFLOW, KIND_DOC)

#: Чем доказано, что метка канала стои́т не в прозе. Проза, НАЗЫВАЮЩАЯ предмет,
#: его читателем не делает — и это не умозрительная тонкость: единственного
#: читателя лога шага, которого видит узкая ось, она числит таковым по слову
#: ``ci_verdict`` в КОММЕНТАРИИ. Поэтому у каждой площадки здесь объявлено, где
#: метка лежит, и «в прозе» считается ОТДЕЛЬНО от «в исполняемом тексте».
EV_EXEC = "mark_in_executable_text"
EV_PROSE = "mark_in_prose_only"
EV_UNMEASURED = "evidence_unmeasured"
WIDE_EVIDENCE: tuple[str, ...] = (EV_EXEC, EV_PROSE, EV_UNMEASURED)

#: Документы ПРОТОКОЛА — объявленный перечень, а не весь ``docs/**``: инструкция,
#: которую сессия ОБЯЗАНА исполнить, живёт ровно здесь. Остальной markdown —
#: запись о прошлом (журнал, ADR, идея), и человек по нему не действует. Заказ
#: спрашивает про человека в ПРОТОКОЛЕ, а не в архиве; выбор населения назван
#: причиной, потому что «и так понятно» причиной не является.
PROTOCOL_DOCS: tuple[str, ...] = ("CLAUDE.md", "docs/ORCHESTRATOR_PROTOCOL.md")
PROTOCOL_DOC_GLOBS: tuple[str, ...] = (".claude/rules/*.md",)

#: Каталоги, которые обход не открывает вовсе. ``tests`` — тем же правилом, что
#: у узкой оси: тест не есть читатель вердикта.
_WIDE_SKIP_DIRS = frozenset({".git", ".venv", "venv", "node_modules", "tests",
                             "__pycache__", ".mypy_cache", ".pytest_cache"})

#: Цены нижней границы — названы ЗАРАНЕЕ и каждая со стороной ошибки.
LOWER_BOUND_PRICES: tuple[str, ...] = (
    "`#` внутри кавычек у shell уходит в прозу — ошибка в сторону ЗАНИЖЕНИЯ "
    "читателя, никогда в сторону выдуманного",
    "комментарий YAML отброшен разборщиком: упоминание канала в нём не видно "
    "вовсе — у рода `workflow_run` прозы нет по построению",
    "человек, читающий лог глазами в UI GitHub без команды в протоколе, не "
    "наблюдаем ни одним признаком дерева",
    "имя инструмента, собранное в рантайме, меткой не ловится (та же цена, "
    "что у узкой оси)",
    "markdown вне объявленного перечня протокола не просматривался — ВЫБОР "
    "с причиной, а не свойство дерева",
)


#: Чем площадка ТРОГАЕТ канал. Перечень ЗАКРЫТ, сумма равна числу площадок.
#: Различение существенно: шаг воркфлоу, зовущий `ci_verdict.py`, СОЗДАЁТ
#: усечённый лог, а не читает его, — и посчитать его читателем было бы ровно
#: той подменой («упоминание не есть чтение»), против которой написан заказ.
ROLE_READS = "role_reads_the_log"
ROLE_INVOKES = "role_invokes_the_writer"
ROLE_UNMEASURED = "role_unmeasured"
WIDE_ROLES: tuple[str, ...] = (ROLE_READS, ROLE_INVOKES, ROLE_UNMEASURED)

#: Форма КОМАНДЫ, чей вход есть лог. Проверяется ПЕРВОЙ: площадка, которая и
#: зовёт писателя, и читает его лог, есть читатель — зов тут не отменяет чтения.
_LOG_READ_FORMS: tuple[re.Pattern, ...] = (
    re.compile(r"\b(grep|egrep|rg|cat|tail|head|less|awk|sed)\b[^\n]{0,80}"
               r"(лог|log)", re.IGNORECASE),
    re.compile(r"run\s+view[^\n]{0,80}--log"),
    re.compile(r"--log-failed"),
    re.compile(r"(jobs|runs)/\S{0,40}/logs"),
)

#: Форма ЗОВА писателя: файл вердикта запускается как программа либо грузится
#: по пути. Это не чтение лога, и своего исхода он не теряет.
_INVOKE_FORMS: tuple[re.Pattern, ...] = (
    re.compile(r"ci_verdict\.py"),
    re.compile(r"ci_verdict\s*\.\s*(read_verdict|main|_NAMES_SHOWN)"),
)


def _role_of(text: str) -> str:
    """Роль площадки по ФОРМЕ, а не по присутствию имени. Третий исход обязателен."""
    if any(form.search(text) for form in _LOG_READ_FORMS):
        return ROLE_READS
    if any(form.search(text) for form in _INVOKE_FORMS):
        return ROLE_INVOKES
    return ROLE_UNMEASURED


class _Unparsed(Exception):
    """Разобрать площадку нечем — ТРЕТИЙ исход, а не ноль и не проза."""


def _narrow_population(rel: str) -> bool:
    """Файл, который УЖЕ прошёл узкую ось (``*.py`` двух её каталогов)."""
    return rel.endswith(".py") and (rel.startswith("scripts/")
                                    or rel.startswith("spa_core/monitoring/"))


def _channels_in(text: str) -> tuple[tuple[str, str], ...]:
    """ВСЕ каналы, чьи метки есть в тексте — без маскировки узкой лестницей.

    Узкая ось отдаёт ОДИН канал на файл (первый по лестнице), и у файла,
    читающего два канала, второй теряется молча. Для вопроса «есть ли читатель
    лога шага вообще» это ошибка в сторону занижения, поэтому перечень полный.
    """
    found: list[tuple[str, str]] = []
    for channel, marks in _READER_MARKS:
        hit = next((mark for mark in marks if mark in text), None)
        if hit is not None:
            found.append((channel, hit))
    return tuple(found)


def _python_text(src: str) -> tuple[str, str]:
    """``(исполняемый текст, проза)`` для ``.py`` — по ТОКЕНАМ.

    Проза — комментарии и строки-ОПЕРАТОРЫ (докстринг модуля, класса, функции).
    Позиции узлов ``ast`` для этого не годятся: ``col_offset`` там считается в
    БАЙТАХ utf-8, а токенайзер — в символах, и на кириллице (её здесь
    большинство) смешение двух шкал резало бы строку не там. Правило токена
    позиций не требует вовсе: строка, стоящая первым токеном логической строки
    и сразу закрытая ``NEWLINE``, есть строка-оператор.
    """
    import io  # noqa: PLC0415
    import tokenize  # noqa: PLC0415

    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError) as exc:
        raise _Unparsed(f"{type(exc).__name__}: {exc}") from exc

    prose = [t.string for t in toks if t.type == tokenize.COMMENT]
    # Соседство считается БЕЗ комментариев и без `NL`: комментарий между
    # `NEWLINE` и строкой не обязан прятать докстринг.
    sig = [t for t in toks if t.type not in (tokenize.COMMENT, tokenize.NL)]
    starts = (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
              tokenize.ENCODING)
    executed: list[str] = []
    for i, tok in enumerate(sig):
        if tok.type == tokenize.STRING:
            prev = sig[i - 1].type if i else tokenize.ENCODING
            nxt = sig[i + 1].type if i + 1 < len(sig) else tokenize.NEWLINE
            if prev in starts and nxt == tokenize.NEWLINE:
                prose.append(tok.string)
                continue
        executed.append(tok.string)
    return "\n".join(executed), "\n".join(prose)


_SH_COMMENT = re.compile(r"(?m)#.*$")


def _shell_text(src: str) -> tuple[str, str]:
    """``(исполняемый текст, проза)`` для ``*.sh``: ``#`` до конца строки — проза."""
    prose = "\n".join(m.group(0) for m in _SH_COMMENT.finditer(src))
    return _SH_COMMENT.sub("", src), prose


_MD_FENCE = re.compile(r"(?s)```.*?```|~~~.*?~~~")
_MD_INLINE = re.compile(r"`[^`\n]+`")


def _doc_text(src: str) -> tuple[str, str]:
    """``(исполняемый текст, проза)`` для markdown-протокола.

    Исполняемое у документа — КОМАНДА: ограждённый блок и строчный код в
    обратных кавычках. Всё прочее есть проза, и она читателем не делает: это
    тот же водораздел, что у комментария в ``.py``, только в другом рендере.
    """
    executed: list[str] = []
    rest = src
    for pattern in (_MD_FENCE, _MD_INLINE):
        executed.extend(m.group(0) for m in pattern.finditer(rest))
        rest = pattern.sub(" ", rest)
    return "\n".join(executed), rest


def _yaml_strings(node) -> list[str]:
    """Все строковые скаляры разобранного воркфлоу (``run``, ``env``, ``with``…)."""
    out: list[str] = []
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str):
                out.append(key)
            out.extend(_yaml_strings(value))
    elif isinstance(node, (list, tuple)):
        for item in node:
            out.extend(_yaml_strings(item))
    return out


def _protocol_docs(root: str, unmeasured: list[dict]) -> list[str]:
    """Объявленный перечень документов ПРОТОКОЛА, одной копией на обе оси.

    Правило населения здесь одно (``PROTOCOL_DOCS`` + ``PROTOCOL_DOC_GLOBS``), и
    зовут его две оси — читателей и возраста записи. Вторая копия правила
    разошлась бы с первой МОЛЧА: ровно тот класс «два дома у одного порога»,
    который ведётся заказом G151 п. 2. Отсутствующий каталог шаблона — третий
    исход (строка в ``unmeasured``), а не пустой список.
    """
    docs = list(PROTOCOL_DOCS)
    for pattern in PROTOCOL_DOC_GLOBS:
        head, _, tail = pattern.rpartition("/")
        base = os.path.join(root, head) if head else root
        if not os.path.isdir(base):
            unmeasured.append({"kind": KIND_DOC, "site": pattern,
                               "reason": f"каталога нет: {base}"})
            continue
        docs.extend((f"{head}/{n}" if head else n)
                    for n in sorted(os.listdir(base)) if fnmatch.fnmatch(n, tail))
    return docs


def _wide_reader_axis(root: str, workflows: dict | None = None):
    """Читатели вердикта ВНЕ узкого населения: площадки, роды, доказательства.

    Возвращает ``(sites, scanned, site_unmeasured, kind_unmeasured)``.
    «Не измерена ПЛОЩАДКА» и «не измерен РОД» — разные исходы: первое печатается
    строкой, второе означает, что про род вопрос остался без ответа вовсе, и
    поднимает код возврата. Род с ПУСТЫМ населением объявляется неизмеренным, а
    не чистым: нули на пустом населении и есть ``vacuous_guard_census``.
    """
    sites: list[dict] = []
    scanned = {kind: 0 for kind in WIDE_KINDS}
    site_unmeasured: list[dict] = []
    kind_unmeasured: dict[str, str] = {}

    def _add(kind: str, site: str, executed: str, prose: str) -> None:
        seen = set()
        for channel, mark in _channels_in(executed):
            seen.add(channel)
            sites.append({"kind": kind, "site": site, "channel": channel,
                          "evidence": EV_EXEC, "mark": mark,
                          "role": _role_of(executed)})
        for channel, mark in _channels_in(prose):
            if channel in seen:
                continue
            sites.append({"kind": kind, "site": site, "channel": channel,
                          "evidence": EV_PROSE, "mark": mark,
                          "role": _role_of(prose)})

    # ── python вне двух каталогов + shell по всему дереву ────────────────────
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in sorted(dirnames) if d not in _WIDE_SKIP_DIRS]
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                kind = KIND_CODE
            elif filename.endswith(".sh"):
                kind = KIND_SHELL
            else:
                continue
            path = os.path.join(dirpath, filename)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if kind == KIND_CODE and _narrow_population(rel):
                continue
            if rel in READER_EXCLUSIONS:
                continue
            scanned[kind] += 1
            try:
                text = open(path, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError) as exc:
                site_unmeasured.append({"kind": kind, "site": rel,
                                        "reason": f"{type(exc).__name__}: {exc}"})
                continue
            raw = _channels_in(text)
            if not raw:
                continue  # ни одной метки — разбирать нечего, и это не находка
            if kind == KIND_CODE:
                try:
                    executed, prose = _python_text(text)
                except _Unparsed as exc:
                    for channel, mark in raw:
                        sites.append({"kind": kind, "site": rel, "channel": channel,
                                      "evidence": EV_UNMEASURED, "mark": mark,
                                      "role": ROLE_UNMEASURED})
                    site_unmeasured.append({"kind": kind, "site": rel,
                                            "reason": f"разобрать нечем: {exc}"})
                    continue
            else:
                executed, prose = _shell_text(text)
            _add(kind, rel, executed, prose)

    # ── воркфлоу: разобранные документы, комментариев в них разборщик не даёт ─
    if workflows is None:
        try:
            workflows = load_workflows(root)
        except Unmeasured as exc:
            kind_unmeasured[KIND_WORKFLOW] = str(exc)
            workflows = {}
    for name, doc in sorted((workflows or {}).items()):
        scanned[KIND_WORKFLOW] += 1
        _add(KIND_WORKFLOW, f".github/workflows/{name}",
             "\n".join(_yaml_strings(doc)), "")

    # ── документы протокола: объявленный перечень ────────────────────────────
    for rel in _protocol_docs(root, site_unmeasured):
        path = os.path.join(root, *rel.split("/"))
        try:
            text = open(path, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError) as exc:
            site_unmeasured.append({"kind": KIND_DOC, "site": rel,
                                    "reason": f"{type(exc).__name__}: {exc}"})
            continue
        scanned[KIND_DOC] += 1
        _add(KIND_DOC, rel, *_doc_text(text))

    for kind in WIDE_KINDS:
        if kind in kind_unmeasured:
            continue
        if not scanned[kind]:
            kind_unmeasured[kind] = ("населения рода нет: ни одной площадки не "
                                     "просмотрено, и ноль находок на пустом "
                                     "населении не есть «читателя нет»")
    return sites, scanned, site_unmeasured, kind_unmeasured


def wide_counts(sites) -> dict:
    """``{канал: {доказательство: сколько}}``. Каждый ноль объявлен (инв. #17)."""
    counts = {channel: {ev: 0 for ev in WIDE_EVIDENCE}
              for channel in READER_CHANNELS}
    for site in sites:
        counts[site["channel"]][site["evidence"]] += 1
    return counts


def wide_roles(sites, channel: str = "") -> dict:
    """``{роль: сколько}`` — по каналу либо по всем площадкам, если он пуст."""
    roles = {role: 0 for role in WIDE_ROLES}
    for site in sites:
        if channel and site["channel"] != channel:
            continue
        roles[site.get("role") or ROLE_UNMEASURED] += 1
    return roles


# ── ось ВОЗРАСТА записи: что СПРАШИВАЕТ читатель (заказ G106 п. 1) ───────────
#
# Заказ ADR-528 поставлен дословно так:
#
#     **`retention-days` есть выбор, а не замер.** Запись теперь переживает
#     раннер и не переживает 14 дней. Спросить надо не «поставить ли больше»,
#     а **какой возраст записи реально спрашивает хоть один читатель** — и
#     мерить это у читателя, а не у настройки. Три исхода обязательны.
#
# Соблазн здесь тот же, что у предела печати: поднять `retention-days` с 14 до
# 90 и считать дело сделанным. Вопрос «поставить ли больше» задан настройке, а
# отвечать на него может только СПРОС, и спрос живёт у читателя.
#
# ## Хранилищ ТРИ, и срок жизни у них разный — это и есть суть замера
#
# ============================= ==============================================
# `local_filesystem_of_the_run` живёт ровно прогон. `retention-days` не
#                               governs ничего: читатель получает запись,
#                               которую сам же и произвёл ⇒ спрашиваемый
#                               возраст ИЗМЕРЕН и равен нулю
# `artifact_store`              единственное хранилище, чей срок жизни и ЕСТЬ
#                               `retention-days`. Обращение к нему видно
#                               признаком (`_FETCH_MARKS`)
# `run_log_store`               лог шага и `conclusion` прогона. Их срок
#                               назначает настройка РЕПОЗИТОРИЯ, которой в
#                               дереве нет ВОВСЕ ⇒ НЕ ИЗМЕРЕНО с названной
#                               причиной, а не «90 дней» по памяти
# ============================= ==============================================
#
# Склеить их значило бы потерять ровно то различие, ради которого заказ и
# написан: мы крутим ОДИН винт (`retention-days`), а читают из ДРУГИХ двух
# хранилищ, и у одного из них винта в дереве нет.
#
# ## Три исхода обязательны (инв. #17)
#
# «Возраст ИЗМЕРЕН и равен нулю» (читатель берёт запись своего прогона),
# «возраст спрашивается у хранилища артефактов» и «срок хранилища в дереве не
# объявлен» — три РАЗНЫХ ответа. Четвёртый, `demand_unmeasured`, — площадка не
# разобрана.
#
# ## Ноль спроса есть ХРАПОВИК, а не вечная зелень
#
# Сегодня хранилище артефактов не спрашивает НИ ОДИН читатель дерева, и вердикт
# `nobody_asks_the_artifact_store` стои́т с кодом 0. Появление первого
# скачивающего (`gh run download` и родня) переводит вердикт в
# `a_named_reader_asks_the_artifact_store` и ПОДНИМАЕТ код до 1: с этого дня
# вопрос «14 дней — достаточно ли» становится живым и обязан быть задан
# замером, а не выбран. Красный тут значит «появился спрос», а не «стало хуже».

#: Исходы спроса. Перечень ЗАКРЫТ, сумма равна населению оси.
DEMAND_ARTIFACT = "asks_the_artifact_store"
DEMAND_LOCAL = "asks_the_record_of_its_own_run"
DEMAND_RUN_LOG = "asks_the_run_log_store"
DEMAND_UNMEASURED = "demand_unmeasured"
DEMANDS: tuple[str, ...] = (DEMAND_ARTIFACT, DEMAND_LOCAL, DEMAND_RUN_LOG,
                            DEMAND_UNMEASURED)

#: Хранилище, у которого читатель спрашивает запись. Перечень ЗАКРЫТ.
STORE_LOCAL = "local_filesystem_of_the_run"
STORE_ARTIFACT = "artifact_store"
STORE_RUN_LOG = "run_log_store"
STORE_UNMEASURED = "store_unmeasured"

#: Канал → (исход спроса, хранилище). Карта ОБЪЯВЛЕНА, а не выведена по ходу:
#: канал уже измерен двумя осями выше, и второй раз о нём не судят.
_CHANNEL_DEMAND: dict[str, tuple[str, str]] = {
    CH_LOCAL_RECORD: (DEMAND_LOCAL, STORE_LOCAL),
    CH_STEP_LOG: (DEMAND_RUN_LOG, STORE_RUN_LOG),
    CH_API: (DEMAND_RUN_LOG, STORE_RUN_LOG),
    CH_UNMEASURED: (DEMAND_UNMEASURED, STORE_UNMEASURED),
}

#: Признак обращения к ХРАНИЛИЩУ АРТЕФАКТОВ — к тому единственному, чей срок
#: жизни назначает `retention-days`. Форма, а не намёк: каждая из этих строк
#: есть команда или действие, скачивающее артефакт прогона.
_FETCH_MARKS: tuple[str, ...] = (
    "gh run download",
    "/actions/artifacts",
    "actions/download-artifact",
    "dawidd6/action-download-artifact",
)

#: Метки, которыми ПИСАТЕЛЬ объявляет путь записи. В воркфлоу они стоят ровно у
#: шага, который запись и создаёт (``record_paths`` ищет их там же), поэтому
#: площадка-воркфлоу с такой меткой есть ПИСАТЕЛЬ, а не читатель: спрашивать у
#: производителя, какой возраст он спрашивает, значило бы считать спрос у того,
#: кто его не предъявляет. ``<testsuite`` в этот перечень не входит намеренно —
#: это чтение готовой записи, а не её объявление.
_WRITER_DECLARATION_MARKS: tuple[str, ...] = ("junitxml", "SPA_PYTEST_STREAM")

#: Почему `run_log_store` не несёт числа. Причина называется ОДИН раз и
#: печатается у каждой строки исхода: «не измерено» без причины и есть то
#: молчание, которое инв. #17 запрещает.
RUN_LOG_WHY = ("срок жизни лога и метаданных прогона назначает настройка "
               "РЕПОЗИТОРИЯ (retention period), которой в дереве нет ни одной "
               "строкой — это НЕ ИЗМЕРЕНО, а не 90 дн. по памяти")

#: Исходы объявленного СРОКА у шага выгрузки. Перечень ЗАКРЫТ.
RET_DECLARED = "retention_declared"
RET_NOT_DECLARED = "retention_not_declared"
RET_UNMEASURED = "retention_unmeasured"
RETENTIONS: tuple[str, ...] = (RET_DECLARED, RET_NOT_DECLARED, RET_UNMEASURED)

#: Вердикт оси. Перечень ЗАКРЫТ.
ANSWER_NOBODY = "nobody_asks_the_artifact_store"
ANSWER_ASKED = "a_named_reader_asks_the_artifact_store"
ANSWER_UNMEASURED = "demand_unmeasured"
ANSWERS: tuple[str, ...] = (ANSWER_NOBODY, ANSWER_ASKED, ANSWER_UNMEASURED)

#: Цены односторонности ЭТОЙ оси — названы заранее и каждая со стороной ошибки.
AGE_PRICES: tuple[str, ...] = (
    "человек, скачавший артефакт кнопкой в UI GitHub, не наблюдаем ни одним "
    "признаком дерева — ошибка в сторону ЗАНИЖЕНИЯ спроса, никогда в сторону "
    "выдуманного читателя",
    "срок хранения лога и метаданных прогона есть настройка РЕПОЗИТОРИЯ: в "
    "дереве её нет, и числа у этого хранилища поэтому нет — НЕ ИЗМЕРЕНО",
    "`retention-days` читается только литералом: `${{ … }}` даёт "
    "`retention_unmeasured`, а не число и не «по умолчанию»",
    "запись, пришедшая к читателю через промежуточного помощника, числится по "
    "метке ЕГО файла: через границу вызова ось не ходит — та же цена, что у "
    "узкой оси читателей",
    "покрытие пути выгрузки решается на литералах (цена главной оси), поэтому "
    "«несёт запись» у шага выгрузки есть НИЖНЯЯ граница",
)


def _retention_axis(workflows: dict | None):
    """Объявленный срок у КАЖДОГО шага выгрузки + несёт ли он запись имён.

    Возвращает ``(rows, counts)``. Срок меряется у ВОРКФЛОУ, а не
    перепечатывается из текста правила: число 14 в заказе есть замер своего
    дня, и перепечатать его было бы ровно тем дефектом, на котором
    ``.claude/rules/site-numbers.md`` поймала саму себя.
    """
    rows: list[dict] = []
    for wf_name, doc in sorted((workflows or {}).items()):
        for job_name, steps in _steps_of(doc):
            records: list[str] = []
            for step in steps:
                if _is_pytest_step(step):
                    records.extend(path for _form, path in record_paths(step))
            for index, step in enumerate(steps):
                if not _is_upload_step(step):
                    continue
                raw = (step.get("with") or {}).get("retention-days")
                if raw is None:
                    outcome, days = RET_NOT_DECLARED, None
                    why = ("срока в шаге нет ⇒ его назначает настройка "
                           "РЕПОЗИТОРИЯ, которой в дереве нет — НЕ ИЗМЕРЕНО")
                elif _EXPRESSION.search(str(raw)):
                    outcome, days, why = RET_UNMEASURED, None, f"выражение: {raw}"
                else:
                    try:
                        days, outcome, why = int(str(raw).strip()), RET_DECLARED, ""
                    except ValueError:
                        outcome, days = RET_UNMEASURED, None
                        why = f"срок не число: {raw!r}"
                carries: list[str] = []
                undecided = 0
                for upload_path in _upload_paths(step):
                    for record in records:
                        covered = _covers(upload_path, record)
                        if covered is True:
                            carries.append(record)
                        elif covered is None:
                            undecided += 1
                rows.append({
                    "workflow": wf_name, "job": job_name,
                    "step": str(step.get("name") or f"#{index}"),
                    "outcome": outcome, "days": days, "why": why,
                    "carries_record": sorted(set(carries)),
                    "coverage_undecided": undecided,
                })
    counts = {name: 0 for name in RETENTIONS}
    for row in rows:
        counts[row["outcome"]] += 1
    return rows, counts


def _fetch_axis(root: str, workflows: dict | None):
    """Площадки, обращающиеся к ХРАНИЛИЩУ АРТЕФАКТОВ, по всему дереву.

    Отдельный обход, а не поле соседней оси, и это ВЫБОР с причиной: соседняя
    ось отбрасывает файл без метки канала (``if not raw: continue``), а
    скачивающий артефакт может не читать вердикт вовсе — тогда он для неё не
    существует. Цена выбора — второй проход по дереву; плата за совмещение
    была бы слепота ровно к тому, о чём спрашивает заказ.

    Возвращает ``(sites, scanned, unmeasured)``. Проза отделена от исполняемого
    текста ТЕМ ЖЕ правилом, что у оси читателей: упоминание команды в
    комментарии ничего не скачивает.
    """
    sites: list[dict] = []
    scanned = {kind: 0 for kind in WIDE_KINDS}
    unmeasured: list[dict] = []

    def _marks(text: str) -> tuple[str, ...]:
        return tuple(mark for mark in _FETCH_MARKS if mark in text)

    def _add(kind: str, rel: str, executed: str, prose: str) -> None:
        seen = set()
        for mark in _marks(executed):
            seen.add(mark)
            sites.append({"kind": kind, "site": rel, "mark": mark,
                          "evidence": EV_EXEC})
        for mark in _marks(prose):
            if mark in seen:
                continue
            sites.append({"kind": kind, "site": rel, "mark": mark,
                          "evidence": EV_PROSE})

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in sorted(dirnames) if d not in _WIDE_SKIP_DIRS]
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                kind = KIND_CODE
            elif filename.endswith(".sh"):
                kind = KIND_SHELL
            else:
                continue
            path = os.path.join(dirpath, filename)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if rel in READER_EXCLUSIONS:
                continue
            scanned[kind] += 1
            try:
                text = open(path, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError) as exc:
                unmeasured.append({"kind": kind, "site": rel,
                                   "reason": f"{type(exc).__name__}: {exc}"})
                continue
            if not _marks(text):
                continue
            if kind == KIND_CODE:
                try:
                    executed, prose = _python_text(text)
                except _Unparsed as exc:
                    for mark in _marks(text):
                        sites.append({"kind": kind, "site": rel, "mark": mark,
                                      "evidence": EV_UNMEASURED})
                    unmeasured.append({"kind": kind, "site": rel,
                                       "reason": f"разобрать нечем: {exc}"})
                    continue
            else:
                executed, prose = _shell_text(text)
            _add(kind, rel, executed, prose)

    for name, doc in sorted((workflows or {}).items()):
        scanned[KIND_WORKFLOW] += 1
        _add(KIND_WORKFLOW, f".github/workflows/{name}",
             "\n".join(_yaml_strings(doc)), "")

    for rel in _protocol_docs(root, unmeasured):
        path = os.path.join(root, *rel.split("/"))
        try:
            text = open(path, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError) as exc:
            unmeasured.append({"kind": KIND_DOC, "site": rel,
                               "reason": f"{type(exc).__name__}: {exc}"})
            continue
        scanned[KIND_DOC] += 1
        _add(KIND_DOC, rel, *_doc_text(text))
    return sites, scanned, unmeasured


def _age_demand_axis(readers, wide_sites, fetch_sites):
    """Что СПРАШИВАЕТ каждый измеренный читатель: возраст и ХРАНИЛИЩЕ.

    Население оси НЕ изобретается заново: это читатели, уже измеренные двумя
    осями выше, — узкая целиком плюс те площадки широкой, у которых метка стои́т
    в ИСПОЛНЯЕМОМ тексте. Площадка, у которой метка только в прозе, спроса не
    предъявляет (проза ничего не читает), и число таких печатается — ноль без
    знаменателя был бы утверждением о приборе, а не о дереве.
    """
    fetch_by_site: dict[str, list[str]] = {}
    for site in fetch_sites:
        if site["evidence"] != EV_EXEC:
            continue
        fetch_by_site.setdefault(site["site"], []).append(site["mark"])

    rows: list[dict] = []
    prose_only = 0
    writer_sites = 0
    seen: set[tuple[str, str]] = set()

    def _row(site: str, channel: str, kind: str) -> None:
        key = (site, channel)
        if key in seen:
            return
        seen.add(key)
        fetched = sorted(set(fetch_by_site.get(site, ())))
        if fetched:
            # Скачивание ПЕРЕБИВАЕТ канал: файл может читать `conclusion` И
            # тянуть артефакт, и спрос к хранилищу артефактов тут главный —
            # именно его срок назначает `retention-days`.
            demand, store, age_days, why = (DEMAND_ARTIFACT, STORE_ARTIFACT,
                                            None, "")
        else:
            demand, store = _CHANNEL_DEMAND.get(
                channel, (DEMAND_UNMEASURED, STORE_UNMEASURED))
            if demand == DEMAND_LOCAL:
                age_days, why = 0, ("запись своего прогона: `retention-days` "
                                    "её не касается вовсе")
            elif demand == DEMAND_RUN_LOG:
                age_days, why = None, RUN_LOG_WHY
            else:
                age_days, why = None, f"канал не разобран: {channel}"
        rows.append({"site": site, "kind": kind, "channel": channel,
                     "demand": demand, "store": store, "age_days": age_days,
                     "why": why, "fetch_marks": fetched})

    for reader in readers or ():
        _row(reader["reader"], reader["channel"], KIND_CODE)
    for site in wide_sites or ():
        if site["evidence"] == EV_PROSE:
            prose_only += 1
            continue
        if (site["kind"] == KIND_WORKFLOW
                and site.get("mark") in _WRITER_DECLARATION_MARKS):
            writer_sites += 1   # производитель записи: спроса не предъявляет
            continue
        if site["evidence"] == EV_UNMEASURED:
            _row(site["site"], CH_UNMEASURED, site["kind"])
            continue
        _row(site["site"], site["channel"], site["kind"])

    counts = {name: 0 for name in DEMANDS}
    for row in rows:
        counts[row["demand"]] += 1
    # Скачивающая площадка ВНЕ населения читателей — находка о самом населении:
    # она спрашивает хранилище артефактов, а ни одна ось её читателем не зовёт.
    outside = sorted({site for site in fetch_by_site
                      if site not in {row["site"] for row in rows}})
    return rows, counts, {"prose_only": prose_only,
                          "writer_sites": writer_sites}, outside


def age_answer(doc: dict) -> dict:
    """Вердикт оси возраста + оба числа, которые обязаны стоять рядом.

    «Спроса нет» без объявленного СРОКА было бы утверждением ни о чём: сравнить
    нечего. Поэтому рядом всегда печатаются и спрос, и предложение, и у каждого
    свой третий исход.
    """
    counts = doc.get("age_demand_counts") or {}
    rows = doc.get("age_demand_rows") or []
    retention = doc.get("retention_rows") or []
    carrying = [row for row in retention if row["carries_record"]]
    declared = [row["days"] for row in carrying
                if row["outcome"] == RET_DECLARED and row["days"] is not None]
    shortest = min(declared) if declared else None
    unmeasured_supply = [row for row in carrying
                         if row["outcome"] != RET_DECLARED]
    if not rows or counts.get(DEMAND_UNMEASURED):
        label = ANSWER_UNMEASURED
    elif counts.get(DEMAND_ARTIFACT):
        label = ANSWER_ASKED
    else:
        label = ANSWER_NOBODY
    return {
        "label": label,
        "shortest_record_retention_days": shortest,
        "record_carrying_uploads": len(carrying),
        "supply_unmeasured": len(unmeasured_supply),
        "asking_sites": sorted(row["site"] for row in rows
                               if row["demand"] == DEMAND_ARTIFACT),
        "outside_population": list(doc.get("fetch_outside_population") or ()),
    }


def _age_lines(doc: dict) -> list[str]:
    """Строки оси возраста. Каждый ноль объявлен, оба числа стоят РЯДОМ."""
    counts = doc.get("age_demand_counts") or {name: 0 for name in DEMANDS}
    rows = doc.get("age_demand_rows") or []
    answer = age_answer(doc)
    ret_counts = doc.get("retention_counts") or {name: 0 for name in RETENTIONS}
    scanned = doc.get("fetch_scanned") or {}
    lines = [
        "  ось ВОЗРАСТА записи (заказ G106 п. 1; спрос мерится у ЧИТАТЕЛЯ, а не "
        f"у настройки): население {len(rows)} читател(ь/я/ей); исключены с "
        "причиной — площадок только с прозой "
        f"{(doc.get('age_excluded') or {}).get('prose_only', 0)}, "
        "воркфлоу-ПИСАТЕЛЕЙ записи "
        f"{(doc.get('age_excluded') or {}).get('writer_sites', 0)}",
        "    " + " · ".join(f"{name} {counts.get(name, 0)}" for name in DEMANDS),
        "    предложение (объявленный срок у шагов выгрузки, ЗАМЕРОМ у воркфлоу): "
        + " · ".join(f"{name} {ret_counts.get(name, 0)}" for name in RETENTIONS)
        + f"; из них несут запись имён {answer['record_carrying_uploads']}, "
        + (f"короткий срок {answer['shortest_record_retention_days']} дн."
           if answer["shortest_record_retention_days"] is not None
           else "короткий срок НЕ ИЗМЕРЕН")
        + f"; срок не измерен у {answer['supply_unmeasured']} несущ(его/их) запись",
        "    скачивающих площадок просмотрено: "
        + " · ".join(f"{kind} {scanned.get(kind, 0)}" for kind in WIDE_KINDS),
    ]
    for row in rows:
        if row["demand"] == DEMAND_LOCAL:
            continue  # ноль возраста уже назван счётчиком; строка не добавляет
        lines.append(f"    [{row['demand']} · {row['store']}] {row['site']}"
                     + (f" — {row['why']}" if row["why"] else "")
                     + (f" — скачивает: {', '.join(row['fetch_marks'])}"
                        if row["fetch_marks"] else ""))
    if answer["label"] == ANSWER_NOBODY:
        lines.append(
            "    ОТВЕТ ЗАКАЗА: хранилище артефактов не спрашивает НИ ОДИН "
            f"измеренный читатель (из {len(rows)}), поэтому "
            + (f"срок {answer['shortest_record_retention_days']} дн. "
               if answer["shortest_record_retention_days"] is not None
               else "объявленный срок ")
            + "не связывает никого из них: это ВЫБОР, а не замер. Возраст, "
            "который спрос действительно предъявляет, ИЗМЕРЕН и равен нулю — "
            f"{counts.get(DEMAND_LOCAL, 0)} читател(ь/я/ей) берут запись своего "
            "же прогона; у "
            f"{counts.get(DEMAND_RUN_LOG, 0)} спрос есть, но его хранилище — "
            "лог прогона, и его срок в дереве НЕ ОБЪЯВЛЕН вовсе")
    elif answer["label"] == ANSWER_ASKED:
        lines.append(
            "    ОТВЕТ ЗАКАЗА: хранилище артефактов спрашивают поимённо — "
            + ", ".join(answer["asking_sites"])
            + ". С этого дня вопрос «достаточно ли "
            + (f"{answer['shortest_record_retention_days']} дн."
               if answer["shortest_record_retention_days"] is not None
               else "объявленного срока")
            + "» ЖИВОЙ и обязан быть отвечен замером спроса, а не выбран")
    else:
        lines.append("    ОТВЕТ ЗАКАЗА: НЕ ИЗМЕРЕНО — спрос не разобран "
                     f"({counts.get(DEMAND_UNMEASURED, 0)} читател(ь/я/ей) "
                     "без разобранного канала либо население пусто); «никто не "
                     "спрашивает» о них НЕ сказано")
    for site in answer["outside_population"]:
        lines.append(f"    [СКАЧИВАЕТ, НО ЧИТАТЕЛЕМ НЕ ЗОВЁТСЯ] {site} — "
                     "площадка спрашивает хранилище артефактов, а ни одна ось "
                     "читателей её не видит: находка о НАСЕЛЕНИИ, не о сроке")
    for row in doc.get("fetch_unmeasured") or ():
        lines.append(f"    [НЕ ИЗМЕРЕНА ПЛОЩАДКА СКАЧИВАНИЯ] {row['kind']} :: "
                     f"{row['site']}: {row['reason']}")
    for price in AGE_PRICES:
        lines.append(f"    ЦЕНА ОДНОСТОРОННОСТИ: {price}")
    return lines


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


def _wide_lines(doc: dict) -> list[str]:
    """Строки второй оси: НИЖНЯЯ ГРАНИЦА узкого числа, роды, доказательства.

    Печатается во ВСЕХ ветках отчёта, включая «писательская ось не измерена»:
    вторая ось ходит по дереву и от разбора воркфлоу не зависит, а молчание о
    ней читалось бы как её ноль.
    """
    sites = doc.get("wide_sites") or []
    counts = doc.get("wide_counts") or wide_counts(sites)
    scanned = doc.get("wide_scanned") or {}
    kinds_unmeasured = doc.get("wide_kind_unmeasured") or {}
    narrow = (doc.get("reader_counts") or {}).get(CH_STEP_LOG)
    narrow_text = narrow if isinstance(narrow, int) else "НЕ ИЗМЕРЕНО"
    narrow_scanned = doc.get("reader_files_scanned")

    lines = ["  ось читателей ВНЕ узкого населения (заказ G106 п. 3; узкое — "
             f"{narrow_scanned if narrow_scanned is not None else 'НЕ ИЗМЕРЕНО'}"
             " файл(ов) .py каталогов scripts/ и spa_core/monitoring/): "
             + " · ".join(f"{kind} {scanned.get(kind, 0)}" for kind in WIDE_KINDS)]
    for channel in READER_CHANNELS:
        row = counts.get(channel) or {ev: 0 for ev in WIDE_EVIDENCE}
        lines.append(f"    {channel}: "
                     + " · ".join(f"{ev} {row.get(ev, 0)}" for ev in WIDE_EVIDENCE))
    roles = wide_roles(sites, CH_STEP_LOG)
    lines.append(f"    роль площадки у {CH_STEP_LOG} (зов писателя чтением НЕ "
                 "является): " + " · ".join(f"{role} {roles[role]}"
                                            for role in WIDE_ROLES))
    for site in sites:
        if site["channel"] != CH_STEP_LOG:
            continue
        lines.append(f"    [{site['evidence']} · {site.get('role')}] {site['kind']}"
                     f" :: {site['site']} — метка «{site['mark']}»")
    step = counts.get(CH_STEP_LOG) or {}
    found = sum(step.get(ev, 0) for ev in WIDE_EVIDENCE)
    executed = step.get(EV_EXEC, 0)
    if found:
        lines.append(f"    ВЫВОД ЗАКАЗА: узкое число канала {CH_STEP_LOG} "
                     f"({narrow_text}) ЕСТЬ НИЖНЯЯ ГРАНИЦА — вне узкого населения "
                     f"найдено площадок {found}, из них метка в исполняемом "
                     f"тексте у {executed}; лог ЧИТАЕТ "
                     f"{roles[ROLE_READS]}, писателя ЗОВЁТ {roles[ROLE_INVOKES]}, "
                     f"форма не разобрана у {roles[ROLE_UNMEASURED]}")
    else:
        lines.append(f"    ВЫВОД ЗАКАЗА: вне узкого населения площадок канала "
                     f"{CH_STEP_LOG} не найдено; это НЕ подтверждает ноль — "
                     "односторонность остаётся, и цены её названы ниже")
    for kind, reason in sorted(kinds_unmeasured.items()):
        lines.append(f"    [НЕ ИЗМЕРЕН РОД] {kind}: {reason}")
    for row in doc.get("wide_site_unmeasured") or []:
        lines.append(f"    [НЕ ИЗМЕРЕНА ПЛОЩАДКА] {row['kind']} :: {row['site']}"
                     f": {row['reason']}")
    for price in LOWER_BOUND_PRICES:
        lines.append(f"    ЦЕНА НИЖНЕЙ ГРАНИЦЫ: {price}")
    return lines


def format_report(doc: dict) -> str:
    """Отчёт для шага 0-офис. Каждый ноль объявлен (инв. #17)."""
    if doc.get("unmeasured_reason"):
        return "\n".join(["НЕ ИЗМЕРЕНО: имена упавших тестов (ось ПИСАТЕЛЯ) — "
                          f"{doc['unmeasured_reason']}"]
                         + _wide_lines(doc) + _age_lines(doc))
    if not doc.get("population"):
        # Пустое население печаталось бы как «все нули», то есть как ЧИСТО —
        # это класс `vacuous_guard_census`, и он fail-OPEN тише красного.
        return "\n".join(["НЕ ИЗМЕРЕНО: имена упавших тестов — ни одного шага, "
                           "запускающего pytest, не найдено; ноль исходов на "
                           "пустом населении не есть «чисто»"]
                          + _wide_lines(doc) + _age_lines(doc))
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
    lines.extend(_wide_lines(doc))
    lines.extend(_age_lines(doc))
    if counts[SURVIVES] == 0 and doc["population"]:
        lines.append("  ВЫВОД: раннер не покидает НИ ОДНА запись имён ⇒ доступа к "
                     f"полному перечню нет ни у одного из {len(doc.get('readers') or ())} "
                     "измеренных читателей, и от предела печати это не зависит")
    lines.append("  НЕ ДОКЛАДЫВАЕТ: читает ли названный читатель канал на самом деле · "
                 "pytest, позванный из скрипта-обёртки · четвёртую форму записи · "
                 "исполнил ли GitHub объявленный срок (это свойство сервиса, не "
                 "дерева) · срок хранения лога и метаданных прогона — настройки "
                 "репозитория в дереве нет ни одной строкой")
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
    writer_rc = {"unmeasured": 2, "names_die_with_the_runner": 1,
                 "names_outlive_the_runner": 0}[label]
    # Худший из двух осей, а не только писательский: род, про который вопрос
    # остался без ответа ВОВСЕ, обязан быть отличим от успеха (инв. #17).
    # Неизмеренная ПЛОЩАДКА кода не поднимает — она печатается строкой, и
    # поднимать из-за одного нечитаемого файла вердикт обо всей оси значило бы
    # потерять разницу между «рода не видно» и «один файл не разобран».
    reader_rc = 2 if doc.get("wide_kind_unmeasured") else 0
    # Третья ось (возраст записи, заказ G106 п. 1) ПОВЫШАЕТ код своим исходом, и
    # ноль спроса здесь работает ХРАПОВИКОМ: пока хранилище артефактов не
    # спрашивает никто, объявленный срок никого не связывает (код 0); первая же
    # появившаяся скачивающая площадка делает вопрос «достаточно ли срока»
    # живым (код 1). Неразобранный спрос — 2: «никто не спрашивает» о нём не
    # сказано. Площадка, не прочитанная по одной ошибке ввода-вывода, кода не
    # поднимает — она печатается строкой (то же правило, что у соседней оси).
    age_rc = {ANSWER_NOBODY: 0, ANSWER_ASKED: 1, ANSWER_UNMEASURED: 2}[
        age_answer(doc)["label"]]
    return max(writer_rc, reader_rc, age_rc)


if __name__ == "__main__":
    sys.exit(main())
