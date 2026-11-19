#!/usr/bin/env python3
"""СОСТАВ долга сирот-скриптов, а не его РАЗМЕР (ADR-1063, заказ G1051 п. 1).

Храповик `spa_core/tests/test_unwired_scripts_ratchet.py` сторожит РАЗМЕР: база
может только убывать, а всякое имя сверх базы краснит дерево. Он отвечает на
свой вопрос верно и ничего не говорит о ДВИЖЕНИИ состава — а именно там жил
дефект, который нашёл заказ G1051 п. 1.

## Замер, ради которого модуль написан (2026-11-19, цикл #1206)

Записи циклов #957…#1205 называли долг тремя именами:
`edge_risk_shape_adaptive_blend` · `edge_rkaw_running_calmar_weighting` ·
`worker_axis_census`. Храповик на чистой вершине `a394065ac` называл
ТРИ ДРУГИХ: `bounded_countdown_probe` · `build_acceptance_tree` ·
`hook_arg_mutation_census`. Пересечение — **ПУСТО**: состав сменился ЦЕЛИКОМ, а
число «три» не дрогнуло ни в одной записи, и ни один сторож об этом не сказал.

Это ровно тот дефект, против которого написан `scripts/ci_control_verdict.py`
(«красный набор 70 → 78» ничего не значит без имён), только на другом долге.

**И вторая половина замера крупнее первой.** Из трёх ушедших имён ПОДКЛЮЧЕНО
было ОДНО (`worker_axis_census` — ступень моста зовёт его подпроцессом,
ADR-843/844, цикл #964). Два других (`edge_*`) вызывающего не имеют
ПО-ПРЕЖНЕМУ: они ушли из долга ЗАПИСЬЮ в реестре R&D (`ADR-842`, цикл #962),
то есть по законному освобождению, а не потому, что их кто-то позвал. Прочитать
«долг уменьшился» как «скрипты подключили» значило бы ошибиться в двух случаях
из трёх — а именно так читается голое число.

## Что здесь измеряется

Вопрос один: **между двумя деревьями состав долга изменился как, и по какой
НАЗВАННОЙ причине у каждого имени.** Причин у ухода четыре, у прихода четыре, и
каждая НАБЛЮДАЕТСЯ в деревьях, а не выводится из прозы:

======================== =========================================================
уход                     наблюдение
======================== =========================================================
`ПОДКЛЮЧЁН`              в дереве ПОСЛЕ у скрипта есть вызывающий
`ПРОЩЁН РЕЕСТРОМ`        вызывающего ПО-ПРЕЖНЕМУ нет; снят записью реестра-продукта
`УДАЛЁН`                 файла скрипта в дереве ПОСЛЕ нет
`ВПИСАН В БАЗУ`          мир не изменился: имя дописано в объявление — ЗАПРЕЩЕНО
======================== =========================================================

======================== =========================================================
приход                   наблюдение
======================== =========================================================
`РОЖДЁН СИРОТОЙ`         файла в дереве ДО не было
`ВЫЗЫВАЮЩИЙ ПОТЕРЯН`     в дереве ДО вызывающий был
`ЗАПИСЬ РЕЕСТРА ИСЧЕЗЛА` в дереве ДО прощал реестр; записи больше нет
`УДАЛЁН ИЗ БАЗЫ`         имя убрано из объявления — направление РАЗРЕШЁННОЕ
======================== =========================================================

**Осей две, и они не взаимозаменяемы.** `red` — набор, на котором КРАСНЕЕТ
храповик (долг СВЕРХ объявленной базы), и именно его имена цитируют записи
циклов; `dead` — весь долг целиком. Имя уходит из `red`, не уходя из `dead`,
ровно тогда, когда его вписали в базу, — то есть ось и есть то место, где
запрещённое дописывание становится видно. Ось объявляется входом и ПЕЧАТАЕТСЯ.

Три исхода вердикта различимы (инв. #17): **0** — состав совпал · **1** —
состав РАЗОШЁЛСЯ (имена и причины названы) · **2** — **НЕ ИЗМЕРЕНО** с
названной причиной. Равные РАЗМЕРЫ при разошедшемся составе — не «порядок», а
находка, и отчёт говорит это отдельной строкой: без неё читатель увидит «3 и 3»
и закроет вопрос.

## Чего модуль НЕ делает

* **Не судит, законно ли освобождение.** «Прощён реестром» — наблюдение, а не
  одобрение: правило вычета и его границы живут в `spa_core/tests/_unwired.py`
  и охраняются `test_unwired_registry_evidence.py` (ADR-792). Здесь только
  названо, что имя ушло ИМЕННО так, а не потому, что его позвали.
* **Не держит второй копии правила проводки.** Единственная дверь измерения —
  `spa_core.tests._unwired`; своей регулярки «что считается вызовом» у модуля
  нет и быть не должно (разойдись они — долг мерился бы двумя мерками).
  Держит `test_the_module_keeps_no_second_copy_of_the_wiring_rule`.
* **Ничего не чинит и ничего не пишет.** Прибор только ЧИТАЕТ.
* **Своей точки входа НЕ держит, и это ЗАМЕР, а не стиль.** Первая редакция несла CLI,
  и сторож соседнего класса (`test_unwired_guard_modules_ratchet`) честно назвал её
  НОВОЙ сиротой: сторож с точкой входа, которого никто не зовёт, есть ровно тот дефект,
  который мерит этот модуль. Поэтому он библиотека: его зовёт батарея и живой храповик
  `test_unwired_scripts_ratchet`, а зов руками — одной строкой
  `python3 -c "from spa_core.monitoring import orphan_script_debt as o; …"`.
  Сделать его артефактом с читателем (манифест + SLO) — отдельное решение, названное
  заказом G1052. Сторож той переписи читает СЫРОЙ текст файла, поэтому и упоминание
  названия точки входа в прозе числилось бы ею: здесь оно не названо намеренно.
* **Не поднимает глубину клона.** Ссылка, которой в клоне нет (усечённый клон —
  `.claude/rules/deployment.md`, поправка #1031), даёт **НЕ ИЗМЕРЕНО** с
  причиной, а не ответ о чужом графе.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
from typing import Dict, Optional, Tuple

from spa_core.tests import _unwired

#: Причины УХОДА имени из долга. Список ЗАКРЫТ: добавить причину — решение
#: (ADR), а не правка строки, иначе «ушёл непонятно почему» получит имя и
#: перестанет быть находкой.
WIRED = "ПОДКЛЮЧЁН"
FORGIVEN = "ПРОЩЁН РЕЕСТРОМ"
REMOVED = "УДАЛЁН"
#: Четвёртая причина ухода существует ТОЛЬКО на оси красного набора храповика и
#: является ЗАПРЕЩЁННЫМ действием (инв. #16): имя дописали в базу, и сторож
#: замолчал, не изменив мира. Она названа именно для того, чтобы такой уход
#: нельзя было прочитать как «долг уменьшился».
BASELINED = "ВПИСАН В БАЗУ"
DEPARTURE_CAUSES: Tuple[str, ...] = (WIRED, FORGIVEN, REMOVED, BASELINED)

#: Причины ПРИХОДА имени в долг. Список тоже закрыт, и по той же причине.
BORN = "РОЖДЁН СИРОТОЙ"
CALLER_LOST = "ВЫЗЫВАЮЩИЙ ПОТЕРЯН"
FORGIVENESS_GONE = "ЗАПИСЬ РЕЕСТРА ИСЧЕЗЛА"
#: Обратная сторона `BASELINED` и, в отличие от неё, направление РАЗРЕШЁННОЕ:
#: база может только убывать, и убывание делает сторожа красным честно.
UNBASELINED = "УДАЛЁН ИЗ БАЗЫ"
ARRIVAL_CAUSES: Tuple[str, ...] = (BORN, CALLER_LOST, FORGIVENESS_GONE, UNBASELINED)

#: Нарушения, которые отчёт обязан называть вслух, а не прятать в причину.
FORBIDDEN_CAUSES: Tuple[str, ...] = (BASELINED,)

#: Две оси вопроса. `red` — то, на чём КРАСНЕЕТ храповик (и что цитируют записи
#: циклов): долг сверх объявленной базы. `dead` — весь долг целиком. Их нельзя
#: смешивать: имя уходит из `red`, не уходя из `dead`, ровно когда его вписали
#: в базу.
AXES: Tuple[str, ...] = ("red", "dead")

#: Объявление долга — база храповика. Читается ИЗ ТОГО ЖЕ дерева, что и долг:
#: сравнивать наблюдение одного дерева с объявлением другого значило бы мерить
#: двумя мерками.
_BASELINE = pathlib.Path("spa_core") / "tests" / "unwired_scripts_baseline.json"

#: Третий исход (инв. #17). Он НЕ состоит в двух списках выше намеренно:
#: «не измерено» не есть причина ухода и не есть причина прихода.
UNMEASURED = "НЕ ИЗМЕРЕНО"

#: Сборщик чистого дерева ссылки. Своей копии `git archive` модуль не держит:
#: рядом уже живёт разобранный и покрытый батареей экспорт, и четвёртая копия
#: той же механики разошлась бы с ними молча.
_EXPORTER = pathlib.Path("scripts") / "build_acceptance_tree.py"


def measure_root(root) -> Dict:
    """Четыре множества имён, которыми описывается долг одного дерева.

    `dead` — то же самое, что сторожит храповик: «вызывающего нет И записи в
    реестре-продукте нет». Остальные три нужны, чтобы НАЗВАТЬ причину: без
    `no_caller` нельзя отличить «подключили» от «простили», без `entrypoints` —
    «удалили» от «подключили».

    **Дерево без ни одной точки входа — это НЕ пустой долг, а НЕ ИЗМЕРЕНО**
    (fail-CLOSED): так выглядит и репозиторий без `scripts/`, и путь, которого
    нет, и дерево, которое не прочиталось. Ноль здесь был бы ответом, которого
    никто не мерил.
    """
    base = pathlib.Path(root)
    try:
        entrypoints = {p.stem for p in _unwired.entrypoint_scripts(base)}
    except OSError as exc:
        return {"measured": False, "root": str(base),
                "cause": f"{UNMEASURED}: дерево {base} не прочитано: {exc}"}
    if not entrypoints:
        return {"measured": False, "root": str(base),
                "cause": (f"{UNMEASURED}: в дереве {base} не найдено ни одной точки "
                          "входа `scripts/*.py` — пустым долгом это не считается")}
    dead = set(_unwired.unwired_scripts(base))
    baseline, baseline_cause = _declared_baseline(base)
    return {
        "measured": True,
        "root": str(base),
        "entrypoints": entrypoints,
        "no_caller": set(_unwired.scripts_without_caller(base)),
        "registry": set(_unwired.registry_recorded_scripts(base)),
        "dead": dead,
        "baseline": baseline,
        "baseline_cause": baseline_cause,
        "red": dead - baseline if baseline_cause is None else set(),
        "red_measured": baseline_cause is None,
    }


def _declared_baseline(base: pathlib.Path) -> Tuple[set, Optional[str]]:
    """Объявленный долг (база храповика) — либо названная причина её отсутствия.

    База не прочитана ⇒ ось красного набора НЕ ИЗМЕРЕНА. Пустое множество здесь
    выдало бы весь долг за красный набор, то есть ответило бы на свой вопрос
    вместо нужного.
    """
    path = base / _BASELINE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return set(), f"объявление долга {path} не прочитано: {exc}"
    try:
        return (set(raw["scripts"])
                | set(raw.get("revealed_by_stricter_detector", {}))), None
    except (KeyError, TypeError) as exc:
        return set(), f"объявление долга {path} не той формы: {exc}"


def departure_cause(name: str, after: Dict) -> Tuple[str, str]:
    """Почему имя УШЛО из долга — по наблюдению в дереве ПОСЛЕ.

    Порядок вопросов не произволен: «файла нет» обязан спрашиваться первым,
    потому что у отсутствующего файла нет ни вызывающего, ни записи в реестре,
    и любой другой порядок назвал бы удаление подключением. «Вписан в базу»
    спрашивается ПОСЛЕДНИМ из наблюдаемых: имя, которое и подключили, и вписали
    в базу, ушло потому, что его ПОЗВАЛИ, — остаток же есть дописывание ради
    тишины.
    """
    if name not in after["entrypoints"]:
        return REMOVED, f"файла scripts/{name}.py в дереве ПОСЛЕ нет"
    if name not in after["no_caller"]:
        return WIRED, "в дереве ПОСЛЕ у скрипта есть вызывающий"
    if name in after["registry"]:
        return FORGIVEN, ("вызывающего ПО-ПРЕЖНЕМУ нет: имя снято с долга ЗАПИСЬЮ "
                          "реестра-продукта, а не вызовом")
    if name in after["baseline"]:
        return BASELINED, ("мир не изменился: скрипт мёртв ПО-ПРЕЖНЕМУ, а имя "
                           "дописано в объявление долга — это ЗАПРЕЩЕНО (инв. #16)")
    return UNMEASURED, ("ушёл из долга, но ни одна из причин в дереве ПОСЛЕ не "
                        "наблюдена — состояние противоречиво")


def arrival_cause(name: str, before: Dict) -> Tuple[str, str]:
    """Почему имя ПРИШЛО в долг — по наблюдению в дереве ДО."""
    if name not in before["entrypoints"]:
        return BORN, "файла в дереве ДО не было — скрипт рождён сиротой"
    if name not in before["no_caller"]:
        return CALLER_LOST, "в дереве ДО у скрипта вызывающий был"
    if name in before["registry"]:
        return FORGIVENESS_GONE, ("в дереве ДО имя прощал реестр-продукт; записи больше "
                                  "нет, а вызывающего не было и нет")
    if name in before["baseline"]:
        return UNBASELINED, ("мир не изменился: скрипт мёртв и в дереве ДО, а имя "
                             "УБРАНО из объявления долга — разрешённое направление")
    return UNMEASURED, ("пришёл в долг, но ни одна из причин в дереве ДО не "
                        "наблюдена — состояние противоречиво")


def delta(before: Dict, after: Dict, axis: str = "red") -> Dict:
    """Состав долга: кто ушёл, кто пришёл и кто остался — с причинами.

    `axis="red"` — набор, на котором КРАСНЕЕТ храповик (именно его имена
    цитируют записи циклов); `axis="dead"` — весь долг. Ось объявляется входом и
    ПЕЧАТАЕТСЯ: ответ о другом наборе выглядел бы так же.

    `size_equal_but_composition_changed` — отдельное поле, а не вывод читателя.
    Ровно этот случай (3 и 3 при пустом пересечении) прожил от #957 до #1205
    незамеченным, потому что совпадение РАЗМЕРОВ читается как «ничего не
    изменилось».
    """
    if axis not in AXES:
        return {"measured": False,
                "cause": f"ось `{axis}` не объявлена; объявлены {AXES}"}
    for side, label in ((before, "ДО"), (after, "ПОСЛЕ")):
        if not side.get("measured"):
            return {"measured": False, "axis": axis,
                    "cause": f"дерево {label}: {side.get('cause', UNMEASURED)}"}
        if axis == "red" and not side.get("red_measured"):
            return {"measured": False, "axis": axis,
                    "cause": (f"дерево {label}: ось красного набора НЕ ИЗМЕРЕНА — "
                              f"{side.get('baseline_cause')}")}
    departed = []
    for name in sorted(before[axis] - after[axis]):
        cause, why = departure_cause(name, after)
        departed.append({"name": name, "cause": cause, "why": why})
    arrived = []
    for name in sorted(after[axis] - before[axis]):
        cause, why = arrival_cause(name, before)
        arrived.append({"name": name, "cause": cause, "why": why})
    held = sorted(before[axis] & after[axis])
    moved = bool(departed or arrived)
    return {
        "measured": True,
        "axis": axis,
        "root_before": before["root"],
        "root_after": after["root"],
        "size_before": len(before[axis]),
        "size_after": len(after[axis]),
        "held": held,
        "departed": departed,
        "arrived": arrived,
        "forbidden": [r for r in departed + arrived
                      if r["cause"] in FORBIDDEN_CAUSES],
        "unmeasured_rows": [r for r in departed + arrived
                            if r["cause"] == UNMEASURED],
        "size_equal_but_composition_changed": (
            moved and len(before[axis]) == len(after[axis])),
        "composition_turned_over_whole": moved and not held,
    }


def verdict(report: Dict) -> Tuple[int, str]:
    """Три исхода, и ни один не выдаётся за другой (инв. #17)."""
    if not report.get("measured"):
        return 2, f"⛔ {UNMEASURED}: {report.get('cause', 'причина не названа')}"
    if not (report["departed"] or report["arrived"]):
        return 0, (f"✅ ось `{report['axis']}`: состав СОВПАЛ — те же "
                   f"{report['size_after']} имён, ушедших и пришедших нет")
    head = (f"⚠️ ось `{report['axis']}`: состав РАЗОШЁЛСЯ — ушло "
            f"{len(report['departed'])}, пришло {len(report['arrived'])}, "
            f"осталось {len(report['held'])} "
            f"(размер {report['size_before']} → {report['size_after']})")
    if report["composition_turned_over_whole"]:
        head += " — пересечение ПУСТО: состав сменился ЦЕЛИКОМ"
    if report["size_equal_but_composition_changed"]:
        head += (" · РАЗМЕР НЕ ДРОГНУЛ — именно так долг и выглядел «постоянным» "
                 "от #957 до #1205")
    if report["forbidden"]:
        head += (" · ЗАПРЕЩЁННОЕ ДЕЙСТВИЕ у "
                 + ", ".join(r["name"] for r in report["forbidden"]))
    return 1, head


def format_report(report: Dict) -> str:
    """Человеческий отчёт. Имена печатаются ВСЕГДА: число без имён и есть дефект."""
    code, head = verdict(report)
    lines = [head]
    if code == 2:
        return "\n".join(lines)
    lines.append(f"   дерево ДО:    {report['root_before']}")
    lines.append(f"   дерево ПОСЛЕ: {report['root_after']}")
    for key, title in (("departed", "УШЛИ из долга"), ("arrived", "ПРИШЛИ в долг")):
        rows = report[key]
        lines.append(f"   {title} ({len(rows)}):" if rows else f"   {title}: нет")
        for row in rows:
            lines.append(f"     • {row['name']} — {row['cause']}: {row['why']}")
    if report["held"]:
        lines.append(f"   ОСТАЛИСЬ ({len(report['held'])}): "
                     + ", ".join(report["held"]))
    return "\n".join(lines)


def _git(repo: pathlib.Path, *args: str) -> Tuple[int, str]:
    try:
        done = subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, timeout=120.0)
    except (OSError, subprocess.SubprocessError) as exc:
        return 128, str(exc)
    return done.returncode, (done.stdout or done.stderr).strip()


def _load_exporter(repo: pathlib.Path):
    """Единственная дверь к сборщику чистого дерева ссылки.

    Берётся ИЗ ТОГО ЖЕ дерева, которое задаёт вопрос: разойдись сборщик с
    измерителем — ответ был бы о другом дереве. Не загрузился ⇒ НЕ ИЗМЕРЕНО с
    названной причиной, а не свой `git archive` втихую.
    """
    path = repo / _EXPORTER
    if not path.exists():
        raise FileNotFoundError(f"сборщика дерева {path} в этом клоне нет")
    spec = importlib.util.spec_from_file_location("_spa_tree_exporter", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"{path} не загружается как модуль")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    export = getattr(mod, "export_tree", None) or getattr(mod, "_export_tree", None)
    if export is None:
        raise AttributeError(f"{path} не отдаёт выгрузчик дерева (export_tree)")
    return export


def measure_ref(repo, ref: str, dest) -> Dict:
    """Долг дерева ОБЪЯВЛЕННОЙ ссылки объявленного клона.

    Клон ВЫБИРАЕТСЯ вызывающим и ПЕЧАТАЕТСЯ в отчёте (поправка #1031: молча
    подставить полное зеркало хуже ошибки — читатель не узнает, о чьём графе
    ему ответили). Ссылки нет в клоне ⇒ третий исход.
    """
    repo = pathlib.Path(repo)
    code, out = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if code != 0:
        return {"measured": False, "root": f"{repo}@{ref}",
                "cause": (f"{UNMEASURED}: ссылки `{ref}` в клоне {repo} нет "
                          f"(git rev-parse код {code}: {out}) — усечённый клон на "
                          "этот вопрос отвечать не способен")}
    sha = out.splitlines()[0].strip()
    dest = pathlib.Path(dest)
    try:
        _load_exporter(repo)(repo, sha, dest)
    except Exception as exc:  # noqa: BLE001 — причина уезжает в вердикт дословно
        return {"measured": False, "root": f"{repo}@{ref}",
                "cause": f"{UNMEASURED}: дерево {sha[:9]} не выгружено: {exc}"}
    got = measure_root(dest)
    got["root"] = f"{repo}@{ref} ({sha[:9]}) → {dest}"
    return got
