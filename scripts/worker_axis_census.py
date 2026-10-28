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

Прибор только ЧИТАЕТ: ни одного файла он не пишет и ничего не перезапускает. Отчёт
(``data/worker_axis_census.json``) записывает ТОТ, КТО ПОЗВАЛ, — ступень моста; прибор
отдаёт документ на stdout (``--json``). Это не мелочь оформления: писателя артефакта
сторож достижимости (`spa_core/tests/_orphan_producer.py`) ищет среди ТОЧЕК ВХОДА и
импортированного кода, а зов подпроцессом по константе пути ему не виден. Писатель,
живущий здесь, был бы объявленным продуктом, которого «никто не вычисляет», — и сторож
это и сказал на первой редакции ADR-843, до доставки.

ПРОВОДКА (ADR-843, заказ G842 п. 2). До 28.10 прибор не звал НИКТО: написанный 14.10,
он держал своё имя красным у храповика сирот `test_unwired_scripts_ratchet` («новые
скрипты с точкой входа, которых никто не вызывает») — то есть был ровно тем, что сам
измеряет: написанной и не позванной проверкой. Чинит это ПРОВОДКА, а не строка в базе:
ступень `findings_bridge.worker_axis_census_step` зовёт прибор подпроцессом с ``--json``,
сама сверяет такт по возрасту отчёта и сама его записывает; артефакт объявлен в
конституции со SLO, и его читает поимённая ветка шага 0-офис. Образец и цена такого зова
названы у соседей — ADR-414 (такт решает ФАЙЛ) и ADR-790 (зов подпроцессом, чтобы
перепись не валила мост).

ПОЧЕМУ ТАКТ ШЕСТЬ ЧАСОВ, а не недельный, как у соседа `python_reader_clock_doors`.
Предмет соседа — дерево исходников, оно за неделю не меняется. Предмет ЭТОГО прибора —
ЖИВОЙ хост: доля строк `ps` с читаемым окружением и видимость работника у живого
запуска. Недельный такт отвечал бы на вопрос о случайной минуте семидневки.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:          # прибор зовут и подпроцессом, и из тестов
    sys.path.insert(0, str(ROOT))
WRAPPER = ROOT / "scripts" / "claude_run_with_timeout.py"

from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.monitoring.call_provenance import describe as provenance_line  # noqa: E402,E501
from spa_core.utils.observation import observed  # noqa: E402

#: НИ ПУТИ ОТЧЁТА, НИ ТАКТА здесь НЕТ — и это решение, а не пропуск. Отчёт пишет
#: ПОЗВАВШИЙ (ступень моста: только она достижима для сторожа писателей), срок решает
#: ФАЙЛ отчёта, значит и путь, и гейт такта живут у него —
#: `findings_bridge.WORKER_AXIS_CENSUS_ARTIFACT` / `…_TACT_DAYS`. Вторая копия любого из
#: них здесь разошлась бы с первой МОЛЧА, а это ровно класс ADR-220, которым прибор и
#: его соседи заняты.


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


def document(rep: dict, found: list, *, root=ROOT, now=None,
             main_file=None, argv_in=None) -> dict:
    """Отчёт прибора как ДОКУМЕНТ — то, что читают конституция и шаг 0-офис.

    ``status`` объявлен словом, а не выведен из длины списка находок читателем:
    вывод «находок нет ⇒ чисто» был бы неверен для третьего исхода, а третий исход
    документом не становится вовсе — он поднимает :class:`NotMeasured` и артефакт не
    пишется (инв. #17: «не измерено» не имеет права выглядеть как «измерено и чисто»).

    ``invoked_by`` — наблюдение «КТО ПОЗВАЛ», и оно здесь по тому же доводу, что у
    соседа (`python_reader_clock_doors`, заказ G37 п. 1): это единственное поле,
    которое покраснеет, если проводку однажды снимут и отметку снова начнёт ставить
    рука цикла. Часы и обе двери разбора — ВХОДЫ, стенных часов в документе нет.
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
        "rows_total": rep["rows_total"],
        "env_readable": rep["env_readable"],
        "env_blind": rep["env_blind"],
        "readable_share": rep["readable_share"],
        "blind_by_class": rep["blind_by_class"],
        "axis_measurable": rep["axis_measurable"],
        "runs": rep["runs"],
        "findings": list(found),
    }


def report(doc: dict) -> list:
    """Строки отчёта. ЕДИНСТВЕННАЯ копия правила отрисовки в приборе.

    И консоль, и шаг 0-офис идут сюда: вторая копия правила расходилась бы с первой
    молча (ADR-220), а расхождение «в консоли одно, в отчёте другое» и есть тот дефект,
    который прибор рядом измеряет. Отсутствующее поле печатается словами «НЕ ИЗМЕРЕНО»,
    а не `None` и не нулём (инв. #17): `None` читается глазом как «пусто, всё в порядке».
    """
    def _n(key, kind=int):
        """Отсутствие наблюдения — СЛОВА, а не `None` и не нуль (инв. #17).

        `None` в выводе читается глазом как «пусто, всё в порядке» — ровно fail-OPEN,
        и собственный контроль этого файла поймал здесь именно его.
        """
        value = observed(doc, key, kind=kind)
        return "НЕ ИЗМЕРЕНО" if value is None else value

    share = observed(doc, "readable_share", kind=float)
    out = [f"перепись измеримости оси РАБОТНИКА · строк ps: {_n('rows_total')}"]
    out.append(f"   окружение читается: {_n('env_readable')} "
               f"({'НЕ ИЗМЕРЕНО' if share is None else f'{share * 100:.1f} %'}) · "
               f"не читается: {_n('env_blind')}")
    for klass, n in (observed(doc, "blind_by_class", kind=dict) or {}).items():
        out.append(f"     слепых [{klass}]: {n}")
    runs = observed(doc, "runs", kind=list)
    out.append("   живых запусков (по аргументу `--run-id` у запускателя): "
               f"{'НЕ ИЗМЕРЕНО' if runs is None else len(runs)}")
    for run in runs or []:
        out.append(f"     {'✅' if run.get('visible') else '❌'} {run.get('label')}: "
                   f"запускатель {run.get('launcher_pids')} · "
                   f"работник(и) {run.get('worker_pids') or '—'} · "
                   f"носители по происхождению {run.get('counts')} · "
                   f"из них сам прибор: {run.get('self') or '—'}")
    out.append(f"   [ЗВАВШИЙ] {provenance_line(observed(doc, 'invoked_by', kind=dict))}")
    found = observed(doc, "findings", kind=list)
    if found:
        out.append("   🔎 НАХОДКИ:")
        out.extend(f"     • {f}" for f in found)
    elif found == []:
        out.append("   ✅ находок нет: ось измерима, у каждого живого запуска работник виден")
    else:
        out.append("   ⛔ НЕ ИЗМЕРЕНО: перечня находок в отчёте нет — это не «находок нет»")
    out.append("   ADVISORY: прибор только ЧИТАЕТ состояние системы и ничего не перезапускает")
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


def run(root=ROOT, *, now=None, wrapper=None, snap=None, argv=None,
        self_pid=None) -> dict:
    """ОДИН замер и документ. Ни файла, ни гейта такта — оба у того, КТО ПОЗВАЛ.

    Разделение не декоративное: писателя артефакта сторож достижимости ищет среди точек
    входа и импортированного кода, и прибор, зовомый подпроцессом по константе пути, ему
    не виден. Поэтому пишет ступень моста (она — точка входа агента
    `com.spa.decision_loop`), а прибор отдаёт документ и остаётся читающим.

    Третий исход сюда НЕ помещается по построению: прибор, не снявший снимка, поднимает
    :class:`NotMeasured`, и документа не существует — значит и записать нечего (инв. #17:
    артефакт с выдуманным вердиктом лгал бы ещё и своим возрастом).

    Все двери к ОС остаются ВХОДАМИ (``wrapper``/``snap``/``argv``/``self_pid``) — иначе
    каждый тест отвечал бы на вопрос о ХОСТЕ, а не о проводке
    (`.claude/rules/deployment.md`, § про инъекцию).
    """
    rep = census(wrapper, snap=snap, argv=argv, self_pid=self_pid)
    return document(rep, findings(rep), root=root, now=now)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true",
                    help="отдать документ на stdout (его записывает ПОЗВАВШИЙ)")
    ap.add_argument("--repo-root", default=str(ROOT),
                    help="дерево, о котором спрашивается происхождение зова")
    args = ap.parse_args(argv)
    try:
        doc = run(root=args.repo_root)
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
