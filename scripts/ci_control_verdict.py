#!/usr/bin/env python3
"""scripts/ci_control_verdict.py — ЧИТАТЕЛЬ вердикта контрольного прогона (ADR-845, G843 п. 2).

ЗАЧЕМ. Приёмку полного набора с 16.10 даёт контрольный прогон по шардам
(`.github/workflows/ci-control.yml` + `scripts/ci_control.py`), и ТОЛЬКО он: у `SPA CI` на
`main` вердикт недостижим по построению — набору нужно ≈6 ч до сводки, а медиана промежутка
между пушами 0.72 ч, промежутков ≥6 ч всего 1.5 % (ADR-844). Вердикт контрольного прогона
живёт **артефактом** (`ci-control-report`, 90 дней), в git не кладётся — и до 28.10 его не
спрашивал НИ ОДИН шаг цикла. `scripts/ci_control.py` его ПЕЧАТАЕТ в прогоне; `scripts/ci_verdict.py`
отвечает за junit ОДНОГО шага. Класс — ADR-345 («написано и не позвано»), названный ADR-844 и
им же не закрытый.

ПОЧЕМУ `conclusion` ВЕРДИКТОМ НЕ ЯВЛЯЕТСЯ — замер 2026-10-28 по 20 последним завершённым
прогонам `ci-control` на `main` (живой API):

* `conclusion` у всех двадцати — `failure`, **20 из 20**;
* вердикт при этом **RED 17 · INCOMPLETE 3**. То есть «упавшие НАЗВАНЫ поимённо» и «не
  измерено ВОВСЕ» в списке прогонов неразличимы — ровно инв. #17, и неразличимость
  встречается в 15 % прогонов;
* число упавших при RED гуляет 2…70, и это НЕ дрожание набора: у двух прогонов из двадцати
  (**10 %**) `head_sha` ≠ коммит, который прогон реально мерил (`inputs.sha` закрепляется
  джобой `manifest`, а в списке прогонов стоит голова ветки). Прогон 40164854726 числится
  на `546687543` и отвечает про `84ab03679` — `failed=2` против `failed=70` у расписанного
  прогона на самом `546687543`. Читать список прогонов значит получить и чужой вердикт, и
  чужой коммит, и ни о чём не узнать.

ЧТО МЕРИТСЯ — три вопроса, и ни один не отвечает на другой:

1. **Каков вердикт** последнего ЗАВЕРШЁННОГО контрольного прогона на ветке: `GREEN` ·
   `RED` (упавшие названы, число) · `INCOMPLETE` (измерено НЕ ВСЁ, причины названы).
   Берётся из `report.json` артефакта, а не из `conclusion` прогона.
2. **Сколько ему часов** — от конца прогона. Старше `STALE_AFTER_H` ⇒ находка: приёмка
   набора есть, но она отвечает про позавчера.
3. **О КАКОМ коммите** этот вердикт — `report.sha` (закреплённый), рядом с `head_sha`
   прогона. Разошлись ⇒ находка: вердикт верен, но он не про то, что числится в списке.

Коды возврата: **0** — измерено, находок нет · **1** — находка НАЗВАНА · **2** — НЕ
ИЗМЕРЕНО (токена нет · сеть · прогонов нет · отчёта у прогона нет или он истёк · отчёт не
разобран) с причиной. Третий исход за «вердикта нет, значит всё хорошо» не выдаётся
(инв. #17): отсутствие вердикта и зелёный вердикт — разные состояния, и второе здесь ни разу
не наблюдалось.

ПРОВОДКА (ADR-845). Прибор только ЧИТАЕТ: ни одного файла он не пишет. Отчёт
(``data/ci_control_verdict.json``) записывает ТОТ, КТО ПОЗВАЛ, — ступень
`findings_bridge.ci_control_verdict_step`; прибор отдаёт документ на stdout (``--json``).
Это не оформление: писателя артефакта сторож достижимости (`spa_core/tests/_orphan_producer.py`)
ищет среди ТОЧЕК ВХОДА и импортированного кода, а зов подпроцессом по константе пути ему не
виден — писатель, живущий здесь, был бы «объявленным продуктом, которого никто не вычисляет»
(урок ADR-843, найденный сторожем до доставки). Артефакт объявлен в конституции со SLO, и его
читает поимённая ветка шага 0-офис.

ТАКТ ШЕСТЬ ЧАСОВ — ровно такт самого прогона (`cron: 23 */6 * * *`). Срок решает ФАЙЛ
отчёта, а не расписание бегуна (ADR-414), и гейт живёт у ступени-писателя в ОДНОЙ копии.

Только stdlib (инв. #4). Сеть — ВХОДЫ (``fetch``/``grab``), поэтому тесты её не трогают и
отвечают на вопрос о проводке, а не о том, что сегодня у GitHub.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:          # прибор зовут и подпроцессом, и из тестов
    sys.path.insert(0, str(ROOT))

from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.monitoring.call_provenance import describe as provenance_line  # noqa: E402,E501
from spa_core.monitoring.record_survival_census import github_fetch  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

#: НИ ПУТИ ОТЧЁТА, НИ ТАКТА здесь НЕТ — и это решение, а не пропуск (как у соседа
#: `worker_axis_census`): отчёт пишет ПОЗВАВШИЙ, срок решает ФАЙЛ отчёта, значит и путь, и
#: гейт такта живут у ступени — `findings_bridge.CI_CONTROL_VERDICT_ARTIFACT` / `…_TACT_DAYS`.
#: Вторая копия любого из них здесь разошлась бы с первой МОЛЧА (класс ADR-220).

WORKFLOW_FILE = "ci-control.yml"
REPORT_ARTIFACT = "ci-control-report"
REPORT_MEMBER = "report.json"
DEFAULT_BRANCH = "main"

#: Репозиторий — ОДНА константа: второй литерал того же пути разошёлся бы с первым молча
#: (класс ADR-220). Корень API живёт у `github_fetch`, и здесь его копии нет.
REPO = "yurii-spa/SPA"

#: Сколько прогонов спрашивать у списка. Нужен ОДИН — последний завершённый, — но список
#: отдаёт и идущие, и снятые, поэтому берётся с запасом: иначе «все N в работе» читалось бы
#: как «прогонов нет».
DEFAULT_RUNS = 10

#: Возраст вердикта, после которого он становится НАХОДКОЙ. Такт прогона — 6 ч
#: (`cron: 23 */6 * * *`), сам прогон ≈0.5–1.6 ч. Порог ВДВОЕ больше такта намеренно: равный
#: такту краснел бы от дрожания расписания GitHub и перестал бы быть сигналом (тот же довод,
#: что у SLO соседа — класс `no_margin`, ADR-646).
STALE_AFTER_H = 12.0

GREEN, RED, INCOMPLETE = "GREEN", "RED", "INCOMPLETE"


class NotMeasured(RuntimeError):
    """Третий исход: вердикта НЕТ. Не «зелено» и не «красно» (инв. #17).

    Документом не становится и в файл не попадает: артефакт с выдуманным вердиктом лгал бы
    ещё и своим возрастом.
    """


# ───────────────────────────── двери наружу ─────────────────────────────────

class _StripAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """Переадресация артефакта уходит в чужое хранилище, и токен туда посылать НЕЛЬЗЯ.

    Замерено 28.10 на живом API: `GET /actions/artifacts/<id>/zip` отвечает 302 на
    blob-хранилище, а `urllib` по умолчанию несёт `Authorization` и на новый адрес —
    хранилище отвечает **HTTP 401**. То есть «вердикт недостижим» выглядело бы отказом
    доступа, хотя токен верен и артефакт на месте.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return urllib.request.Request(newurl, headers={"User-Agent": "spa-ci-control-verdict"})


def artifact_grab(token: str | None = None):
    """Читатель БАЙТОВ артефакта. Отдельная дверь от `github_fetch` по предмету.

    `github_fetch` разбирает JSON и переадресацию не переживает; здесь нужен zip и
    снятие токена на переадресации. Это разные правила, а не вторая копия одного: токен
    по-прежнему добывается ОДНИМ правилом — тем, что внутри `github_fetch`.
    """
    opener = urllib.request.build_opener(_StripAuthOnRedirect)
    head = {"Accept": "application/vnd.github+json",
            "User-Agent": "spa-ci-control-verdict"}
    if token:
        head["Authorization"] = f"Bearer {token}"

    def grab(url: str) -> bytes:
        with opener.open(urllib.request.Request(url, headers=head), timeout=300) as resp:
            return resp.read()

    return grab


def _keychain_token() -> str | None:
    """Токен для ДВЕРИ БАЙТОВ — тем же правилом, что у `github_fetch`, и не копией.

    `github_fetch` правило инкапсулирует и наружу токен не отдаёт, поэтому для zip-двери он
    спрашивается ЕЩЁ РАЗ у того же читателя. Отсутствие — `None`, а не исключение: о нём
    скажет `github_fetch`, и говорить дважды значило бы иметь два ответа на один вопрос.
    """
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT_SPA")
    if tok:
        return tok
    proc = subprocess.run(
        ["security", "find-generic-password", "-s", "GITHUB_PAT_SPA", "-w"],
        capture_output=True, text=True, check=False)
    return (proc.stdout.strip() or None) if proc.returncode == 0 else None


# ───────────────────────────── замер ─────────────────────────────────

def _parse_moment(raw):
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _run_row(run: dict) -> dict:
    """Строка прогона из списка — БЕЗ вердикта, и это объявлено словом.

    `verdict: "НЕ ЗАПРАШИВАЛСЯ"` стоит здесь намеренно: `None` читался бы как «вердикта
    нет», а его тут просто не спрашивали — скачивать отчёт каждого прогона значило бы
    отвечать на другой вопрос за десять загрузок.
    """
    return {"id": str(run.get("id")), "status": run.get("status"),
            "conclusion": run.get("conclusion"), "event": run.get("event"),
            "head_sha": run.get("head_sha"), "head_branch": run.get("head_branch"),
            "created_at": run.get("created_at"), "updated_at": run.get("updated_at"),
            "url": run.get("html_url"), "verdict": "НЕ ЗАПРАШИВАЛСЯ"}


def report_of_run(run_id: str, *, fetch, grab) -> dict:
    """`report.json` одного прогона. Любая немочь — :class:`NotMeasured` с причиной."""
    try:
        listing = fetch(f"/repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        raise NotMeasured(f"перечень артефактов прогона {run_id} не прочитан: "
                          f"{type(exc).__name__}: {exc}") from exc
    rows = (listing or {}).get("artifacts") or []
    live = [a for a in rows if a.get("name") == REPORT_ARTIFACT and a.get("expired") is False]
    if not live:
        expired = [a for a in rows if a.get("name") == REPORT_ARTIFACT]
        why = ("истёк (90 дней)" if expired else
               "его нет вовсе — прогон умер раньше сводки")
        raise NotMeasured(f"у прогона {run_id} отчёта `{REPORT_ARTIFACT}` нет: {why}. "
                          f"`conclusion` вердиктом НЕ является")
    art = live[0]
    url = art.get("archive_download_url") or (
        f"https://api.github.com/repos/{REPO}/actions/artifacts/{art.get('id')}/zip")
    try:
        raw = grab(url)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        raise NotMeasured(f"отчёт прогона {run_id} не скачан: "
                          f"{type(exc).__name__}: {exc}") from exc
    try:
        doc = json.loads(zipfile.ZipFile(io.BytesIO(raw)).read(REPORT_MEMBER))
    except (zipfile.BadZipFile, KeyError, ValueError, TypeError) as exc:
        raise NotMeasured(f"отчёт прогона {run_id} не разобран "
                          f"({type(exc).__name__}: {exc})") from exc
    if not isinstance(doc, dict) or not doc.get("verdict"):
        raise NotMeasured(f"отчёт прогона {run_id} вердикта не несёт — "
                          f"это не «вердикт зелёный»")
    return doc


def census(*, fetch, grab, branch: str = DEFAULT_BRANCH, runs: int = DEFAULT_RUNS,
           now=None) -> dict:
    """ОДИН замер: вердикт последнего завершённого прогона, его возраст и его коммит.

    Ветка — ВХОД со значением `main`: вердикт о доставленном коде спрашивается у `main`, а
    прогоны по `workflow_dispatch` с ветвей кандидатов отвечают о другом предмете. Идущие
    прогоны называются ОТДЕЛЬНО (`in_progress`): «вердикт стар, но новый уже идёт» и
    «вердикт стар и ничего не идёт» — разные состояния.
    """
    moment = now if now is not None else dt.datetime.now(dt.timezone.utc)
    path = (f"/repos/{REPO}/actions/workflows/{WORKFLOW_FILE}/runs"
            f"?branch={branch}&per_page={int(runs)}")
    try:
        listing = fetch(path)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        raise NotMeasured(f"список прогонов `{WORKFLOW_FILE}` не прочитан: "
                          f"{type(exc).__name__}: {exc}") from exc
    rows = [r for r in ((listing or {}).get("workflow_runs") or []) if isinstance(r, dict)]
    if not rows:
        raise NotMeasured(f"прогонов `{WORKFLOW_FILE}` на ветке {branch} не найдено — "
                          f"это НЕ «набор не падал»")
    done = [r for r in rows if r.get("status") == "completed"]
    if not done:
        raise NotMeasured(
            f"все {len(rows)} прогон(а) `{WORKFLOW_FILE}` на ветке {branch} ещё идут — "
            f"вердикта пока нет ни у одного")
    latest = done[0]
    doc = report_of_run(str(latest.get("id")), fetch=fetch, grab=grab)
    ended = _parse_moment(latest.get("updated_at"))
    age_h = None if ended is None else (moment - ended).total_seconds() / 3600.0
    totals = doc.get("totals") if isinstance(doc.get("totals"), dict) else {}
    return {
        "branch": branch,
        "runs_scanned": len(rows),
        "in_progress": [_run_row(r) for r in rows if r.get("status") != "completed"],
        "run": _run_row(latest),
        "verdict": doc.get("verdict"),
        "measured_sha": doc.get("sha"),
        "head_sha": latest.get("head_sha"),
        "verdict_age_h": age_h,
        "failed": len(doc.get("failures") or []),
        "incomplete_reasons": [str(x) for x in (doc.get("incomplete") or [])][:5],
        "not_obtained": len(doc.get("not_obtained") or []),
        "shards": len(doc.get("shards") or []),
        # Ключи — РОВНО те, что кладёт `ci_control.aggregate`, и проверены на живом
        # отчёте. Выдуманный ключ дал бы «НЕ ИЗМЕРЕНО» на здоровом отчёте, то есть
        # сторож жаловался бы на свою же опечатку (первая редакция спрашивала
        # `no_outcome`, которого в отчёте нет вовсе — поймано живым прогоном).
        "totals": {k: totals.get(k) for k in
                   ("population", "files", "passed", "skipped", "failed", "error",
                    "not_obtained", "collect_errors", "shards_planned",
                    "shards_complete")},
        # Окружение замера: вердикт из ДРУГОГО окружения — вердикт о другом предмете
        # (тот же довод, по которому `ci_control.compare` отвечает NOT COMPARABLE).
        "env": doc.get("env") if isinstance(doc.get("env"), dict) else None,
    }


def findings(rep: dict) -> list:
    """Находки — утверждения о ВЕРДИКТЕ, и каждая названа своими словами."""
    out = []
    verdict = rep.get("verdict")
    run = rep.get("run") or {}
    if verdict == INCOMPLETE:
        why = "; ".join(str(x) for x in (rep.get("incomplete_reasons") or [])) or "причина не названа"
        out.append(f"последний контрольный прогон ({run.get('id')}) измерил НЕ ВСЁ "
                   f"(INCOMPLETE): {why}. Вердикта о наборе НЕТ — и `conclusion` "
                   f"({run.get('conclusion')}) этого не говорит")
    elif verdict == RED:
        out.append(f"набор КРАСЕН: прогон {run.get('id')} на {str(rep.get('measured_sha'))[:9]} "
                   f"дал failed={rep.get('failed')} при shards={rep.get('shards')} и "
                   f"not_obtained={rep.get('not_obtained')} — упавшие НАЗВАНЫ поимённо "
                   f"в `report.json` артефакта")
    elif verdict != GREEN:
        out.append(f"вердикт прогона {run.get('id')} не опознан: {verdict!r} — "
                   f"это не «зелено»")
    measured, head = rep.get("measured_sha"), rep.get("head_sha")
    if measured and head and measured != head:
        out.append(f"прогон {run.get('id')} числится на {str(head)[:9]}, а мерил "
                   f"{str(measured)[:9]} (коммит закреплён джобой `manifest` по "
                   f"`inputs.sha`): вердикт верен, но он НЕ про то, что стоит в списке "
                   f"прогонов")
    age = rep.get("verdict_age_h")
    if age is None:
        out.append("возраст вердикта НЕ ИЗМЕРЕН: у прогона нет разбираемой отметки конца")
    elif age > STALE_AFTER_H:
        idle = "и ни одного нового прогона не идёт" if not rep.get("in_progress") \
            else f"идущих прогонов: {len(rep['in_progress'])}"
        out.append(f"свежего вердикта нет: последнему {age:.1f} ч при такте прогона 6 ч "
                   f"(порог {STALE_AFTER_H:.0f} ч), {idle}")
    return out


def document(rep: dict, found: list, *, root=ROOT, now=None,
             main_file=None, argv_in=None) -> dict:
    """Отчёт как ДОКУМЕНТ — то, что читают конституция и шаг 0-офис.

    ``status`` объявлен СЛОВОМ, а не выведен читателем из длины списка находок: такой
    вывод был бы неверен для третьего исхода, а третий исход документом не становится
    вовсе (:class:`NotMeasured`).

    ``invoked_by`` — наблюдение «КТО ПОЗВАЛ»; единственное поле, которое покраснеет, если
    проводку однажды снимут и прибор снова начнёт звать рука цикла (тот же довод, что у
    соседей `python_reader_clock_doors` и `worker_axis_census`).
    """
    moment = now if now is not None else dt.datetime.now(dt.timezone.utc)
    prov = call_provenance(
        tree_root=Path(root),
        **({"main_file": main_file} if main_file is not None else {}),
        **({"argv": argv_in} if argv_in is not None else {}))
    return {
        "generated_at": moment.isoformat(),
        "status": "FINDING" if found else "CLEAN",
        "advisory": True,
        "invoked_by": prov,
        "branch": rep["branch"],
        "verdict": rep["verdict"],
        "verdict_age_h": rep["verdict_age_h"],
        "stale_after_h": STALE_AFTER_H,
        "measured_sha": rep["measured_sha"],
        "head_sha": rep["head_sha"],
        "run": rep["run"],
        "failed": rep["failed"],
        "shards": rep["shards"],
        "not_obtained": rep["not_obtained"],
        "incomplete_reasons": rep["incomplete_reasons"],
        "totals": rep["totals"],
        "env": rep["env"],
        "runs_scanned": rep["runs_scanned"],
        "in_progress": rep["in_progress"],
        "findings": list(found),
    }


def report(doc: dict) -> list:
    """Строки отчёта. ЕДИНСТВЕННАЯ копия правила отрисовки в приборе.

    И консоль, и шаг 0-офис идут сюда: вторая копия правила расходится с первой молча
    (ADR-220). Отсутствующее наблюдение печатается СЛОВАМИ «НЕ ИЗМЕРЕНО», а не `None` и не
    нулём (инв. #17): `None` читается глазом как «пусто, всё в порядке».
    """
    def _n(key, kind: type = int):
        value = observed(doc, key, kind=kind)
        return "НЕ ИЗМЕРЕНО" if value is None else value

    run = observed(doc, "run", kind=dict) or {}

    def _short(key):
        """Укорачивать можно ТОЛЬКО измеренное. `str(None)[:9]` дал бы «None», а
        `"НЕ ИЗМЕРЕНО"[:9]` — обрубок «НЕ ИЗМЕРЕ», который читается как опечатка, а не
        как отсутствие наблюдения. Поймано своим же контролем этого файла."""
        value = observed(doc, key, kind=str)
        return "НЕ ИЗМЕРЕНО" if value is None else str(value)[:9]

    def _of_run(key):
        """Поле прогона: отсутствие — СЛОВА. `None` в строке читается глазом как
        «пусто, всё в порядке» — ровно fail-OPEN, и свой контроль нашёл здесь строку
        «прогон None (None, conclusion None)»."""
        value = run.get(key)
        return "НЕ ИЗМЕРЕНО" if value is None else value

    age = observed(doc, "verdict_age_h", kind=float)
    out = [f"вердикт контрольного прогона CI (ветка {_n('branch', kind=str)}): "
           f"{_n('verdict', kind=str)} · возраст "
           f"{'НЕ ИЗМЕРЕН' if age is None else f'{age:.1f} ч'} "
           f"(порог {_n('stale_after_h', kind=float)} ч)"]
    out.append(f"   прогон {_of_run('id')} ({_of_run('event')}, conclusion "
               f"{_of_run('conclusion')}) — `conclusion` вердиктом НЕ является")
    out.append(f"   мерил коммит {_short('measured_sha')} · "
               f"числится на {_short('head_sha')}")
    out.append(f"   упавших {_n('failed')} · шардов {_n('shards')} · "
               f"не измерено шардами {_n('not_obtained')}")
    totals = observed(doc, "totals", kind=dict)
    if totals is None:
        out.append("   итоги прогона: НЕ ИЗМЕРЕНО")
    else:
        out.append("   итоги: " + " · ".join(
            f"{k}={'НЕ ИЗМЕРЕНО' if v is None else v}" for k, v in totals.items()))
    env = observed(doc, "env", kind=dict)
    if env is None:
        out.append("   окружение замера: НЕ ИЗМЕРЕНО — сравнивать этот вердикт "
                   "с предписанной командой не с чем")
    else:
        out.append(f"   окружение: python {env.get('python')} · pytest "
                   f"{env.get('pytest')} · SPA_ENV={env.get('SPA_ENV')} · "
                   f"PYTHONHASHSEED={env.get('PYTHONHASHSEED')} · корней "
                   f"{len(env.get('roots') or [])}")
    for why in observed(doc, "incomplete_reasons", kind=list) or []:
        out.append(f"   ⛔ НЕ ИЗМЕРЕНО шардом: {why}")
    idle = observed(doc, "in_progress", kind=list)
    out.append("   идущих прогонов: "
               f"{'НЕ ИЗМЕРЕНО' if idle is None else len(idle)} "
               f"(из {_n('runs_scanned')} прочитанных строк списка)")
    out.append(f"   [ЗВАВШИЙ] {provenance_line(observed(doc, 'invoked_by', kind=dict))}")
    found = observed(doc, "findings", kind=list)
    if found:
        out.append("   🔎 НАХОДКИ:")
        out.extend(f"     • {f}" for f in found)
    elif found == []:
        out.append("   ✅ находок нет: вердикт ЗЕЛЁН, свеж и про тот коммит, что в списке")
    else:
        out.append("   ⛔ НЕ ИЗМЕРЕНО: перечня находок в отчёте нет — это не «находок нет»")
    out.append("   ADVISORY: прибор только ЧИТАЕТ вердикт и ничего не запускает и не чинит")
    return out


def format_report(doc: dict) -> list:
    """Строки для ЧИТАТЕЛЯ — обязательного шага 0-офис.

    Отличие от :func:`report` ровно одно и оно про читателя, а не про предмет: у офиса
    заведено правило «красные строки = действовать», поэтому находка помечается знаком.
    """
    lines = report(doc)
    if str(doc.get("status")) == "FINDING":
        lines[0] = f"⚠️ {lines[0]}"
    return lines


def run(root=ROOT, *, now=None, fetch=None, grab=None, branch: str = DEFAULT_BRANCH,
        runs: int = DEFAULT_RUNS) -> dict:
    """ОДИН замер и документ. Ни файла, ни гейта такта — оба у того, КТО ПОЗВАЛ.

    Разделение не декоративное (урок ADR-843): писателя артефакта сторож достижимости ищет
    среди точек входа и импортированного кода, и прибор, зовомый подпроцессом по константе
    пути, ему не виден. Поэтому пишет ступень моста, а прибор остаётся ЧИТАЮЩИМ.

    ``fetch`` и ``grab`` — двери к сети ВХОДАМИ: без них каждый тест отвечал бы на вопрос
    «что сегодня у GitHub», а не «цела ли проводка» (`.claude/rules/deployment.md`, § про
    инъекцию).
    """
    if fetch is None:
        try:
            fetch = github_fetch()
        except (RuntimeError, OSError) as exc:
            # `OSError` здесь не для полноты: читатель токена зовёт `security`
            # подпроцессом, и на машине без него (или с урезанным `PATH`) поднимается
            # `FileNotFoundError`. Своим контролем этого файла пойман код возврата
            # **1** вместо 2 — то есть «вердикта нет» выглядело бы НАХОДКОЙ прибора,
            # а трассировка — его ответом.
            raise NotMeasured(f"вердикт не спрошен: {type(exc).__name__}: {exc}") from exc
    if grab is None:
        grab = artifact_grab(_keychain_token())
    rep = census(fetch=fetch, grab=grab, branch=branch, runs=runs, now=now)
    return document(rep, findings(rep), root=root, now=now)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--json", action="store_true",
                    help="отдать документ на stdout (его записывает ПОЗВАВШИЙ)")
    ap.add_argument("--branch", default=DEFAULT_BRANCH,
                    help="ветка, о вердикте которой спрашивается (умолчание — main)")
    ap.add_argument("--runs", type=int, default=DEFAULT_RUNS,
                    help="сколько строк списка прогонов прочитать")
    ap.add_argument("--repo-root", default=str(ROOT),
                    help="дерево, о котором спрашивается происхождение зова")
    args = ap.parse_args(argv)
    try:
        doc = run(root=args.repo_root, branch=args.branch, runs=args.runs)
    except NotMeasured as exc:
        print(f"⛔ НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        if args.json:
            print(json.dumps({"unmeasured": str(exc)}, ensure_ascii=False))
        return 2

    if args.json:
        print(json.dumps(doc, ensure_ascii=False))
    else:
        for line in report(doc):
            print(line)
    return 1 if doc["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
