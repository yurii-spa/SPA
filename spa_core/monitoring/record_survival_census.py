# LLM_FORBIDDEN
"""Переживает ли запись прогона ОТМЕНУ (заказ G109 п. 1, ADR-534).

Заказ поставлен дословно так:

    **Запись не покидает раннер в 79 % прогонов, и это теперь ИЗМЕРЕНО числом.**
    Выгрузка под ``!cancelled()`` верна, ``always()`` ставить нельзя. Спросить
    надо другое: **что из записи можно сохранить ДО отмены** — например,
    складывать РАЗБОР (а не 34 МБ записи) в конце каждого шага. Мерить по
    ИСХОДУ: доля прогонов, у которых разбор уцелел.

## Почему вопрос задаётся УСЛОВИЮ, а не размеру

Посылка заказа называет виновником РАЗМЕР («34 МБ записи») и предлагает лечить
его сжатием предмета — складывать разбор вместо записи. Прибор меряет цену, и
цена говорит обратное: вся запись целиком уже выгружается за **секунды**
(наблюдённая длительность шага выгрузки — ось ``price``), а в хранилище она
едет сжатой, то есть «34 МБ» есть размер НА ДИСКЕ, а не то, что передаётся.
Если цена выгрузки измерима секундами, то сжимать предмет незачем: запись
теряет не вес, а **условие шага**.

Поэтому ось A спрашивает у ВОРОТ: покрывает ли условие шага выгрузки путь
ОТМЕНЫ. ``!cancelled()`` не покрывает его ПО ПОСТРОЕНИЮ — и это верный ответ
на СВОЙ вопрос (на пути отказа выгрузка работает), но не на нужный, потому что
отмена есть ГЛАВНЫЙ путь прогона, а не краевой.

## Сосед отвечает на другой вопрос, и его зелёный ответ верен

``failed_name_survival_census`` (ADR-528, заказ G87 п. 1) спрашивает, переживает
ли запись **ОТКАЗ**: пишется ли она, покрывает ли её выгрузка, исполняется ли
выгрузка после упавшего шага. Его исход ``record_survives_as_artifact`` сегодня
верен. Этот прибор не является поправкой к нему и его не правит (инв. #16):
предмет другой — **путь ОТМЕНЫ**, которого у соседа нет среди исходов вовсе.
Разделение предметов закреплено тестом.

## Доля считается по НАСЕЛЕНИЮ С ДОСТАВЛЕННЫМ ЛЕКАРСТВОМ, а не по всем прогонам

Шаг выгрузки появился только с ADR-528 (28.09). Прогон, чей воркфлоу шага не
объявлял, в знаменатель доли не входит: у него запись потеряна потому, что
лекарства ЕЩЁ НЕ БЫЛО, а не потому, что оно не сработало. Склеить два класса
значило бы размазать отказ механизма по отсутствию механизма — поэтому ось A
читается у воркфлоу **того sha, на котором шёл прогон**, а не у сегодняшнего
дерева. Клон без этого sha ⇒ ``door_unmeasured``, а не «шага нет».

## Исходы ЗАКРЫТЫ, и срок хранения — отдельный исход

================================= ======================================
``survived``                      запись покинула раннер и доступна сейчас
``expired``                       строка есть, но ``expired`` взведён
``absent``                        записи нет, и прогон МЛАДШЕ срока хранения
``absent_beyond_retention_term``  записи нет, и прогон СТАРШЕ срока хранения
``unmeasured``                    не разобрано, с названной причиной
================================= ======================================

``expired`` склеивать с ``absent`` нельзя: в первом случае механизм СРАБОТАЛ и
запись унёс срок хранения (``retention-days``), во втором её не было никогда.

``absent_beyond_retention_term`` отделён по той же причине, но от ДРУГОГО
смешения: после срока GitHub удаляет саму СТРОКУ об артефакте, а не только
взводит ``expired`` (замер 09.10: строк с ``expired: true`` в окне НОЛЬ при
``retention-days: 14`` и окне 19 дн.), поэтому «не выгружали» и «унёс срок»
в API НЕОТЛИЧИМЫ. Такой прогон не идёт в долю ни числителем, ни знаменателем:
иначе доля падала бы сама от хода календаря. Срок читается ТОЛЬКО литералом;
``${{ … }}`` даёт «срок не измерен», и тогда отсутствие записи есть
``unmeasured``, а не отсутствие.

## Цена `always()` обязана быть ЧИСЛОМ, а не доводом

Ось ``price`` берёт длительность шага выгрузки и размер артефакта у тех
прогонов, где выгрузка исполнилась. Выборка названа своим размером: цена
измерена на тех прогонах, где её вообще можно наблюдать, и это НИЖНЯЯ граница
знания о ней, а не свойство всех прогонов. Нет ни одного такого прогона ⇒ цена
``None`` с причиной, а не ноль.

## Сеть есть ВХОД, и её отсутствие — третий исход

``fetch`` инъектируется. Нет токена, сеть недоступна, ответ не разобран ⇒
``UNMEASURED`` с названной причиной и ненулевой код возврата. Ноль прогонов
никогда не выдаётся за «ничего не терялось»: слепой проход назван отдельно.

**ADVISORY.** Прибор только ЧИТАЕТ: ни одного порога, ни одной базы храповика,
ни одного файла воркфлоу он не меняет. RiskPolicy v1.0, стоп-кран, аллокатор,
живой трек и ``landing/`` не задеты.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed

ARTIFACT_NAME = "record_survival_census.json"
ORDER = ("G109 п. 1 (ADR-534) — что из записи можно сохранить ДО отмены; "
         "доля прогонов, у которых разбор уцелел")

STATUS_OPEN = "CLASS_OPEN"
STATUS_CLOSED = "CLASS_CLOSED"
STATUS_UNMEASURED = "UNMEASURED"

#: Репозиторий и воркфлоу — ВХОДЫ, объявленные литералом: предмет заказа есть
#: именно шаг тестов `test.yml`, и подставлять сюда что-то другое значило бы
#: ответить на другой вопрос под тем же именем.
DEFAULT_REPO = "yurii-spa/SPA"
WORKFLOW_FILE = ".github/workflows/test.yml"
WORKFLOW_JOB = "test"

#: Имя записи, объявленное ПИСАТЕЛЕМ (`test-records-<нога>-<номер>`). Префикс, а
#: не полное имя: номер ноги и прогона часть имени, и сверять по ним нечего.
RECORD_PREFIX = "test-records-"

#: Путь, который объявляет ПИСАТЕЛЬ записи. Выгрузка обязана его ПОКРЫВАТЬ —
#: имя шага доказательством не является (урок соседа ADR-528).
WRITER_DIR = "reports"

#: Окно населения — ВХОД. Умолчание взято у предела страницы API (3 страницы по
#: 100): меньше окна население перестаёт быть сравнимым с замером ADR-534
#: («300 прогонов 12.09–02.10»), больше — упирается в срок жизни строк об
#: артефактах, после которого ось исхода честно отвечает «не измерено».
DEFAULT_WINDOW_RUNS = 300
_PAGE = 100

#: Потолок страниц у КАЖДОГО перечня — ВХОД, а не придирка к чистоте. Найден
#: мутационным замером: пагинация выходила только по «страница короче полной», и
#: при ответе, который всегда полон, оба перечня крутились БЕСКОНЕЧНО, а батарея
#: не краснела и не проходила — она ИСЧЕЗАЛА (зависала). Потолок взят с запасом
#: к объявленному окну (300 прогонов = 3 страницы; строк записей в репозитории
#: 410 = 5 страниц), а его достижение есть ТРЕТИЙ ИСХОД с названной причиной, а
#: не молчаливый обрыв перечня: обрезанное население выдало бы себя за полное.
MAX_PAGES = 50

API_ROOT = "https://api.github.com"

# ───────────────────────────── классы ВОРОТ ───────────────────────────────

DOOR_ALWAYS = "always"
DOOR_NOT_CANCELLED = "not_cancelled"
DOOR_UNCONDITIONAL = "unconditional"
DOOR_OTHER_CONDITION = "other_condition"
DOOR_STEP_NOT_COVERING = "step_does_not_cover_writer"
DOOR_NO_STEP = "no_upload_step"
DOOR_UNMEASURED = "door_unmeasured"

DOOR_CLASSES: Tuple[str, ...] = (
    DOOR_ALWAYS, DOOR_NOT_CANCELLED, DOOR_UNCONDITIONAL, DOOR_OTHER_CONDITION,
    DOOR_STEP_NOT_COVERING, DOOR_NO_STEP, DOOR_UNMEASURED,
)

#: Покрывает ли класс ВОРОТ путь ОТМЕНЫ. ``None`` — третий исход: условие
#: разобрано как выражение, но его значение при отмене прибором не выводится.
#: Гадать здесь запрещено: `fail-CLOSED` означает «не знаю», а не «покрывает».
DOOR_COVERS_CANCELLATION: Dict[str, Optional[bool]] = {
    DOOR_ALWAYS: True,
    DOOR_NOT_CANCELLED: False,
    DOOR_UNCONDITIONAL: False,
    DOOR_OTHER_CONDITION: None,
    DOOR_STEP_NOT_COVERING: False,
    DOOR_NO_STEP: False,
    DOOR_UNMEASURED: None,
}

# ───────────────────────────── классы ИСХОДА ──────────────────────────────

OUT_SURVIVED = "survived"
OUT_EXPIRED = "expired"
OUT_ABSENT = "absent"
#: Прогон старше объявленного срока хранения, у которого строк записи НЕТ. Это
#: НЕ «записи не было»: GitHub удаляет саму СТРОКУ об артефакте, а не только
#: взводит `expired`, поэтому после срока «не выгружали» и «унёс срок» в API
#: НЕОТЛИЧИМЫ. Замер 09.10: во окне 300 прогонов (19 дн.) при `retention-days: 14`
#: строк с `expired: true` НОЛЬ — то есть молчание здесь не про сохранность.
#: Склеить этот класс с `absent` значило бы сделать долю зависящей от того, когда
#: её мерили: один и тот же прогон попадал бы то в числитель, то в знаменатель.
OUT_BEYOND_TERM = "absent_beyond_retention_term"
OUT_UNMEASURED = "unmeasured"

OUTCOMES: Tuple[str, ...] = (OUT_SURVIVED, OUT_EXPIRED, OUT_ABSENT,
                             OUT_BEYOND_TERM, OUT_UNMEASURED)

#: Путь прогона. Берётся у `conclusion` и НЕ сворачивается: отмена и отказ — не
#: степени одного, а разные пути, и доля уцелевшего у них отличается на порядки.
PATH_UNFINISHED = "unfinished"


def path_of(conclusion: Optional[str]) -> str:
    """Путь прогона. ``None`` у `conclusion` значит «ещё идёт», а не «успех»."""
    return conclusion if conclusion else PATH_UNFINISHED


# ──────────────────────────── ось A: ВОРОТА ───────────────────────────────

def _normalise_condition(raw: Any) -> Optional[str]:
    """Условие шага без обёртки ``${{ }}`` и пробелов. ``None`` — условия нет."""
    if raw is None:
        return None
    text = str(raw).strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2].strip()
    return "".join(text.split())


def door_class_of_source(source: str) -> Tuple[str, Dict[str, Any]]:
    """Класс ВОРОТ по тексту воркфлоу.

    Разбор НАСТОЯЩИЙ (``yaml.safe_load``), а не второй самодельный: самодельный
    и есть тот дефект, который ловит ADR-522. Ввоз внутри функции — модуль
    обязан импортироваться в рантайме, где `yaml` не стоит.
    """
    detail: Dict[str, Any] = {"condition": None, "step_name": None, "path": None,
                              "retention_days": None}
    try:
        import yaml  # noqa: PLC0415 — рантайм stdlib-only, см. docstring
    except Exception as exc:  # noqa: BLE001
        detail["reason"] = f"разборщик YAML недоступен: {type(exc).__name__}: {exc}"
        return DOOR_UNMEASURED, detail
    try:
        doc = yaml.safe_load(source)
    except Exception as exc:  # noqa: BLE001
        detail["reason"] = f"воркфлоу не разобран: {type(exc).__name__}: {exc}"
        return DOOR_UNMEASURED, detail
    if not isinstance(doc, dict):
        detail["reason"] = "воркфлоу не является отображением"
        return DOOR_UNMEASURED, detail
    jobs = doc.get("jobs")
    job = jobs.get(WORKFLOW_JOB) if isinstance(jobs, dict) else None
    steps = job.get("steps") if isinstance(job, dict) else None
    if not isinstance(steps, list):
        detail["reason"] = f"в воркфлоу нет шагов джобы `{WORKFLOW_JOB}`"
        return DOOR_UNMEASURED, detail

    uploads: List[Dict[str, Any]] = [
        st for st in steps
        if isinstance(st, dict) and "upload-artifact" in str(st.get("uses") or "")
    ]
    if not uploads:
        return DOOR_NO_STEP, detail

    # Покрытие пути ПИСАТЕЛЯ, а не имя шага: шаг `Upload test results`, который
    # выгружает чужой каталог, записи не спасает (урок соседа ADR-528).
    covering = [st for st in uploads if _covers_writer(st)]
    chosen = (covering or uploads)[-1]
    detail["step_name"] = chosen.get("name")
    with_block = chosen.get("with")
    detail["path"] = (with_block or {}).get("path") if isinstance(with_block, dict) else None
    if not covering:
        return DOOR_STEP_NOT_COVERING, detail

    cond = _normalise_condition(chosen.get("if"))
    detail["condition"] = cond
    # Срок хранения читается ТОЛЬКО литералом: `${{ … }}` даёт «не измерено», а
    # не число и не умолчание сервиса — та же цена, что у соседа ADR-528.
    raw_term = (with_block or {}).get("retention-days") if isinstance(with_block, dict) else None
    detail["retention_days"] = raw_term if isinstance(raw_term, int) else None
    if cond is None:
        return DOOR_UNCONDITIONAL, detail
    if cond == "always()":
        return DOOR_ALWAYS, detail
    if cond == "!cancelled()":
        return DOOR_NOT_CANCELLED, detail
    return DOOR_OTHER_CONDITION, detail


def _covers_writer(step: Dict[str, Any]) -> bool:
    """Покрывает ли ``with.path`` шага каталог, объявленный ПИСАТЕЛЕМ."""
    with_block = step.get("with")
    if not isinstance(with_block, dict):
        return False
    raw = with_block.get("path")
    if raw is None:
        return False
    for line in str(raw).splitlines():
        candidate = line.strip().rstrip("/")
        if not candidate:
            continue
        if candidate == WRITER_DIR or candidate.startswith(WRITER_DIR + "/"):
            return True
    return False


def workflow_source_from_git(repo_root: Path) -> Callable[[str], Tuple[Optional[str], Optional[str]]]:
    """Читатель воркфлоу по sha из локального клона.

    Возвращает ``(текст, причина-отказа)``. Обрезанный клон отвечает причиной, а
    не пустой строкой: «sha в дереве нет» и «шага выгрузки нет» — разные вещи.
    """

    def read(sha: str) -> Tuple[Optional[str], Optional[str]]:
        proc = subprocess.run(
            ["git", "show", f"{sha}:{WORKFLOW_FILE}"],
            capture_output=True, text=True, cwd=str(repo_root), check=False)
        if proc.returncode != 0:
            return None, (f"sha {sha[:9]} или файл {WORKFLOW_FILE} в этом клоне "
                          f"отсутствует (git show код {proc.returncode})")
        return proc.stdout, None

    return read


# ───────────────────────────── вход: сеть ─────────────────────────────────

def github_fetch(token: Optional[str] = None) -> Callable[[str], Any]:
    """Читатель API. Отсутствие токена — исключение, а не пустой ответ."""
    tok = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT_SPA")
    if not tok:
        tok = _token_from_keychain()
    if not tok:
        raise RuntimeError("токена нет: ни GITHUB_TOKEN, ни GITHUB_PAT_SPA, "
                           "ни Keychain GITHUB_PAT_SPA")

    def fetch(path: str) -> Any:
        req = urllib.request.Request(
            API_ROOT + path,
            headers={"Authorization": f"Bearer {tok}",
                     "Accept": "application/vnd.github+json",
                     "User-Agent": "spa-record-survival-census"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)

    return fetch


def _token_from_keychain() -> Optional[str]:
    proc = subprocess.run(
        ["security", "find-generic-password", "-s", "GITHUB_PAT_SPA", "-w"],
        capture_output=True, text=True, check=False)
    return proc.stdout.strip() or None if proc.returncode == 0 else None


# ─────────────────────────── ось B: ИСХОД ────────────────────────────────

def classify_outcome(artifacts: Sequence[Dict[str, Any]]) -> str:
    """Исход по строкам артефактов ОДНОГО прогона (уже отфильтрованным)."""
    if not artifacts:
        return OUT_ABSENT
    live = [a for a in artifacts if a.get("expired") is False]
    expired = [a for a in artifacts if a.get("expired") is True]
    if live:
        return OUT_SURVIVED
    if expired:
        return OUT_EXPIRED
    # Строка есть, а поля `expired` в ней нет ⇒ исход НЕ ИЗМЕРЕН: объявлять её
    # уцелевшей значило бы подставить догадку вместо наблюдения (инв. #17).
    return OUT_UNMEASURED


#: Классы ВОРОТ, при которых отсутствие записи объяснено САМИМИ воротами: срок
#: хранения у них ни при чём, и «не измерено» тут было бы вторым домом одному
#: утверждению.
_DOOR_EXPLAINS_ABSENCE: Tuple[str, ...] = (
    DOOR_NO_STEP, DOOR_STEP_NOT_COVERING, DOOR_UNMEASURED)


def _beyond_term(outcome: str, door: str, detail: Dict[str, Any],
                 created_at: Any, now: datetime) -> Optional[bool]:
    """Унёс ли запись СРОК ХРАНЕНИЯ.

    ``True`` — прогон старше объявленного срока, строк нет; ``False`` — срок
    известен и не вышел; ``None`` — срок или возраст не измерены.
    """
    if outcome != OUT_ABSENT or door in _DOOR_EXPLAINS_ABSENCE:
        return False
    term = detail.get("retention_days")
    created = _parse_ts(created_at)
    if not isinstance(term, int) or created is None:
        return None
    return (now - created).total_seconds() > term * 86400.0


class PageCeilingReached(RuntimeError):
    """Потолок страниц достигнут: население НЕ полно и это обязано быть сказано."""


def _list_runs(fetch: Callable[[str], Any], repo: str, workflow_id: int,
               window: int) -> List[Dict[str, Any]]:
    runs: List[Dict[str, Any]] = []
    page = 1
    while len(runs) < window:
        if page > MAX_PAGES:
            raise PageCeilingReached(
                f"перечень прогонов не кончился за {MAX_PAGES} страниц — "
                f"население НЕ полно, вердикта по нему нет")
        batch = fetch(f"/repos/{repo}/actions/workflows/{workflow_id}/runs"
                      f"?branch=main&per_page={_PAGE}&page={page}")
        got = batch.get("workflow_runs") or []
        runs.extend(got)
        if len(got) < _PAGE:
            break
        page += 1
    return runs[:window]


def _workflow_id(fetch: Callable[[str], Any], repo: str) -> Optional[int]:
    doc = fetch(f"/repos/{repo}/actions/workflows?per_page={_PAGE}")
    for wf in doc.get("workflows") or []:
        if wf.get("path") == WORKFLOW_FILE:
            return wf.get("id")
    return None


def _list_record_artifacts(fetch: Callable[[str], Any], repo: str
                           ) -> Dict[int, List[Dict[str, Any]]]:
    """Строки записей, разложенные по прогону. Один сквозной перечень, не 300
    запросов: предмет один и тот же, а 300 обращений к API сделали бы такт
    прибора дороже его собственного ответа."""
    by_run: Dict[int, List[Dict[str, Any]]] = {}
    page = 1
    while True:
        if page > MAX_PAGES:
            raise PageCeilingReached(
                f"перечень записей не кончился за {MAX_PAGES} страниц — "
                f"население НЕ полно, вердикта по нему нет")
        doc = fetch(f"/repos/{repo}/actions/artifacts?per_page={_PAGE}&page={page}")
        got = doc.get("artifacts") or []
        for art in got:
            if not str(art.get("name") or "").startswith(RECORD_PREFIX):
                continue
            run = art.get("workflow_run") or {}
            rid = run.get("id")
            if rid is None:
                continue
            by_run.setdefault(int(rid), []).append(art)
        if len(got) < _PAGE:
            break
        page += 1
    return by_run


# ──────────────────────────── ось C: ЦЕНА ────────────────────────────────

def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def measure_price(fetch: Callable[[str], Any], repo: str,
                  run_ids: Sequence[int],
                  artifacts_by_run: Dict[int, List[Dict[str, Any]]]
                  ) -> Dict[str, Any]:
    """Цена выгрузки: длительности шага (с) и размеры записи (байты).

    Выборка — прогоны, где выгрузка ИСПОЛНИЛАСЬ: только у них цена наблюдаема.
    Её размер назван, потому что это НИЖНЯЯ граница знания о цене, а не
    свойство всех прогонов.
    """
    out: Dict[str, Any] = {
        "sampled_runs": len(run_ids),
        "step_seconds": None,
        "artifact_bytes": None,
        "reason": None,
    }
    if not run_ids:
        out["reason"] = ("ни одного прогона с исполнившейся выгрузкой — цена НЕ "
                         "ИЗМЕРЕНА (это не ноль секунд)")
        return out
    durations: List[float] = []
    unreadable = 0
    for rid in run_ids:
        try:
            doc = fetch(f"/repos/{repo}/actions/runs/{rid}/jobs?per_page={_PAGE}")
        except Exception:  # noqa: BLE001 — одна нечитаемая джоба не есть ноль
            unreadable += 1
            continue
        for job in doc.get("jobs") or []:
            for step in job.get("steps") or []:
                if not _is_upload_step_name(step.get("name")):
                    continue
                started = _parse_ts(step.get("started_at"))
                finished = _parse_ts(step.get("completed_at"))
                if started is None or finished is None:
                    unreadable += 1
                    continue
                delta = (finished - started).total_seconds()
                if delta >= 0:
                    durations.append(delta)
    sizes = [int(a["size_in_bytes"]) for rid in run_ids
             for a in artifacts_by_run.get(rid, [])
             if isinstance(a.get("size_in_bytes"), int)]
    out["jobs_unreadable"] = unreadable
    if durations:
        out["step_seconds"] = {"n": len(durations), "min": min(durations),
                               "median": statistics.median(durations),
                               "max": max(durations)}
    else:
        out["reason"] = "длительность шага выгрузки не прочитана ни у одной джобы"
    if sizes:
        out["artifact_bytes"] = {"n": len(sizes), "min": min(sizes),
                                 "median": statistics.median(sizes),
                                 "max": max(sizes)}
    return out


#: Имя шага выгрузки у ПИСАТЕЛЯ. Литерал, а не подстрока «upload»: подстрочная
#: сверка приняла бы любой чужой шаг с тем же словом (ADR-333).
UPLOAD_STEP_NAMES: Tuple[str, ...] = ("Upload test records (junit + stream)",)


def _is_upload_step_name(name: Any) -> bool:
    return isinstance(name, str) and name.strip() in UPLOAD_STEP_NAMES


# ─────────────────────────────── сборка ──────────────────────────────────

def run_census(*, repo: str = DEFAULT_REPO,
               window_runs: int = DEFAULT_WINDOW_RUNS,
               fetch: Optional[Callable[[str], Any]] = None,
               workflow_source_at: Optional[Callable[[str], Tuple[Optional[str], Optional[str]]]] = None,
               repo_root: Optional[Path] = None,
               now: Optional[datetime] = None) -> Dict[str, Any]:
    """Отчёт переписи. ``measured=False`` ⇒ вердикта нет вовсе."""
    stamp = (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    report: Dict[str, Any] = {
        "generated_at": stamp,
        "order": ORDER,
        "measured": False,
        "status": STATUS_UNMEASURED,
        "reason": None,
        # Форма отчёта ПОСТОЯННА: ключ объявлен всегда, «не вычислено» — `None`,
        # а не отсутствие ключа (инв. #17).
        "repo": repo,
        "workflow": WORKFLOW_FILE,
        "window_runs": window_runs,
        "population": None,
        "door": None,
        "survival": None,
        "price": None,
    }

    if fetch is None:
        try:
            fetch = github_fetch()
        except Exception as exc:  # noqa: BLE001
            report["reason"] = f"вход сети не открыт: {exc}"
            return report
    if workflow_source_at is None:
        root = repo_root or Path(__file__).resolve().parents[2]
        workflow_source_at = workflow_source_from_git(root)

    try:
        wf_id = _workflow_id(fetch, repo)
    except Exception as exc:  # noqa: BLE001
        report["reason"] = f"перечень воркфлоу не прочитан: {type(exc).__name__}: {exc}"
        return report
    if wf_id is None:
        report["reason"] = f"воркфлоу {WORKFLOW_FILE} не найден в репозитории {repo}"
        return report

    try:
        runs = _list_runs(fetch, repo, int(wf_id), window_runs)
        artifacts_by_run = _list_record_artifacts(fetch, repo)
    except Exception as exc:  # noqa: BLE001
        report["reason"] = f"население не прочитано: {type(exc).__name__}: {exc}"
        return report

    if not runs:
        # Слепой проход: ни одного прогона не прочитано ⇒ «ничего не терялось»
        # верно ПО ПОСТРОЕНИЮ и ответом не является.
        report["reason"] = ("ни одного прогона не прочитано — население не "
                            "измерено, а не равно нулю")
        return report

    rows: List[Dict[str, Any]] = []
    door_counts: Dict[str, int] = {cls: 0 for cls in DOOR_CLASSES}
    outcome_counts: Dict[str, int] = {out: 0 for out in OUTCOMES}
    for run in runs:
        sha = str(run.get("head_sha") or "")
        source, why = workflow_source_at(sha) if sha else (None, "у прогона нет head_sha")
        if source is None:
            door, detail = DOOR_UNMEASURED, {"reason": why}
        else:
            door, detail = door_class_of_source(source)
        arts = artifacts_by_run.get(int(run["id"]), [])
        outcome = classify_outcome(arts)
        # Срок хранения применяется ТОЛЬКО там, где лекарство доставлено: у
        # прогона без шага выгрузки отсутствие записи объяснено ВОРОТАМИ, и
        # поминать срок значило бы объяснить одно и то же дважды.
        beyond = _beyond_term(outcome, door, detail, run.get("created_at"),
                              now or datetime.now(timezone.utc))
        if beyond is True:
            outcome = OUT_BEYOND_TERM
        elif beyond is None and outcome == OUT_ABSENT and door not in _DOOR_EXPLAINS_ABSENCE:
            outcome = OUT_UNMEASURED
        door_counts[door] += 1
        outcome_counts[outcome] += 1
        rows.append({
            "run_id": run.get("id"),
            "created_at": run.get("created_at"),
            "head_sha": sha[:9],
            "event": run.get("event"),
            "path": path_of(run.get("conclusion")),
            "door": door,
            "door_detail": detail,
            "outcome": outcome,
            "artifacts": len(arts),
            "artifact_bytes": [a.get("size_in_bytes") for a in arts],
        })

    report["population"] = {
        "runs": len(rows),
        "oldest_created_at": rows[-1]["created_at"],
        "newest_created_at": rows[0]["created_at"],
        "by_path": _counter([r["path"] for r in rows]),
        "artifact_rows": sum(len(v) for v in artifacts_by_run.values()),
    }
    report["door"] = {
        "by_class": door_counts,
        "covers_cancellation": {cls: DOOR_COVERS_CANCELLATION[cls]
                                for cls in DOOR_CLASSES if door_counts[cls]},
    }
    report["survival"] = _survival(rows)
    report["outcomes"] = outcome_counts
    # Тождество учёта: перечень исходов ЗАКРЫТ, сумма равна населению. Утверждение
    # ОПРОВЕРЖИМО: считается по ОБЪЯВЛЕННОМУ перечню имён, а не `sum(values())`,
    # иначе оно держалось бы всегда и мутанта бы пережило.
    report["accounting"] = {
        "outcomes_sum": sum(outcome_counts[o] for o in OUTCOMES),
        "doors_sum": sum(door_counts[c] for c in DOOR_CLASSES),
        "runs": len(rows),
    }
    survived_ids = [r["run_id"] for r in rows if r["outcome"] == OUT_SURVIVED]
    try:
        report["price"] = measure_price(fetch, repo, survived_ids, artifacts_by_run)
    except Exception as exc:  # noqa: BLE001
        report["price"] = {"sampled_runs": len(survived_ids), "step_seconds": None,
                           "artifact_bytes": None,
                           "reason": f"цена не измерена: {type(exc).__name__}: {exc}"}
    report["rows"] = rows

    report["measured"] = True
    # Класс закрыт РОВНО тогда, когда ворота путь отмены ПОКРЫВАЮТ у всего
    # населения с доставленным лекарством. Нулевая доля уцелевшего класс не
    # закрывает и не открывает: доля есть ПОСЛЕДСТВИЕ ворот, а ворота — предмет.
    cancel = report["survival"]["cancellation_path"]
    report["status"] = (STATUS_CLOSED if cancel["door_covers"] is True
                        else STATUS_OPEN)
    return report


def _counter(values: Sequence[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


def _share(numerator: int, denominator: int) -> Optional[float]:
    """Доля в процентах. Пустой знаменатель ⇒ ``None``: ноль из нуля не есть ноль."""
    if denominator <= 0:
        return None
    return round(100.0 * numerator / denominator, 1)


def _survival(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Доля уцелевшего — РАЗДЕЛЬНО по пути прогона и только там, где лекарство
    доставлено."""
    # «Лекарство доставлено» = у воркфлоу ТОГО sha есть выгрузка, ПОКРЫВАЮЩАЯ
    # путь писателя. Условие шага при этом может быть любым, в том числе
    # неразобранным (`other_condition`): такой прогон остаётся в знаменателе, а
    # неизвестность уезжает в `door_covers=None` — выкинуть его из знаменателя
    # значило бы спрятать «не знаю» в чистый ноль.
    _NOT_DELIVERED = (DOOR_NO_STEP, DOOR_STEP_NOT_COVERING, DOOR_UNMEASURED)
    delivered = [r for r in rows if r["door"] not in _NOT_DELIVERED]
    not_delivered = [r for r in rows if r["door"] == DOOR_NO_STEP]
    not_covering = [r for r in rows if r["door"] == DOOR_STEP_NOT_COVERING]
    door_unmeasured = [r for r in rows if r["door"] == DOOR_UNMEASURED]

    def leg(path_names: Tuple[str, ...]) -> Dict[str, Any]:
        sel = [r for r in delivered if r["path"] in path_names]
        survived = [r for r in sel if r["outcome"] == OUT_SURVIVED]
        doors = {r["door"] for r in sel}
        covers: Optional[bool]
        if not doors:
            covers = None
        elif all(DOOR_COVERS_CANCELLATION[d] is True for d in doors):
            covers = True
        elif all(DOOR_COVERS_CANCELLATION[d] is False for d in doors):
            covers = False
        else:
            covers = None
        return {
            "runs": len(sel),
            "survived": len(survived),
            "expired": sum(1 for r in sel if r["outcome"] == OUT_EXPIRED),
            "absent": sum(1 for r in sel if r["outcome"] == OUT_ABSENT),
            "beyond_term": sum(1 for r in sel if r["outcome"] == OUT_BEYOND_TERM),
            "unmeasured": sum(1 for r in sel if r["outcome"] == OUT_UNMEASURED),
            # Доля считается по прогонам, об исходе которых ЕСТЬ наблюдение:
            # «срок унёс» и «не измерено» ни в числитель, ни в знаменатель не
            # идут — иначе число зависело бы от того, когда его мерили.
            "decided": len(sel) - sum(1 for r in sel if r["outcome"]
                                      in (OUT_BEYOND_TERM, OUT_UNMEASURED)),
            "share_pct": _share(len(survived),
                                len(sel) - sum(1 for r in sel if r["outcome"]
                                               in (OUT_BEYOND_TERM, OUT_UNMEASURED))),
            "door_covers": covers,
            "door_classes": sorted(doors),
            # Записей НА ПРОГОН: матрица объявляет две ноги, и «уцелела одна из
            # двух» есть ДРУГОЙ исход, чем «уцелели обе». Склеивание спрятало бы
            # ровно то, чем объясняются уцелевшие на пути отмены.
            "artifacts_per_survived_run": _counter(
                [str(r["artifacts"]) for r in survived]),
        }

    return {
        "medicine_delivered_runs": len(delivered),
        "no_upload_step_runs": len(not_delivered),
        "step_not_covering_runs": len(not_covering),
        "door_unmeasured_runs": len(door_unmeasured),
        "cancellation_path": leg(("cancelled",)),
        "failure_path": leg(("failure",)),
        "success_path": leg(("success",)),
        "other_paths": leg(tuple(sorted({r["path"] for r in delivered}
                                        - {"cancelled", "failure", "success"}))),
    }


# ─────────────────────────────── вывод ───────────────────────────────────

def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    path = Path(data_dir) / ARTIFACT_NAME
    atomic_save(report, str(path))
    return path


def _fmt_share(value: Optional[float]) -> str:
    return "НЕ ИЗМЕРЕНО" if value is None else f"{value:.1f} %"


def _fmt_covers(value: Optional[bool]) -> str:
    return {True: "ПОКРЫВАЮТ", False: "НЕ ПОКРЫВАЮТ", None: "НЕ ИЗМЕРЕНО"}[value]


def format_report(report: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    if not report.get("measured"):
        lines.append(f"НЕ ИЗМЕРЕНО: {report.get('reason')}")
        return lines
    pop = report["population"]
    sur = report["survival"]
    lines.append(
        f"Переживает ли запись прогона ОТМЕНУ (заказ {ORDER}): {report['status']}")
    lines.append(f"  население {pop['runs']} прогон(ов) "
                 f"{pop['oldest_created_at']} … {pop['newest_created_at']} · "
                 f"по пути " + " · ".join(f"{k} {v}" for k, v in
                                          sorted(pop["by_path"].items(), key=lambda t: -t[1])))
    lines.append("  [ВОРОТА] " + " · ".join(
        f"{k} {v}" for k, v in report["door"]["by_class"].items() if v))
    for name, label in (("cancellation_path", "ОТМЕНА"),
                        ("failure_path", "ОТКАЗ"),
                        ("success_path", "УСПЕХ"),
                        ("other_paths", "прочие")):
        branch = sur[name]
        if not branch["runs"]:
            continue
        lines.append(
            f"  [{label}] прогонов {branch['runs']} · с наблюдённым исходом "
            f"{branch['decided']} · уцелело {branch['survived']} "
            f"= {_fmt_share(branch['share_pct'])} · срок взведён {branch['expired']} · "
            f"нет записи {branch['absent']} · старше срока хранения "
            f"{branch['beyond_term']} · не измерено {branch['unmeasured']} · "
            f"ворота путь ОТМЕНЫ {_fmt_covers(branch['door_covers'])}")
        if branch["artifacts_per_survived_run"]:
            lines.append("      записей на уцелевший прогон: " + " · ".join(
                f"{k} шт — {v} прогон(ов)"
                for k, v in sorted(branch["artifacts_per_survived_run"].items())))
    lines.append(f"  [ЛЕКАРСТВО НЕ ДОСТАВЛЕНО] прогонов без шага выгрузки "
                 f"{sur['no_upload_step_runs']} · шаг есть, но путь писателя не "
                 f"покрывает {sur['step_not_covering_runs']} — они НЕ в знаменателе "
                 f"доли: запись у них потеряна потому, что лекарства не было")
    if sur["door_unmeasured_runs"]:
        lines.append(f"  [ВОРОТА НЕ ИЗМЕРЕНЫ] {sur['door_unmeasured_runs']} "
                     f"прогон(ов): воркфлоу того sha не прочитан (обрезанный клон)")
    # `... or {}` здесь склеило бы «раздела цены в отчёте НЕТ» с «цена пуста»
    # (инв. #17); `observed` делает честную форму короче подстановки.
    price = observed(report, "price", kind=dict)
    if price is None:
        lines.append("  [ЦЕНА] НЕ ИЗМЕРЕНА: раздела цены в отчёте нет")
        price = {}
    steps = price.get("step_seconds")
    sizes = price.get("artifact_bytes")
    if steps:
        lines.append(f"  [ЦЕНА] шаг выгрузки {steps['min']:.0f}…{steps['max']:.0f} с "
                     f"(медиана {steps['median']:.0f}, наблюдений {steps['n']}) — "
                     f"цена, которой стоило бы `always()`")
    else:
        lines.append(f"  [ЦЕНА] НЕ ИЗМЕРЕНА: {price.get('reason')}")
    if sizes:
        lines.append(f"  [РАЗМЕР] запись в хранилище {sizes['min']/1e6:.1f}…"
                     f"{sizes['max']/1e6:.1f} МБ (медиана {sizes['median']/1e6:.1f}, "
                     f"наблюдений {sizes['n']}) — это СЖАТЫЙ размер, не размер на диске")
    acc = report["accounting"]
    lines.append(f"  [УЧЁТ] сумма исходов {acc['outcomes_sum']} · сумма ворот "
                 f"{acc['doors_sum']} · население {acc['runs']}")
    lines.append("  ADVISORY: прибор только ЧИТАЕТ — ни порогов, ни баз храповиков, "
                 "ни воркфлоу он не меняет; RiskPolicy v1.0, стоп-кран, аллокатор, "
                 "живой трек и landing/ не тронуты")
    return lines


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        fetch: Optional[Callable[[str], Any]] = None) -> Dict[str, Any]:
    """Точка входа ступени моста (`findings_bridge`).

    Артефакт оставляется ВСЕГДА, включая третий исход: «не измерено» с названной
    причиной обязано доехать до читателя, иначе шаг 0-офис увидит отсутствие
    файла и не отличит его от «ступень не запускалась».
    """
    repo_root = Path(root) if root else Path(__file__).resolve().parents[2]
    data_dir = repo_root / "data"
    report = run_census(fetch=fetch, repo_root=repo_root, now=now)
    try:
        save_artifact(report, data_dir)
    except Exception as exc:  # noqa: BLE001 — перепись не смеет валить мост
        report = dict(report)
        report["artifact_not_written"] = f"{type(exc).__name__}: {exc}"
    return {"measured": bool(report.get("measured")), "doc": report}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--window-runs", type=int, default=DEFAULT_WINDOW_RUNS,
                    help="окно населения (ВХОД, печатается в артефакте)")
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", action="store_true", help=f"записать {ARTIFACT_NAME}")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[2]
    data_dir = Path(args.data_dir) if args.data_dir else (repo_root / "data")
    report = run_census(repo=args.repo, window_runs=args.window_runs,
                        repo_root=repo_root)
    if args.save:
        save_artifact(report, data_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    else:
        for line in format_report(report):
            print(line)
    if not report.get("measured"):
        return 2
    return 1 if report["status"] == STATUS_OPEN else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
