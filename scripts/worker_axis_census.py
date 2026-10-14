#!/usr/bin/env python3
"""scripts/worker_axis_census.py — перепись ИЗМЕРИМОСТИ оси РАБОТНИКА (ADR-722, G721 п. 3).

ЗАЧЕМ. Ось РАБОТНИКА (`SPA_RUN_ID` в ОКРУЖЕНИИ) — единственная личность цикла, переживающая
запускателя; на ней стоя́т и замок цикла (ADR-720), и захват карточки (ADR-721), и — с
ADR-722 — журнальный захват. Но живость по ней измеряется ЧТЕНИЕМ ОКРУЖЕНИЯ в выводе `ps`,
а окружение читается далеко не у всех процессов: замер 14.10 на рабочем Маке — **74 строки
из 650**. Если окружение работника не читается, прибор честно отвечает третьим исходом
(`unmeasured` ⇒ `unchecked`), и вопрос «не превратится ли третий исход в постоянный
`unchecked` на 3–4.17 ч» решает НЕ рассуждение, а частота. До этого прибора её не мерил
никто (так и сказано в карточке `inbox-zhurnal-obyavlenii-merit-zapuskatelya-vt`, п. 3).

ЧТО МЕРИТСЯ — три вопроса, и ни один не отвечает на другой:

1. **Население читаемости.** Сколько строк `ps -Ewww` несут окружение, сколько нет, и КТО
   именно слеп (по классу исполняемого файла). Ответ сам по себе ничего не доказывает:
   слепыми могут быть процессы, никакой метки не несущие.
2. **Способна ли слепота спрятать РАБОТНИКА.** Живой запуск опознаётся по ЗАПУСКАТЕЛЮ:
   обёртка цикла несёт метку АРГУМЕНТОМ (`--run-id <метка>`), и argv читается даже когда
   окружение — нет. Для каждой такой метки спрашивается ось РАБОТНИКА. Запускатель жив, а
   работника по метке не видно ⇒ находка: либо работник умер (и тогда об этом обязан знать
   замок), либо он жив и НЕ ВИДЕН — ровно тот постоянный `unchecked`, которого боится п. 3.
3. **Происхождение совпадения** (ADR-722, G721 п. 2): сколько носителей метки несут её в
   окружении, сколько в командной строке, сколько не определено, и сколько из них — сам
   прибор замера.

Коды возврата: **0** — измерено, находок нет · **1** — находка НАЗВАНА · **2** — НЕ
ИЗМЕРЕНО (прибор не ответил) с причиной. Третий исход не выдаётся за «чисто» (инв. #17).

Прибор только ЧИТАЕТ: ни одного файла он не пишет и ничего не перезапускает.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = ROOT / "scripts" / "claude_run_with_timeout.py"

#: Класс исполняемого файла по ПУТИ. Платформенные двоичные файлы Apple окружение в
#: `ps -E` не отдают (это не наша настройка и починить её нельзя), поэтому класс —
#: объяснение слепоты, а не её оправдание.
APPLE_PREFIXES = ("/System/", "/usr/", "/bin/", "/sbin/", "/Library/Apple/", "/Applications/")

#: Метка запускателя в ЕГО КОМАНДНОЙ строке. `claude_run_with_timeout` кладёт
#: `SPA_RUN_ID` только в окружение ПОТОМКА (`env[RUN_ID_VAR] = run_id` перед `Popen`),
#: поэтому сам он опознаётся ровно этим аргументом и ничем иным.
#:
#: ⚠️ Одного флага НЕДОСТАТОЧНО, и это замерено на первом же прогоне: оболочка, в чьей
#: командной строке лежал heredoc с ТЕКСТОМ этого файла, была опознана запускателем с
#: меткой «<метка>`),» и дала ложную находку «работника не видно». Командная строка —
#: не личность (тот же урок, что у `match_origin`), поэтому запускателем считается
#: только строка, в которой назван САМ прибор запуска И метка имеет форму метки.
LAUNCHER_RE = re.compile(r"--run-id[= ]+(\S+)")
LAUNCHER_TOOL = "claude_run_with_timeout"
LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def launcher_label(cmd: str):
    """(`метка`, "") либо (`None`, причина) — метка ЗАПУСКАТЕЛЯ из его командной строки."""
    if not cmd or LAUNCHER_TOOL not in cmd:
        return None, "в командной строке не назван прибор запуска"
    m = LAUNCHER_RE.search(cmd)
    if not m:
        return None, "прибор запуска назван, но метки в аргументах нет"
    label = m.group(1)
    if not LABEL_RE.match(label):
        # Форма не подходит ⇒ это не метка, а совпадение текста. Выдать её за метку
        # значило бы спросить ось о строке, которой ни у кого в окружении нет, и
        # получить «работника не видно» — находку из ничего.
        return None, f"аргумент {label[:40]!r} формы метки не имеет"
    return label, ""


class NotMeasured(RuntimeError):
    """Прибор не ответил. ТРЕТИЙ ИСХОД, а не пустая перепись."""


def load_wrapper(path=WRAPPER):
    p = Path(path)
    if not p.exists():
        raise NotMeasured(f"нет прибора владения: {p}")
    spec = importlib.util.spec_from_file_location("_wac_wrapper", p)
    if spec is None or spec.loader is None:
        raise NotMeasured(f"не удалось загрузить {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for attr in ("Snapshot", "argv_rows", "origin_census", "RUN_ID_VAR",
                 "MATCH_ENV", "MATCH_CMDLINE", "MATCH_UNMEASURED", "PsUnavailable"):
        if not hasattr(mod, attr):
            raise NotMeasured(f"{p}: нет ожидаемого символа {attr!r}")
    return mod


def binary_class(cmd: str) -> str:
    exe = (cmd or "").split(None, 1)[0] if cmd else ""
    if not exe:
        return "неизвестно"
    for pre in APPLE_PREFIXES:
        if exe.startswith(pre):
            return f"платформенный Apple ({pre})"
    if not exe.startswith("/"):
        # argv[0] без пути — исполняемый файл не назван, класс не определён.
        return "путь не назван"
    return "сторонний"


def env_readable(tail: str) -> bool:
    """Та же мерка, что у `Snapshot.take` — своей копии правила быть не должно.

    Проверяется наличие `PATH=` среди присоединённых пар: это переменная, которая есть у
    всякого процесса, запущенного оболочкой или launchd, поэтому её отсутствие означает
    «окружение не отдано», а не «переменной нет»."""
    return "=" in (tail or "") and " PATH=" in " " + (tail or "")


def census(wrapper=None, *, snap=None, argv=None, self_pid=None) -> dict:
    """Полная перепись. Все три двери к ОС — ВХОДЫ (`.claude/rules/deployment.md`)."""
    wrapper = wrapper or load_wrapper()
    try:
        snap = snap if snap is not None else wrapper.Snapshot.take()
        rows = argv if argv is not None else wrapper.argv_rows()
    except wrapper.PsUnavailable as exc:
        raise NotMeasured(f"снимок процессов не снят: {exc}") from exc

    readable = blind = 0
    blind_by_class: dict = {}
    for pid, (_ppid, _state, _age, tail) in snap.rows.items():
        if env_readable(tail):
            readable += 1
        else:
            blind += 1
            blind_by_class[binary_class(rows.get(pid, tail))] = \
                blind_by_class.get(binary_class(rows.get(pid, tail)), 0) + 1

    # ── живые ЗАПУСКАТЕЛИ и видимость их работников ──────────────────────────
    launchers = {}
    for pid, cmd in rows.items():
        label, _why = launcher_label(cmd or "")
        if label:
            launchers.setdefault(label, []).append(pid)

    runs = []
    for label, pids in sorted(launchers.items()):
        oc = wrapper.origin_census(snap, label, argv=rows, self_pid=self_pid)
        by_env = [p for p, (kind, _) in oc["origin"].items() if kind == wrapper.MATCH_ENV]
        # Сам запускатель носителем СВОЕЙ метки по окружению не является (он кладёт её
        # только потомку), но вычитаем его явно: совпадение по его argv — это он сам.
        workers = sorted(set(by_env) - set(pids) - set(oc["self"]))
        runs.append({"label": label, "launcher_pids": sorted(pids),
                     "worker_pids": workers, "visible": bool(workers),
                     "counts": oc["counts"], "self": oc["self"]})

    return {
        "rows_total": len(snap.rows),
        "env_readable": readable,
        "env_blind": blind,
        "readable_share": (readable / len(snap.rows)) if snap.rows else None,
        "blind_by_class": dict(sorted(blind_by_class.items(), key=lambda kv: -kv[1])),
        "axis_measurable": readable > 0,
        "runs": runs,
    }


def findings(rep: dict) -> list:
    out = []
    if not rep["axis_measurable"]:
        out.append("окружение не читается НИ У ОДНОГО процесса — ось РАБОТНИКА слепа "
                   "целиком: каждый вердикт о занятости станет `unchecked` (это и есть "
                   "постоянный третий исход, которого боится п. 3 карточки)")
    for run in rep["runs"]:
        if not run["visible"]:
            out.append(f"запуск {run['label']}: запускатель ЖИВ (pid "
                       f"{', '.join(map(str, run['launcher_pids']))}), а работника с его "
                       f"меткой в окружении НЕ ВИДНО — либо работник мёртв (тогда об этом "
                       f"обязан знать замок), либо жив и невидим для оси")
        if run["counts"].get("cmdline"):
            out.append(f"запуск {run['label']}: {run['counts']['cmdline']} носител(я/ей) "
                       f"метки несут её в КОМАНДНОЙ строке — работником это не доказано")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        rep = census()
    except NotMeasured as exc:
        print(f"⛔ НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        if args.json:
            print(json.dumps({"unmeasured": str(exc)}, ensure_ascii=False))
        return 2

    found = findings(rep)
    if args.json:
        print(json.dumps({**rep, "findings": found}, ensure_ascii=False, indent=1))
        return 1 if found else 0

    share = rep["readable_share"]
    print(f"Перепись измеримости оси РАБОТНИКА · строк ps: {rep['rows_total']}")
    print(f"  окружение читается: {rep['env_readable']} "
          f"({'—' if share is None else f'{share*100:.1f} %'}) · не читается: {rep['env_blind']}")
    for klass, n in rep["blind_by_class"].items():
        print(f"    слепых [{klass}]: {n}")
    print(f"  живых запусков (по аргументу `--run-id` у запускателя): {len(rep['runs'])}")
    for run in rep["runs"]:
        mark = "✅" if run["visible"] else "❌"
        print(f"    {mark} {run['label']}: запускатель {run['launcher_pids']} · "
              f"работник(и) {run['worker_pids'] or '—'} · носители по происхождению "
              f"{run['counts']} · из них сам прибор: {run['self'] or '—'}")
    if found:
        print("\n🔎 НАХОДКИ:")
        for f in found:
            print(f"  • {f}")
        return 1
    print("\n✅ находок нет: ось измерима, у каждого живого запуска работник виден.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
