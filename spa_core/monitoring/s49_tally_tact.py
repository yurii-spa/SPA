"""КТО обязан звать сводку §49 приказа «Portfolio CIO» и с КАКИМ ТАКТОМ — замер.

Заказ **G93 п. 3** (хвост ADR-505) дословно:

    «Сводка не читается никем. Прибор есть, читателя у него нет: в перечне
     артефактов шага 0-офис он не значится. Объявлять SLO механически нельзя
     (урок G86 п. 4) — сначала замер: кто и с каким тактом обязан его звать.»

Заказ запрещает ровно то, чем соблазн закрыть его в одну строку: вписать
`slo_hours` в манифест и объявить проводку готовой. Такт — не вкус автора. У
сводки есть входы, и она устаревает ТОГДА, когда может измениться её вход;
значит такт обязан быть ВЫЧИСЛЕН из входов, а не выбран.

## Три вопроса, и каждый мерится отдельно

1. **ТАКТ-ПОЛ.** Вердикт сводки есть функция артефактов, объявленных мерой
   критериев §49 (`architecture/manifest.json`, привязка разбирается соседом
   `s49_criterion_price.parse_bindings` — ВТОРОЙ копии правила здесь нет,
   ADR-220). У каждого такого артефакта объявлен свой `slo_hours`. Сводка
   перестаёт быть правдой, как только истёк САМЫЙ КОРОТКИЙ из них: звать её
   реже — значит печатать вердикт о мире, которого уже нет. Поэтому
   **такт-пол = min(`slo_hours`) по привязкам населения**.
   Критерий без привязки и привязка без `slo_hours` — **третий исход** с
   названной причиной, а не ноль и не пропуск (инв. #17): «такт этого критерия
   не измерен» и «такт этого критерия велик» чинятся разным.
2. **КТО ЗОВЁТ СЕГОДНЯ.** Население зовущих — ОБЪЯВЛЕННЫЙ состав ступеней моста
   (`findings_bridge.CENSUS_PRODUCT`, контракт по ADR-158), а не обход диска.
   У каждой ступени спрашивается её исходник разбором AST, и ответов ТРИ:

   ============== =============================================================
   `calls`        модуль ступени И импортирует сводку, И зовёт у неё `measure`
                  или `main` — это зовущий
   `imports_only` импортирует и НЕ зовёт. **Импорт не есть вызов**, и разница
                  здесь не придирка: храповик неподключённых скриптов
                  (`test_unwired_scripts_ratchet`) считает проводкой ЛЮБУЮ
                  ссылку, поэтому один импорт ради чужого правила делает
                  сироту «подключённой» молча — зелёный сторож при живой дыре
   `no_reference` ссылки нет вовсе
   ============== =============================================================

3. **ЧТО ДОХОДИТ ДО ЧИТАТЕЛЯ.** Вердикт сводки доходит до шага 0-офис только
   артефактом. У каждого зовущего спрашивается его артефакт: несёт ли он
   вердикты критериев так, что `satisfied` отличимо от `not_satisfied`
   (`carries_verdicts`), или сворачивает их в один класс (`collapses_verdicts`),
   или артефакта ещё нет вовсе (`artifact_absent` — **не** «не несёт»: объявлен
   и ни разу не произведён есть третье положение дел).

## Почему прибор НЕСЁТ сводку, а не только судит о такте

Иначе он сам был бы ответом «читателя нет» без читателя. Артефакт прибора
содержит ТАЛЛИ — счёт `выполнено · не выполнено · не измерено` и построчные
вердикты, — и его читает поимённая ветка шага 0-офис. Прогон сводки стои́т
измеренных **61,1 с** (два замера 03.10: 61,07 и 61,22) — при такте в часы это
доли процента, и стоимость кладётся в артефакт ЗАМЕРОМ, а не оценкой.

## Чего прибор НЕ докладывает (назвать слепоту — часть замера)

* **Наблюдённый период бегуна.** Сравниваются ОБЪЯВЛЕННЫЕ такты (`slo_hours`
  манифеста). ADR-506 измерил, что у `com.spa.decision_loop` объявленный срок и
  наблюдённый период расходятся ПО ПОСТРОЕНИЮ (`StartInterval` считается от
  ЗАВЕРШЕНИЯ прогона), и это отдельный замер, а не этот.
* **Верность самой пробы.** «Критерий выполнен» здесь — вердикт мерки, а не
  истина о системе; правду мерки держит её контроль в обе стороны
  (`.claude/rules/acceptance.md`, п. 3).
* **Полноту населения зовущих.** Оно ОБЪЯВЛЕНО составом ступеней. Зовущий вне
  моста (чужой агент, рука) прибору не виден, и это сказано вслух, а не
  подразумевается.
* **Ничего не чинит.** ADVISORY: ни строки risk-логики, RiskPolicy, стоп-крана,
  аллокатора, живого трека или `landing/**`.

## Коды возврата

* **0** — замер состоялся И такт-пол обслужен: есть зовущий, чей объявленный
  такт не длиннее пола.
* **1** — замер состоялся и есть находка (зовущего нет вовсе · все зовущие
  медленнее пола · вердикт сводки не доходит до читателя). Числа печатаются.
* **2** — замера НЕТ ВОВСЕ: сводка не снята, население не прочитано, состав
  ступеней не прочитан. Про такт при этом НЕ СКАЗАНО НИЧЕГО, и выдать это за
  «такт в порядке» нельзя.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from spa_core.monitoring.card_acceptance import (  # noqa: E402
    NOT_SATISFIED,
    SATISFIED,
    UNMEASURED,
)
from spa_core.monitoring import s49_criterion_price as price_meter  # noqa: E402
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT = "s49_tally_tact.json"

#: Имя модуля сводки §49 — предмет вопроса «кто её зовёт».
SUMMARY_MODULE = "cio_acceptance_rollup"

#: Имена, зов которых у модуля сводки означает «сводка СНЯТА», а не «имя
#: упомянуто». Объявлены списком намеренно: вывести их из исходника значило бы
#: согласиться, что любой атрибут сводки есть её зов.
SUMMARY_ENTRIES = ("measure", "main")

#: Такт ступени: гейт заведомо КОРОЧЕ измеренного такта-пола, чтобы гейт никогда
#: не был причиной устаревания вердикта. Пол меряется прибором каждый прогон, и
#: если он опустится ниже этого числа, прибор скажет это сам своей находкой
#: `carrier_slower_than_floor` — про СВОЙ артефакт в том числе.
MEASUREMENT_TACT_DAYS = 6.0 / 24.0

#: Исходы у ОДНОЙ ступени на вопрос «зовёт ли она сводку».
CALLS = "calls"
IMPORTS_ONLY = "imports_only"
NO_REFERENCE = "no_reference"
SOURCE_UNREADABLE = "source_unreadable"

#: Исходы у ОДНОГО артефакта зовущего на вопрос «доходит ли ТАЛЛИ до читателя».
#:
#: Разница между первыми двумя измерена мутацией, а не придумана: первая
#: редакция спрашивала у артефакта, встречаются ли в нём ОБА слова `satisfied` и
#: `not_satisfied`, — то есть судила о СХЕМЕ носителя по СЕГОДНЯШНИМ значениям.
#: Артефакт, у которого в этот день все критерии выполнены, она объявила бы
#: «вердикта не несущим», а мутация `and`→`or` в ней выживала: сцена не умела
#: отличить «схема не выражает» от «значение сегодня одно».
#:
#: Правильный вопрос — ЧТО АРТЕФАКТ ОБЪЯВЛЯЕТ: счёт по населению (таллии, её
#: можно ПРОЧЕСТЬ) или только построчные вердикты (читателю пришлось бы сложить
#: их самому, то есть завести ВТОРУЮ копию мерки, ADR-220).
CARRIES_TALLY = "carries_tally"
CARRIES_VERDICTS_ONLY = "carries_verdicts_only"
NAMES_NO_CRITERION = "names_no_criterion"
ARTIFACT_ABSENT = "artifact_absent"
ARTIFACT_UNREADABLE = "artifact_unreadable"

#: Словарь вердиктов §49. Значение ИЗ него, стоящее у критерия, и есть вердикт;
#: счёт ПО нему — таллии.
VERDICT_VOCABULARY = (SATISFIED, NOT_SATISFIED, UNMEASURED)

#: Исходы у ОДНОГО критерия на вопрос «что он даёт такту-полу».
TACT_BOUND = "bound"
TACT_BOUND_WITHOUT_SLO = "bound_without_slo"
TACT_UNBOUND = "unbound"

#: Исходы сводного вопроса «обслужен ли такт-пол».
FLOOR_SERVED = "floor_served"
NO_CALLER_AT_ALL = "no_caller_at_all"
CALLERS_SLOWER_THAN_FLOOR = "callers_slower_than_floor"

VERDICT_RU = {
    FLOOR_SERVED: "у сводки есть зовущий, чей такт не длиннее пола",
    NO_CALLER_AT_ALL: "сводку не зовёт НИ ОДНА ступень — читателя у вердикта нет",
    CALLERS_SLOWER_THAN_FLOOR: "зовущие есть, но все медленнее такта-пола",
}


class Unmeasured(Exception):
    """Замера нет вовсе. Про такт при этом не сказано НИЧЕГО."""


def _stamp_now(now=None) -> str:
    """Момент замера строкой ISO с поясом. Часы — ВХОД, а не окружение."""
    moment = now if now is not None else dt.datetime.now(dt.timezone.utc)
    return moment.isoformat()


# ─────────────────────────── 1. такт-пол ───────────────────────────

def tact_floor(criteria, *, repo_root: str) -> dict:
    """Такт-пол = min(`slo_hours`) по привязкам населения §49.

    Привязка читается СОСЕДОМ (`s49_criterion_price.parse_bindings`): правило
    «какой артефакт объявлен мерой какого критерия» уже существует, и вторая его
    копия разошлась бы с первой молча (ADR-220).

    Три исхода у критерия, и они различимы: привязка с числом · привязка без
    числа · привязки нет. Второй и третий В ПОЛ НЕ ВХОДЯТ и перечисляются
    отдельно — усреднить их нулём значило бы объявить пол нулевым там, где он
    просто не измерен.
    """
    try:
        manifest = price_meter.read_manifest(repo_root)
    except price_meter.Unmeasured as exc:
        raise Unmeasured(f"такт-пол не измерен: {exc}") from exc
    bindings = (price_meter.parse_bindings(manifest) or {}).get("bindings") or {}

    rows = []
    for name in criteria:
        entries = bindings.get(name) or []
        if not entries:
            rows.append({"criterion": name, "state": TACT_UNBOUND,
                         "slo_hours": None, "artifact": None,
                         "why": "мерой этого критерия не объявлен НИ ОДИН артефакт "
                                "конституции — такт его входа взять неоткуда"})
            continue
        numeric = [e for e in entries
                   if isinstance(e.get("slo_hours"), (int, float))
                   and not isinstance(e.get("slo_hours"), bool)]
        if not numeric:
            paths = ", ".join(sorted({str(e.get("path")) for e in entries}))
            rows.append({"criterion": name, "state": TACT_BOUND_WITHOUT_SLO,
                         "slo_hours": None, "artifact": paths,
                         "why": f"привязка есть ({paths}), а `slo_hours` при ней не "
                                f"объявлен — срок входа НЕ ИЗМЕРЕН, и подставить "
                                f"сюда число значило бы его выдумать"})
            continue
        best = min(numeric, key=lambda e: float(e["slo_hours"]))
        rows.append({"criterion": name, "state": TACT_BOUND,
                     "slo_hours": float(best["slo_hours"]),
                     "artifact": str(best.get("path")),
                     "why": f"вход {best.get('path')} объявлен со сроком "
                            f"{float(best['slo_hours']):g} ч"})

    bound = [r for r in rows if r["state"] == TACT_BOUND]
    if not bound:
        raise Unmeasured(
            "ни у одного критерия §49 нет привязки с объявленным `slo_hours` — "
            f"пола нет вовсе (критериев осмотрено {len(rows)}). «Пол не измерен» "
            "не есть «пол любой»")
    floor_row = min(bound, key=lambda r: r["slo_hours"])
    return {"floor_hours": floor_row["slo_hours"],
            "floor_set_by": floor_row["criterion"],
            "floor_input": floor_row["artifact"],
            "rows": rows,
            "counts": {state: sum(1 for r in rows if r["state"] == state)
                       for state in (TACT_BOUND, TACT_BOUND_WITHOUT_SLO, TACT_UNBOUND)}}


# ─────────────────────────── 2. кто зовёт ───────────────────────────

def _summary_aliases(tree: ast.AST) -> set:
    """Имена, под которыми модуль сводки связан в этом исходнике.

    Форма импорта ЗНАЧИМА и теряется в плоском множестве имён: `import x as y`
    даёт зов `y.measure`, а `from x import measure` — зов `measure` без точки.
    Обе формы учтены, и для второй имя входа кладётся прямо в множество зовов.
    """
    aliases, direct = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == SUMMARY_MODULE or a.name.endswith("." + SUMMARY_MODULE):
                    aliases.add((a.asname or a.name).split(".")[0]
                                if a.asname else a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == SUMMARY_MODULE or mod.endswith("." + SUMMARY_MODULE):
                for a in node.names:
                    if a.name in SUMMARY_ENTRIES:
                        direct.add(a.asname or a.name)
    return aliases, direct


def summary_call_state(source: str) -> tuple:
    """Зовёт ли этот исходник сводку. Возвращает (исход, пояснение).

    **Импорт не есть вызов.** Разделение существует затем, что храповик
    неподключённых скриптов считает проводкой любую ссылку: один импорт ради
    чужого правила делает сироту «подключённой», и сторож замолкает при живой
    дыре. Здесь молчания нет — `imports_only` называется вслух.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return SOURCE_UNREADABLE, f"исходник не разобран: {exc}"
    aliases, direct = _summary_aliases(tree)
    if not aliases and not direct:
        return NO_REFERENCE, "ссылки на модуль сводки в исходнике нет"
    called = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Attribute) and func.attr in SUMMARY_ENTRIES
                and isinstance(func.value, ast.Name) and func.value.id in aliases):
            called.append(f"{func.value.id}.{func.attr}")
        elif isinstance(func, ast.Name) and func.id in direct:
            called.append(func.id)
    if called:
        return CALLS, "сводка снимается зовом " + ", ".join(sorted(set(called)))
    names = ", ".join(sorted(aliases | direct))
    return IMPORTS_ONLY, (f"модуль сводки связан именем {names} и НЕ позван: ни "
                          f"одного зова {', '.join(SUMMARY_ENTRIES)}. Импорт не есть "
                          f"вызов, и храповик проводки этой разницы не видит")


def _tally_declared(node) -> bool:
    """Объявляет ли документ СЧЁТ по словарю вердиктов.

    Счёт — отображение «вердикт → число», и ключей из словаря в нём не меньше
    двух: одного ключа мало, он может оказаться чужим совпадением имени.
    """
    if isinstance(node, dict):
        keys = [k for k in node if k in VERDICT_VOCABULARY
                and isinstance(node.get(k), (int, float))
                and not isinstance(node.get(k), bool)]
        if len(keys) >= 2:
            return True
        return any(_tally_declared(v) for v in node.values())
    if isinstance(node, list):
        return any(_tally_declared(v) for v in node)
    return False


def _verdict_values(node) -> bool:
    """Встречается ли в документе ЗНАЧЕНИЕ из словаря вердиктов.

    Спрашивается о значении, а не о присутствии слова в тексте: имя поля
    `unmeasured` у чужого счёта словарём вердиктов не является.
    """
    if isinstance(node, dict):
        return any(_verdict_values(v) for v in node.values())
    if isinstance(node, list):
        return any(_verdict_values(v) for v in node)
    return isinstance(node, str) and node in VERDICT_VOCABULARY


def _artifact_state(path: Path, criteria) -> tuple:
    """Доходит ли ТАЛЛИ §49 до читателя этим артефактом.

    `artifact_absent` — ТРЕТИЙ исход, а не «не несёт»: объявленный и ни разу не
    произведённый артефакт есть другое положение дел, и чинится оно пуском
    производителя, а не правкой его схемы.
    """
    if not path.is_file():
        return ARTIFACT_ABSENT, f"артефакта {path.name} в каталоге данных нет"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return ARTIFACT_UNREADABLE, f"{path.name} не прочитан: {type(exc).__name__}"
    blob = json.dumps(doc, ensure_ascii=False)
    named = [c for c in criteria if c and c in blob]
    if not named:
        return NAMES_NO_CRITERION, (f"{path.name} не называет ни одного критерия "
                                    f"§49 — вердикта о них в нём нет")
    if _tally_declared(doc):
        return CARRIES_TALLY, (f"{path.name} объявляет счёт по словарю вердиктов — "
                               f"таллии можно ПРОЧЕСТЬ, а не вывести")
    if _verdict_values(doc):
        return CARRIES_VERDICTS_ONLY, (
            f"{path.name} несёт построчные вердикты критери(я/ев) {len(named)} и НЕ "
            f"объявляет счёта: читателю пришлось бы складывать их самому, то есть "
            f"завести ВТОРУЮ копию мерки")
    return CARRIES_VERDICTS_ONLY, (
        f"{path.name} называет критери(й/ев) {len(named)} и ни одного значения из "
        f"словаря вердиктов — о выполнении критериев он не говорит")


def callers(repo_root: str, *, data_dir: str, criteria,
            stages: Optional[dict] = None, manifest: Optional[dict] = None) -> dict:
    """Кто сегодня зовёт сводку, с каким объявленным тактом и что доносит.

    Население ОБЪЯВЛЕНО составом ступеней моста (ADR-158), а не найдено обходом
    диска: угаданный зовущий отвечал бы на вопрос, которого никто не задавал.
    """
    if stages is None:
        try:
            from spa_core.monitoring import findings_bridge  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            raise Unmeasured(
                f"состав ступеней моста не прочитан ({type(exc).__name__}: {exc}) — "
                f"население зовущих НЕ ИЗМЕРЕНО") from exc
        stages = dict(findings_bridge.CENSUS_PRODUCT)
    if manifest is None:
        try:
            manifest = price_meter.read_manifest(repo_root)
        except price_meter.Unmeasured as exc:
            raise Unmeasured(f"такты зовущих не измерены: {exc}") from exc
    slo_by_path = {}
    for entry in manifest.get("artifacts") or ():
        path = entry.get("path")
        if path:
            slo_by_path[str(path)] = observed(entry, "slo_hours", kind=(int, float))

    rows = []
    for stage, product in sorted(stages.items()):
        module_rel = str(product.get("module") or "")
        src_path = Path(repo_root) / module_rel
        if not src_path.is_file():
            rows.append({"stage": stage, "module": module_rel,
                         "state": SOURCE_UNREADABLE,
                         "why": f"модуля ступени {module_rel} в дереве нет",
                         "artifact": product.get("artifact"),
                         "slo_hours": None, "carries": None, "carries_why": None})
            continue
        try:
            source = src_path.read_text(encoding="utf-8")
        except OSError as exc:
            rows.append({"stage": stage, "module": module_rel,
                         "state": SOURCE_UNREADABLE,
                         "why": f"{module_rel} не прочитан: {type(exc).__name__}",
                         "artifact": product.get("artifact"),
                         "slo_hours": None, "carries": None, "carries_why": None})
            continue
        state, why = summary_call_state(source)
        if state == NO_REFERENCE:
            continue
        artifact_rel = str(product.get("artifact") or "")
        row = {"stage": stage, "module": module_rel, "state": state, "why": why,
               "artifact": artifact_rel,
               "slo_hours": slo_by_path.get(artifact_rel),
               "carries": None, "carries_why": None}
        if state == CALLS and artifact_rel:
            row["carries"], row["carries_why"] = _artifact_state(
                Path(data_dir) / Path(artifact_rel).name, criteria)
        rows.append(row)
    return {"rows": rows,
            "calling": [r for r in rows if r["state"] == CALLS],
            "imports_only": [r for r in rows if r["state"] == IMPORTS_ONLY]}


# ─────────────────────────── сводный замер ───────────────────────────

def measure(repo_root: str | Path = _REPO_ROOT, *, data_dir: Optional[str] = None,
            measure_tree: Optional[str] = None, ref: str = "origin/main",
            rollup=None, stages: Optional[dict] = None, now=None,
            clock: Callable[[], float] = time.monotonic, **kw) -> dict:
    """Снять сводку §49, измерить её такт-пол и назвать зовущих.

    `rollup` подменяем намеренно и разрешается В МОМЕНТ ЗОВА: умолчание в
    сигнатуре связывается при ОПРЕДЕЛЕНИИ функции, и контроль, думающий, что
    подменил сводку, мерил бы настоящую (зелёный по построению, урок ADR-505).
    """
    if rollup is None:
        import cio_acceptance_rollup as rollup  # noqa: PLC0415
    root = str(repo_root)
    tree = measure_tree or root
    data = data_dir or os.path.join(tree, "data")

    started = clock()
    try:
        report = rollup.measure(root, ref=ref, measure_tree=tree,
                               data_dir=data_dir, **kw)
    except rollup.Unmeasured as exc:
        raise Unmeasured(f"сводка §49 не снята: {exc}") from exc
    cost_s = round(clock() - started, 3)

    criteria = [r.get("criterion") for r in report.get("rows") or ()]
    floor = tact_floor(criteria, repo_root=root)
    who = callers(root, data_dir=data, criteria=criteria, stages=stages)

    with_tact = [r for r in who["calling"]
                 if isinstance(r.get("slo_hours"), (int, float))]
    served = [r for r in with_tact if float(r["slo_hours"]) <= floor["floor_hours"]]
    if not who["calling"]:
        verdict = NO_CALLER_AT_ALL
        gap = None
        fastest = None
    elif served:
        verdict = FLOOR_SERVED
        gap = None
        fastest = min(served, key=lambda r: float(r["slo_hours"]))["stage"]
    elif with_tact:
        verdict = CALLERS_SLOWER_THAN_FLOOR
        best = min(with_tact, key=lambda r: float(r["slo_hours"]))
        gap = round(float(best["slo_hours"]) / floor["floor_hours"], 2)
        fastest = best["stage"]
    else:
        raise Unmeasured(
            "сводку зовут, но ни у одного зовущего не объявлен `slo_hours` — "
            "такт зовущих НЕ ИЗМЕРЕН, и выдать это за «такт в порядке» нельзя: "
            + " · ".join(f"{r['stage']} ({r['artifact']})" for r in who["calling"]))

    # `or {}` читалось сторожем инв. #17 как подстановка наблюдения. Поведение
    # не меняется (отсутствие счёта и так доходит до читателя как `None` в
    # каждом поле ТАЛЛИ), но форма перестаёт быть подстановкой.
    _counts = observed(report, "counts", kind=dict)
    tally = dict(_counts) if _counts is not None else {}
    findings = sum((
        1 if verdict != FLOOR_SERVED else 0,
        sum(1 for r in who["calling"] if r.get("carries") != CARRIES_TALLY),
        len(who["imports_only"]),
    ))
    return {"status": "OK", "generated_at": _stamp_now(now),
            "measure_tree": tree, "data_dir": data,
            "population": report.get("population"),
            "tally": {"satisfied": tally.get(SATISFIED),
                      "not_satisfied": tally.get(NOT_SATISFIED),
                      "unmeasured": tally.get(UNMEASURED)},
            "tally_rows": [{"criterion": r.get("criterion"), "probe": r.get("probe"),
                            "verdict": r.get("verdict")}
                           for r in report.get("rows") or ()],
            "tally_cost_s": cost_s,
            "tact_floor_hours": floor["floor_hours"],
            "tact_floor_set_by": floor["floor_set_by"],
            "tact_floor_input": floor["floor_input"],
            "tact_floor_counts": floor["counts"],
            "tact_rows": floor["rows"],
            "caller_rows": who["rows"],
            "callers_calling": [r["stage"] for r in who["calling"]],
            "callers_imports_only": [r["stage"] for r in who["imports_only"]],
            "fastest_caller": fastest,
            "gap_ratio": gap,
            "verdict": verdict,
            "findings": findings}


def run(root: str | Path = _REPO_ROOT, *, data_dir: Optional[Path] = None,
        dest: Optional[Path] = None, write: bool = True, if_due: bool = True,
        now=None, tact_days: float = MEASUREMENT_TACT_DAYS, **kw) -> dict:
    """Один ТАКТ замера для ступени моста (`findings_bridge.CENSUS_STAGE`).

    **«Не мерили» и «измерено» — РАЗНЫЕ исходы** (инв. #17): внутри такта
    возвращается ``{"measured": False, "reason": …}``, а не выдуманный вердикт.

    Гейт такта НЕ копируется — он взят у соседа (`python_reader_clock_doors`),
    который его уже меряет: две копии одной мерки расходятся молча (ADR-220).
    """
    root = Path(root)
    source = Path(data_dir) if data_dir is not None else root / "data"
    target = Path(dest) if dest is not None else source / ARTIFACT
    if if_due:
        from spa_core.monitoring.python_reader_clock_doors import measurement_due
        due, why = measurement_due(target, now=now, tact_days=tact_days)
        if not due:
            return {"measured": False, "reason": why, "artifact": str(target)}
    try:
        doc = measure(root, data_dir=str(source), now=now, **kw)
    except Unmeasured as exc:
        # Отметка стои́т и у ОТКАЗА: иначе один отказ делал бы такт нечитаемым
        # навсегда — «не смогли прочитать, когда мерили» означает «мерим», и
        # ступень пошла бы каждый тик моста до конца времён.
        doc = {"status": "UNMEASURED", "reason": str(exc),
               "generated_at": _stamp_now(now)}
    if write:
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(doc, str(target))
    return {"measured": True, "doc": doc, "artifact": str(target)}


def report(doc: dict, max_rows: int = 20) -> list:
    """Отрисовка для шага 0-офис. Делегирована ПРОИЗВОДИТЕЛЮ (ADR-158)."""
    lines: list = []
    if str(doc.get("status")) != "OK":
        lines.append(f"НЕ ИЗМЕРЕНО: {doc.get('reason', 'причина не названа')}")
        lines.append("  про такт сводки §49 НЕ СКАЗАНО НИЧЕГО — выдать это за "
                     "«такт в порядке» нельзя")
        return lines
    tally = observed(doc, "tally", kind=dict) or {}
    def _num(key):
        value = tally.get(key)
        return "НЕ ИЗМЕРЕНО" if not isinstance(value, (int, float)) else int(value)
    lines.append(
        f"Такт сводки §49 (заказ G93 п. 3): ТАЛЛИ — ВЫПОЛНЕНО {_num('satisfied')} · "
        f"НЕ ВЫПОЛНЕНО {_num('not_satisfied')} · НЕ ИЗМЕРЕНО {_num('unmeasured')} "
        f"из {doc.get('population')}")
    floor = observed(doc, "tact_floor_hours", kind=(int, float))
    lines.append(
        f"  такт-пол {'НЕ ИЗМЕРЕН' if floor is None else f'{float(floor):g} ч'}"
        f" (ставит {doc.get('tact_floor_set_by')} через {doc.get('tact_floor_input')})"
        f"; прогон сводки {doc.get('tally_cost_s')} с")
    verdict = str(doc.get("verdict") or "")
    lines.append(f"  ОТВЕТ: {VERDICT_RU.get(verdict, verdict)}"
                 + (f" — быстрейший {doc.get('fastest_caller')}, медленнее пола "
                    f"в {doc.get('gap_ratio')}×" if doc.get("gap_ratio") else ""))
    counts = observed(doc, "tact_floor_counts", kind=dict) or {}
    lines.append("  критерии по вкладу в пол: "
                 + " · ".join(f"{k} {counts.get(k, 0)}"
                              for k in (TACT_BOUND, TACT_BOUND_WITHOUT_SLO,
                                        TACT_UNBOUND)))
    shown = 0
    for row in doc.get("caller_rows") or ():
        if shown >= max_rows:
            break
        if row.get("state") == IMPORTS_ONLY:
            lines.append(f"  [{IMPORTS_ONLY}] {row['stage']} — {row['why']}")
            shown += 1
        elif row.get("state") == CALLS and row.get("carries") != CARRIES_TALLY:
            lines.append(f"  [{row.get('carries')}] {row['stage']} "
                         f"(такт {row.get('slo_hours')} ч) — {row.get('carries_why')}")
            shown += 1
    lines.append("  НЕ ДОКЛАДЫВАЕТ: наблюдённый период бегуна (сравниваются "
                 "ОБЪЯВЛЕННЫЕ такты; ADR-506 измерил, что они расходятся по "
                 "построению) · верность самой пробы · зовущего вне состава ступеней")
    lines.append("  ADVISORY: прибор только ЧИТАЕТ (applied=False)")
    return lines


def format_report(doc: dict, max_rows: int = 10) -> list:
    """Отрисовка для шага 0-офис. Правило отрисовки живёт У ПРОИЗВОДИТЕЛЯ — вторая
    копия у читателя разошлась бы с ним молча (ADR-220)."""
    head = ["— такт сводки §49 приказа «Portfolio CIO» (ADR-547) —"]
    return head + ["   " + line for line in report(doc, max_rows=max_rows)]


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--repo-root", default=str(_REPO_ROOT))
    ap.add_argument("--data-dir", default=None,
                    help="каталог артефактов (умолчание — <repo-root>/data)")
    ap.add_argument("--measure-tree", default=None,
                    help="дерево, О КОТОРОМ выносится вердикт сводки")
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--if-due", action="store_true",
                    help=f"мерить, только если с прошлого замера прошло "
                         f"{MEASUREMENT_TACT_DAYS * 24:g} ч")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    outcome = run(args.repo_root, data_dir=(Path(args.data_dir) if args.data_dir
                                            else None),
                  write=not args.no_write, if_due=args.if_due,
                  measure_tree=args.measure_tree, ref=args.ref)
    if not outcome.get("measured"):
        print(f"внутри такта, НЕ мерили — {outcome.get('reason')}")
        return 0
    doc = outcome["doc"]
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print("\n".join(report(doc)))
    if str(doc.get("status")) != "OK":
        return 2
    return 1 if int(doc.get("findings") or 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
