#!/usr/bin/env python3
"""Перепись доставки: **открытый PR — это НЕ доставленная работа** (ADR-477).

Зачем
------------------------------------------------------------------------------
Рядом уже живёт сторож `scripts/check_pr_ci_runs.py` (ADR-145). Он отвечает на свой
вопрос — «а прогон-то БЫЛ?» — и отвечает честно. Но на вопрос «а работа-то ДОЕХАЛА?»
он не отвечает и не может: у PR может быть три зелёных прогона и ноль строк на `main`.

Замер 2026-09-25, ради которого прибор написан. Приказ владельца «Portfolio CIO»
(`inbox-task-portfolio-cio-dynamic-capital-alloc`, `critical`, `in-progress`) состоит
из **52 разделов**. На `main` тело карточки обрывалось на середине **§5**: разделы
6–52 и аудит `docs/research/RS-portfolio-cio-audit-2026-08-29.md` физически
существовали только в **ЧЕРНОВОМ PR #50** от 29.08. Двадцать восемь дней каждый
цикл читал приказ владельца на 5 разделах из 52 — и ни один сторож об этом не сказал:
у PR #50 прогоны ЕСТЬ (три), поэтому `pr-ci-liveness` был по нему ЗЕЛЁН. Зелёный
ответ на свой вопрос никогда не есть ответ на нужный
(`.claude/rules/deployment.md`, «четыре вопроса — четыре разных сторожа»).

Что именно мерится
------------------------------------------------------------------------------
Для каждого открытого PR: **сколько он открыт** и **лежат ли на базовой ветке те
файлы, которые он ДОБАВЛЯЕТ**. Добавляемый файл выбран предметом потому, что по нему
вопрос разрешим однозначно: путь на базе либо есть, либо нет. У «изменяемого» файла
такого ответа нет — путь есть и до мёржа, — поэтому PR без добавляемых файлов прибор
объявляет ВНЕ СВОЕЙ ДОСЯГАЕМОСТИ (`unmeasured_scope`), а не чистым: «не измерено»,
выданное за «прошло», — тот самый дефект (инв. #17, урок #465).

Дефект — это КОНЪЮНКЦИЯ, а не отсутствие файла само по себе: свежий PR по построению
несёт пути, которых на базе нет, — это и есть PR, а не потеря. Поэтому
`NOT_ARRIVED` требует и возраста сверх порога (`--max-age-days`, по умолчанию 7),
и отсутствия пути на базе. PR моложе порога — `in_flight`, и это НОРМА.

Три исхода, а не два (инв. #17)
------------------------------------------------------------------------------
* `arrived`          — все добавляемые пути уже есть на базе (работа доехала);
* `in_flight`        — моложе порога; отсутствие путей на базе — норма;
* `NOT_ARRIVED`      — открыт дольше порога, и добавляемых путей на базе НЕТ. Дефект;
* `unmeasured_scope` — PR не добавляет файлов: предмет вне досягаемости прибора;
* `unmeasured`       — измерить не удалось (сеть, API, база недоступна). НЕ «чисто».

**«Посмотреть не смог» ≠ «на базе нет».** Дверь к базе (`exists_on_base`) обязана
уметь ОТКАЗАТЬ: прочтя отказ как «нет», прибор выдал бы ложный CRITICAL, а как
«есть» — ложную чистоту. Отказ двери — самостоятельный исход с названной причиной.

Коды возврата: `0` — доехало (или в пути) · `1` — есть НЕ доехавший · `2` — НЕ
ИЗМЕРЕНО. Прибор только НАЗЫВАЕТ: он ничего не мёржит, не закрывает и не пушит.

Только stdlib. Сеть, база и часы — входы (`fetch=`, `exists_on_base=`, `now=`),
поэтому тесты не трогают ни сеть, ни календарь.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Optional

API = "https://api.github.com"
DEFAULT_REPO = "yurii-spa/SPA"
DEFAULT_MAX_AGE_DAYS = 7.0

ARRIVED = "arrived"
IN_FLIGHT = "in_flight"
NOT_ARRIVED = "NOT_ARRIVED"
UNMEASURED_SCOPE = "unmeasured_scope"
UNMEASURED = "unmeasured"

EXIT_OK = 0
EXIT_DEFECT = 1
EXIT_UNMEASURED = 2


class BaseUnreadable(Exception):
    """Дверь к базовой ветке отказала. НЕ «файла нет» — «посмотреть не смог»."""


# ---------------------------------------------------------------- входы по умолчанию

def _http_get(url: str, token: Optional[str]) -> object:
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "spa-pr-delivery-census",
    })
    if token:
        req.add_header("Authorization", f"token {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def git_base_door(repo_root: str = ".") -> Callable[[str, str], bool]:
    """Дверь к базе через локальный git. Не нашла ВЕТКУ ⇒ `BaseUnreadable`.

    Различение существенно: отсутствующая ветка означает «спросить не у кого», а
    отсутствующий в существующей ветке путь — настоящее «не доехало».
    """
    def exists_on_base(base_ref: str, path: str) -> bool:
        ref = f"{base_ref}:{path}"
        try:
            probe = subprocess.run(["git", "rev-parse", "--verify", f"{base_ref}^{{commit}}"],
                                   cwd=repo_root, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            raise BaseUnreadable(f"git не запустился: {type(exc).__name__}: {exc}") from exc
        if probe.returncode != 0:
            raise BaseUnreadable(f"базовая ветка `{base_ref}` не найдена локально — "
                                 f"спрашивать не у кого (git rev-parse: "
                                 f"{probe.stderr.strip()[:120]})")
        try:
            got = subprocess.run(["git", "cat-file", "-e", ref],
                                 cwd=repo_root, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            raise BaseUnreadable(f"git не запустился: {type(exc).__name__}: {exc}") from exc
        return got.returncode == 0
    return exists_on_base


# ------------------------------------------------------------------------- измерение

def open_pulls(repo: str, fetch: Callable[[str], object]) -> list:
    return fetch(f"{API}/repos/{repo}/pulls?state=open&per_page=100")


def added_paths(repo: str, number: int, fetch: Callable[[str], object]) -> list:
    """Только `status == "added"`: по такому пути вопрос «доехало?» разрешим."""
    docs = fetch(f"{API}/repos/{repo}/pulls/{number}/files?per_page=300")
    if not isinstance(docs, list):
        raise ValueError("ответ API по файлам PR не является списком")
    return [d["filename"] for d in docs
            if isinstance(d, dict) and d.get("status") == "added" and d.get("filename")]


def _age_days(created_at: str, now: datetime) -> float:
    born = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    if born.tzinfo is None:
        born = born.replace(tzinfo=timezone.utc)
    return (now - born).total_seconds() / 86400.0


def verdict_for_pull(pull: dict, repo: str, fetch, exists_on_base,
                     now: datetime, max_age_days: float) -> dict:
    """Один PR → один вердикт. Не бросает: любой отказ становится исходом."""
    number = pull.get("number")
    title = (pull.get("title") or "")[:80]
    base_ref = ((pull.get("base") or {}).get("ref")) or "main"
    out = {"pr": number, "title": title, "base": base_ref, "draft": bool(pull.get("draft")),
           "age_days": None, "added": [], "missing": [], "state": UNMEASURED, "reason": ""}

    created = pull.get("created_at")
    if not created:
        out["reason"] = "у PR не названа дата создания — возраст мерить нечем"
        return out
    try:
        out["age_days"] = round(_age_days(created, now), 1)
    except (ValueError, TypeError) as exc:
        out["reason"] = f"дата создания не разобрана: {type(exc).__name__}: {exc}"
        return out

    try:
        paths = added_paths(repo, number, fetch)
    except Exception as exc:
        out["reason"] = f"список файлов PR не получен: {type(exc).__name__}: {exc}"
        return out
    out["added"] = paths

    if not paths:
        out["state"] = UNMEASURED_SCOPE
        out["reason"] = ("PR не ДОБАВЛЯЕТ ни одного файла — по изменяемым путям вопрос "
                         "«доехало?» этим прибором не разрешим (путь есть и до мёржа)")
        return out

    missing = []
    for p in paths:
        try:
            present = exists_on_base(f"origin/{base_ref}", p)
        except BaseUnreadable as exc:
            out["reason"] = f"база не прочитана: {exc}"
            return out
        except Exception as exc:
            out["reason"] = f"база не прочитана: {type(exc).__name__}: {exc}"
            return out
        if not present:
            missing.append(p)
    out["missing"] = missing

    if not missing:
        out["state"] = ARRIVED
        return out
    if out["age_days"] < max_age_days:
        out["state"] = IN_FLIGHT
        out["reason"] = (f"открыт {out['age_days']:g} дн (< порога {max_age_days:g}) — "
                         f"путей на базе нет, и это НОРМА для работы в пути")
        return out
    out["state"] = NOT_ARRIVED
    out["reason"] = (f"открыт {out['age_days']:g} дн, и {len(missing)} добавляемых файл(ов) "
                     f"на `origin/{base_ref}` НЕТ — работа не доехала, хотя PR существует")
    return out


def census(repo: str, fetch, exists_on_base, now: datetime,
           max_age_days: float = DEFAULT_MAX_AGE_DAYS) -> dict:
    try:
        pulls = open_pulls(repo, fetch)
    except Exception as exc:
        return {"repo": repo, "state": UNMEASURED, "max_age_days": max_age_days, "pulls": [],
                "reason": f"список PR не получен: {type(exc).__name__}: {exc}"}
    if not isinstance(pulls, list):
        return {"repo": repo, "state": UNMEASURED, "max_age_days": max_age_days, "pulls": [],
                "reason": "ответ API по списку PR не является списком"}
    verdicts = [verdict_for_pull(p, repo, fetch, exists_on_base, now, max_age_days)
                for p in pulls if isinstance(p, dict)]
    if any(v["state"] == NOT_ARRIVED for v in verdicts):
        state = NOT_ARRIVED
    elif any(v["state"] in (UNMEASURED, UNMEASURED_SCOPE) for v in verdicts):
        state = UNMEASURED
    else:
        state = ARRIVED
    return {"repo": repo, "state": state, "max_age_days": max_age_days,
            "pulls": verdicts, "reason": ""}


def exit_code(report: dict) -> int:
    return {NOT_ARRIVED: EXIT_DEFECT, UNMEASURED: EXIT_UNMEASURED}.get(report["state"], EXIT_OK)


MARK = {ARRIVED: "✅", IN_FLIGHT: "🕐", NOT_ARRIVED: "❌",
        UNMEASURED_SCOPE: "❔", UNMEASURED: "❔"}


def render(report: dict) -> str:
    lines = [f"открытых PR: {len(report['pulls'])} · порог {report['max_age_days']:g} дн "
             f"· общий вердикт: {report['state']}"]
    if report.get("reason"):
        lines.append(f"  {report['reason']}")
    for v in sorted(report["pulls"], key=lambda x: -(x["age_days"] or 0)):
        age = "возраст не измерен" if v["age_days"] is None else f"{v['age_days']:g} дн"
        draft = " ЧЕРНОВИК" if v["draft"] else ""
        lines.append(f"  {MARK[v['state']]} PR #{v['pr']} {age}{draft} → {v['base']} "
                     f"· добавляет {len(v['added'])}, нет на базе {len(v['missing'])}"
                     f"  «{v['title']}»")
        if v["reason"]:
            lines.append(f"      {v['reason']}")
        for p in v["missing"][:8]:
            lines.append(f"      НЕ ДОЕХАЛ: {p}")
        if len(v["missing"]) > 8:
            lines.append(f"      … ещё {len(v['missing']) - 8} путь(ей)")
    if report["state"] == NOT_ARRIVED:
        lines.append("")
        lines.append("Открытый PR — это НЕ доставленная работа. Снять черновик и смержить "
                     "самому (CLAUDE.md, хвост ADR-285) либо ПЕРЕНЕСТИ содержимое "
                     "дописыванием к origin-версии и закрыть PR — ADR-477.")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=os.environ.get("SPA_REPO", DEFAULT_REPO))
    ap.add_argument("--repo-root", default=".", help="дерево, у которого спрашивать базу")
    ap.add_argument("--max-age-days", type=float, default=DEFAULT_MAX_AGE_DAYS)
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT_SPA")
    report = census(args.repo,
                    lambda url: _http_get(url, token),
                    git_base_door(args.repo_root),
                    datetime.now(timezone.utc),
                    args.max_age_days)
    print(json.dumps(report, ensure_ascii=False, indent=1) if args.json else render(report))
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
