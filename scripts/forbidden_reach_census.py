#!/usr/bin/env python3
"""scripts/forbidden_reach_census.py — правило, видящее ТОЛЬКО прямой импорт.

Вопрос, на который отвечает прибор
----------------------------------
«Сколько файлов рантайм-домена ввозят запрещённую библиотеку ЧЕРЕЗ ПОМОЩНИКА —
то есть так, что прямой сторож (``scripts/lint_forbidden_imports.py``) не видит
этого ни одной своей формой?»

Заказ G107 п. 3 (хвост ADR-529) поставил его дословно: тот же вопрос, который
ADR-529 задал правилу принадлежности §49, не задан ни одному другому правилу
дерева, решающему «входит ли файл в область» по ОДНОМУ своему импорту. Названы
два: ``lint_forbidden_imports`` (инв. #3 и #4) и ``lint_llm_forbidden``
(инв. #3). У обоих область объявлена пятью каталогами, а нарушение — ПРЯМЫМ
импортом в самом файле. Население такого класса не измерено ни разу, и цена
ошибки здесь не «вердикт звучит шире замера», а ПРОПУЩЕННОЕ нарушение
инварианта.

Почему это НЕ вторая копия правила
----------------------------------
Прибор не решает, что запрещено и где: перечень библиотек (``FORBIDDEN``),
перечень доменов (``DOMAINS``) и разбор форм импорта (``scan_source``) берутся
у самого сторожа одной копией. Вторая дверь LLM-сторожа (ЗАПУСК бинаря
подпроцессом) берётся у её единственного владельца —
``spa_core.ci.llm_forbidden_lint.find_llm_subprocess_launches``. Граф импортов
дерева и обход в ширину берутся у ADR-529
(``spa_core.monitoring.membership_reach_census``). Прибор добавляет ровно одно:
ДОРОГУ от файла домена до ввозящего файла.

Две односторонности, и они смотрят в РАЗНЫЕ стороны
---------------------------------------------------
1. **Занижение** — предмет заказа: библиотека, ввезённая через помощника,
   прямому сторожу не видна вовсе. Это ось ``OUTCOMES``.
2. **Завышение** — названное ADR-529 п. 2 словом: «дорога импорта есть
   достижимость, а не исполнение». Здесь она ИЗМЕРЕНА: второй род графа
   (``build_graph(..., module_level_only=True)``) оставляет только импорты
   верхнего уровня без охраны, то есть те, что исполняются САМИМ фактом
   импорта файла. Дорога, которая целиком лежит в таком графе, есть
   ``executed_by_the_import_itself``; любая другая — ``deferred_or_guarded``
   (внутри функции, под ``try/except ImportError``, под ``if TYPE_CHECKING``).
   Без этой оси единственная находка живого дерева читалась бы как нарушение
   инварианта #3, которым она НЕ является.

Перечень исходов ЗАКРЫТ, сумма равна населению (инв. #17)
--------------------------------------------------------
Население — пары «файл домена × запрещённая библиотека». Четыре исхода:

* ``brought_in_directly``        — файл ввозит сам; прямой сторож это ВИДИТ;
* ``brought_in_through_helper``  — НАХОДКА: не ввозит сам, но достигает
  ввозящего файла за 1…``max_depth`` дуг;
* ``reached_beyond_declared_depth`` — достигает, но дальше объявленного
  предела; это ЦЕНА предела, напечатанная рядом, а не «дороги нет»;
* ``not_brought_in``             — не достигает вовсе.

Третий исход
------------
«Не измерено» отделено и от «чисто», и от «находка»: нечитаемый файл дерева,
отсутствующий каталог домена, нулевое население, расхождение обходов (файл
домена, видимый сторожу и не видимый графу) и несовпадение паритета дают код
возврата **2** с НАЗВАННОЙ причиной. Ноль находок при нуле осмотренных пар —
тоже код 2.

Контроль, который прибор несёт сам
----------------------------------
Множество пар ``brought_in_directly`` сверяется с находками САМОГО сторожа
(``lint_forbidden_imports.scan_tree``) — другим обходом и другой функцией.
Сверка прибора с самим собой была бы зелёной по построению (урок #722);
здесь обходы РАЗНЫЕ, и расхождение есть третий исход, а не находка.

Чего прибор НЕ делает (названо, а не умолчано)
----------------------------------------------
* не правит ни одного сторожа и не расширяет его область — это РЕШЕНИЕ
  (вердикт инварианта сдвинулся бы), а прибор только ЧИТАЕТ;
* не утверждает, что дорога исполняется, если её звено охранено, — он это
  РАЗЛИЧАЕТ;
* ось ЗАПУСКА бинаря LLM меряется ТОЛЬКО достижимостью: запуск есть ВЫЗОВ,
  и исполнится ли вызов — вопрос о проводке, а не об импорте. Сказано вслух,
  а не умолчано нулём;
* имя, собранное в рантайме, относительный импорт за пределы дерева и
  подмену ``sys.modules`` третьим лицом прибор не видит — это НИЖНЯЯ граница
  с названной ценой (ось ИМЕНИ графа печатается рядом).

Коды возврата: 0 — дорог через помощника нет · 1 — есть находка ·
2 — НЕ ИЗМЕРЕНО.

Только stdlib. LLM_FORBIDDEN — это разбор синтаксиса, не суждение.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import json
import os
import pathlib
import sys

# launchd/CI зовут скрипт ПО ПУТИ: `sys.path[0]` — каталог `scripts/`, поэтому
# корень репозитория добавляется явно (класс ADR-347 / ADR-370).
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_SCRIPTS_DIR)
for _p in (REPO_ROOT, _SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lint_forbidden_imports as linter  # noqa: E402  — ОДНА копия правила
from spa_core.utils.atomic import atomic_save  # noqa: E402  — инв. #5
from spa_core.monitoring.membership_reach_census import (  # noqa: E402
    MAX_DEPTH,
    Unmeasured,
    _chain,
    build_graph,
    reverse_bfs,
)

# ── ось пары «файл домена × запрещённая библиотека». Перечень ЗАКРЫТ ─────────
DIRECT = "brought_in_directly"
VIA_HELPER = "brought_in_through_helper"
BEYOND = "reached_beyond_declared_depth"
NOT_REACHED = "not_brought_in"

OUTCOMES: tuple[str, ...] = (DIRECT, VIA_HELPER, BEYOND, NOT_REACHED)

# ── ось ИСПОЛНЕНИЯ дороги. Отдельная ось, в сумму населения НЕ входит ────────
EXECUTED = "executed_by_the_import_itself"
DEFERRED = "deferred_or_guarded"

EXEC_OUTCOMES: tuple[str, ...] = (EXECUTED, DEFERRED)

#: Ось ЗАПУСКА бинаря LLM: у неё нет оси исполнения по построению — запуск есть
#: ВЫЗОВ, и этот прибор о вызовах не судит. Имя исхода объявлено, чтобы
#: отсутствие суждения было видно читателю, а не выглядело нулём.
LAUNCH_EXEC_NOT_ASKED = "execution_not_asked_a_launch_is_a_call"


# ─────────────────────────── ТАКТ: ключ по входам вердикта ───────────────────
#: Куда ложится переиспользуемый вердикт. Каталог `data/` объявлен
#: runtime-only (`.gitignore`: `data/*.json`), поэтому ключ и ответ НЕ едут в
#: git вместе с кодом. Каталога нет ⇒ такта нет вовсе: сцена в `tempfile`
#: обязана мерить заново, а не читать чужой кеш.
CACHE_REL = "data/forbidden_reach_census_tact.json"


def _utc_now() -> str:
    """Момент замера. Умолчание — настоящие часы; вход ``now=`` их подменяет."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

#: Классы входов, от которых вердикт МОЖЕТ измениться. Перечень ЗАКРЫТ, и
#: каждый класс берётся у ТОЙ ЖЕ двери, которой читает сам замер, — литерала
#: рядом нет ни у одного (урок ADR-920/ADR-926: мерка, объявленная литералом
#: возле кода, меряет себя). Добавить вход, не добавив его сюда, значит
#: переиспользовать устаревший вердикт — поэтому дверей ровно столько, сколько
#: класс несёт, и сторож `tact_key_covers_every_door` краснеет на новой.
KEY_CLASSES: tuple[str, ...] = (
    "tree",            # путь дерева: ответ несёт абсолютный `repo_root`
    "py_files",        # пути и БАЙТЫ каждого .py — `_py_files`, дверь графа
    "top_level_names", # имена верхнего уровня — `_top_level_names`, дверь ОСИ ИМЕНИ
    "rule_modules",    # байты ЗАГРУЖЕННЫХ правил: они живут не в мерянном дереве
    "max_depth",       # объявленный предел дороги — ПАРАМЕТР, а не файл
    "interpreter",     # форма AST и порядок обхода
)


def _rule_module_files() -> list[tuple[str, str]]:
    """Файлы ЗАГРУЖЕННЫХ правил — у самих модулей, а не перечнем имён.

    Правило приезжает из дерева ЗАПУЩЕННОГО прибора, и это НЕ обязательно
    мерянное дерево: `measure(tmp)` судит чужие файлы правилом хозяина. Байты
    правила поэтому входят в ключ отдельным классом; выводятся они из
    `__file__` загруженных модулей, поэтому новый ввоз правила попадает в ключ
    сам, без второй копии перечня.
    """
    import spa_core.monitoring.membership_reach_census as _reach
    mods = [linter, _reach, sys.modules[__name__]]
    try:
        import spa_core.ci.llm_forbidden_lint as _llm
    except Exception:  # noqa: BLE001 — не ввезено ⇒ и в ключ входить нечему
        pass
    else:
        mods.append(_llm)
    # Метка — БАЗОВОЕ ИМЯ файла, а не `__name__` модуля: запущенный скрипт
    # зовётся `__main__`, а ввезённый шагом 0-офис — `forbidden_reach_census`,
    # и ключ, различающий их, не совпал бы НИКОГДА между двумя вызывающими
    # (найдено своим же замером на живом дереве, цикл #1040).
    out: list[tuple[str, str]] = []
    for mod in mods:
        path = getattr(mod, "__file__", None)
        if path:
            abspath = os.path.abspath(path)
            out.append((os.path.basename(abspath), abspath))
    return sorted(set(out))


def tact_key(repo_root: str, max_depth: int = MAX_DEPTH) -> tuple[str, dict, list[str]]:
    """Ключ такта: от чего вердикт МОЖЕТ измениться, и ни от чего больше.

    Возврат — ``(ключ, материал поимённо, причины НЕ ИЗМЕРЕНО)``. Ключ не
    посчитан ⇒ список причин непуст, и вызывающий ОБЯЗАН мерить: промах ключа
    и нечитаемый вход дают ОДНО действие (мерить), но РАЗНЫЕ причины, и обе
    печатаются. «Ключ совпал» — единственное основание переиспользовать ответ,
    потому что при совпадении всех шести классов замер не может дать другой
    ответ ПО ПОСТРОЕНИЮ (инв. #16: это не ослабление проверки, а отказ платить
    второй раз за тот же вопрос).

    Цена ключа измерена: 0.26 с против 634.3 с у замера (цикл #1040) — читать и
    хешировать не то же, что разбирать: 116 МБ читаются за 0.21 с и разбираются
    за сотни секунд.
    """
    import spa_core.monitoring.membership_reach_census as _reach

    unmeasured: list[str] = []
    root = pathlib.Path(repo_root)
    material: dict = {"tree": os.path.abspath(repo_root),
                      "max_depth": int(max_depth),
                      "interpreter": sys.version}

    try:
        files = _reach._py_files(root)
    except OSError as exc:
        unmeasured.append(f"перечень .py не снят ({type(exc).__name__}: {exc})")
        files = []
    digest = hashlib.sha256()
    for rel in files:
        digest.update(rel.encode("utf-8"))
        digest.update(b"\x00")
        try:
            digest.update(hashlib.sha256((root / rel).read_bytes()).digest())
        except OSError as exc:
            unmeasured.append(f"{rel}: байты не прочитаны ({type(exc).__name__}) — ключ НЕ ПОЛОН")
    material["py_files"] = {"count": len(files), "digest": digest.hexdigest()}

    try:
        material["top_level_names"] = sorted(_reach._top_level_names(root))
    except OSError as exc:
        unmeasured.append(f"имена верхнего уровня не сняты ({type(exc).__name__}: {exc})")
        material["top_level_names"] = None

    rules: list[list[str]] = []
    for name, path in _rule_module_files():
        try:
            rules.append([name, hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()])
        except OSError as exc:
            unmeasured.append(f"правило {name}: байты не прочитаны ({type(exc).__name__}) — ключ НЕ ПОЛОН")
    material["rule_modules"] = rules

    if not files:
        unmeasured.append("ни одного файла .py — ключ НЕ ПОЛОН")

    key = hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return key, material, unmeasured


def _cache_path(repo_root: str) -> str | None:
    """Путь кеша такта. ``None`` = каталога `data/` нет, такта нет вовсе."""
    path = pathlib.Path(repo_root) / CACHE_REL
    return str(path) if path.parent.is_dir() else None


def _load_cache(path: str) -> tuple[dict | None, str | None]:
    """Прочитанный кеш либо ``(None, причина)``. Битый кеш = промах, не ответ."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        return None, "кеша такта ещё нет"
    except (OSError, ValueError) as exc:
        return None, f"кеш такта не прочитан ({type(exc).__name__}: {exc})"
    if not isinstance(doc, dict) or "key" not in doc or "answer" not in doc:
        return None, "кеш такта не той формы — промах"
    return doc, None


class _LazyGraph:
    """Второй род графа, собираемый при ПЕРВОМ спросе и ни секундой раньше.

    ``reverse_bfs`` берёт у графа ровно ``["edges"]``, поэтому ленивость видна
    только здесь и не протекает ни в соседа, ни в ось исходов.
    """

    def __init__(self, repo_root: str):
        self._repo_root = repo_root
        self._graph: dict | None = None

    @property
    def built(self) -> bool:
        return self._graph is not None

    def __getitem__(self, key: str):
        if self._graph is None:
            self._graph = build_graph(self._repo_root, module_level_only=True)
        return self._graph[key]


def _module_level_finding_lines(tree: ast.Module) -> frozenset[int]:
    """Номера строк импортов ВЕРХНЕГО УРОВНЯ без охраны.

    Сторож отдаёт находку с номером строки, но не с её местом в дереве; место —
    вопрос ЭТОГО прибора, и спрашивается он у того же разбора. Пересечение по
    номеру строки, а не повторный разбор форм: какие формы считать импортом,
    решает сторож.
    """
    out: set[int] = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            out.add(node.lineno)
    return frozenset(out)


def _seeds(root: pathlib.Path, files: list[str]):
    """Семена двух родов: кто ввозит библиотеку и кто ввозит её НА ИМПОРТЕ.

    Возврат: (по-библиотеке → множество файлов, то же для верхнего уровня,
    множество файлов с запуском бинаря LLM, список «не измерено»).
    """
    by_lib: dict[str, set[str]] = {lib: set() for lib in linter.FORBIDDEN}
    by_lib_exec: dict[str, set[str]] = {lib: set() for lib in linter.FORBIDDEN}
    launchers: set[str] = set()
    unmeasured: list[str] = []

    try:
        from spa_core.ci.llm_forbidden_lint import find_llm_subprocess_launches
    except Exception as exc:  # noqa: BLE001 — любая причина = «нечем спросить»
        find_llm_subprocess_launches = None
        unmeasured.append(
            f"вторая дверь LLM-сторожа не импортирована ({type(exc).__name__}: "
            f"{exc}) — ось ЗАПУСКА НЕ ИЗМЕРЕНА")

    for rel in files:
        try:
            src = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unmeasured.append(f"{rel}: не прочитан ({type(exc).__name__}) — НЕ ИЗМЕРЕН")
            continue
        try:
            findings = linter.scan_source(rel, src)
        except (SyntaxError, ValueError) as exc:
            unmeasured.append(f"{rel}: не разобран ({type(exc).__name__}) — НЕ ИЗМЕРЕН")
            continue
        if findings:
            # Разбор ради МЕСТА импорта нужен только там, где сторож что-то
            # нашёл: на чистом файле места спрашивать не о чем, а проход по
            # дереву целиком стоит десятки секунд у шага цикла.
            top = _module_level_finding_lines(ast.parse(src))
            for finding in findings:
                by_lib[finding.lib].add(rel)
                if finding.lineno in top:
                    by_lib_exec[finding.lib].add(rel)
        if find_llm_subprocess_launches is not None:
            try:
                if find_llm_subprocess_launches(src, rel):
                    launchers.add(rel)
            except SyntaxError:
                unmeasured.append(f"{rel}: вторая дверь не разобрала файл — НЕ ИЗМЕРЕН")
    return by_lib, by_lib_exec, launchers, unmeasured


def _domain_files(files: list[str]) -> list[str]:
    """Файлы объявленных доменов. Перечень доменов — у сторожа, не здесь."""
    return [rel for rel in files
            if any(rel.startswith(domain + "/") for domain in linter.DOMAINS)]


def _reach_axis(graph: dict, domain_files: list[str], seeds_by_key: dict[str, set[str]],
                max_depth: int, exec_graph: dict | None,
                exec_seeds: dict[str, set[str]] | None) -> tuple[dict, list[dict]]:
    """Одна ось: четыре исхода на пару + поимённые находки."""
    counts = {outcome: 0 for outcome in OUTCOMES}
    findings: list[dict] = []
    for key in sorted(seeds_by_key):
        dist, hop = reverse_bfs(graph, seeds_by_key[key])
        exec_dist: dict[str, int] | None = None
        for rel in domain_files:
            reached = dist.get(rel)
            if reached is None:
                counts[NOT_REACHED] += 1
                continue
            if reached == 0:
                counts[DIRECT] += 1
                continue
            if reached > max_depth:
                counts[BEYOND] += 1
                continue
            counts[VIA_HELPER] += 1
            record = {
                "path": rel,
                "key": key,
                "distance": reached,
                "chain": _chain(rel, hop),
            }
            if exec_graph is None or exec_seeds is None:
                record["execution"] = LAUNCH_EXEC_NOT_ASKED
            else:
                if exec_dist is None:
                    exec_dist, _ = reverse_bfs(exec_graph,
                                               exec_seeds.get(key, set()))
                hops = exec_dist.get(rel)
                record["execution"] = (
                    EXECUTED if hops is not None and 1 <= hops <= max_depth
                    else DEFERRED)
            findings.append(record)
    return counts, findings


def _measure_fresh(repo_root: str, max_depth: int) -> dict:
    """ЗАМЕР. Единственный вход — путь дерева и объявленный предел глубины.

    Разбирает дерево целиком; цена на живом дереве — 634.3 с (замер #1039).
    Звать напрямую — значит отказаться от такта ОСОЗНАННО; обычная дверь —
    :func:`measure`.
    """
    root = pathlib.Path(repo_root)
    graph = build_graph(repo_root)
    files = graph["files"]
    unmeasured: list[str] = [
        f"{rel}: граф не разобрал файл ({reason}) — НЕ ИЗМЕРЕН"
        for rel, reason in sorted(graph["unparsed"].items())
    ]

    by_lib, by_lib_exec, launchers, seed_unmeasured = _seeds(root, files)
    unmeasured.extend(seed_unmeasured)

    domain_files = _domain_files(files)
    # Второй род графа стоит столько же, сколько первый, а нужен ТОЛЬКО когда
    # ось занижения что-то нашла: у пустой находки нечего спрашивать об
    # исполнении. Лениво — чтобы шаг цикла не платил за ответ, которого нет.
    exec_graph = _LazyGraph(repo_root)
    counts, findings = _reach_axis(graph, domain_files, by_lib, max_depth,
                                   exec_graph, by_lib_exec)
    launch_counts, launch_findings = _reach_axis(
        graph, domain_files, {"llm_subprocess_launch": launchers}, max_depth,
        None, None)

    # ── контроль: прямые пары ДОЛЖНЫ совпасть с находками самого сторожа ─────
    parity: dict = {}
    try:
        own_findings, own_unmeasured, own_scanned = linter.scan_tree(repo_root)
        own_pairs = {(f.path, f.lib) for f in own_findings}
        mine_pairs = {(rel, lib) for lib, seeds in by_lib.items()
                      for rel in seeds if rel in set(domain_files)}
        parity = {
            "neighbour_pairs": len(own_pairs),
            "census_pairs": len(mine_pairs),
            "equal": own_pairs == mine_pairs,
            "neighbour_scanned": own_scanned,
            "census_domain_files": len(domain_files),
            "walks_agree": own_scanned == len(domain_files),
        }
        for line in own_unmeasured:
            unmeasured.append(f"сторож: {line}")
        if not parity["equal"]:
            unmeasured.append(
                "паритет прямых пар РАЗОШЁЛСЯ со сторожем "
                f"({sorted(own_pairs ^ mine_pairs)}) — вердикт НЕ ИЗМЕРЕН")
        if not parity["walks_agree"]:
            unmeasured.append(
                f"обходы доменов расошлись: сторож осмотрел {own_scanned} файл(ов), "
                f"граф видит {len(domain_files)} — файл домена вне графа не измерен ничем")
    except Exception as exc:  # noqa: BLE001 — нечем спросить = третий исход
        unmeasured.append(f"контроль паритета не выполнен ({type(exc).__name__}: {exc})")

    population = len(domain_files) * len(linter.FORBIDDEN)
    if population == 0:
        unmeasured.append("население равно нулю — мерить было нечем, это не «чисто»")

    return {
        "repo_root": os.path.abspath(repo_root),
        "max_depth": max_depth,
        "domains": list(linter.DOMAINS),
        "libraries": dict(linter.FORBIDDEN),
        "domain_files": len(domain_files),
        "population": population,
        "counts": counts,
        "counts_sum": sum(counts.values()),
        "findings": findings,
        "execution_counts": {
            outcome: sum(1 for f in findings if f["execution"] == outcome)
            for outcome in EXEC_OUTCOMES
        },
        "launch": {
            "seed_files": sorted(launchers),
            "counts": launch_counts,
            "findings": launch_findings,
        },
        "seed_files": {lib: sorted(rels) for lib, rels in sorted(by_lib.items()) if rels},
        "parity": parity,
        "name_counts": graph["name_counts"],
        "unmeasured": unmeasured,
    }


def measure(repo_root: str = REPO_ROOT, max_depth: int = MAX_DEPTH, *,
            cache: bool = True, now: str | None = None) -> dict:
    """Перепись С ТАКТОМ: ключ совпал ⇒ ответ переиспользован, иначе ЗАМЕР.

    Такт объявлен заказом G914 п. 2 и стои́т на одном условии: ключ обязан
    покрывать ВСЕ входы, от которых вердикт может измениться (``KEY_CLASSES``).
    Поэтому:

    * ключ совпал ⇒ ответ отдаётся с НАЗВАННЫМ моментом замера
      (``doc["tact"]["measured_at"]``), и читатель не вправе принять его за
      «измерено сейчас»;
    * ключ НЕ совпал, кеша нет, кеш битый, ключ НЕ ПОСЧИТАН ⇒ **ЗАМЕР**.
      Промах ключа — это «мерить», а никогда «чисто» (инв. #17).

    Причины «ключ не посчитан» живут в ``doc["tact"]["unmeasured"]`` и НЕ
    попадают в ``doc["unmeasured"]`` намеренно: когда ключ снять не удалось,
    цикл МЕРИТ, то есть вердикт полностью измерен, и опускать его до
    «НЕ ИЗМЕРЕНО» значило бы соврать в обратную сторону. Видимость при этом
    не теряется — ``format_report`` печатает эти причины отдельной строкой.
    """
    key, material, key_unmeasured = tact_key(repo_root, max_depth)
    path = _cache_path(repo_root) if cache else None
    miss = None
    if path is None:
        miss = ("такт выключен вызывающим" if not cache
                else f"каталога {os.path.dirname(CACHE_REL)}/ нет — такта нет")
    elif key_unmeasured:
        miss = "ключ НЕ ПОЛОН — переиспользовать нечего"
    else:
        stored, reason = _load_cache(path)
        if stored is None:
            miss = reason
        elif stored.get("key") != key:
            miss = "ключ НЕ совпал — дерево или правило изменились"
        else:
            doc = dict(stored["answer"])
            doc["tact"] = {
                "key": key,
                "reused": True,
                "measured_at": stored.get("measured_at"),
                "cache": path,
                "miss": None,
                "unmeasured": list(key_unmeasured),
                "classes": list(KEY_CLASSES),
            }
            return doc

    doc = _measure_fresh(repo_root, max_depth)
    measured_at = now if now is not None else _utc_now()
    doc["tact"] = {
        "key": key,
        "reused": False,
        "measured_at": measured_at,
        "cache": path,
        "miss": miss,
        "unmeasured": list(key_unmeasured),
        "classes": list(KEY_CLASSES),
    }
    doc["tact"]["stored"] = False
    if path is not None and not key_unmeasured:
        answer = {k: v for k, v in doc.items() if k != "tact"}
        try:
            atomic_save({"key": key, "measured_at": measured_at,
                         "material": material, "answer": answer}, path)
        except (OSError, TypeError, ValueError) as exc:
            # Запись не удалась ⇒ следующий зов СНОВА померит. Это дорого, но
            # честно; молчание сделало бы «такт не работает» неотличимым от
            # «такт работает», и отличить их можно только ОТДЕЛЬНЫМ полем.
            doc["tact"]["store_failed"] = f"{type(exc).__name__}: {exc}"
        else:
            doc["tact"]["stored"] = True
    return doc


def verdict(doc: dict) -> str:
    """Один из трёх исходов: НЕ ИЗМЕРЕНО · НАХОДКА · НИЖНЯЯ ГРАНИЦА."""
    if doc["unmeasured"] or not doc["population"]:
        return "НЕ ИЗМЕРЕНО"
    if doc["counts"][VIA_HELPER] or doc["launch"]["counts"][VIA_HELPER]:
        return "НАХОДКА"
    return "НИЖНЯЯ ГРАНИЦА"


def format_report(doc: dict) -> str:
    lines = [
        f"правило, видящее только прямой импорт (заказ G107 п. 3): {verdict(doc)}"
        f" · население {doc['population']} пар"
        f" ({doc['domain_files']} файл(ов) домена × {len(doc['libraries'])} библиотек)"
        f" · предел дороги {doc['max_depth']} дуг",
        "[ИСХОДЫ] " + " · ".join(f"{name} {doc['counts'][name]}" for name in OUTCOMES)
        + f" · сумма {doc['counts_sum']}",
    ]
    for finding in doc["findings"]:
        lines.append(
            f"   [НАХОДКА/{finding['execution']}] {finding['path']} ввозит "
            f"«{finding['key']}» за {finding['distance']} дуг(и), минуя прямого "
            f"сторожа: " + " → ".join(finding["chain"]))
    launch = doc["launch"]
    lines.append(
        f"[ЗАПУСК БИНАРЯ LLM] семян {len(launch['seed_files'])} · "
        + " · ".join(f"{name} {launch['counts'][name]}" for name in OUTCOMES)
        + f" · ось исполнения: {LAUNCH_EXEC_NOT_ASKED}")
    for finding in launch["findings"]:
        lines.append(
            f"   [НАХОДКА/{finding['execution']}] {finding['path']} достигает "
            f"запуска за {finding['distance']} дуг(и): "
            + " → ".join(finding["chain"]))
    if doc["parity"]:
        parity = doc["parity"]
        lines.append(
            f"[КОНТРОЛЬ] прямых пар у сторожа {parity['neighbour_pairs']}, "
            f"у переписи {parity['census_pairs']} — "
            + ("РАВНО" if parity["equal"] else "РАЗОШЛОСЬ")
            + "; обходы доменов "
            + ("согласны" if parity.get("walks_agree") else "РАЗОШЛИСЬ"))
    lines.append(
        "[ЦЕНА ПРЕДЕЛА] дорог дальше предела: "
        f"{doc['counts'][BEYOND]} — это НЕ «дороги нет», а объявленный выбор")
    lines.append("[ОСЬ ИМЕНИ] " + " · ".join(
        f"{name} {count}" for name, count in sorted(doc["name_counts"].items())))
    for line in doc["unmeasured"][:12]:
        lines.append(f"   [НЕ ИЗМЕРЕНО] {line}")
    if len(doc["unmeasured"]) > 12:
        lines.append(f"   [НЕ ИЗМЕРЕНО] …и ещё {len(doc['unmeasured']) - 12} причин(ы)")
    tact = doc.get("tact")
    if tact is None:
        lines.append("[ТАКТ] НЕ ИЗМЕРЕН: ответ пришёл без блока такта")
    elif tact["reused"]:
        lines.append(
            f"[ТАКТ] ответ ПЕРЕИСПОЛЬЗОВАН по ключу {tact['key'][:12]} — "
            f"замер снят {tact['measured_at']}, а НЕ сейчас; "
            f"входов в ключе {len(tact['classes'])}")
    else:
        lines.append(
            f"[ТАКТ] ИЗМЕРЕНО сейчас ({tact['measured_at']}), ключ "
            f"{tact['key'][:12]} — причина промаха: {tact['miss']}")
    for line in (tact or {}).get("unmeasured", [])[:3]:
        lines.append(f"   [ТАКТ НЕ ПОЛОН] {line}")
    if (tact or {}).get("store_failed"):
        lines.append(f"   [ТАКТ НЕ ЗАПИСАН] {tact['store_failed']} — следующий "
                     "зов померит заново")
    lines.append("ADVISORY: прибор только ЧИТАЕТ — ни один сторож не изменён")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=REPO_ROOT)
    parser.add_argument("--max-depth", type=int, default=MAX_DEPTH)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-cache", action="store_true",
                        help="мерить заново, не читая и не записывая такт")
    parser.add_argument("--tact-key", action="store_true",
                        help="напечатать ключ такта и его материал, не мерить")
    parser.add_argument("--now", default=None,
                        help="момент замера (ISO-8601); умолчание — часы")
    args = parser.parse_args(argv)

    if args.tact_key:
        key, material, unmeasured = tact_key(args.root, args.max_depth)
        print(json.dumps({"key": key, "material": material,
                          "unmeasured": unmeasured},
                         ensure_ascii=False, indent=2, sort_keys=True))
        return 2 if unmeasured else 0

    try:
        doc = measure(args.root, args.max_depth, cache=not args.no_cache,
                      now=args.now)
    except Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}")
        return 2

    print(json.dumps(doc, ensure_ascii=False, indent=2) if args.json
          else format_report(doc))

    state = verdict(doc)
    if state == "НЕ ИЗМЕРЕНО":
        return 2
    return 1 if state == "НАХОДКА" else 0


if __name__ == "__main__":
    sys.exit(main())
