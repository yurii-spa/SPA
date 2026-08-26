#!/usr/bin/env python3
"""Сторож: у head'а каждого открытого PR обязан быть хотя бы ОДИН прогон Actions.

Авария 2026-08-26 (PR #46, ADR-145). Событие `pull_request` не создало НИ ОДНОГО
прогона GitHub Actions. Не «прогон упал» — прогона не было вовсе. На странице PR
стояла одна зелёная галочка стороннего деплоя, и PR выглядел проверенным.

Замер: у каждого предыдущего head ветки прогон `ci.yml` есть (`7543ba7`, `91f9c07`,
`91eddc7`, `a4fd5f9` …), у `c7586a5` — нет вообще, при том что в диффе пять
`.py`-файлов, то есть `paths-ignore` ни при чём. Actions при этом жив: ручной
`workflow_dispatch` создал прогон сразу.

Класс — тот же, что инвариант #17 запрещает у чисел: **«не измерено» стало
неотличимо от «прошло»**, и неотличимо в успокаивающую сторону. Только молчит не
тест, а весь CI, и увидеть это можно единственным способом — спросить «а прогон-то
БЫЛ?».

## Почему по расписанию, а не проверкой на самом PR

Сторож, живущий на том же событии, которое он сторожит, **не может увидеть, что
событие не сработало**: не запустился CI — не запустился и он. Поэтому вход
independent: `schedule`. Это ровно та ошибка, за которую проект уже платил
(`.claude/rules/deployment.md`, «четыре вопроса — четыре разных сторожа»): зелёный
ответ на один вопрос не означает ответа на другой.

## Три исхода, а не два (инвариант #17)

* `checked`   — у head'а есть прогоны, число названо;
* `no_runs`   — прогонов НОЛЬ. Это и есть дефект;
* `unchecked` — измерить не удалось (нет токена, сеть, отказ API). Это НЕ «всё
  хорошо» и НЕ «дефект»: у исхода свой код возврата, потому что молчание сторожа
  обязано отличаться от его одобрения.

Коды возврата: `0` — все проверены и прогоны есть · `1` — есть PR без прогонов ·
`2` — не измерено. Сторож НАЗЫВАЕТ; он ничего не запускает и не чинит.

Только stdlib. Сеть инъектируется (`fetch=`), поэтому тесты её не трогают.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Callable, Optional

API = "https://api.github.com"
DEFAULT_REPO = "yurii-spa/SPA"

#: Проверки, которые НЕ считаются прогоном Actions. Сторонний деплой рисует на PR
#: зелёную галочку и ровно поэтому авария выглядела успехом: галочка была, прогонов
#: не было. Сравнение идёт по прогонам Actions, а не по галочкам.
NOT_A_RUN = ("cloudflare",)

CHECKED = "checked"
NO_RUNS = "no_runs"
UNCHECKED = "unchecked"

EXIT_OK = 0
EXIT_DEFECT = 1
EXIT_UNMEASURED = 2


def _http_get(url: str, token: Optional[str]) -> object:
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "spa-pr-ci-liveness",
    })
    if token:
        req.add_header("Authorization", f"token {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def open_pulls(repo: str, fetch: Callable[[str], object]) -> list:
    return fetch(f"{API}/repos/{repo}/pulls?state=open&per_page=100")


def runs_for_sha(repo: str, sha: str, fetch: Callable[[str], object]) -> list:
    doc = fetch(f"{API}/repos/{repo}/actions/runs?head_sha={sha}&per_page=100")
    if not isinstance(doc, dict):
        return []
    return doc.get("workflow_runs") or []


def verdict_for_pull(pull: dict, repo: str, fetch: Callable[[str], object]) -> dict:
    """Один PR → один вердикт. Не бросает: отказ сети — это `unchecked`, не падение."""
    number = pull.get("number")
    sha = ((pull.get("head") or {}).get("sha")) or ""
    title = (pull.get("title") or "")[:80]
    if not sha:
        return {"pr": number, "title": title, "head_sha": None,
                "state": UNCHECKED, "runs": None,
                "reason": "у PR не назван head_sha — сверять не с чем"}
    try:
        runs = runs_for_sha(repo, sha, fetch)
    except Exception as exc:  # сеть/API/разбор — молчание сторожа, а не одобрение
        return {"pr": number, "title": title, "head_sha": sha,
                "state": UNCHECKED, "runs": None,
                "reason": f"прогоны не запрошены: {type(exc).__name__}: {exc}"}
    real = [r for r in runs
            if not any(bad in str(r.get("name", "")).lower() for bad in NOT_A_RUN)]
    if not real:
        return {"pr": number, "title": title, "head_sha": sha,
                "state": NO_RUNS, "runs": 0,
                "reason": "у head'а НЕТ ни одного прогона Actions — PR не проверен, "
                          "хотя может выглядеть зелёным за счёт сторонних галочек"}
    return {"pr": number, "title": title, "head_sha": sha,
            "state": CHECKED, "runs": len(real), "reason": ""}


def audit(repo: str, fetch: Callable[[str], object]) -> dict:
    try:
        pulls = open_pulls(repo, fetch)
    except Exception as exc:
        return {"repo": repo, "state": UNCHECKED, "pulls": [],
                "reason": f"список PR не получен: {type(exc).__name__}: {exc}"}
    if not isinstance(pulls, list):
        return {"repo": repo, "state": UNCHECKED, "pulls": [],
                "reason": "ответ API по списку PR не является списком"}
    verdicts = [verdict_for_pull(p, repo, fetch) for p in pulls if isinstance(p, dict)]
    if any(v["state"] == NO_RUNS for v in verdicts):
        state = NO_RUNS
    elif any(v["state"] == UNCHECKED for v in verdicts):
        state = UNCHECKED
    else:
        state = CHECKED
    return {"repo": repo, "state": state, "pulls": verdicts, "reason": ""}


def exit_code(report: dict) -> int:
    return {NO_RUNS: EXIT_DEFECT, UNCHECKED: EXIT_UNMEASURED}.get(report["state"], EXIT_OK)


def render(report: dict) -> str:
    lines = []
    n = len(report["pulls"])
    lines.append(f"открытых PR: {n} · общий вердикт: {report['state']}")
    if report.get("reason"):
        lines.append(f"  {report['reason']}")
    for v in report["pulls"]:
        mark = {CHECKED: "✅", NO_RUNS: "❌", UNCHECKED: "❔"}[v["state"]]
        runs = "не измерено" if v["runs"] is None else f"прогонов {v['runs']}"
        lines.append(f"  {mark} PR #{v['pr']} {(v['head_sha'] or '???')[:7]} — {runs}"
                     f"  «{v['title']}»")
        if v["reason"]:
            lines.append(f"      {v['reason']}")
    if report["state"] == NO_RUNS:
        lines.append("")
        lines.append("PR без прогонов НЕ проверен. Запустить вручную (workflow_dispatch) "
                     "или выяснить, почему событие pull_request не сработало — ADR-145.")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=os.environ.get("SPA_REPO", DEFAULT_REPO))
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT_SPA")
    report = audit(args.repo, lambda url: _http_get(url, token))
    print(json.dumps(report, ensure_ascii=False, indent=1) if args.json else render(report))
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
