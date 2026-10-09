"""Меняет ли расширение населения сам вердикт §49 — ЗАПИСЬЮ прогона, не теорией.

Заказ **G107 п. 1** (поставлен ADR-529, лежал остатком с 01.10) звучит дословно:

> **983 пары — это поправка к ВЕРДИКТУ критерия §49, и её никто не применил.**
> Прибор назвал дороги; вердикт ``no_regression_census`` по-прежнему судит об
> исходе 129 пар и звучит при этом утверждением обо всех. Спросить прямо:
> сколько из 983 упали бы в последнем прогоне, то есть **меняет ли расширение
> населения сам вердикт**. Исход мерить ЗАПИСЬЮ прогона (она теперь переживает
> раннер, ADR-528), а не теорией; расширять население соседа замером ЗАПРЕЩЕНО —
> это отдельное решение, потому что сдвигает вердикт критерия владельца.

## Почему это не повторение двух соседей

ADR-529 (``membership_reach_census``) ответил на вопрос «СКОЛЬКО дорог правило
не видит» — и остановился ровно там, где начинается цена: дорога названа, а что
с ней стало в прогоне, не спросил никто. ADR-528 отвечает на «переживает ли
запись раннер». Здесь вопрос третий и свой: **стоит ли за найденными дорогами
хоть одна настоящая поломка**, то есть является ли слепота правила вредом или
только свойством. Ответ на него нельзя вывести из двух предыдущих: дорога без
поломки вреда не несёт, поломка без дороги вердиктом не ловится.

## Что подаётся ВХОДОМ, а не спрашивается у окружения

* **запись прогона** (``--record``, можно несколько). Прибор pytest не
  запускает: так он проверяется фикстурой, остаётся read-only и не зависит от
  того, чем занят хост. Записи не подано ⇒ ищется в объявленном каталоге
  ``reports/`` (тот же, который объявляют оба воркфлоу — одна копия пути), и его
  пустота есть **третий исход с названной причиной**, а не «чисто»;
* **дерево** (``--root``). Дерево и запись обязаны быть ОДНИМ срезом: тест,
  родившийся позже записи, иначе читается как «не дошёл до вердикта». Прибор
  этого не выдумывает — он печатает ЧИСЛА связи (сколько файлов записи нет в
  дереве, сколько тестов дерева нет в записи) и ``hostname``/``timestamp``,
  которые pytest написал сам;
* **предел глубины** (``--max-depth``) — ВЫБОР соседа, а не свойство дерева;
* **предел цены** (``--price-depth``) — до какой глубины мерить ЦЕНУ предела.

## Две оси, оба перечня ЗАКРЫТЫ (инв. #17)

**Ось члена ДОБАВЛЕННОГО населения** (сумма равна числу добавленных пар):

* ``failed_in_the_record`` — **НАХОДКА**: пара, которой правило не видит, в
  настоящем прогоне УПАЛА. Вердикт §49 об её исходе не говорит ничего;
* ``passed_in_the_record`` — зелена;
* ``absent_from_the_record`` — третий исход: члена в записи нет вовсе;
* ``all_cases_skipped`` — третий исход: все случаи пропущены, исход не наблюдён.

Два последних различаются МАШИННО (``no_regression_census.ABSENT_FROM_RECORD`` /
``ALL_CASES_SKIPPED``), а не по прозе строки: разбирать исход подстрокой
запрещено (ADR-333), а чинятся они в разных местах.

**Ось ВЕРДИКТА** — по каждой объявленной поверхности и по критерию целиком:

* ``verdict_label_unchanged`` — ярлык тот же;
* ``verdict_label_changes`` — ярлык ДРУГОЙ, и направление названо.

Ярлык целиком и ярлык поверхности — РАЗНЫЕ вопросы, и мерить только первый
значило бы потерять находку: одна красная поверхность делает ярлык критерия
``REGRESSION`` независимо от того, что происходит с двумя остальными.

## Правило вердикта ОДНО, и население соседа не тронуто

Вердикт считает ``no_regression_census.judge`` — та самая функция, которой
считает себя сам критерий (вынесена из его ``measure`` одной копией, ADR-522).
Дороги даёт ``membership_reach_census``. Прибор не добавляет ни одной своей
мерки: он лишь прикладывает ЧУЖУЮ мерку к ДРУГОМУ населению и печатает разницу.
Население самого критерия при этом не расширяется — это отдельное решение
(предмет №2 границы ADR-285: вердикт критерия владельца).

## ADVISORY

Прибор только ЧИТАЕТ: pytest не запускает, тестов не правит и не ослабляет
(инв. #16); RiskPolicy v1.0, стоп-кран, аллокатор, гейт исполнения, живой трек,
``landing/**`` и флот не трогаются. LLM запрещён (инв. #3). Ввозы — только
stdlib (инв. #4). Артефакта НАМЕРЕННО не производит (ADR-524, та же причина, что
у ADR-529): читатель — шаг 0-офис. Часов, pid, сети и git-окружения не
спрашивает: входов ровно два — путь дерева и путь записи.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

from spa_core.monitoring import membership_reach_census as reach
from spa_core.monitoring.no_regression_census import (
    ABSENT_FROM_RECORD,
    ALL_CASES_SKIPPED,
    UNMEASURED,
    judge,
    population as census_population,
    read_record,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Каталог записи — тот же, который объявляют ОБА воркфлоу (`--junitxml=reports/…`
#: в `test.yml` и `ci.yml`). Одна копия пути: второй разошёлся бы с воркфлоу молча
#: и прибор доложил бы «записи нет» на дереве, где она лежит.
RECORD_DIR = "reports"
RECORD_GLOB = "junit-*.xml"

# ── ось члена ДОБАВЛЕННОГО населения. Перечень ЗАКРЫТ: сумма = число пар ──────
FAILED = "failed_in_the_record"
PASSED = "passed_in_the_record"

OUTCOMES: tuple[str, ...] = (FAILED, PASSED, ABSENT_FROM_RECORD, ALL_CASES_SKIPPED)

# ── ось ВЕРДИКТА ─────────────────────────────────────────────────────────────
SAME = "verdict_label_unchanged"
CHANGED = "verdict_label_changes"


def find_records(repo_root: str = REPO_ROOT) -> tuple[list[str], str]:
    """Записи прогона в объявленном каталоге + причина, если их нет.

    Причина возвращается ВСЕГДА вместе со списком: «записей нет» без причины
    неотличимо от «каталога нет», а чинятся они в разных местах — первое
    прогоном, второе тем, что запись с хоста никто не держит (заказы G106/G150).
    """
    base = pathlib.Path(repo_root) / RECORD_DIR
    if not base.is_dir():
        return [], (f"каталога записи `{RECORD_DIR}/` в дереве нет: запись прогона "
                    "на хосте не держит никто, а §49 измеряется ТОЛЬКО записью")
    found = sorted(p.as_posix() for p in base.glob(RECORD_GLOB))
    if not found:
        return [], (f"каталог `{RECORD_DIR}/` есть, но ни одного файла "
                    f"`{RECORD_GLOB}` в нём нет")
    return found, ""


def _binding(repo_root: str, record: dict, tests: list[str]) -> dict:
    """ЧИСЛА связи записи с деревом. Происхождение записи НЕ выдумывается.

    Прибор не вправе утверждать, что запись снята на ЭТОМ дереве, — это сказал бы
    тот, кто её подал. Зато он вправе измерить СОГЛАСИЕ, и у него ДВЕ стороны:

    * **со стороны дерева** — тест дерева, которого в записи нет вовсе;
    * **со стороны записи** — случай, которому файла в ЭТОМ дереве не нашлось.
      Поля «файл записи, которого нет в дереве» здесь НЕТ намеренно, и это
      найдено контролем, а не рассуждением: ``_file_of_case`` соседа привязывает
      случай к файлу ПО СУЩЕСТВОВАНИЮ файла, поэтому случай из чужого срезa в
      ``record["files"]`` не попадает ВОВСЕ — он попадает в
      ``cases_without_file``. Поле, пустое по построению, было бы ложным
      успокоением: оно всегда зелено и ни о чём не говорит.

    Оба числа растут ровно тогда, когда дерево и запись разъехались срезом.
    """
    in_record = set(record["files"])
    return {
        "record_files": len(in_record),
        "tree_tests": len(tests),
        "tree_tests_absent_from_record": sorted(set(tests) - in_record),
        "cases_without_file": record["cases_without_file"],
        "records_meta": record["records_meta"],
    }


def _outcome_of(rel: str, record: dict) -> str:
    """Исход ОДНОГО файла по записи — спрошенный у ЧУЖОЙ мерки, а не свой.

    Своя копия классификации («есть `bad` ⇒ упал») разошлась бы с вердиктом
    критерия при первой же правке соседа, поэтому исход одного файла берётся у
    ``judge`` — той же функции, которой считает себя сам критерий.
    """
    one = judge({"_": [rel]}, record)
    if one["failed"]:
        return FAILED
    if one["unmeasured_members"]:
        return one["unmeasured_members"][0]["kind"]
    return PASSED


def _added_pairs(findings: list[dict]) -> dict[str, list[str]]:
    """Добавленное население по поверхностям: ``{поверхность: [файлы]}``."""
    out: dict[str, set[str]] = {}
    for row in findings:
        out.setdefault(row["surface"], set()).add(row["file"])
    return {surface: sorted(files) for surface, files in out.items()}


def measure(repo_root: str = REPO_ROOT, records: list[str] | None = None,
            max_depth: int = reach.MAX_DEPTH,
            price_depth: int | None = None,
            graph: dict | None = None) -> dict:
    """Разница вердикта §49 между объявленным населением и расширенным."""
    base = {
        "repo_root": repo_root,
        "max_depth": max_depth,
        "price_depth": price_depth,
        "records": [],
        "record_search_reason": "",
    }
    if records is None:
        records, why = find_records(repo_root)
        base["record_search_reason"] = why
    if not records:
        return {**base, "measured": False,
                "unmeasured_reason": base["record_search_reason"]
                or "записи прогона не подано, а искать её не просили"}
    base["records"] = list(records)

    record = read_record(list(records), repo_root=repo_root)
    if not record["records_read"]:
        why = "; ".join(f"{u['record']} — {u['reason']}"
                        for u in record["records_unread"]) or "запись не прочитана"
        return {**base, "measured": False,
                "unmeasured_reason": f"ни одна запись прогона не прочитана: {why}"}
    base["records_read"] = record["records_read"]
    base["records_unread"] = record["records_unread"]

    try:
        graph = graph if graph is not None else reach.build_graph(repo_root)
    except reach.Unmeasured as exc:
        return {**base, "measured": False,
                "unmeasured_reason": f"граф импортов не построен: {exc}"}

    narrow = reach.measure(repo_root, max_depth=max_depth, graph=graph)
    if narrow.get("unmeasured_reason") or not narrow.get("population"):
        return {**base, "measured": False,
                "unmeasured_reason": ("дороги не измерены: "
                                      + (narrow.get("unmeasured_reason")
                                         or "население пар ПУСТО — ноль исходов на "
                                            "пустом населении не есть «чисто»"))}

    pop = census_population(repo_root)
    declared = {name: list(spec["files"]) for name, spec in pop["surfaces"].items()}
    added = _added_pairs(narrow["findings"])
    for name in declared:
        added.setdefault(name, [])
    if not sum(len(files) for files in added.values()):
        return {**base, "measured": False,
                "unmeasured_reason": "правило не слепо ни на одной паре: добавлять "
                                     "к населению нечего, и вердикт сдвинуть нечем"}

    # Пересечение обязано быть ПУСТЫМ по построению (находкой объявляется только
    # пара, которой правило НЕ видит). Измеряется, а не предполагается: непустое
    # пересечение означало бы, что добавленное население считает одного члена
    # дважды, и тогда «ярлык сменился» могло бы быть следствием двойного счёта.
    overlap = sorted(f"{name}::{rel}" for name, files in added.items()
                     for rel in files if rel in set(declared.get(name, ())))

    widened = {name: sorted(set(declared.get(name, ())) | set(added.get(name, ())))
               for name in set(declared) | set(added)}

    judged_declared = judge(declared, record)
    judged_widened = judge(widened, record)

    counts = {name: 0 for name in OUTCOMES}
    findings: list[dict] = []
    outcome_cache: dict[str, str] = {}
    for row in narrow["findings"]:
        rel = row["file"]
        if rel not in outcome_cache:
            outcome_cache[rel] = _outcome_of(rel, record)
        outcome = outcome_cache[rel]
        counts[outcome] += 1
        if outcome == FAILED:
            findings.append({"file": rel, "surface": row["surface"],
                             "depth": row["depth"], "chain": row["chain"]})

    per_surface: dict[str, dict] = {}
    for name in sorted(widened):
        before = judged_declared["verdict_by_surface"].get(name, UNMEASURED)
        after = judged_widened["verdict_by_surface"].get(name, UNMEASURED)
        per_surface[name] = {
            "population_declared": len(declared.get(name, ())),
            "population_added": len(added.get(name, ())),
            "verdict_declared": before,
            "verdict_widened": after,
            "shift": SAME if before == after else CHANGED,
            "failed_added": sorted({row["file"] for row in findings
                                    if row["surface"] == name}),
        }

    failed_declared = {row["file"] for row in judged_declared["failed"]}
    failed_widened = {row["file"] for row in judged_widened["failed"]}

    price = _price_of_the_limit(repo_root, graph, narrow, record, max_depth,
                               price_depth)

    tests, _unparsed, _outside = reach._test_files(repo_root, graph)
    return {
        **base,
        "measured": True,
        "unmeasured_reason": "",
        "pairs_declared": sum(len(f) for f in declared.values()),
        "pairs_added": sum(len(f) for f in added.values()),
        "counts": counts,
        "findings": sorted(findings, key=lambda r: (r["surface"], r["file"])),
        "per_surface": per_surface,
        "verdict_declared": judged_declared["verdict"],
        "verdict_widened": judged_widened["verdict"],
        "shift": (SAME if judged_declared["verdict"] == judged_widened["verdict"]
                  else CHANGED),
        "surfaces_changed": sorted(name for name, row in per_surface.items()
                                   if row["shift"] == CHANGED),
        "files_failed_declared": sorted(failed_declared),
        "files_failed_added_only": sorted(failed_widened - failed_declared),
        "files_failed_widened": len(failed_widened),
        "overlap": overlap,
        "lower_bound_prices": {
            "pairs_beyond_depth": narrow["counts"][reach.BEYOND],
            "name_outside_tree": narrow["name_counts"].get(reach.NAME_OUTSIDE, 0),
            "name_unresolved": narrow["name_counts"].get(reach.NAME_UNRESOLVED, 0),
        },
        "price_of_the_limit": price,
        "binding": _binding(repo_root, record, tests),
    }


def _price_of_the_limit(repo_root: str, graph: dict, narrow: dict, record: dict,
                        max_depth: int, price_depth: int | None) -> dict:
    """Цена предела глубины — ИЗМЕРЕННАЯ, а не названная числом пар.

    ``reached_beyond_declared_depth`` говорит, сколько пар предел отрезал. Чего
    стоит отрез, видно только по записи: отрезанная пара, которая в прогоне
    УПАЛА, есть ровно та поломка, о которой вердикт молчит дважды — и правилом,
    и пределом. Предел подаётся ВХОДОМ, поэтому цена мерится ТЕМ ЖЕ прибором
    соседа с другим входом, а не второй копией обхода.
    """
    if price_depth is None:
        return {"state": "not_asked",
                "why": "предел цены не подан (`--price-depth`): цена предела "
                       "глубины НЕ измерена, и ноль здесь не печатается"}
    if price_depth <= max_depth:
        return {"state": "unmeasured",
                "why": f"предел цены {price_depth} не больше предела находок "
                       f"{max_depth} — мерить нечего"}
    wide = reach.measure(repo_root, max_depth=price_depth, graph=graph)
    if wide.get("unmeasured_reason") or not wide.get("population"):
        return {"state": "unmeasured",
                "why": wide.get("unmeasured_reason") or "население пар ПУСТО"}
    near = {(row["file"], row["surface"]) for row in narrow["findings"]}
    beyond = [row for row in wide["findings"]
              if (row["file"], row["surface"]) not in near]
    counts = {name: 0 for name in OUTCOMES}
    failed: list[dict] = []
    cache: dict[str, str] = {}
    for row in beyond:
        rel = row["file"]
        if rel not in cache:
            cache[rel] = _outcome_of(rel, record)
        counts[cache[rel]] += 1
        if cache[rel] == FAILED:
            failed.append({"file": rel, "surface": row["surface"],
                           "depth": row["depth"]})
    return {"state": "measured", "price_depth": price_depth,
            "pairs": len(beyond), "counts": counts,
            "failed": sorted(failed, key=lambda r: (r["surface"], r["file"]))}


def verdict(doc: dict) -> str:
    if not doc.get("measured"):
        return "unmeasured"
    if doc["surfaces_changed"] or doc["shift"] == CHANGED:
        return "the_extension_changes_the_verdict"
    if doc["counts"][FAILED]:
        return "the_extension_adds_failures_without_changing_a_label"
    return "the_extension_changes_nothing"


def format_report(doc: dict) -> str:
    """Отчёт для шага 0-офис. Каждый ноль объявлен (инв. #17)."""
    if not doc.get("measured"):
        return ("НЕ ИЗМЕРЕНО: меняет ли расширение населения вердикт §49 — "
                f"{doc.get('unmeasured_reason')}")
    counts = doc["counts"]
    lines = [
        f"меняет ли расширение населения вердикт §49 (заказ G107 п. 1): "
        f"объявленное население {doc['pairs_declared']} пар(ы), добавляется "
        f"{doc['pairs_added']} (дороги через помощника, предел {doc['max_depth']}); "
        f"запись(и) прогона: {', '.join(doc['records_read'])}",
        "  " + " · ".join(f"{name} {counts[name]}" for name in OUTCOMES),
    ]
    lines.append(f"  ОТВЕТ заказа: ярлык критерия {doc['verdict_declared']} → "
                 f"{doc['verdict_widened']} ({doc['shift']}); поверхностей сменило "
                 f"ярлык {len(doc['surfaces_changed'])} из {len(doc['per_surface'])}"
                 + (": " + ", ".join(doc["surfaces_changed"])
                    if doc["surfaces_changed"] else ""))
    for name, row in sorted(doc["per_surface"].items()):
        lines.append(f"  [{row['shift']}] {name}: население {row['population_declared']}"
                     f" + {row['population_added']} ⇒ {row['verdict_declared']} → "
                     f"{row['verdict_widened']}"
                     + (f"; упало добавленных файлов {len(row['failed_added'])}"
                        if row["failed_added"] else ""))
    lines.append(f"  поломка СЧЁТОМ ФАЙЛОВ: правило видит "
                 f"{len(doc['files_failed_declared'])} из "
                 f"{doc['files_failed_widened']}; не видит "
                 f"{len(doc['files_failed_added_only'])}")
    for row in doc["findings"][:12]:
        lines.append(f"  [{FAILED}] {row['file']} → {row['surface']} "
                     f"(глубина {row['depth']}): " + " → ".join(row["chain"]))
    if len(doc["findings"]) > 12:
        lines.append(f"  … ещё {len(doc['findings']) - 12} находок(и) того же вида "
                     "(полный перечень — `--json`)")
    if doc["overlap"]:
        lines.append(f"  [НЕ ИЗМЕРЕНО] добавленное население пересекается с "
                     f"объявленным на {len(doc['overlap'])} пар(е/ах) — член "
                     "посчитан дважды: " + " · ".join(doc["overlap"][:5]))
    b = doc["binding"]
    lines.append(f"  связь записи с деревом: файлов записи {b['record_files']} · "
                 f"тестов дерева {b['tree_tests']}, из них нет в записи "
                 f"{len(b['tree_tests_absent_from_record'])} · случаев, которым "
                 f"файла в ЭТОМ дереве не нашлось, {b['cases_without_file']}"
                 + (" · запись снята: " + ", ".join(
                     f"{m.get('hostname') or 'хост НЕ НАЗВАН'}@"
                     f"{m.get('timestamp') or 'время НЕ НАЗВАНО'}"
                     for m in b["records_meta"][:3]) if b["records_meta"] else ""))
    price = doc["price_of_the_limit"]
    if price["state"] == "measured":
        lines.append(f"  ЦЕНА ПРЕДЕЛА (глубина {doc['max_depth']} → "
                     f"{price['price_depth']}): пар {price['pairs']}, из них упало "
                     f"{price['counts'][FAILED]}"
                     + (": " + ", ".join(f"{r['file']}→{r['surface']}"
                                         for r in price["failed"][:5])
                        if price["failed"] else ""))
    else:
        lines.append(f"  [{'НЕ ИЗМЕРЕНО' if price['state'] == 'unmeasured' else 'НЕ СПРОШЕНО'}]"
                     f" цена предела глубины: {price['why']}")
    p = doc["lower_bound_prices"]
    lines.append(f"  НИЖНЯЯ ГРАНИЦА: {counts[FAILED]} есть нижняя граница, и у неё "
                 f"три названные цены — пар за пределом глубины "
                 f"{p['pairs_beyond_depth']} · имя вне дерева "
                 f"{p['name_outside_tree']} · имя не разрешено {p['name_unresolved']}")
    lines.append("  НЕ ДОКЛАДЫВАЕТ: правоту самих тестов (читается исход, не "
                 "правота) · ТРОГАЕТ ли тест поверхность на самом деле (дорога "
                 "импорта есть достижимость, а не исполнение) · на каком дереве "
                 "снята запись (это говорит тот, кто её подал; прибор печатает "
                 "ЧИСЛА связи) · верность перечня поверхностей (он объявлен соседом)")
    lines.append("  ADVISORY: прибор только ЧИТАЕТ (applied=False); население "
                 "критерия НЕ расширено — это отдельное решение владельца")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Меняет ли расширение населения §49 сам вердикт — измерено "
                    "ЗАПИСЬЮ прогона (заказ G107 п. 1)")
    parser.add_argument("--root", default=REPO_ROOT)
    parser.add_argument("--record", action="append", default=None,
                        help=f"запись прогона (junit). Не подано ⇒ поиск в "
                             f"`{RECORD_DIR}/{RECORD_GLOB}`")
    parser.add_argument("--max-depth", type=int, default=reach.MAX_DEPTH)
    parser.add_argument("--price-depth", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    doc = measure(args.root, records=args.record, max_depth=args.max_depth,
                  price_depth=args.price_depth)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_report(doc))
    return {"unmeasured": 2,
            "the_extension_changes_the_verdict": 1,
            "the_extension_adds_failures_without_changing_a_label": 1,
            "the_extension_changes_nothing": 0}[verdict(doc)]


if __name__ == "__main__":
    sys.exit(main())
