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

ПРИЧИНА внутри «НЕ ИЗМЕРЕНО» тоже обязана быть ЗАМЕРОМ (ADR-1058, цикл #1197). «Отчёта у прогона
нет» есть ОДНО наблюдение, «прогон не дожил до сводки» — ДРУГОЕ, и до 18.11 второе подставлялось
вместо первого по умолчанию: заказанный предшественником вердикт ИДУЩЕГО прогона 44393343317
(`status: in_progress`, шёл 1.0 ч) читался как «прогон умер раньше сводки». Живость спрашивается у
строки прогона (:func:`run_liveness`) и ТОЛЬКО когда отчёта нет; три состояния — завершён · ещё
идёт · живость НЕ ИЗМЕРЕНА — различимы, и ни одно не подставляется вместо другого. Код возврата у
всех трёх один (**2**): вердиктом не является ни одно из них, а различие живёт в ПРИЧИНЕ, у которой
есть читатель — следующий цикл, выбирающий между «ждать» и «заказать новый прогон» (≈1–1.6 ч
раннера и потерянный якорь дельты).

РЕЖИМ `--delta` И ОСЬ ПЕРЕЕЗДА (ADR-1077, заказ G1064 п. 2). Дельта двух прогонов судит
каждое имя по ДВУМ независимым осям: РОД (вынес ли прогон вердикт — ADR-1055) и ПЕРЕЕЗД
(о том же ли соседстве этот вердикт). Контрольный прогон идёт по 12 шардам, и состав шарда
пересчитывается каждый раз: замер #1222 на живой паре 45091782823 → 45108124169 — от ОДНОГО
добавленного тест-файла переехало **1570 файлов из 3011**, и переехали ВСЕ ТРИ настоящих
«пришедших» имени той дельты. Поэтому «пришло и переехало» — **третий исход, код 2**, а не 0
(«чисто» соврало бы) и не 1 («гнаться» отдало бы фантом). План шардов берётся из артефакта
`ctl-manifest`, у которого срок хранения **30 дней против 90** у отчёта: «вердикт есть, плана
нет» штатно, и ось тогда слепа С НАЗВАННОЙ ПРИЧИНОЙ, а дельта по родам остаётся измеренной.

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
import collections
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
from spa_core.monitoring import red_set_delta  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

#: НИ ПУТИ ОТЧЁТА, НИ ТАКТА здесь НЕТ — и это решение, а не пропуск (как у соседа
#: `worker_axis_census`): отчёт пишет ПОЗВАВШИЙ, срок решает ФАЙЛ отчёта, значит и путь, и
#: гейт такта живут у ступени — `findings_bridge.CI_CONTROL_VERDICT_ARTIFACT` / `…_TACT_DAYS`.
#: Вторая копия любого из них здесь разошлась бы с первой МОЛЧА (класс ADR-220).

WORKFLOW_FILE = "ci-control.yml"
REPORT_ARTIFACT = "ci-control-report"
REPORT_MEMBER = "report.json"
DEFAULT_BRANCH = "main"

#: Артефакт ПЛАНА ШАРДОВ того же прогона (ADR-1077). Имя и срок хранения — у
#: воркфлоу (`ci-control.yml`, джоба `manifest`), и ПАРИТЕТ с ним проверяет
#: батарея: литерал, разошедшийся с воркфлоу, молча ответил бы «карты нет» о
#: живом артефакте. Срок РАЗНЫЙ с отчётом — **30 дней против 90**, поэтому
#: «отчёт есть, карты нет» штатно и ось переезда тогда НЕ ИЗМЕРЕНА, а дельта
#: по родам остаётся измеренной.
MANIFEST_ARTIFACT = "ctl-manifest"
MANIFEST_MEMBER = "manifest.json"
MANIFEST_RETENTION_DAYS = 30

#: Что в отчёте считается КРАСНЫМ. `ci_control.aggregate` кладёт в `failures` И упавшие, И
#: ошибочные (`outcomes.get(n) in (FAILED, ERROR)`), а в `totals` разводит их по ДВУМ
#: ключам. Поэтому объявленный операнд — СУММА двух, а не `failed`: взять один ключ значило
#: бы кричать «названо не всё» на здоровом отчёте, у которого есть ошибки, и находка
#: говорила бы о своей же арифметике. Литералы — те же, что у производителя (`ci_control`
#: PASSED/SKIPPED/FAILED/ERROR), и их парность с ним держит тест батареи.
RED_OUTCOMES = ("failed", "error")
DECLARED_RED_KEYS = ("failed", "error")

#: Сколько худших файлов НАЗЫВАТЬ в отчёте. Перечень обрезан намеренно: полное население
#: живёт в документе (`red_census.worst` — тот же порог) и в самом `report.json`, а строка
#: отчёта обязана отвечать на вопрос «с чего начинать», а не воспроизводить артефакт.
WORST_FILES = 8

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

#: Окно, в котором ОТМЕНА прогона и СОЗДАНИЕ соседнего прогона той же группы считаются
#: одним событием — вытеснением заказа. Замер 2026-11-24 по ВСЕМ 400 прогонам
#: `ci-control` (живой API): отменённых **24**, и у **16** из них другой прогон создан в
#: пределах 60 с от отмены — чаще в ту же секунду (у прогона 45292542397 отмена
#: 23:58:36Z против создания 45293308721 в 23:58:35Z). Окно не ноль, потому что обе
#: отметки ставит GitHub и они дрожат на секунды; окно не минуты, потому что тогда в него
#: попадал бы любой сосед шестичасового такта. У остальных ВОСЬМИ совпадения в окне нет,
#: и причина их отмены остаётся НЕ ИЗМЕРЕННОЙ, а не «ручной»: догадка здесь и была бы
#: ровно тем, против чего написан инв. #17.
DISPLACEMENT_WINDOW_S = 60.0

#: Исходы :func:`cancellation_cause`. Ни один вердиктом не является — различаются ПРИЧИНЫ
#: отмены, и у различия есть читатель: вытесненный заказ надо ПОВТОРИТЬ (прогон не шёл
#: вовсе), а прогон, умерший на своём пределе, повторять бессмысленно.
CXL_DISPLACED, CXL_NO_NEIGHBOUR, CXL_UNMEASURED = "displaced", "no_neighbour", "unmeasured"

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


#: Состояния прогона, РАЗЛИЧИМЫЕ у :func:`run_liveness`. Ни одно из трёх вердиктом не
#: является — различаются ПРИЧИНЫ отсутствия вердикта, и это разные причины.
LIVE_DONE, LIVE_RUNNING, LIVE_UNMEASURED = "completed", "running", "unmeasured"


def run_liveness(run_id: str, *, fetch, now=None) -> dict:
    """ДОЖИЛ ли прогон до сводки — ОТДЕЛЬНЫЙ вопрос, и ответ на него НЕ выводится из
    отсутствия отчёта (ADR-1058).

    Замер 2026-11-18 (цикл #1197): заказанный предшественником вердикт прогона
    **44393343317** прибор объявил НЕ ИЗМЕРЕННЫМ с причиной «его нет вовсе — прогон умер
    раньше сводки», а живой API в ту же минуту отвечал `status: in_progress` (начат
    20:39Z, шёл 1.0 ч). Отчёт появляется ТОЛЬКО со сводкой, поэтому у идущего прогона его
    нет ПОКА — и это не смерть. Отсутствие отчёта есть ОДНО наблюдение, живость прогона —
    ДРУГОЕ, и первое ко второму не сводится.

    Цена ложной причины — не косметика: «умер» приглашает заказать НОВЫЙ прогон (≈1–1.6 ч
    раннера) и потерять якорь дельты, а «ещё идёт» требует ровно обратного — ждать и
    перечитать. Выдуманная причина внутри честного «НЕ ИЗМЕРЕНО» опаснее молчания: она
    выглядит как замер.

    Три исхода РАЗЛИЧИМЫ (инв. #17) и ни один не подставляется вместо другого:
    завершён · ещё идёт · живость НЕ ИЗМЕРЕНА (строка прогона не прочитана). Вопрос
    задаётся ТОЛЬКО когда отчёта нет: на счастливом пути лишнего запроса не делается.
    """
    try:
        run = fetch(f"/repos/{REPO}/actions/runs/{run_id}")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        return {"state": LIVE_UNMEASURED, "status": None, "conclusion": None,
                "age_h": None, "lived_s": None, "cancelled_at": None,
                "why": f"строка прогона {run_id} не прочитана: "
                       f"{type(exc).__name__}: {exc}"}
    if not isinstance(run, dict) or not run.get("status"):
        return {"state": LIVE_UNMEASURED, "status": None, "conclusion": None,
                "age_h": None, "lived_s": None, "cancelled_at": None,
                "why": f"строка прогона {run_id} статуса не несёт — "
                       f"это НЕ «прогон завершён»"}
    status = str(run.get("status"))
    started = _parse_moment(run.get("run_started_at") or run.get("created_at"))
    moment = now if now is not None else dt.datetime.now(dt.timezone.utc)
    age_h = None if started is None else (moment - started).total_seconds() / 3600.0
    # СРОК ЖИЗНИ завершённого прогона — ДРУГОЕ число, чем «сколько прошло от старта до
    # сейчас», и до 24.11 печаталось второе под словом первого: прогон 45292542397 жил
    # 346 с, а причина отсутствия отчёта сообщала «идёт 1.1ч». Число было верное, слово
    # — нет, и читают строку глазами. `updated_at` у завершённого прогона и есть момент,
    # когда он кончился (для отменённого — момент отмены).
    ended = _parse_moment(run.get("updated_at"))
    lived_s = (None if (started is None or ended is None)
               else (ended - started).total_seconds())
    return {"state": LIVE_DONE if status == "completed" else LIVE_RUNNING,
            "status": status, "conclusion": run.get("conclusion"), "age_h": age_h,
            "lived_s": lived_s,
            "cancelled_at": run.get("updated_at") if status == "completed" else None,
            "why": None}


def cancellation_cause(run_id: str, *, fetch, cancelled_at=None) -> dict:
    """ЧЕМ отменён прогон — вопрос ОТДЕЛЬНЫЙ от «дожил ли он до сводки».

    **Замер 2026-11-24 (цикл #1228), ради которого дверь написана.** Цикл #1227, исполняя
    свой же порядок «заказывать контрольный прогон КАЖДОЙ доставкой», заказал два прогона
    с промежутком 2.5 мин: `45292219029` (вершина кода, 23:50:24Z) и `45292542397`
    (вершина пост-записи, 23:52:50Z). Второй не шёл НИ ОДНОЙ секунды: группа
    `ci-control` объявлена с `cancel-in-progress: false`, то есть новый прогон не снимает
    идущий, а становится ОЖИДАЮЩИМ, — и ожидающий в группе GitHub держит РОВНО ОДИН.
    В 23:58:35Z расписанный прогон `45293308721` (`cron: 23 */6 * * *`) встал в ту же
    группу, и ожидающий `45292542397` был ОТМЕНЁН в 23:58:36Z, прожив 346 с. Вердикта он
    не вынес ни в одну сторону, а цикл, его заказавший, записал в заказ номер как якорь
    дельты — то есть потратил такт на измерение, которого не было.

    Население класса ИЗМЕРЕНО по ВСЕМ 400 прогонам воркфлоу: отменённых **24** (6.0 %),
    и у **16** из них другой прогон создан в пределах :data:`DISPLACEMENT_WINDOW_S` от
    отмены. Форма наблюдается КАСКАДОМ — #183 снят созданием #184, #184 созданием #185,
    #185 созданием #186, — и это ровно «каждый новый заказ убивает предыдущий ожидающий».

    **Почему вопрос задаётся БЕЗ фильтра по ветке.** Группа объявлена строкой
    `group: ci-control` без `github.ref` в ней, поэтому вытеснить заказ может прогон
    ЛЮБОЙ ветки. Спросить список с `?branch=main` значило бы ответить на более узкий
    вопрос и назвать вытеснение «не измеренным» там, где оно измеримо.

    Три исхода РАЗЛИЧИМЫ (инв. #17), и ни один не подставляется вместо другого:

    * :data:`CXL_DISPLACED` — в окне от отмены создан прогон той же группы, он НАЗВАН
      (номер и событие). Заказ не шёл вовсе ⇒ его надо ПОВТОРИТЬ;
    * :data:`CXL_NO_NEIGHBOUR` — совпадения в окне НЕТ. Это НЕ «отменён рукой»: рука,
      предел джобы и вытеснение за пределами окна здесь неразличимы, и причина остаётся
      НЕ ИЗМЕРЕННОЙ;
    * :data:`CXL_UNMEASURED` — список прогонов не прочитан либо момент отмены не разобран.
      Подставить сюда любой из двух предыдущих значило бы выдать «не спросили» за ответ.
    """
    moment = _parse_moment(cancelled_at)
    if moment is None:
        return {"state": CXL_UNMEASURED, "by": [],
                "why": f"момент отмены прогона {run_id} не прочитан "
                       f"(`updated_at`: {cancelled_at!r})"}
    path = f"/repos/{REPO}/actions/workflows/{WORKFLOW_FILE}/runs?per_page=100"
    try:
        listing = fetch(path)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        return {"state": CXL_UNMEASURED, "by": [],
                "why": f"список прогонов `{WORKFLOW_FILE}` не прочитан: "
                       f"{type(exc).__name__}: {exc}"}
    rows = (listing or {}).get("workflow_runs")
    if not isinstance(rows, list):
        return {"state": CXL_UNMEASURED, "by": [],
                "why": f"список прогонов `{WORKFLOW_FILE}` строк не несёт — это НЕ "
                       f"«соседей не было»"}
    near = []
    for row in rows:
        if str(row.get("id")) == str(run_id):
            continue
        born = _parse_moment(row.get("created_at"))
        if born is None:
            continue
        if abs((born - moment).total_seconds()) <= DISPLACEMENT_WINDOW_S:
            near.append({"id": str(row.get("id")), "event": row.get("event"),
                         "created_at": row.get("created_at")})
    if near:
        return {"state": CXL_DISPLACED, "by": near, "why": None}
    return {"state": CXL_NO_NEIGHBOUR, "by": [],
            "why": f"в окне ±{DISPLACEMENT_WINDOW_S:.0f} с от отмены прогонов группы "
                   f"`ci-control` не создавалось"}


def _lifetime(live: dict) -> str:
    """Срок жизни завершённого прогона словом, которое ему соответствует."""
    lived = live.get("lived_s")
    return "" if lived is None else f", прожил {lived:.0f} с"


def _cancelled_cause(run_id: str, live: dict, *, fetch) -> str:
    """Строка причины для ОТМЕНЁННОГО прогона — у неё свой адресат и своё действие."""
    cxl = cancellation_cause(run_id, fetch=fetch,
                             cancelled_at=live.get("cancelled_at"))
    head = (f"его нет вовсе — прогон ОТМЕНЁН (`status: completed`, "
            f"`conclusion: {live['conclusion']}`{_lifetime(live)})")
    if cxl["state"] == CXL_DISPLACED:
        who = ", ".join(f"{r['id']} (`{r['event']}`, создан {r['created_at']})"
                        for r in cxl["by"])
        return (f"{head}: ЗАКАЗ ВЫТЕСНЕН из группы `ci-control` — в окне "
                f"±{DISPLACEMENT_WINDOW_S:.0f} с от отмены создан прогон {who}. Группа "
                f"объявлена `cancel-in-progress: false`, то есть второй заказ, поданный "
                f"пока прогон группы идёт, становится ОЖИДАЮЩИМ, а ожидающий GitHub "
                f"держит РОВНО ОДИН и отменяет его ЛЮБЫМ третьим (включая расписанный "
                f"каждые 6 ч). Вердикта этот прогон не выносил НИ В ОДНУ сторону: "
                f"заказывать надо ОДИН раз, на ПОСЛЕДНЕЙ вершине доставки, и перечитать, "
                f"что заказ ЖИВ")
    if cxl["state"] == CXL_NO_NEIGHBOUR:
        return (f"{head}, а ЧЕМ отменён — НЕ ИЗМЕРЕНО ({cxl['why']}): рука, предел джобы "
                f"и вытеснение за пределами окна здесь неразличимы")
    return (f"{head}, а ЧЕМ отменён — НЕ ИЗМЕРЕНО ({cxl['why']})")


def _absence_cause(run_id: str, *, fetch, now=None) -> str:
    """ПОЧЕМУ отчёта нет — причина ЗАРАБОТАННАЯ, а не назначенная по умолчанию."""
    live = run_liveness(run_id, fetch=fetch, now=now)
    age = "" if live.get("age_h") is None else f", идёт {live['age_h']:.1f}ч"
    if live["state"] == LIVE_RUNNING:
        # Строка утверждает РОВНО одно состояние и не поминает соседнее даже
        # отрицанием: «это НЕ умер…» стояло здесь в первой редакции и ломало
        # утверждение «идущий прогон не назван мёртвым» СВОИМ ЖЕ словом (поймано
        # прогоном). Почему состояния разные — объяснено в докстроке и ADR-1058, а не
        # в причине, которую читают и глазами, и подстрокой.
        return (f"его нет ПОКА — прогон ЕЩЁ ИДЁТ (`status: {live['status']}`{age}): "
                f"отчёт кладётся сводкой, и ждать здесь надо, а не заказывать новый "
                f"прогон")
    if live["state"] == LIVE_DONE:
        # «Отменён» и «умер на своём пределе» — РАЗНЫЕ состояния с разным действием
        # читателя, и до 24.11 они сливались в одно слово «умер раньше сводки»
        # (цикл #1228). Отменённый прогон не шёл вовсе ⇒ заказ повторяют; умерший
        # повторять бессмысленно — он дойдёт до того же предела.
        if str(live.get("conclusion")) == "cancelled":
            return _cancelled_cause(run_id, live, fetch=fetch)
        return (f"его нет вовсе — прогон умер раньше сводки "
                f"(`status: completed`, `conclusion: {live['conclusion']}`"
                f"{_lifetime(live)})")
    return (f"его нет, а ДОЖИЛ ЛИ прогон до сводки — НЕ ИЗМЕРЕНО ({live['why']}): "
            f"«умер» и «ещё идёт» здесь неразличимы, и выдумывать их запрещено")


def report_of_run(run_id: str, *, fetch, grab, now=None) -> dict:
    """`report.json` одного прогона. Любая немочь — :class:`NotMeasured` с причиной.

    `now` — ВХОД (умолчание — стенные часы): возраст идущего прогона есть замер, и в
    тестах обе стороны этого сравнения закрепляются одним якорем.
    """
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
               _absence_cause(run_id, fetch=fetch, now=now))
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


def manifest_of_run(run_id: str, *, fetch, grab, now=None) -> dict:
    """`manifest.json` артефакта `ctl-manifest` одного прогона (ADR-1077).

    Отдельная дверь от :func:`report_of_run` по ПРЕДМЕТУ, а не ради симметрии:
    артефакты РАЗНЫЕ (`ctl-manifest` против `ci-control-report`), сроки
    хранения разные (30 против 90 дней), и вопросы разные — «какие имена
    красны» против «о том же ли соседстве». Немочь — :class:`NotMeasured` с
    причиной; РУШИТЬ дельту она не вправе, и зовущий её ловит
    (:func:`_shard_map_of_run`).
    """
    try:
        listing = fetch(f"/repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        raise NotMeasured(f"перечень артефактов прогона {run_id} не прочитан: "
                          f"{type(exc).__name__}: {exc}") from exc
    rows = (listing or {}).get("artifacts") or []
    live = [a for a in rows
            if a.get("name") == MANIFEST_ARTIFACT and a.get("expired") is False]
    if not live:
        expired = [a for a in rows if a.get("name") == MANIFEST_ARTIFACT]
        why = (f"истёк ({MANIFEST_RETENTION_DAYS} дней — срок КОРОЧЕ, чем у "
               f"отчёта, поэтому состояние «вердикт есть, плана шардов нет» "
               f"штатно" if expired else
               _absence_cause(run_id, fetch=fetch, now=now))
        raise NotMeasured(f"у прогона {run_id} плана шардов "
                          f"`{MANIFEST_ARTIFACT}` нет: {why}")
    art = live[0]
    url = art.get("archive_download_url") or (
        f"https://api.github.com/repos/{REPO}/actions/artifacts/{art.get('id')}/zip")
    try:
        raw = grab(url)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        raise NotMeasured(f"план шардов прогона {run_id} не скачан: "
                          f"{type(exc).__name__}: {exc}") from exc
    try:
        doc = json.loads(zipfile.ZipFile(io.BytesIO(raw)).read(MANIFEST_MEMBER))
    except (zipfile.BadZipFile, KeyError, ValueError, TypeError) as exc:
        raise NotMeasured(f"план шардов прогона {run_id} не разобран "
                          f"({type(exc).__name__}: {exc})") from exc
    return doc


def _shard_map_of_run(run_id: str, *, fetch, grab, now=None):
    """Карта шардов прогона либо НАЗВАННАЯ немочь — но НЕ исключение наружу.

    Разбор манифеста живёт у `red_set_delta.shard_map_of` в ЕДИНСТВЕННОЙ копии:
    второй разошёлся бы с первым молча. Здесь — только добыча байтов.

    **Номер прогона знает ТОЛЬКО эта дверь** (заказ G1065 п. 13): в самом
    манифесте его нет — `ci_control.cmd_plan` пишет `sha` и номера не пишет
    вовсе. Поэтому `run_id` уезжает ВХОДОМ в оба исхода, а вершину карта
    берёт из манифеста сама. До 23.11 у карты было одно поле `run`, и в него
    попадал то номер прогона (здесь), то вершина (у разборщика), — два рода в
    одном имени, неразличимые по построению.
    """
    try:
        doc = manifest_of_run(run_id, fetch=fetch, grab=grab, now=now)
    except NotMeasured as exc:
        return red_set_delta.unmeasured_shard_map(str(exc), run=run_id)
    return red_set_delta.shard_map_of(
        doc, label=f"план шардов прогона {run_id}", run=run_id)


def _load_cause_line():
    """`cause_line` свода ПО ПУТИ — ЕДИНСТВЕННАЯ копия правила про ось причин (ADR-891).

    Своя копия здесь означала бы два ответа на один вопрос: одна строка сказала бы
    «причин нет», другая «НЕ ИЗМЕРЕНО», и расхождение было бы молчаливым (класс
    ADR-220). Дверь не нашлась ⇒ НАЗВАННЫЙ третий исход, а не выдуманная строка.
    """
    path = ROOT / "scripts" / "ci_control.py"
    if not path.is_file():
        return lambda _axis: ("ось причин НЕ ИЗМЕРЕНА: свода "
                              f"`{path}` нет — правило чтения оси живёт у него, и "
                              "выдумывать второе запрещено")
    import importlib.util
    spec = importlib.util.spec_from_file_location("_civ_ci_control", path)
    if spec is None or spec.loader is None:
        return lambda _axis: ("ось причин НЕ ИЗМЕРЕНА: "
                              f"`{path}` не загружается (загрузчика нет)")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        line = module.cause_line
    except Exception as exc:                                        # noqa: BLE001
        return lambda _axis, _why=f"{type(exc).__name__}: {exc}": (
            f"ось причин НЕ ИЗМЕРЕНА: свод не ввезён ({_why})")
    return line


def red_census(rep: dict) -> dict:
    """ПЕРЕПИСЬ красного населения ОДНОГО отчёта: из ЧЕГО состоит число упавших.

    ЗАЧЕМ (заказ G885 п. 4). До 01.11 читатель вердикта отдавал про красное РОВНО одно
    число и приписку «упавшие НАЗВАНЫ поимённо в `report.json` артефакта». Имена там и
    лежали — и не брал их НИ ОДИН читатель. Замер 01.11 на `126a2ec2a`: **79** падений в
    **50** файлах, из них **13** файлов несут по два и больше (42 падения) и **37** —
    одиночки. Девять разобранных храповиков (заказ G885 п. 1) есть подмножество, доля
    которого в населении до этой переписи не измерялась ни разу, то есть «с чего начинать»
    выбиралось вкусом.

    ЧТО СЧИТАЕТСЯ, и ни одна ось не отвечает на вопрос другой:

    * **названных** — строк `failures` с разбираемым `nodeid`;
    * **объявленных** — `totals.failed + totals.error` (см. :data:`DECLARED_RED_KEYS`);
    * **второй перечень того же прогона** — `non_passed`, независимая запись исходов.
      Три числа у здорового отчёта равны, и расхождение любой пары есть находка:
      красное, которое объявлено и не названо, нечем ни разобрать, ни починить;
    * **файлы** — и отдельно те, что несут ≥2 падения: у такого файла это ОДНА работа,
      а не несколько (урок #1002 на `test_fixture_schema_gap_ratchet` — три красных
      теста оказались одной правкой).

    ТРИ ИСХОДА РАЗЛИЧИМЫ (инв. #17): перепись измерена · измерена и население ПУСТО
    (зелёный отчёт) · **НЕ ИЗМЕРЕНА** — перечня `failures` в отчёте нет вовсе. Третий
    исход отдаётся словом и причиной, а НЕ нулём: «красное не названо» и «красного нет»
    чинятся разным, и свести их значило бы вернуть предмет на шаг дальше.

    Строка `failures`, у которой `nodeid` не строка или пуст, в ноль не списывается — она
    ложится в `nameless_rows`: безымянное падение есть падение, о котором не известно
    ничего, и молча терять его хуже, чем назвать.
    """
    raw = rep.get("failures")
    if not isinstance(raw, list):
        why = (f"перечня `failures` у отчёта нет (там {type(raw).__name__}) — "
               f"это НЕ «красного нет»")
        # Ось причин получает СВОЮ причину, а не чужую: без перечня падений у неё нет
        # НОСИТЕЛЯ, и сказать «отчёт собран сводом старше оси» было бы неверным
        # объяснением верного исхода — ровно тот дефект, против которого ось заведена.
        return {"status": "unmeasured", "why": why,
                "cause_axis": {"status": "unmeasured",
                               "why": f"у оси нет носителя: {why}"}}
    rows = [r for r in raw if isinstance(r, dict)]
    names, nameless = [], len(raw) - len(rows)
    for row in rows:
        nodeid = row.get("nodeid")
        if isinstance(nodeid, str) and nodeid.strip():
            names.append(nodeid.strip())
        else:
            nameless += 1
    files = collections.Counter(n.split("::")[0] for n in names)
    roots = collections.Counter(f.split("/")[0] for f in files.elements())
    multi = {f: c for f, c in files.items() if c > 1}

    totals = rep.get("totals") if isinstance(rep.get("totals"), dict) else {}
    parts = {k: totals.get(k) for k in DECLARED_RED_KEYS}
    declared = (sum(parts.values()) if all(isinstance(v, int) for v in parts.values())
                else None)
    non_passed = rep.get("non_passed")
    cross = (sum(1 for v in non_passed.values() if v in RED_OUTCOMES)
             if isinstance(non_passed, dict) else None)
    shards = rep.get("shards") if isinstance(rep.get("shards"), list) else []
    return {
        "status": "measured",
        "named": len(names),
        "nameless_rows": nameless,
        "declared": declared,
        "declared_parts": parts,
        "cross_named": cross,
        "files": len(files),
        "subjects_multi": len(multi),
        "subjects_single": sum(1 for c in files.values() if c == 1),
        "in_multi": sum(multi.values()),
        "roots": dict(sorted(roots.items())),
        "worst": [[f, c] for f, c in files.most_common(WORST_FILES)],
        "shards_with_red": len({r.get("shard") for r in rows
                                if r.get("shard") is not None}),
        "shards_total": len(shards),
        "outcomes": dict(sorted(collections.Counter(
            str(r.get("outcome")) for r in rows).items())),
        # Ось ПРИЧИН (ADR-891) приезжает ГОТОВОЙ от свода: опознаёт её единственная
        # дверь `failure_cause_census`, и переопознавать её здесь было бы вторым
        # ответом на один вопрос. Блока нет ⇒ `None`, и строка скажет «НЕ ИЗМЕРЕНО:
        # отчёт собран сводом старше оси» — не ноль (инв. #17).
        "cause_axis": (rep.get("cause_axis")
                       if isinstance(rep.get("cause_axis"), dict) else None),
    }


def census_line(cen) -> str:
    """ОДНА строка про население красного — ЕДИНСТВЕННАЯ копия этого правила.

    Её читают и находка о красном наборе, и блок отчёта: вторая копия разошлась бы с
    первой молча (класс ADR-220). Не измерено ⇒ СЛОВА с причиной, а не ноль.
    """
    if not isinstance(cen, dict):
        return ("перепись красного НЕ ИЗМЕРЕНА: её в документе нет вовсе — "
                "из ЧЕГО состоит это число, не знает никто")
    if cen.get("status") != "measured":
        return (f"перепись красного НЕ ИЗМЕРЕНА: {cen.get('why') or 'причина не названа'}")
    roots = cen.get("roots") or {}
    worst = cen.get("worst") or []
    return (f"перепись: названных {cen.get('named')} в {cen.get('files')} файл(ах) — "
            f"{cen.get('subjects_multi')} файл(а) несут ≥2 ({cen.get('in_multi')} "
            f"падени(я), одна работа каждый), одиночек {cen.get('subjects_single')}"
            + (f"; корни " + " · ".join(f"{k} {v}" for k, v in roots.items()) if roots else "")
            + (f"; худший {worst[0][0]} ({worst[0][1]})" if worst else ""))


def census_findings(cen, verdict) -> list:
    """Находки О ПЕРЕПИСИ — утверждения, которые чинятся отдельно от самих красных.

    Расхождение двух независимых записей одного прогона (`failures` против `non_passed`)
    и расхождение названного с объявленным (`totals.failed + totals.error`) — это НЕ
    «набор красен», а «про красное известно не всё», и смешивать их с вердиктом нельзя:
    первое чинится в наборе, второе — у производителя отчёта.

    Отсутствие переписи при НЕ-зелёном вердикте есть находка; при зелёном — нет: у
    зелёного отчёта перечень падений пуст ПО ПОСТРОЕНИЮ, и требовать его значило бы
    краснеть на здоровом прогоне.
    """
    out = []
    if not isinstance(cen, dict) or cen.get("status") != "measured":
        if verdict != GREEN:
            why = ((cen or {}).get("why") if isinstance(cen, dict)
                   else "переписи в документе нет вовсе")
            out.append(f"население красного НЕ ИЗМЕРЕНО: {why or 'причина не названа'} — "
                       f"число упавших есть, а из чего оно состоит, не знает никто")
        return out
    named = cen.get("named")
    declared, cross = cen.get("declared"), cen.get("cross_named")
    if declared is None:
        out.append("объявленное число красного НЕ ИЗМЕРЕНО: в итогах нет ключей "
                   f"{' + '.join(DECLARED_RED_KEYS)} — названное сверить не с чем")
    elif declared != named:
        out.append(f"красное НАЗВАНО не всё: объявлено {declared} "
                   f"({' + '.join(f'{k}={v}' for k, v in (cen.get('declared_parts') or {}).items())}), "
                   f"названо {named} — разница {declared - named} падени(й) существует и "
                   f"не имеет имени, то есть разобрать её нечем")
    if cross is not None and cross != named:
        out.append(f"две независимые записи ОДНОГО прогона не сходятся: `failures` "
                   f"называет {named}, `non_passed` — {cross}; какая из них полна, по "
                   f"отчёту не видно")
    if cen.get("nameless_rows"):
        out.append(f"{cen['nameless_rows']} строк(и) перечня падений без разбираемого "
                   f"`nodeid`: падение есть, имени у него нет")
    # Ось ПРИЧИН (ADR-891). Население названо — а ПОЧЕМУ оно упало, у отчёта могло не
    # оказаться вовсе; «79 красных» читается как «79 поломок», и это разные числа.
    axis = cen.get("cause_axis")
    if not isinstance(axis, dict) or axis.get("status") != "measured":
        if named:
            why = ((axis or {}).get("why") if isinstance(axis, dict)
                   else "блока `cause_axis` в отчёте нет вовсе — свод старше ADR-891")
            out.append(f"ПРИЧИНА {named} падени(й) НЕ ИЗМЕРЕНА: "
                       f"{why or 'причина не названа'} — население названо, а свести "
                       f"его к числу ДЕФЕКТОВ нечем")
    else:
        # ОБМОРОК СЕССИИ (ADR-892) — находка СВОЕГО рода, и она не про набор.
        # Прогон 41318580149 (`9ebe92509`) её уже нёс: шард 7 умер внутренне
        # (`TypeError` в отрисовке провала самим pytest, exit 3), и до ADR-892
        # читатель говорил о том же событии ДВЕ неверные вещи — «причина не
        # опознана» про жертву и «две записи СПОРЯТ» про запись обморока.
        deaths = axis.get("session_deaths") or []
        if deaths:
            who = ", ".join(str(d.get("shard")) for d in deaths)
            first = deaths[0]
            out.append(f"СЕССИЯ pytest УМЕРЛА внутренне у шард(ов) {who} "
                       f"({first.get('kind') or '«тип не назван»'}: "
                       f"{str(first.get('skeleton') or '«сообщения нет»')[:120]}): под "
                       f"обмороком {axis.get('session_victims_n') or 0} падени(й) — это "
                       f"свойство ИНСТРУМЕНТА, а не дефект набора, и чинится оно не в "
                       f"тесте; в вилку дефектов эти падения не входят")
        elif axis.get("session_victims_n"):
            out.append(f"{axis['session_victims_n']} падени(й) помечены потоковой "
                       f"записью как жертвы обморока сессии, а самой записи обморока "
                       f"junit не несёт ни у одного шарда: две записи одного прогона "
                       f"знают о событии РАЗНОЕ")
        miss = axis.get("unattributed_n") or 0
        if miss:
            out.append(f"у {miss} из {axis.get('population')} падени(й) причина НЕ "
                       f"ОПОЗНАНА (поимённо в `cause_axis.unattributed`): junit-запись "
                       f"их не несёт, и это свойство ЗАПИСИ, а не отсутствие причины")
        if axis.get("record_only_n"):
            out.append(f"{axis['record_only_n']} падени(й) есть в junit-записи и НЕ "
                       f"числятся упавшими в отчёте: две записи одного прогона спорят")
        bad = [k for k, ok in (axis.get("identities_hold") or {}).items() if not ok]
        if bad:
            out.append(f"тождество учёта оси причин НАРУШЕНО у {', '.join(sorted(bad))}: "
                       f"род вне объявленного перечня исчезает из печатаемой строки молча")
    return out


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
    # Здесь прогон завершён ПО ПОСТРОЕНИЮ (`done` отобран по `status == "completed"`),
    # поэтому причина «умер раньше сводки» на этом пути заработана и до ADR-1058. Якорь
    # времени всё равно уезжает входом: вторая копия часов разошлась бы с первой молча.
    doc = report_of_run(str(latest.get("id")), fetch=fetch, grab=grab, now=moment)
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
        "red_census": red_census(doc),
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
                   f"not_obtained={rep.get('not_obtained')} — "
                   + census_line(rep.get("red_census")))
    elif verdict != GREEN:
        out.append(f"вердикт прогона {run.get('id')} не опознан: {verdict!r} — "
                   f"это не «зелено»")
    out.extend(census_findings(rep.get("red_census"), verdict))
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
        "red_census": rep["red_census"],
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
    cen = observed(doc, "red_census", kind=dict)
    out.append(f"   {census_line(cen)}")
    out.append("   " + ("ось причин НЕ ИЗМЕРЕНА: переписи красного в документе нет "
                        "ВОВСЕ — у оси нет носителя"
                        if not isinstance(cen, dict)
                        else _load_cause_line()(cen.get("cause_axis"))))
    if cen is not None and cen.get("status") == "measured":
        worst = cen.get("worst") or []
        out.append("   с чего начинать (худшие файлы): " + (" · ".join(
            f"{f} ×{c}" for f, c in worst) or "НЕ ИЗМЕРЕНО — имён в перечне нет"))
        out.append(f"   сверка перечней: названных {cen.get('named')} · объявлено "
                   f"{'НЕ ИЗМЕРЕНО' if cen.get('declared') is None else cen['declared']}"
                   f" · второй перечень прогона "
                   f"{'НЕ ИЗМЕРЕНО' if cen.get('cross_named') is None else cen['cross_named']}"
                   f" · шардов с красным {cen.get('shards_with_red')} из "
                   f"{cen.get('shards_total')}")
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


def delta_run(prev_run: str, curr_run: str, *, fetch=None, grab=None, now=None):
    """Дельта красного набора ДВУХ прогонов ПО РОДАМ (ADR-1055, цикл #1194).

    Отдельный режим, а НЕ новая строка обычного отчёта: обычный отчёт читает шаг
    0-офис, и дописывать в него секцию значило бы подчинить её чужому словарю
    статусов (урок #1130). Поэтому умолчание этого файла не меняется ни байтом.

    Дверь к сети — ЕДИНСТВЕННАЯ (:func:`report_of_run`); второй её копии нет
    намеренно, иначе «какой документ сравнивается» имело бы два ответа.

    **Номера прогонов здесь приходят ИЗВНЕ** (заказ предыдущего цикла), а не отбираются
    по `status == "completed"`, как в :func:`census`. Поэтому ровно на этом пути «отчёта
    нет» законно означает И «прогон ещё идёт» — причину называет :func:`run_liveness`
    (ADR-1058), а не умолчание.
    """
    if fetch is None:
        try:
            fetch = github_fetch()
        except (RuntimeError, OSError) as exc:
            raise NotMeasured(f"дельта не спрошена: {type(exc).__name__}: {exc}") from exc
    if grab is None:
        grab = artifact_grab(_keychain_token())
    prev = report_of_run(prev_run, fetch=fetch, grab=grab, now=now)
    curr = report_of_run(curr_run, fetch=fetch, grab=grab, now=now)
    return red_set_delta.delta(
        prev, curr,
        prev_shards=_shard_map_of_run(prev_run, fetch=fetch, grab=grab, now=now),
        curr_shards=_shard_map_of_run(curr_run, fetch=fetch, grab=grab, now=now))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--delta", nargs=2, metavar=("ПРЕЖНИЙ", "ТЕКУЩИЙ"),
                    help="дельта красного набора двух прогонов ПО РОДАМ и ПО "
                         "ОСИ ПЕРЕЕЗДА: пришедшее имя рода `wallclock_timeout` "
                         "регрессией не является (ADR-1055), а пришедшее имя, "
                         "СМЕНИВШЕЕ ШАРД, есть третий исход — код 2, не 0 "
                         "(ADR-1077)")
    ap.add_argument("--json", action="store_true",
                    help="отдать документ на stdout (его записывает ПОЗВАВШИЙ)")
    ap.add_argument("--branch", default=DEFAULT_BRANCH,
                    help="ветка, о вердикте которой спрашивается (умолчание — main)")
    ap.add_argument("--runs", type=int, default=DEFAULT_RUNS,
                    help="сколько строк списка прогонов прочитать")
    ap.add_argument("--repo-root", default=str(ROOT),
                    help="дерево, о котором спрашивается происхождение зова")
    args = ap.parse_args(argv)

    if args.delta:
        try:
            d = delta_run(args.delta[0], args.delta[1])
        except NotMeasured as exc:
            print(f"⛔ НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
            if args.json:
                print(json.dumps({"unmeasured": str(exc)}, ensure_ascii=False))
            return 2
        if args.json:
            print(json.dumps({
                "schema": "spa-red-set-delta/1",
                "status": d.status,
                "reason": d.reason,
                "prev": {"run": d.prev.run, "sha": d.prev.sha,
                         "names": len(d.prev.names)},
                "curr": {"run": d.curr.run, "sha": d.curr.sha,
                         "names": len(d.curr.names)},
                "arrived": [t._asdict() for t in d.arrived],
                "departed": [t._asdict() for t in d.departed],
                "defect_arrivals": [t.nodeid for t in d.defect_arrivals],
                # ось ПЕРЕЕЗДА (ADR-1077): «гнаться» и «ось слепа» — РАЗНЫЕ
                # ключи, и ни один не подставляется вместо другого.
                "shard_axis": {
                    "measured": d.shard_axis_measured,
                    "prev": {"status": d.prev_shards.status,
                             "reason": d.prev_shards.reason,
                             "files": len(d.prev_shards.by_file)},
                    "curr": {"status": d.curr_shards.status,
                             "reason": d.curr_shards.reason,
                             "files": len(d.curr_shards.by_file)},
                },
                "chase": [t.nodeid for t in d.chase],
                "shard_blind_arrivals": [t.nodeid for t in d.shard_blind_arrivals],
                "moved_departures": [t.nodeid for t in d.moved_departures],
            }, ensure_ascii=False))
        else:
            for line in red_set_delta.format_delta(d):
                print(line)
        # 2 — НЕ ИЗМЕРЕНО · 1 — пришло имя, о котором вердикт ЕСТЬ И шард тот
        # же · 0 — чисто. Три исхода различимы кодом возврата (инв. #17).
        #
        # ОСЬ ПЕРЕЕЗДА (ADR-1077, заказ G1064 п. 2). Пришедшее имя, которое
        # ПЕРЕЕХАЛО на другой шард, даёт **2**, а не 0 и не 1: вердикта о его
        # содержании эта дельта не несёт. Ноль соврал бы в сторону «чисто» —
        # ровно то, что заказ запрещает; единица отдала бы следующему циклу
        # имя, которого он не воспроизведёт (замер #1222: 3 из 3 настоящих
        # пришедших имён дельты 45091782823 → 45108124169 переехали).
        # Одно «гнаться» перебивает любое число слепых: там есть что чинить.
        if d.status == red_set_delta.UNMEASURED:
            return 2
        if d.chase:
            return 1
        return 2 if d.shard_blind_arrivals else 0

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
