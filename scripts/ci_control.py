#!/usr/bin/env python3
# LLM_FORBIDDEN
"""Контрольный прогон CI по шардам: план · свод · сравнение (`.github/workflows/ci-control.yml`).

**Почему он нужен (замер 2026-10-16).** Из последних 30 прогонов `SPA CI` (`ci.yml`) ни один
не дошёл до вердикта: 28 пушевых СНЯТЫ следующим пушем (`concurrency: spa-ci-${ref}-push`,
`cancel-in-progress`), единственный расписанный (38873867566, джоба 116884127339, `9b7e6442f`)
шёл 08:28→14:28Z и был убит 6-часовым пределом джобы Actions на `[ 94%]` шага
`spa_core/tests/` — 97 знаков `F`, ни одного имени (`-q`). В `SPA Tests` (`test.yml`) тот же
шаг в расписанном прогоне 38877303508 снят `timeout-minutes: 240` (09:09→13:09Z). То есть
полный набор в ОДНУ джобу не помещается по построению, а пушевые прогоны вытесняют друг
друга раньше, чем успевают дойти. Порог джобы поднимать некуда (360 мин — потолок GitHub),
а `--timeout` на тест — не тот орган (инв. #16).

**Что делает этот модуль.** Режет ТО ЖЕ население, что предписанная команда `CLAUDE.md`,
на шарды по ФАЙЛУ (детерминированно, по измеренному весу), а затем сводит результаты шардов
в один вердикт с ТРЕМЯ исходами — и третий исход здесь главный:

* ``GREEN`` — каждый шард отчитался, союз шардов == населению, каждый тест получил исход,
  упавших нет;
* ``RED`` — всё измерено, и упавшие НАЗВАНЫ поимённо (с шардом);
* ``INCOMPLETE`` — хоть один шард отсутствует / снят / отменён / без записи, или союз ≠
  населению, или у какого-то теста нет исхода. Никогда не зелёный (инв. #17).

Подкоманды::

    plan      --collected F --weights W --shards N --budget-min M --sha S --out-dir D
    aggregate --manifest-dir D --shards-dir S [--needs-result R] --out-json J --out-md M
    compare   BASE.json HEAD.json [--out-json J]
    weights   [--stream F]... [--junit F]... [--root R] --out W

Только stdlib (инв. #4). Источник записей шардов — `spa_core.ci.pytest_stream_record`
(строка на событие, сброс после каждой) и `spa_core.ci.pytest_collect_manifest`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

REPORT_SCHEMA = "spa-ci-control-report/1"
MANIFEST_SCHEMA = "spa-ci-control-manifest/1"
WEIGHTS_SCHEMA = "spa-ci-control-weights/1"

GREEN, RED, INCOMPLETE = "GREEN", "RED", "INCOMPLETE"
EXIT = {GREEN: 0, RED: 1, INCOMPLETE: 2}

PASSED, SKIPPED, FAILED, ERROR = "passed", "skipped", "failed", "error"
_RANK = {PASSED: 1, SKIPPED: 2, FAILED: 3, ERROR: 4}

#: Результаты `needs.<job>.result`, при которых шард НЕ дал ответа. `failure` сюда не входит:
#: шард с упавшими тестами — красный, а не отсутствующий.
_UNANSWERED_RESULTS = ("cancelled", "skipped")

SHARD_DIR_PREFIX = "ctl-shard-"

#: Файлы, которые шард обязан оставить. Имя — часть контракта с воркфлоу.
STREAM_FILE = "stream.jsonl"
COLLECTED_FILE = "collected.jsonl"
EXIT_FILE = "exit.json"
SHARD_FILE = "shard.json"


def _load_plugin_reader():
    """`read_manifest` из плагина — по ПУТИ, чтобы скрипт работал без `spa_core` в sys.path."""
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "spa_core" / "ci" / "pytest_collect_manifest.py"
    spec = importlib.util.spec_from_file_location("_ctl_collect_manifest", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.read_manifest


read_manifest = _load_plugin_reader()


def file_of(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


# ── потоковая запись шарда ───────────────────────────────────────────────────

def load_stream(path: str) -> dict:
    """Разобрать запись `pytest_stream_record`. Нет файла ⇒ ``present=False`` (не «ноль»)."""
    out = {"present": False, "session": False, "end": None, "outcomes": {}, "msgs": {},
           "unfinished": [], "t0": None, "t1": None, "file_wall": {}, "bad_lines": 0}
    if not os.path.exists(path):
        return out
    out["present"] = True
    started: list[tuple[float, str]] = []
    finished: set[str] = set()
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except ValueError:
                out["bad_lines"] += 1          # оборванная последняя строка — не повод терять остальные
                continue
            kind = ev.get("e")
            t = ev.get("t")
            if isinstance(t, (int, float)):
                out["t0"] = t if out["t0"] is None else min(out["t0"], t)
                out["t1"] = t if out["t1"] is None else max(out["t1"], t)
            if kind == "session":
                out["session"] = True
            elif kind == "end":
                out["end"] = ev
            elif kind == "start":
                started.append((float(t or 0.0), ev.get("n", "")))
            elif kind in ("ok", "skip", "fail"):
                n = ev.get("n", "")
                if kind == "ok":
                    outcome = PASSED
                elif kind == "skip":
                    outcome = SKIPPED
                else:
                    outcome = FAILED if ev.get("w") == "call" else ERROR
                    if ev.get("msg"):
                        out["msgs"].setdefault(n, ev.get("msg"))
                prev = out["outcomes"].get(n)
                if prev is None or _RANK[outcome] > _RANK[prev]:
                    out["outcomes"][n] = outcome
                finished.add(n)
    out["unfinished"] = [n for _, n in started if n not in finished]
    # Стена на файл: от старта теста до старта следующего. Последний тест шарда
    # меряется до конца сессии, если конец есть; иначе — не меряется (нет конца).
    wall: dict[str, float] = {}
    end_t = out["end"].get("t") if out["end"] else None
    for i, (t, n) in enumerate(started):
        nxt = started[i + 1][0] if i + 1 < len(started) else end_t
        if nxt is None:
            continue
        wall[file_of(n)] = wall.get(file_of(n), 0.0) + max(0.0, float(nxt) - t)
    out["file_wall"] = {k: round(v, 3) for k, v in wall.items()}
    return out


# ── веса ─────────────────────────────────────────────────────────────────────

def _junit_file(classname: str, root: Path) -> str | None:
    parts = classname.split(".")
    for i in range(len(parts), 0, -1):
        cand = "/".join(parts[:i]) + ".py"
        if (root / cand).is_file():
            return cand
    return None


def build_weights(streams: list[str], junits: list[str], root: Path, source: dict) -> dict:
    files: dict[str, float] = {}
    tests = 0
    total = 0.0
    for path in streams:
        rec = load_stream(path)
        for f, w in rec["file_wall"].items():
            files[f] = round(files.get(f, 0.0) + w, 3)
            total += w
        tests += len(rec["outcomes"])
    for path in junits:
        for case in ET.parse(path).getroot().iter("testcase"):
            f = _junit_file(case.get("classname", ""), root)
            if f is None:
                continue
            d = float(case.get("time") or 0.0)
            files[f] = round(files.get(f, 0.0) + d, 3)
            total += d
            tests += 1
    per_test = round(total / tests, 4) if tests else None
    return {"schema": WEIGHTS_SCHEMA, "source": source, "unit": "seconds of wall per test file",
            "per_test_fallback_s": per_test, "measured_files": len(files),
            "files": dict(sorted(files.items()))}


# ── план ─────────────────────────────────────────────────────────────────────

def make_plan(collected: list[str], collect_errors: list[dict], weights: dict, shards: int,
              budget_s: float) -> dict:
    """Детерминированное разбиение по файлу: LPT по весу, ничья — по пути, затем по номеру шарда.

    Порядок файлов ВНУТРИ шарда — порядок сборки предписанного прогона (порядок населения),
    чтобы относительный порядок тестов не менялся.
    """
    if shards < 1:
        raise ValueError("число шардов обязано быть ≥ 1")
    order: list[str] = []
    counts: dict[str, int] = {}
    for n in collected:
        f = file_of(n)
        if f not in counts:
            order.append(f)
            counts[f] = 0
        counts[f] += 1
    global_errors = []
    for err in collect_errors:
        path = err.get("n", "")
        if path.endswith(".py") and "::" not in path:
            if path not in counts:
                order.append(path)
                counts[path] = 0
        else:
            global_errors.append(err)      # каталог / conftest: шардом не лечится, это красное
    per_test = float(weights.get("per_test_fallback_s") or 0.2)
    known = weights.get("files") or {}
    est: dict[str, float] = {}
    estimated = 0
    for f in order:
        if f in known:
            est[f] = float(known[f])
        else:
            est[f] = max(1.0, counts[f] * per_test)
            estimated += 1
    load = [0.0] * shards
    assign: dict[str, int] = {}
    for f in sorted(order, key=lambda p: (-est[p], p)):
        i = min(range(shards), key=lambda k: (load[k], k))
        assign[f] = i
        load[i] += est[f]
    plan = []
    for i in range(shards):
        files = [f for f in order if assign[f] == i]
        plan.append({"shard": i, "files": files, "tests": sum(counts[f] for f in files),
                     "est_s": round(load[i], 1)})
    worst = max(load) if load else 0.0
    return {"files": order, "tests_per_file": counts, "global_collect_errors": global_errors,
            "shards": plan, "est_total_s": round(sum(load), 1), "est_max_shard_s": round(worst, 1),
            "budget_s": budget_s, "estimated_files": estimated, "within_budget": worst <= budget_s}


def cmd_plan(args) -> int:
    got = read_manifest(args.collected)
    if got["collected"] is None:
        print(f"CI-CONTROL PLAN: INCOMPLETE — перечня населения нет: {got['why']}")
        return 2
    if not got["collected"] and not got["collect_errors"]:
        print("CI-CONTROL PLAN: INCOMPLETE — собрано ноль тестов: пустое население неотличимо "
              "от сломанной сборки (инв. #17)")
        return 2
    weights = json.loads(Path(args.weights).read_text(encoding="utf-8"))
    plan = make_plan(got["collected"], got["collect_errors"], weights, args.shards,
                     args.budget_min * 60.0)
    manifest = {
        "schema": MANIFEST_SCHEMA, "sha": args.sha,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "env": _env_fingerprint(args.roots),
        "roots": args.roots, "population": len(got["collected"]),
        "collected": got["collected"], "collect_errors": got["collect_errors"],
        "weights_source": weights.get("source"), **plan,
    }
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    for sh in plan["shards"]:
        (out / f"shard-{sh['shard']}.txt").write_text("\n".join(sh["files"]) + "\n",
                                                      encoding="utf-8")
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as fh:
            fh.write(f"shards={json.dumps([s['shard'] for s in plan['shards']])}\n")
    print(f"population {manifest['population']} tests in {len(plan['files'])} files · "
          f"{args.shards} shards · est. max shard {plan['est_max_shard_s'] / 60:.1f} min "
          f"(budget {args.budget_min} min) · files without measured weight: "
          f"{plan['estimated_files']}")
    for sh in plan["shards"]:
        print(f"  shard {sh['shard']:>2}: {len(sh['files']):>4} files {sh['tests']:>6} tests "
              f"est {sh['est_s'] / 60:6.1f} min")
    if not plan["within_budget"]:
        print("CI-CONTROL PLAN: INCOMPLETE — оценка самого тяжёлого шарда больше бюджета; "
              "прибавить шардов, а не поднимать границу")
        return 2
    return 0


def _env_fingerprint(roots: list[str]) -> dict:
    import platform
    try:
        import pytest  # noqa: F401 — версия входит в окружение прогона
        pv = pytest.__version__
    except Exception:                                         # pragma: no cover
        pv = None
    return {"python": platform.python_version(), "implementation": platform.python_implementation(),
            "system": platform.system(), "runner_os": os.environ.get("RUNNER_OS"),
            "image": os.environ.get("ImageOS"), "pytest": pv,
            "SPA_ENV": os.environ.get("SPA_ENV"), "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED"),
            "workflow": os.environ.get("GITHUB_WORKFLOW"), "roots": list(roots)}


# ── свод ─────────────────────────────────────────────────────────────────────

def aggregate(manifest: dict | None, shards_dir: Path, needs_result: str | None = None,
              run: dict | None = None) -> dict:
    incomplete: list[dict] = []
    report: dict = {"schema": REPORT_SCHEMA, "verdict": None, "run": run or {},
                    "sha": (manifest or {}).get("sha"), "env": (manifest or {}).get("env"),
                    "incomplete": incomplete}
    if manifest is None or manifest.get("schema") != MANIFEST_SCHEMA:
        incomplete.append({"shard": None, "reason": "манифеста населения нет или он не того вида — "
                                                    "сравнивать результаты шардов не с чем"})
        report.update(verdict=INCOMPLETE, totals=None, failures=[], collect_errors=[],
                      not_obtained=[], population=[], non_passed={}, shards=[], file_wall_s={})
        return report

    population: list[str] = list(manifest.get("collected") or [])
    files: list[str] = list(manifest.get("files") or [])
    plan: list[dict] = list(manifest.get("shards") or [])
    if needs_result and needs_result in _UNANSWERED_RESULTS:
        incomplete.append({"shard": None,
                           "reason": f"джоба шардов закончилась как «{needs_result}» — ответа нет"})

    # 1. союз списков шардов == населению по файлам, без дублей
    listed: list[str] = [f for sh in plan for f in sh.get("files", [])]
    from collections import Counter
    dup = sorted(f for f, c in Counter(listed).items() if c > 1)
    if dup:
        incomplete.append({"shard": None, "reason": f"файл назначен в несколько шардов: {dup[:20]}"})
    lost = sorted(set(files) - set(listed))
    extra = sorted(set(listed) - set(files))
    if lost:
        incomplete.append({"shard": None,
                           "reason": f"союз шардов ≠ населению: {len(lost)} файлов не назначены "
                                     f"ни одному шарду: {lost[:20]}"})
    if extra:
        incomplete.append({"shard": None,
                           "reason": f"союз шардов ≠ населению: {len(extra)} файлов вне населения: "
                                     f"{extra[:20]}"})
    pop_files = {file_of(n) for n in population}
    if not pop_files <= set(files):
        incomplete.append({"shard": None, "reason": "манифест противоречив: у тестов есть файлы вне "
                                                    "списка файлов"})

    by_file: dict[str, list[str]] = {}
    for n in population:
        by_file.setdefault(file_of(n), []).append(n)

    outcomes: dict[str, str] = {}
    owner: dict[str, int] = {}
    msgs: dict[str, str] = {}
    collect_errors = [dict(e, shard=None) for e in manifest.get("collect_errors") or []]
    shard_rows: list[dict] = []
    file_wall: dict[str, float] = {}
    present_dirs = {p.name for p in shards_dir.iterdir()} if shards_dir.is_dir() else set()

    for sh in plan:
        i = sh["shard"]
        problems: list[str] = []
        d = shards_dir / f"{SHARD_DIR_PREFIX}{i}"
        present_dirs.discard(d.name)
        row = {"shard": i, "files": len(sh.get("files", [])), "tests": sh.get("tests"),
               "est_s": sh.get("est_s"), "wall_s": None, "exit": None, "problems": problems,
               "unfinished": []}
        shard_rows.append(row)
        if not d.is_dir():
            problems.append("артефакта шарда нет (шард не отчитался)")
            continue
        meta = d / SHARD_FILE
        if meta.exists():
            try:
                declared = json.loads(meta.read_text(encoding="utf-8")).get("shard")
            except ValueError:
                declared = "<битый>"
            if str(declared) != str(i):
                problems.append(f"артефакт ctl-shard-{i} называет себя шардом {declared}")
        planned = [n for f in sh.get("files", []) for n in by_file.get(f, [])]
        got = read_manifest(str(d / COLLECTED_FILE))
        if got["collected"] is None:
            problems.append(f"перечня собранного нет: {got['why']}")
        else:
            missing = sorted(set(planned) - set(got["collected"]))
            surplus = sorted(set(got["collected"]) - set(planned))
            if missing:
                problems.append(f"шард не собрал {len(missing)} тестов населения: {missing[:10]}")
            if surplus:
                problems.append(f"шард собрал {len(surplus)} тестов вне населения: {surplus[:10]}")
        for err in got["collect_errors"]:
            collect_errors.append(dict(err, shard=i))
        rec = load_stream(str(d / STREAM_FILE))
        if not rec["present"]:
            problems.append("потоковой записи нет")
        elif rec["end"] is None:
            problems.append("сессия pytest не дошла до конца (снят, отменён или убит)")
        row["unfinished"] = rec["unfinished"][:20]
        if rec["t0"] is not None and rec["t1"] is not None:
            row["wall_s"] = round(rec["t1"] - rec["t0"], 1)
        for f, w in rec["file_wall"].items():
            file_wall[f] = w
        shard_fails = 0
        planned_set = set(planned)
        for n, o in rec["outcomes"].items():
            if n not in planned_set:
                continue                 # вне населения — уже названо выше как surplus
            outcomes[n] = o
            owner[n] = i
            if o in (FAILED, ERROR):
                shard_fails += 1
                if n in rec["msgs"]:
                    msgs[n] = rec["msgs"][n]
        exit_path = d / EXIT_FILE
        code = None
        if exit_path.exists():
            try:
                code = json.loads(exit_path.read_text(encoding="utf-8")).get("exit")
            except ValueError:
                code = None
        row["exit"] = code
        if code is None:
            problems.append("кода возврата pytest нет (шаг снят до записи)")
        elif code not in (0, 1):
            problems.append(f"pytest вернул {code} — прогон прерван, а не измерен")
        elif code == 1 and shard_fails == 0 and not got["collect_errors"]:
            problems.append("pytest сказал «упало», а ни одного упавшего имени в записи нет")
        elif code == 0 and shard_fails:
            problems.append(f"pytest сказал «зелёно», а запись называет {shard_fails} упавших")
    for name in sorted(present_dirs):
        if name.startswith(SHARD_DIR_PREFIX):
            incomplete.append({"shard": None, "reason": f"артефакт {name} не принадлежит плану"})

    for row in shard_rows:
        for p in row["problems"]:
            incomplete.append({"shard": row["shard"], "reason": p})

    not_obtained = [n for n in population if n not in outcomes]
    if not_obtained:
        incomplete.append({"shard": None,
                           "reason": f"{len(not_obtained)} тестов населения без исхода "
                                     "(не получено)"})
    shard_of_file = {f: sh["shard"] for sh in plan for f in sh.get("files", [])}
    failures = [{"nodeid": n, "outcome": outcomes[n], "shard": owner.get(n),
                 "msg": msgs.get(n, "")}
                for n in population if outcomes.get(n) in (FAILED, ERROR)]
    for e in collect_errors:
        if e.get("shard") is None:
            e["shard"] = shard_of_file.get(e.get("n"))
    # Ошибка сборки, увиденная и манифестом, и шардом, — одна ошибка.
    seen: set[str] = set()
    uniq_ce = []
    for e in collect_errors:
        if e["n"] in seen:
            continue
        seen.add(e["n"])
        uniq_ce.append(e)
    counts = {k: 0 for k in (PASSED, SKIPPED, FAILED, ERROR)}
    for o in outcomes.values():
        counts[o] += 1
    totals = {"population": len(population), "files": len(files), **counts,
              "not_obtained": len(not_obtained), "collect_errors": len(uniq_ce),
              "shards_planned": len(plan),
              "shards_complete": sum(1 for r in shard_rows if not r["problems"])}
    if incomplete:
        verdict = INCOMPLETE
    elif failures or uniq_ce:
        verdict = RED
    else:
        verdict = GREEN
    report.update(verdict=verdict, totals=totals, failures=failures, collect_errors=uniq_ce,
                  not_obtained=not_obtained, population=population,
                  non_passed={n: o for n, o in outcomes.items() if o != PASSED},
                  shards=shard_rows, file_wall_s=dict(sorted(file_wall.items())))
    return report


def render_md(report: dict, limit: int = 200) -> str:
    v = report["verdict"]
    lines = [f"# CI control run — {v}", ""]
    lines.append(f"- SHA: `{report.get('sha')}`")
    run = report.get("run") or {}
    if run.get("url"):
        lines.append(f"- Run: {run['url']}")
    env = report.get("env") or {}
    if env:
        lines.append(f"- Env: python {env.get('python')} · pytest {env.get('pytest')} · "
                     f"{env.get('image') or env.get('system')} · SPA_ENV={env.get('SPA_ENV')} · "
                     f"PYTHONHASHSEED={env.get('PYTHONHASHSEED')}")
    t = report.get("totals")
    if t:
        lines += ["", "| population | passed | failed | error | skipped | not obtained | "
                      "collect errors | shards complete |",
                  "|---|---|---|---|---|---|---|---|",
                  f"| {t['population']} | {t['passed']} | {t['failed']} | {t['error']} | "
                  f"{t['skipped']} | {t['not_obtained']} | {t['collect_errors']} | "
                  f"{t['shards_complete']}/{t['shards_planned']} |"]
    if report["incomplete"]:
        lines += ["", "## INCOMPLETE — why", ""]
        for item in report["incomplete"]:
            where = "global" if item["shard"] is None else f"shard {item['shard']}"
            lines.append(f"- [{where}] {item['reason']}")
    if report.get("failures"):
        lines += ["", f"## Failed / error ({len(report['failures'])})", ""]
        for f in report["failures"][:limit]:
            lines.append(f"- `{f['nodeid']}` — {f['outcome']} (shard {f['shard']})"
                         + (f" — {f['msg']}" if f.get("msg") else ""))
        if len(report["failures"]) > limit:
            lines.append(f"- … and {len(report['failures']) - limit} more (full list in JSON)")
    if report.get("collect_errors"):
        lines += ["", "## Collection errors", ""]
        for e in report["collect_errors"]:
            lines.append(f"- `{e['n']}` (shard {e.get('shard')}) — {e.get('msg', '')}")
    if report.get("not_obtained"):
        lines += ["", f"## Not obtained ({len(report['not_obtained'])}, first 50)", ""]
        lines += [f"- `{n}`" for n in report["not_obtained"][:50]]
    if report.get("shards"):
        lines += ["", "## Shards", "", "| shard | files | tests | est min | wall min | exit | "
                                       "problems |", "|---|---|---|---|---|---|---|"]
        for r in report["shards"]:
            wall = "—" if r["wall_s"] is None else f"{r['wall_s'] / 60:.1f}"
            est = "—" if r.get("est_s") is None else f"{r['est_s'] / 60:.1f}"
            lines.append(f"| {r['shard']} | {r['files']} | {r['tests']} | {est} | {wall} | "
                         f"{r['exit']} | {'; '.join(r['problems']) or '—'} |")
    return "\n".join(lines) + "\n"


def cmd_aggregate(args) -> int:
    mpath = Path(args.manifest_dir) / "manifest.json"
    manifest = None
    if mpath.exists():
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except ValueError:
            manifest = None
    run = {"id": os.environ.get("GITHUB_RUN_ID"), "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
           "event": os.environ.get("GITHUB_EVENT_NAME")}
    if os.environ.get("GITHUB_SERVER_URL") and os.environ.get("GITHUB_REPOSITORY") and run["id"]:
        run["url"] = (f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}"
                      f"/actions/runs/{run['id']}")
    report = aggregate(manifest, Path(args.shards_dir), args.needs_result, run)
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    md = render_md(report)
    Path(args.out_md).write_text(md, encoding="utf-8")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(md)
    t = report.get("totals") or {}
    print(f"CI-CONTROL VERDICT: {report['verdict']} · sha {report.get('sha')} · "
          f"failed {t.get('failed')} · error {t.get('error')} · not obtained "
          f"{t.get('not_obtained')} · shards {t.get('shards_complete')}/{t.get('shards_planned')}")
    for item in report["incomplete"][:30]:
        where = "global" if item["shard"] is None else f"shard {item['shard']}"
        print(f"  INCOMPLETE [{where}] {item['reason']}")
    for f in report.get("failures", [])[:50]:
        print(f"  {f['outcome'].upper()} [shard {f['shard']}] {f['nodeid']}")
    return EXIT[report["verdict"]]


# ── сравнение двух вердиктов ─────────────────────────────────────────────────

NEW, PRE_EXISTING, NOT_OBTAINED = "new", "pre_existing", "not_obtained"


def compare(base: dict, head: dict) -> dict:
    """Классифицировать упавшие ГОЛОВЫ относительно БАЗЫ: new / pre_existing / not_obtained.

    * ``pre_existing`` — в базе тот же тест тоже упал/ошибся;
    * ``new`` — в базе тест ИЗМЕРЕН и прошёл/пропущен, либо его в населении базы не было
      (новый тест, который падает, — новая поломка, а не старая);
    * ``not_obtained`` — в базе тест был в населении, но исхода не получил: сказать
      «новое» или «старое» НЕЛЬЗЯ, и это называется словом, а не догадкой.

    Сравнимость — предусловие: одна схема, одно окружение (python major.minor, корни,
    SPA_ENV, PYTHONHASHSEED). Несравнимые отчёты ⇒ ``comparable=False`` и ни одной метки.
    """
    reasons = []
    for name, rep in (("base", base), ("head", head)):
        if rep.get("schema") != REPORT_SCHEMA:
            reasons.append(f"{name}: не отчёт контрольного прогона")
    if not reasons:
        eb, eh = base.get("env") or {}, head.get("env") or {}
        for key in ("roots", "SPA_ENV", "PYTHONHASHSEED", "workflow", "implementation"):
            if eb.get(key) != eh.get(key):
                reasons.append(f"окружение различается: {key} {eb.get(key)!r} ≠ {eh.get(key)!r}")
        pb = ".".join(str(eb.get("python") or "").split(".")[:2])
        ph = ".".join(str(eh.get("python") or "").split(".")[:2])
        if pb != ph:
            reasons.append(f"окружение различается: python {pb} ≠ {ph}")
    out = {"comparable": not reasons, "why_not": reasons, "base_sha": base.get("sha"),
           "head_sha": head.get("sha"), "base_verdict": base.get("verdict"),
           "head_verdict": head.get("verdict"), NEW: [], PRE_EXISTING: [], NOT_OBTAINED: [],
           "fixed": [], "head_not_obtained": len(head.get("not_obtained") or [])}
    if reasons:
        return out
    base_missing = set(base.get("not_obtained") or [])
    base_np = base.get("non_passed") or {}
    head_np = head.get("non_passed") or {}
    for f in head.get("failures") or []:
        n = f["nodeid"]
        if n in base_missing:
            out[NOT_OBTAINED].append(n)
        elif base_np.get(n) in (FAILED, ERROR):
            out[PRE_EXISTING].append(n)
        else:                          # измерен и прошёл, либо нового теста в базе не было
            out[NEW].append(n)
    head_pop = set(head.get("population") or [])
    head_missing = set(head.get("not_obtained") or [])
    for f in base.get("failures") or []:
        n = f["nodeid"]
        if n in head_pop and n not in head_missing and head_np.get(n) not in (FAILED, ERROR):
            out["fixed"].append(n)
    return out


def cmd_compare(args) -> int:
    base = json.loads(Path(args.base).read_text(encoding="utf-8"))
    head = json.loads(Path(args.head).read_text(encoding="utf-8"))
    res = compare(base, head)
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    if not res["comparable"]:
        print("CI-CONTROL COMPARE: NOT COMPARABLE — " + "; ".join(res["why_not"]))
        return 2
    print(f"CI-CONTROL COMPARE {res['base_sha']} ({res['base_verdict']}) → "
          f"{res['head_sha']} ({res['head_verdict']}): new {len(res[NEW])} · pre-existing "
          f"{len(res[PRE_EXISTING])} · not obtained {len(res[NOT_OBTAINED])} · fixed "
          f"{len(res['fixed'])}")
    for key in (NEW, NOT_OBTAINED):
        for n in res[key][:100]:
            print(f"  {key.upper()} {n}")
    if res[NEW]:
        return 1
    if res[NOT_OBTAINED] or res["head_verdict"] == INCOMPLETE:
        return 2
    return 0


def cmd_weights(args) -> int:
    source = {"note": args.note or "", "streams": args.stream or [], "junits": args.junit or []}
    w = build_weights(args.stream or [], args.junit or [], Path(args.root), source)
    Path(args.out).write_text(json.dumps(w, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"weights: {w['measured_files']} files, fallback {w['per_test_fallback_s']} s/test")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan")
    pl.add_argument("--collected", required=True)
    pl.add_argument("--weights", required=True)
    pl.add_argument("--shards", type=int, required=True)
    pl.add_argument("--budget-min", type=float, required=True)
    pl.add_argument("--sha", required=True)
    pl.add_argument("--roots", nargs="+", required=True)
    pl.add_argument("--out-dir", required=True)
    pl.add_argument("--github-output")
    ag = sub.add_parser("aggregate")
    ag.add_argument("--manifest-dir", required=True)
    ag.add_argument("--shards-dir", required=True)
    ag.add_argument("--needs-result")
    ag.add_argument("--out-json", required=True)
    ag.add_argument("--out-md", required=True)
    ag.add_argument("--summary")
    cp = sub.add_parser("compare")
    cp.add_argument("base")
    cp.add_argument("head")
    cp.add_argument("--out-json")
    wt = sub.add_parser("weights")
    wt.add_argument("--stream", action="append")
    wt.add_argument("--junit", action="append")
    wt.add_argument("--root", default=".")
    wt.add_argument("--note")
    wt.add_argument("--out", required=True)
    args = p.parse_args(argv)
    return {"plan": cmd_plan, "aggregate": cmd_aggregate, "compare": cmd_compare,
            "weights": cmd_weights}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
