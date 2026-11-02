#!/usr/bin/env python3
# LLM_FORBIDDEN
"""Подорожание шага: РАБОТА или СРЕДА — производитель отчёта (ADR-896).

**Зачем этот файл существует.** `spa_core/monitoring/step_time_drift.py` написан
02.10 (хвост [ADR-534](../docs/decisions/ADR-534-where-the-time-of-the-test-step-goes.md),
заказ G87 п. 3) и **не был позван НИ РАЗУ**: храповик
`spa_core/tests/test_unwired_guard_modules_ratchet.py` держал его в красном с
одним именем в жалобе. Прибор умел сравнивать две записи, но взять их было
НЕКОМУ: записи живут артефактами прогона в GitHub, и ни один читатель за ними не
ходил. «Написать проверку и не позвать её — то же, что не написать».

**Где лежит вход (замер 2026-11-02, живой API).** Контрольный прогон
`.github/workflows/ci-control.yml` режет предписанное население на 12 шардов, и
КАЖДЫЙ выгружает свою потоковую запись артефактом `ctl-shard-<N>` (член
`stream.jsonl`, 3.2 МБ в распакованном виде, 0.54–1.26 МБ в zip, срок хранения
30 дней). Пара прогонов стои́т 24 загрузки ≈15 МБ — цена НАЗВАНА, потому что
такт выбран по ней.

**Почему прогон СОСТАВНОЙ, а склейка записей запрещена.** Шарды идут
параллельно на 12 раннерах. `span` случая определён как «от своего старта до
старта следующего», поэтому склеенная запись мерила бы чередование раннеров.
Сложение идёт по ФАЙЛУ (`step_time_drift.profile_of_parts`), и файл, пришедший
из двух частей, НАЗЫВАЕТСЯ, а не складывается молча.

**Контроль «раннер против раннера» берётся у матрицы одного коммита** —
`.github/workflows/test.yml` гоняет один sha на py3.11 и py3.12 и выгружает
`test-records-<версия>-<номер>` (член `stream-spa_core.jsonl`). Контроль НЕ
подменяется нулём и не выдумывается: его отсутствие есть НАЗВАННЫЙ третий исход
(`unmeasured:no_same_commit_control`), и прибор печатает ПОЧЕМУ. Замер
2026-11-02: контроль сегодня НЕ ДОБЫВАЕТСЯ, и это ИЗМЕРЕНО, а не предположено —
на свежайшем прогоне `SPA Tests` 41355826308 нога **py3.11** записала 776
случаев в 26 файлах и вышла со `status=3` (INTERNALERROR) через 428.8 с, а нога
**py3.12** — 113 229 случаев в 2198 файлах и была снята топором (`ended=false`,
243 мин). Две ноги одного коммита сделали работу, различающуюся в 146 раз;
сопоставимых файлов у них меньше порога, и прибор отказывает НАЗВАННОЙ причиной
вместо подстановки единицы.

**Ловушка, на которой этот разбор чуть не соврал (и потому записана здесь).**
Прогон `SPA Tests` сначала выглядел «мёртвым с 2026-07-04»: так ответил
`GET /actions/workflows/299283229/runs`. Номер был взят ГЛАЗАМИ из перечня
воркфлоу и оказался СОСЕДНЕЙ строкой — 299283229 это «Deploy Landing», а `SPA
Tests` живёт под 299283233. Поэтому прибор адресует воркфлоу **ПУТЁМ ФАЙЛА**
(`workflows/test.yml/runs`), а не номером: путь объявлен в дереве и соврать не
может, номер — свойство чужого реестра.

**Оговорка про контроль, которую нельзя молчать:** 3.11 против 3.12 — это и
другой РАННЕР, и другой ИНТЕРПРЕТАТОР. Поэтому он есть ВЕРХНЯЯ граница шума
среды, а не чистый «раннер против раннера»; сравнение с ним ошибается в сторону
«находки нет», то есть fail-CLOSED по отношению к выводу «среда виновата».

**Три исхода кода возврата** (инв. #17): 0 — измерено, находки нет · 1 —
измерено, находка НАЗВАНА · 2 — НЕ ИЗМЕРЕНО с причиной. Третий НЕ пишет отчёт:
артефакт с выдуманным вердиктом лгал бы ещё и своим возрастом.

Прибор только ЧИТАЕТ (`applied=False`): ни тестов, ни воркфлоу, ни порогов он не
трогает. Только stdlib (инв. #4).
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import sys
import urllib.error
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:               # прибор зовут и подпроцессом, и из тестов
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

# Дверь БАЙТОВ и правило добычи токена берутся У СОСЕДА, а не копируются: вторая
# копия «снять Authorization на переадресации» разошлась бы с первой МОЛЧА, и
# тогда «вердикт недостижим» снова выглядело бы отказом доступа (класс ADR-220).
from ci_control_verdict import REPO, _keychain_token, artifact_grab  # noqa: E402
from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.monitoring.call_provenance import describe as provenance_line  # noqa: E402,E501
from spa_core.monitoring.record_survival_census import github_fetch  # noqa: E402
from spa_core.monitoring.step_time_census import READ_OK, READ_UNREADABLE  # noqa: E402
from spa_core.monitoring.step_time_census import census_from_events, parse_lines, unreadable  # noqa: E402,E501
from spa_core.monitoring.step_time_drift import (CODE_FINDING, CODE_OK,  # noqa: E402
                                                 CODE_UNMEASURED, drift_profiles,
                                                 exit_code, profile_of_parts,
                                                 read_as_work_or_environment, render)

#: Составной прогон: 12 шардов, запись у каждого своя.
CONTROL_WORKFLOW = "ci-control.yml"
SHARD_PREFIX = "ctl-shard-"
SHARD_MEMBER = "stream.jsonl"

#: Контроль среды: ОДИН коммит на двух раннерах матрицы.
MATRIX_WORKFLOW = "test.yml"
MATRIX_PREFIX = "test-records-"
MATRIX_MEMBER = "stream-spa_core.jsonl"
MATRIX_VERSIONS = ("3.11", "3.12")

DEFAULT_BRANCH = "main"

#: Сколько прогонов спрашивать у списка. Нужны ДВА завершённых, но список отдаёт и
#: идущие, и снятые, поэтому берётся с запасом: иначе «все в работе» читалось бы как
#: «прогонов нет». Тот же довод, что у `ci_control_verdict.DEFAULT_RUNS`.
RUNS_ASKED = 10

#: Сколько прогонов ПРОБОВАТЬ скачать. Предел нужен потому, что каждая попытка стои́т
#: 12 загрузок: прогон, умерший до шардов, не должен уводить прибор в обход всей
#: истории. Третий исход при исчерпании — названный, а не «пары нет».
RUNS_TRIED = 3

SCHEMA = "step_time_drift/1"


# ───────────────────────────── двери наружу ─────────────────────────────────

def _runs(fetch, workflow: str, branch: str, limit: int = RUNS_ASKED) -> list:
    path = (f"/repos/{REPO}/actions/workflows/{workflow}/runs"
            f"?per_page={int(limit)}&branch={branch}")
    doc = fetch(path) or {}
    rows = doc.get("workflow_runs") or []
    return [r for r in rows if r.get("status") == "completed"]


def _artifacts(fetch, run_id) -> list:
    doc = fetch(f"/repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100") or {}
    return doc.get("artifacts") or []


def _member(raw: bytes, member: str) -> str:
    return zipfile.ZipFile(io.BytesIO(raw)).read(member).decode("utf-8", "replace")


def _census_of_artifact(art: dict, member: str, *, grab):
    """Запись одного артефакта. Любая немочь — НАЗВАННЫЙ третий исход, не нули."""
    name = str(art.get("name"))
    if art.get("expired") is not False:
        return unreadable(READ_UNREADABLE,
                          f"артефакт {name} истёк (срок хранения прошёл)")
    url = art.get("archive_download_url") or (
        f"https://api.github.com/repos/{REPO}/actions/artifacts/{art.get('id')}/zip")
    try:
        raw = grab(url)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        return unreadable(READ_UNREADABLE,
                          f"артефакт {name} не скачан: {type(exc).__name__}: {exc}")
    try:
        text = _member(raw, member)
    except (zipfile.BadZipFile, KeyError, ValueError, TypeError) as exc:
        return unreadable(READ_UNREADABLE,
                          f"в артефакте {name} нет члена {member} "
                          f"({type(exc).__name__}: {exc})")
    events, torn = parse_lines(text.splitlines())
    return census_from_events(events, torn_lines=torn)


def parts_of_run(run_id, *, fetch, grab, prefix: str = SHARD_PREFIX,
                 member: str = SHARD_MEMBER):
    """`[(метка, запись)]` по всем частям прогона. Пустой список = частей НЕТ."""
    rows = [a for a in _artifacts(fetch, run_id) if str(a.get("name")).startswith(prefix)]
    rows.sort(key=lambda a: str(a.get("name")))
    return [(str(a.get("name")), _census_of_artifact(a, member, grab=grab)) for a in rows]


# ───────────────────────────── замер ─────────────────────────────────

def _run_row(run: dict, profile=None) -> dict:
    row = {"run": str(run.get("id")), "sha": (run.get("head_sha") or "")[:9],
           "created_at": run.get("created_at"), "event": run.get("event"),
           "conclusion": run.get("conclusion")}
    if profile is not None:
        row.update({"parts": profile.parts, "parts_read": profile.parts_read,
                    "parts_unread": [list(p) for p in profile.parts_unread],
                    "cases": profile.n_cases, "ended": profile.ended})
    return row


def pair_of_profiles(*, fetch, grab, branch: str = DEFAULT_BRANCH,
                     runs_tried: int = RUNS_TRIED):
    """Две самые свежие завершённые записи прогона: (позже, раньше, причина).

    Прогон, у которого частей нет вовсе (умер до шардов) или ни одна не читается,
    НАЗЫВАЕТСЯ и пропускается — иначе он молча становился бы «пары нет».
    """
    skipped: list = []
    found: list = []
    for run in _runs(fetch, CONTROL_WORKFLOW, branch)[:runs_tried]:
        parts = parts_of_run(run.get("id"), fetch=fetch, grab=grab)
        if not parts:
            skipped.append(f"{run.get('id')}: частей `{SHARD_PREFIX}*` нет вовсе")
            continue
        profile = profile_of_parts(parts)
        if profile.read != READ_OK:
            skipped.append(f"{run.get('id')}: {profile.reason}")
            continue
        found.append((run, profile))
        if len(found) == 2:
            break
    if len(found) < 2:
        why = ("завершённых прогонов с читаемой записью найдено "
               f"{len(found)} из нужных 2 (спрошено {runs_tried})")
        if skipped:
            why += "; пропущены: " + "; ".join(skipped[:3])
        return None, None, why
    return found[0], found[1], ""


def control_of_matrix(*, fetch, grab, branch: str = DEFAULT_BRANCH):
    """Масштаб «раннер против раннера» у матрицы ОДНОГО коммита: (ratio, причина).

    Отсутствие — третий исход с НАЗВАННОЙ причиной, а не единица и не ноль:
    подстановка единицы объявила бы находкой любое отличие, подстановка нуля —
    ни одного.
    """
    runs = _runs(fetch, MATRIX_WORKFLOW, branch)
    if not runs:
        return None, (f"у `{MATRIX_WORKFLOW}` нет ни одного завершённого прогона "
                      f"на ветке {branch}")
    for run in runs[:RUNS_TRIED]:
        rows = [a for a in _artifacts(fetch, run.get("id"))
                if str(a.get("name")).startswith(MATRIX_PREFIX)]
        sides = []
        for version in MATRIX_VERSIONS:
            mine = [a for a in rows
                    if str(a.get("name")).startswith(MATRIX_PREFIX + version + "-")]
            if mine:
                sides.append((version, mine[0]))
        if len(sides) != len(MATRIX_VERSIONS):
            continue
        censuses = [(v, _census_of_artifact(a, MATRIX_MEMBER, grab=grab))
                    for v, a in sides]
        first = profile_of_parts([censuses[0]])
        second = profile_of_parts([censuses[1]])
        measured = drift_profiles(first, second)
        if measured.get("verdict") != "measured":
            return None, (f"матрица прогона {run.get('id')} не сравнена: "
                          f"{measured.get('verdict')}")
        return measured["median_ratio"], (
            f"матрица прогона {run.get('id')} ({'/'.join(MATRIX_VERSIONS)}) — "
            f"ВЕРХНЯЯ граница шума среды: раннер И интерпретатор разом")
    newest = runs[0]
    return None, (f"ни у одного из последних прогонов `{MATRIX_WORKFLOW}` нет живой "
                  f"пары записей `{MATRIX_PREFIX}<версия>-*` (свежайший — "
                  f"{newest.get('id')} от {newest.get('created_at')})")


def measure(*, fetch, grab, now=None, branch: str = DEFAULT_BRANCH,
            tree_root=None) -> dict:
    """Документ отчёта. Исходы различимы и ни один не выдаётся за другой."""
    moment = (now or dt.datetime.now(dt.timezone.utc)).isoformat()
    doc = {"schema": SCHEMA, "generated_at": moment, "branch": branch,
           "applied": False,
           "invoked_by": call_provenance(tree_root=tree_root or ROOT)}
    try:
        later, base, why = pair_of_profiles(fetch=fetch, grab=grab, branch=branch)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        doc.update({"status": "unmeasured", "verdict": "unmeasured:runs_not_listed",
                    "kind": "unmeasured:runs_not_listed", "findings": [],
                    "reason": f"перечень прогонов не прочитан: "
                              f"{type(exc).__name__}: {exc}"})
        return doc
    if later is None:
        doc.update({"status": "unmeasured", "verdict": "unmeasured:no_pair_of_runs",
                    "kind": "unmeasured:no_pair_of_runs", "findings": [],
                    "reason": why})
        return doc
    later_run, later_profile = later
    base_run, base_profile = base
    result = drift_profiles(base_profile, later_profile)
    try:
        ratio, control_why = control_of_matrix(fetch=fetch, grab=grab, branch=branch)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        ratio, control_why = None, (f"контроль не спрошен: "
                                    f"{type(exc).__name__}: {exc}")
    kind = read_as_work_or_environment(result, ratio)
    doc.update({
        "status": "measured" if result.get("verdict") == "measured" else "unmeasured",
        "verdict": result.get("verdict"),
        "kind": kind,
        "base": _run_row(base_run, base_profile),
        "later": _run_row(later_run, later_profile),
        "control": {"ratio": ratio, "reason": control_why},
        "drift": result,
    })
    doc["findings"] = findings(doc)
    doc["reason"] = result.get("reason") or control_why
    return doc


def findings(doc: dict) -> list:
    """Что в этом документе есть НАХОДКА. Перечень закрытый (см. `FINDING_KINDS`).

    `unmeasured:*` находкой не становится НИКОГДА — ровно та подмена, которую
    подключение вскрыло у кода возврата прибора (ADR-896).
    """
    result = doc.get("drift") or {}
    if result.get("verdict") != "measured":
        return []
    out: list = []
    if exit_code({**result, "kind": doc.get("kind")}) == CODE_FINDING:
        out.append("шаг подорожал: медиана ×%.3f, размах %.3f, род — %s"
                   % (result["median_ratio"], result["iqr"], doc.get("kind")))
    for side, key in (("base", "resumed_base"), ("later", "resumed_later")):
        if result.get(key):
            out.append("%s: шард ДОИГРЫВАЛСЯ (сессий в записях больше, чем частей) — "
                       "население этого прогона БОЛЬШЕ работы, часть случаев "
                       "записана дважды" % side)
    for side in ("base", "later"):
        unread = (doc.get(side) or {}).get("parts_unread") or []
        if unread:
            out.append("%s: частей НЕ ПРОЧИТАНО %d из %d — сопоставимых файлов "
                       "меньше, и это НЕ «работа не менялась»"
                       % (side, len(unread), (doc.get(side) or {}).get("parts")))
    if result.get("files_in_two_parts"):
        out.append("файл пришёл из ДВУХ частей (%d) — секунды двух раннеров в одном "
                   "числе: %s" % (len(result["files_in_two_parts"]),
                                  ", ".join(result["files_in_two_parts"][:3])))
    return out


# ───────────────────────────── отчёт ─────────────────────────────────

def format_report(doc: dict) -> list:
    """Строки для шага 0-офис. Правило отрисовки ОДНО и живёт здесь."""
    out = ["   — подорожание шага тестов: работа или среда (ADR-896) —"]
    if not isinstance(doc, dict):
        return out + ["   ❗НЕ ИЗМЕРЕНО: документа нет"]
    out.append("   [ЗВАВШИЙ] " + provenance_line(doc.get("invoked_by")))
    if doc.get("status") != "measured":
        return out + ["   ❗НЕ ИЗМЕРЕНО: %s — %s" % (doc.get("verdict"),
                                                     doc.get("reason")),
                      "   ADVISORY: прибор только ЧИТАЕТ (applied=False)"]
    base, later = doc.get("base") or {}, doc.get("later") or {}
    out.append("   раньше: прогон %s (%s, %s) · позже: прогон %s (%s, %s)"
               % (base.get("run"), base.get("sha"), base.get("created_at"),
                  later.get("run"), later.get("sha"), later.get("created_at")))
    control = doc.get("control") or {}
    body = render(doc.get("drift") or {}, "прогон %s" % base.get("run"),
                  "прогон %s" % later.get("run"), control.get("ratio"),
                  control.get("reason"))
    out.extend("   " + line.strip() for line in body.splitlines()[1:])
    # Род, НАПИСАННЫЙ в документе, и род, ПЕРЕСЧИТАННЫЙ отрисовкой, обязаны
    # совпадать: это один вопрос, и два ответа на него означают, что документ
    # записан не тем кодом, которым читается (класс ADR-220). Расхождение
    # печатается ГРОМКО, а не сглаживается выбором «которому верить».
    recomputed = read_as_work_or_environment(doc.get("drift") or {}, control.get("ratio"))
    if recomputed != doc.get("kind"):
        out.append("   ❗ДВА ОТВЕТА на один вопрос: документ несёт род %r, пересчёт "
                   "даёт %r" % (doc.get("kind"), recomputed))
    if control.get("ratio") is None:
        out.append("   ❗контроль среды НЕ ДОБЫТ: %s" % control.get("reason"))
    for line in doc.get("findings") or []:
        out.append("   ⚠️ %s" % line)
    if not doc.get("findings"):
        out.append("   находок нет")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Подорожание шага: работа или среда (ADR-896, заказ G891 п. 7).")
    ap.add_argument("--json", action="store_true", help="печатать документ как JSON")
    ap.add_argument("--branch", default=DEFAULT_BRANCH)
    ap.add_argument("--repo-root", default=str(ROOT),
                    help="дерево, у которого спрашивается точка входа (провенанс)")
    args = ap.parse_args(argv)

    try:
        fetch = github_fetch()
    except RuntimeError as exc:
        print(json.dumps({"schema": SCHEMA, "status": "unmeasured",
                          "verdict": "unmeasured:no_token", "findings": [],
                          "reason": str(exc)}, ensure_ascii=False))
        return CODE_UNMEASURED
    doc = measure(fetch=fetch, grab=artifact_grab(_keychain_token()),
                  branch=args.branch, tree_root=Path(args.repo_root))
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    else:
        print("\n".join(format_report(doc)))
    if doc.get("status") != "measured":
        return CODE_UNMEASURED
    return CODE_FINDING if doc.get("findings") else CODE_OK


if __name__ == "__main__":                                   # pragma: no cover
    sys.exit(main())
