"""Перепись тестов, зелёных ПО ПОСТРОЕНИЮ: предпосылка делает утверждение неопровержимым.

Заказ **G92, п. 2** приказа владельца «Portfolio CIO» (хвост
[ADR-504](../../docs/decisions/ADR-504-a-tautological-comparison-is-not-a-green.md)).

## Вопрос

ADR-504 нашёл ДВА теста набора — `test_agreeing_copies_are_satisfied` и
`test_a_delivered_closure_is_satisfied`, — чей зелёный был свойством ДЕРЕВА, а не
наблюдением о согласии копий, которое стоит в их названиях. Обе фикстуры оставляли
`HEAD` равным `ref`, поэтому сверка была пуста ПО ПОСТРОЕНИЮ: подмена логики согласия
тесты бы не уронила. Нашли их случайно — правкой их же предмета.

Заказ: форма общая, и класс в наборе **не измерен**. Мерить дифференциально —
«подменить решающую ветку у прибора и посмотреть, какие тесты НЕ покраснели»,
население назвать числом. Храповика до замера не заводить: база с ложными
срабатываниями учит дописывать в неё.

## Почему обычная мутация на этот вопрос НЕ отвечает

Мутационный прогон знает два исхода: мутант убит (тест покраснел) или выжил. Выживший
мутант сливает ДВА разных положения дел, и лечатся они в разных местах:

| положение | где дефект | что делать |
|---|---|---|
| тест вовсе не доходит до решающей ветки | **сцены нет** | это не предмет класса |
| тест доходит, но его зелёный не зависит ни от одного исхода решения | **сцена инертна** | вот он, «зелёный по построению» |

Поэтому перепись меряет ДВЕ вещи, а не одну: **достижимость** решения этим тестом
(прогон с записью: решение, вычисленное во время теста, называет себя само) и
**чувствительность** (прогон с решением, принудительно заданным `True`, и отдельно
`False`). Достижимость спрашивается ОДНИМ прогоном на весь набор, а не прогоном на
каждое решение: запись — побочный эффект вычисления условия, и она не стоит ничего.

## Четыре исхода, и они различимы (инв. #17)

| вердикт | что он значит |
|---|---|
| `sensitive` | хотя бы одно принуждённое решение роняет тест ⇒ зелёный есть наблюдение |
| `green_by_construction` | тест вычисляет решения прибора, и НИ ОДНО принуждение его не роняет |
| `not_reached` | тест не вычислил ни одного решения прибора — сцена вне населения |
| `unmeasured` | предпосылка не обеспечена: тест красен/пропущен на базе, шум инструментовки, решение не собралось |

`not_reached` не есть «чисто»: это ответ «предмета здесь нет», и он остаётся полем
строки, а не растворяется в нуле. `unmeasured` вердиктом не притворяется.

## Переход в `skipped` считается ЗА тест, а не против него

`.claude/rules/deployment.md` (урок #465): в дифференциальном замере тест, ставший
`skipped`, не краснеет и не проходит — он ИСЧЕЗАЕТ, и глазами это читается как
«всё в порядке». Красным здесь считается только `failed`/`error`; исчезновение под
принуждением НЕ засчитывается в убийство мутанта и отдельно называется полем
`vanished_under_force`.

## Контроль шума инструментовки

Запись достижимости — правка исходника прибора, и она способна сама изменить вердикт
теста (прибор, читающий собственный текст, увидит вставленные вызовы). Поэтому прогон
с записью сверяется с ЧИСТЫМ прогоном поимённо: тест, у которого исход разошёлся,
объявляется `unmeasured` с причиной `instrumentation_noise`, а не молча участвует в
замере. Правка хирургическая — заменяется РОВНО пролёт условия, остальной файл
побайтово тот же: `ast.unparse` снёс бы комментарии и покрасил бы приборы, читающие
свой исходник (память цикла: «mutation run needs an unparse-noise control»).

## Перепись ничего не чинит

`applied=False`. Найденный тест — предмет своей карточки, а не прицепа (инв. #16).
Храповика нет НАМЕРЕННО: заказ велит сперва назвать население числом.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]
if str(_REPO_ROOT) not in sys.path:  # pragma: no cover - путь импорта
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

VERDICT_SENSITIVE = "sensitive"
VERDICT_GREEN_BY_CONSTRUCTION = "green_by_construction"
VERDICT_NOT_REACHED = "not_reached"
VERDICT_UNMEASURED = "unmeasured"

#: Вердикты, которые читатель обязан увидеть как НАХОДКУ (ненулевой код возврата).
FINDING_VERDICTS = (VERDICT_GREEN_BY_CONSTRUCTION,)

#: Исходы прогона, считающиеся КРАСНЫМ. `skipped` сюда намеренно не входит.
RED_OUTCOMES = ("failed", "error")

#: Прибор по умолчанию и население его тестов — то, где класс и был найден (ADR-504).
DEFAULT_INSTRUMENT = "spa_core/monitoring/card_acceptance.py"
DEFAULT_FUNC_PREFIX = "_probe_"
DEFAULT_MODULE = "spa_core.monitoring.card_acceptance"
DEFAULT_TEST_DIR = "spa_core/tests"
DEFAULT_LEDGER = "data/green_by_construction_census.json"
ARTIFACT = "green_by_construction_census.json"

#: Такт ступени моста. Прогон стои́т МИНУТ (сотни вызовов pytest), поэтому
#: шестичасовой бегун не вправе звать его каждый раз; срок решает ФАЙЛ, а не
#: расписание запуска — иначе «раз в неделю» держалось бы на том, что никто не
#: трогал cron (ADR-414, тот же порядок, что у `python_reader_clock_doors`).
MEASUREMENT_TACT_DAYS = 7

#: Население СТУПЕНИ — ОДИН файл, и это ВЫБОР с названной ценой, а не свойство
#: класса. Полное население (все тесты, называющие прибор) стои́т часа и в такт
#: шестичасового бегуна не умещается; ступень меряет то дерево проб, где класс
#: и был найден (ADR-504), а полный замер зовётся рукой через CLI. Разница
#: объявлена здесь, чтобы «ступень зелена» не читалось как «набор измерен».
STAGE_TEST_FILES = ("spa_core/tests/test_card_copies_agree_probe.py",)


# ── плагин прогона: кто дошёл до решения и чем кончился ──────────────────────
#
# Плагин кладётся отдельным файлом и подключается `-p gbc_plugin`. Он НЕ меняет
# поведение тестов: только читает множество `_GBC_SEEN` прибора и исход теста.
_PLUGIN_SRC = '''\
"""Служебный плагин переписи green_by_construction. Ничего не чинит и не меняет."""
import json
import os
import sys

_OUT = os.environ["GBC_OUT"]
_MOD = os.environ["GBC_MODULE"]
_state = {}


def _seen():
    mod = sys.modules.get(_MOD)
    return getattr(mod, "_GBC_SEEN", None) if mod is not None else None


def pytest_runtest_logstart(nodeid, location):
    _state["outcome"] = "passed"
    seen = _seen()
    if seen is not None:
        seen.clear()


def pytest_runtest_logreport(report):
    if report.outcome == "failed":
        _state["outcome"] = "failed"
    elif report.outcome == "skipped" and _state.get("outcome") == "passed":
        _state["outcome"] = "skipped"


def pytest_runtest_logfinish(nodeid, location):
    seen = _seen()
    rec = {"nodeid": nodeid,
           "outcome": _state.get("outcome", "passed"),
           "seen": sorted(seen) if seen is not None else []}
    with open(_OUT, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\\n")
    _state.clear()
'''

#: Хвост, дописываемый к прибору на время прогона достижимости.
_RECORDER_SRC = '''

# --- перепись green_by_construction: запись достижимости (временно) ----------
_GBC_SEEN: set = set()


def _GBC_REC(_gbc_id, _gbc_value):
    _GBC_SEEN.add(_gbc_id)
    return _gbc_value
'''


# ── разбор прибора: что считается РЕШАЮЩЕЙ ВЕТКОЙ ────────────────────────────

def decision_points(source: str, func_prefix: str = DEFAULT_FUNC_PREFIX) -> List[dict]:
    """Решающие ветки прибора: условия `if`, `X if C else Y` и фильтры включений.

    Берутся только ветки ВНУТРИ функций, чьё имя начинается с ``func_prefix``, —
    прибор объявляет свои пробы именем, и решать за него, что в модуле «решающее»,
    перепись не вправе.

    Возврат — список словарей, отсортированный по положению в файле. ``id``
    адресует ветку именем функции и координатой (`имя:строка:столбец`), а не
    порядковым номером: номер сдвинулся бы от любой правки выше по файлу и
    склеил бы замеры разных дней молча.
    """
    tree = ast.parse(source)
    found: Dict[str, dict] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not fn.name.startswith(func_prefix):
            continue
        for node in ast.walk(fn):
            tests: List[Tuple[ast.expr, str]] = []
            if isinstance(node, ast.If):
                tests.append((node.test, "if"))
            elif isinstance(node, ast.IfExp):
                tests.append((node.test, "ifexp"))
            elif isinstance(node, ast.comprehension):
                tests.extend((t, "comprehension") for t in node.ifs)
            for test, kind in tests:
                if getattr(test, "end_lineno", None) is None:
                    continue
                did = f"{fn.name}:{test.lineno}:{test.col_offset}"
                found.setdefault(did, {
                    "id": did, "func": fn.name, "kind": kind,
                    "lineno": test.lineno, "col_offset": test.col_offset,
                    "end_lineno": test.end_lineno,
                    "end_col_offset": test.end_col_offset,
                })
    return [found[k] for k in sorted(found, key=lambda k: (found[k]["lineno"],
                                                           found[k]["col_offset"]))]


def _line_starts(blob: bytes) -> List[int]:
    starts = [0]
    for i, byte in enumerate(blob):
        if byte == 0x0A:
            starts.append(i + 1)
    return starts


def _span(starts: Sequence[int], dec: dict) -> Tuple[int, int]:
    """Байтовый пролёт условия. Байтовый, а не символьный: ``col_offset`` у AST
    считается в БАЙТАХ utf-8, и на файле с русскими комментариями символьный
    срез уехал бы ровно там, где текст перестал быть ascii."""
    return (starts[dec["lineno"] - 1] + dec["col_offset"],
            starts[dec["end_lineno"] - 1] + dec["end_col_offset"])


def _splice(source: str, edits: Iterable[Tuple[int, int, bytes]]) -> str:
    """Заменить пролёты. Применяются С КОНЦА: иначе каждая правка сдвигала бы
    координаты всех следующих, и вторая встала бы мимо."""
    blob = source.encode("utf-8")
    for start, end, repl in sorted(edits, key=lambda e: e[0], reverse=True):
        blob = blob[:start] + repl + blob[end:]
    return blob.decode("utf-8")


def instrument_source(source: str, decisions: Sequence[dict]) -> str:
    """Обернуть каждое решение записью достижимости. Поведение не меняется:
    ``_GBC_REC`` возвращает ровно то, что получил, и вычисление условия остаётся
    на своём месте (короткое замыкание внутри условия сохранено — оборачивается
    условие ЦЕЛИКОМ, а не его части)."""
    starts = _line_starts(source.encode("utf-8"))
    blob = source.encode("utf-8")
    edits = []
    for dec in decisions:
        start, end = _span(starts, dec)
        original = blob[start:end]
        repl = b"_GBC_REC(" + json.dumps(dec["id"]).encode("utf-8") + b", (" \
            + original + b"))"
        edits.append((start, end, repl))
    return _splice(source, edits) + _RECORDER_SRC


def force_source(source: str, decision: dict, value: bool) -> Optional[str]:
    """Принудить одно решение. ``None`` — правка не разобралась (третий исход,
    а не тихий пропуск: такое решение попадает в `unforceable` с названной
    причиной)."""
    starts = _line_starts(source.encode("utf-8"))
    start, end = _span(starts, decision)
    out = _splice(source, [(start, end, b"True" if value else b"False")])
    try:
        ast.parse(out)
    except SyntaxError:
        return None
    return out


# ── классификация ────────────────────────────────────────────────────────────

def classify_test(*, baseline_outcome: Optional[str], reached: Sequence[str],
                  red_under: Sequence[str], vanished_under: Sequence[str],
                  unforceable_reached: Sequence[str]) -> Tuple[str, str]:
    """Вердикт одного теста. Чистая функция — вся арифметика класса живёт здесь.

    Порядок ветвей существен. `sensitive` решается ПЕРВЫМ среди измеренных:
    положительное свидетельство (тест покраснел хотя бы от одного принуждения)
    сильнее любого пробела в остатке, и отдать такой тест в `unmeasured` из-за
    несобравшейся соседней правки значило бы потерять доказанный зелёный.
    """
    if baseline_outcome is None:
        return VERDICT_UNMEASURED, "теста нет в записи базового прогона"
    if baseline_outcome in RED_OUTCOMES:
        return VERDICT_UNMEASURED, f"на базе {baseline_outcome} — предпосылка не обеспечена"
    if baseline_outcome == "skipped":
        return VERDICT_UNMEASURED, "на базе skipped — тест не исполнялся"
    if red_under:
        return VERDICT_SENSITIVE, (f"роняется принуждением {len(red_under)} решени(я): "
                                   + ", ".join(sorted(red_under)[:3]))
    if not reached:
        return VERDICT_NOT_REACHED, "не вычислил ни одного решения прибора"
    if unforceable_reached:
        return VERDICT_UNMEASURED, ("достигнутое решение не принудить: "
                                    + ", ".join(sorted(unforceable_reached)[:3]))
    detail = (f"вычисляет {len(reached)} решени(я) прибора, "
              f"ни одно принуждение его не роняет")
    if vanished_under:
        detail += (f"; под {len(vanished_under)} принуждени(ями) тест ИСЧЕЗАЕТ "
                   f"(skipped), а не краснеет")
    return VERDICT_GREEN_BY_CONSTRUCTION, detail


def summarise(rows: Sequence[dict]) -> Dict[str, int]:
    counts = {v: 0 for v in (VERDICT_SENSITIVE, VERDICT_GREEN_BY_CONSTRUCTION,
                             VERDICT_NOT_REACHED, VERDICT_UNMEASURED)}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    return counts


# ── прогон ───────────────────────────────────────────────────────────────────

def _read_records(path: Path) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        out[rec["nodeid"]] = rec
    return out


def _run_pytest(root: Path, files: Sequence[str], *, module: str,
                plugin_dir: Path, timeout: int) -> dict:
    scratch = Path(tempfile.mkdtemp(prefix="gbc_out_"))
    out_path = scratch / "records.jsonl"
    env = dict(os.environ)
    env["SPA_ENV"] = "ci"
    env["PYTHONHASHSEED"] = "0"
    env["GBC_OUT"] = str(out_path)
    env["GBC_MODULE"] = module
    env["PYTHONPATH"] = os.pathsep.join(
        [str(plugin_dir)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    # `--basetemp` обязателен, а не украшение: замер прогоняет pytest СОТНИ раз,
    # и временные каталоги фикстур копятся в общем корне быстрее, чем pytest
    # успевает их подчищать. Цикл #756 узнал это, посадив машину на 100 % диска
    # посреди собственного замера; каталог прогона теперь свой и удаляется сразу.
    cmd = [sys.executable, "-m", "pytest", *files, "-q", "--tb=no",
           "--basetemp", str(scratch / "pt"), "-p", "no:cacheprovider",
           "-p", "no:randomly", "-p", "gbc_plugin"]
    try:
        proc = subprocess.run(cmd, cwd=str(root), env=env, text=True,
                              capture_output=True, timeout=timeout)
        rc, tail = proc.returncode, (proc.stdout or "")[-2000:]
    except subprocess.TimeoutExpired:
        rc, tail = -9, "TIMEOUT"
    records = _read_records(out_path)
    shutil.rmtree(scratch, ignore_errors=True)
    return {"rc": rc, "records": records, "tail": tail}


def _make_copy(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    # `cp -Rc` на APFS клонирует (CoW) и стоит секунду на 8 000 файлов; на файловой
    # системе без клонирования флаг не поддержан — тогда обычное копирование.
    rc = subprocess.run(["cp", "-Rc", str(src), str(dst)],
                        capture_output=True).returncode
    if rc != 0:
        shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)


def discover_test_files(root: Path, module: str, test_dir: str) -> List[str]:
    """Тесты, НАЗЫВАЮЩИЕ прибор. Адресация — по имени модуля в тексте файла:
    тест, не упомянувший прибор, не может быть о нём, а тест, упомянувший его,
    ещё только КАНДИДАТ — доходит ли он до решения, решает прогон, а не grep."""
    needle = module.rsplit(".", 1)[-1]
    out = []
    base = root / test_dir
    if not base.is_dir():
        return out
    for path in sorted(base.glob("test_*.py")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if needle in text:
            out.append(str(path.relative_to(root)))
    return out


def run_differential(root: Path, *, instrument: str = DEFAULT_INSTRUMENT,
                     module: str = DEFAULT_MODULE,
                     func_prefix: str = DEFAULT_FUNC_PREFIX,
                     test_files: Optional[Sequence[str]] = None,
                     workers: int = 4, timeout: int = 1800,
                     limit_decisions: Optional[int] = None,
                     workdir: Optional[Path] = None) -> dict:
    """Дифференциальный замер. Живое дерево НЕ трогается: все прогоны идут на
    одноразовых копиях, и чистый базовый прогон — тоже на копии, иначе разница
    «копия против оригинала» подмешалась бы в замер шума."""
    root = Path(root).resolve()
    inst_path = root / instrument
    doc: dict = {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "applied": False,
        "root": str(root),
        "instrument": instrument,
        "module": module,
        "func_prefix": func_prefix,
        # Население ОБЪЯВЛЯЕТСЯ полем, а не выводится читателем из `rows`:
        # «зелёных по построению 1» без него прочлось бы как «во всём наборе
        # один», тогда как ступень меряет один файл проб, а полный замер —
        # десятки. Пустой список здесь — честное «ещё не выбрано», и он
        # переписывается ровно там, где перечень становится известен.
        "stage_population": [],
    }
    if not inst_path.is_file():
        doc.update(status="UNMEASURED", reason=f"прибора нет: {instrument}")
        return doc
    source = inst_path.read_text(encoding="utf-8")
    decisions = decision_points(source, func_prefix)
    if limit_decisions is not None:
        decisions = decisions[:limit_decisions]
    files = list(test_files) if test_files is not None else \
        discover_test_files(root, module, DEFAULT_TEST_DIR)
    doc.update(decisions_total=len(decisions), test_files=list(files),
               stage_population=list(files))
    if not files:
        doc.update(status="UNMEASURED", reason="ни одного теста, называющего прибор")
        return doc
    if not decisions:
        doc.update(status="UNMEASURED",
                   reason=f"в приборе нет решающих веток под префиксом {func_prefix!r}")
        return doc

    holder = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="gbc_run_"))
    holder.mkdir(parents=True, exist_ok=True)
    plugin_dir = holder / "plugin"
    plugin_dir.mkdir(exist_ok=True)
    (plugin_dir / "gbc_plugin.py").write_text(_PLUGIN_SRC, encoding="utf-8")

    copies = [holder / f"w{i}" for i in range(max(1, workers))]
    for copy in copies:
        _make_copy(root, copy)

    def _write(copy: Path, text: str) -> None:
        (copy / instrument).write_text(text, encoding="utf-8")

    # 1. чистый базовый прогон
    _write(copies[0], source)
    base = _run_pytest(copies[0], files, module=module,
                       plugin_dir=plugin_dir, timeout=timeout)
    # 2. прогон с записью достижимости
    _write(copies[0], instrument_source(source, decisions))
    traced = _run_pytest(copies[0], files, module=module,
                         plugin_dir=plugin_dir, timeout=timeout)
    _write(copies[0], source)

    noisy = sorted(n for n, rec in traced["records"].items()
                   if n in base["records"]
                   and rec["outcome"] != base["records"][n]["outcome"])
    missing = sorted(set(base["records"]) - set(traced["records"]))
    doc["noise_control"] = {"diverged": noisy, "lost": missing,
                            "base_tests": len(base["records"]),
                            "traced_tests": len(traced["records"])}
    if not base["records"]:
        doc.update(status="UNMEASURED",
                   reason=f"базовый прогон не собрал ни одного теста: {base['tail'][-300:]}")
        return doc
    if len(noisy) + len(missing) >= len(base["records"]):
        doc.update(status="UNMEASURED",
                   reason="инструментовка сдвинула исход У ВСЕХ тестов — замер не о приборе")
        return doc

    reach: Dict[str, Set[str]] = {}
    for nodeid, rec in traced["records"].items():
        reach[nodeid] = set(rec.get("seen") or ())
    by_decision: Dict[str, Set[str]] = {}
    for nodeid, seen in reach.items():
        for did in seen:
            by_decision.setdefault(did, set()).add(nodeid)

    # 3. принуждение каждого ДОСТИГНУТОГО решения в обе стороны
    jobs: List[Tuple[dict, bool, List[str]]] = []
    unforceable: List[str] = []
    index = {d["id"]: d for d in decisions}
    for did in sorted(by_decision):
        dec = index.get(did)
        if dec is None:
            continue
        job_files = sorted({n.split("::", 1)[0] for n in by_decision[did]})
        for value in (True, False):
            if force_source(source, dec, value) is None:
                unforceable.append(did)
                continue
            jobs.append((dec, value, job_files))

    red_under: Dict[str, Set[str]] = {}
    vanished_under: Dict[str, Set[str]] = {}
    forced_runs: List[dict] = []
    lock_free_copies = list(copies)

    def _one(args: Tuple[int, Tuple[dict, bool, List[str]]]) -> dict:
        slot, (dec, value, job_files) = args
        copy = lock_free_copies[slot % len(lock_free_copies)]
        forced = force_source(source, dec, value)
        _write(copy, forced or source)
        try:
            out = _run_pytest(copy, job_files, module=module,
                              plugin_dir=plugin_dir, timeout=timeout)
        finally:
            _write(copy, source)
        return {"decision": dec["id"], "value": value, "rc": out["rc"],
                "records": out["records"], "files": job_files}

    # Каждый работник пишет в СВОЮ копию: правка исходника не переносима между
    # потоками, и общая копия дала бы прогон под чужой мутацией молча.
    slots = [(i, job) for i, job in enumerate(jobs)]
    if len(lock_free_copies) > 1:
        with ThreadPoolExecutor(max_workers=len(lock_free_copies)) as pool:
            batches = [slots[i::len(lock_free_copies)]
                       for i in range(len(lock_free_copies))]

            def _serial(batch):
                return [_one(item) for item in batch]
            for part in pool.map(_serial, batches):
                forced_runs.extend(part)
    else:
        forced_runs = [_one(item) for item in slots]

    for run in forced_runs:
        did = run["decision"]
        for nodeid in by_decision.get(did, ()):  # только те, кто его достигал
            rec = run["records"].get(nodeid)
            was = base["records"].get(nodeid, {}).get("outcome")
            if rec is None:
                continue
            if rec["outcome"] in RED_OUTCOMES and was not in RED_OUTCOMES:
                red_under.setdefault(nodeid, set()).add(did)
            elif rec["outcome"] == "skipped" and was == "passed":
                vanished_under.setdefault(nodeid, set()).add(did)

    rows: List[dict] = []
    unforceable_set = set(unforceable)
    for nodeid in sorted(set(base["records"]) | set(reach)):
        if nodeid in noisy or nodeid in missing:
            rows.append({"nodeid": nodeid, "verdict": VERDICT_UNMEASURED,
                         "detail": "instrumentation_noise: инструментовка сдвинула исход",
                         "reached": [], "red_under": []})
            continue
        reached = sorted(reach.get(nodeid, ()))
        verdict, detail = classify_test(
            baseline_outcome=base["records"].get(nodeid, {}).get("outcome"),
            reached=reached,
            red_under=sorted(red_under.get(nodeid, ())),
            vanished_under=sorted(vanished_under.get(nodeid, ())),
            unforceable_reached=sorted(unforceable_set & set(reached)),
        )
        rows.append({"nodeid": nodeid, "verdict": verdict, "detail": detail,
                     "reached": reached,
                     "red_under": sorted(red_under.get(nodeid, ())),
                     "vanished_under": sorted(vanished_under.get(nodeid, ()))})

    doc.update(
        status="OK",
        decisions_reached=len(by_decision),
        decisions_unforceable=sorted(set(unforceable)),
        forced_runs=len(forced_runs),
        counts=summarise(rows),
        rows=rows,
    )
    if workdir is None:
        shutil.rmtree(holder, ignore_errors=True)
    return doc


def run(root: str | Path = _REPO_ROOT, *, data_dir: Optional[Path] = None,
        dest: Optional[Path] = None, write: bool = True, if_due: bool = True,
        test_files: Optional[Sequence[str]] = None, workers: int = 2,
        now=None, tact_days: int = MEASUREMENT_TACT_DAYS) -> dict:
    """Один ТАКТ замера для ступени моста (`findings_bridge.CENSUS_STAGE`).

    Зачем обёртка при наличии :func:`run_differential`: у ступени объявленная
    форма вызова — ``<модуль>.run(root=args.root)``, и сторожа проводки
    отвечают на вопрос «есть ли на свете вызов, который этот артефакт пишет»
    ровно по ней.

    **«Не мерили» и «измерено» — РАЗНЫЕ исходы** (инв. #17): внутри такта
    возвращается ``{"measured": False, "reason": …}``, а не выдуманный вердикт.
    Ноль находок в этой ветке был бы утверждением о населении, которого никто
    не смотрел.

    Гейт такта НЕ копируется: он взят у соседа (`python_reader_clock_doors`),
    который его уже меряет, — две копии одной мерки расходятся молча (ADR-220).
    """
    root = Path(root)
    source = Path(data_dir) if data_dir is not None else root / "data"
    target = Path(dest) if dest is not None else source / ARTIFACT
    if if_due:
        from spa_core.monitoring.python_reader_clock_doors import measurement_due
        due, why = measurement_due(target, now=now, tact_days=tact_days)
        if not due:
            return {"measured": False, "reason": why, "artifact": str(target)}
    doc = run_differential(root, test_files=list(test_files or STAGE_TEST_FILES),
                           workers=workers)
    if write:
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(doc, str(target))
    return {"measured": True, "doc": doc, "artifact": str(target)}


def report(doc: dict, max_rows: int = 25) -> List[str]:
    lines: List[str] = []
    if str(doc.get("status")) != "OK":
        lines.append(f"НЕ ИЗМЕРЕНО: {doc.get('reason', 'причина не названа')}")
        return lines
    counts = observed(doc, "counts", kind=dict) or {}
    total = sum(counts.values())
    lines.append(
        f"Перепись «зелёный по построению» (заказ G92 п. 2): население {total} тест(ов) "
        f"из {len(doc.get('test_files') or ())} файл(ов); решений у прибора "
        f"{doc.get('decisions_total')}, достигнуто {doc.get('decisions_reached')}, "
        f"принуждений прогнано {doc.get('forced_runs')}")
    lines.append("  " + " · ".join(f"{k} {counts.get(k, 0)}" for k in (
        VERDICT_SENSITIVE, VERDICT_GREEN_BY_CONSTRUCTION,
        VERDICT_NOT_REACHED, VERDICT_UNMEASURED)))
    noise = doc.get("noise_control") or {}
    lines.append(f"  контроль шума: разошлось {len(noise.get('diverged') or ())}, "
                 f"потеряно {len(noise.get('lost') or ())} из "
                 f"{noise.get('base_tests')} тест(ов) базового прогона")
    shown = 0
    for row in doc.get("rows") or ():
        if row["verdict"] != VERDICT_GREEN_BY_CONSTRUCTION:
            continue
        if shown >= max_rows:
            break
        lines.append(f"  [{row['verdict']}] {row['nodeid']} — {row['detail']}")
        shown += 1
    rest = counts.get(VERDICT_GREEN_BY_CONSTRUCTION, 0) - shown
    if rest > 0:
        lines.append(f"  … ещё {rest} находк(и) того же вида (полный перечень — `--json`)")
    lines.append("  НЕ ДОКЛАДЫВАЕТ: решения прибора вне функций с объявленным префиксом · "
                 "ветки, достижимые только из подпроцесса теста · верность самого "
                 "перечня тестов (он собран по упоминанию имени прибора)")
    lines.append("  ADVISORY: перепись только ЧИТАЕТ (applied=False)")
    return lines


def format_report(doc: dict, max_rows: int = 10) -> List[str]:
    """Отрисовка для шага 0-офис. Правило отрисовки живёт У ПРОИЗВОДИТЕЛЯ —
    вторая копия у читателя разошлась бы с ним молча (ADR-220)."""
    head = ["— тесты, зелёные ПО ПОСТРОЕНИЮ (ADR-543) —"]
    return head + ["   " + line for line in report(doc, max_rows=max_rows)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", default=str(_REPO_ROOT))
    ap.add_argument("--instrument", default=DEFAULT_INSTRUMENT)
    ap.add_argument("--module", default=DEFAULT_MODULE)
    ap.add_argument("--func-prefix", default=DEFAULT_FUNC_PREFIX)
    ap.add_argument("--test-file", action="append", default=None,
                    help="явный файл теста (можно повторять); умолчание — все, "
                         "называющие прибор")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--limit-decisions", type=int, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-rows", type=int, default=25)
    args = ap.parse_args(argv)

    doc = run_differential(Path(args.root), instrument=args.instrument,
                           module=args.module, func_prefix=args.func_prefix,
                           test_files=args.test_file, workers=args.workers,
                           timeout=args.timeout,
                           limit_decisions=args.limit_decisions)
    if not args.no_write:
        dest = Path(args.out) if args.out else Path(args.root) / DEFAULT_LEDGER
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(doc, str(dest))
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        for line in report(doc, max_rows=args.max_rows):
            print(line)
    if str(doc.get("status")) != "OK":
        return 2
    counts = observed(doc, "counts", kind=dict)
    if counts is None:
        print("НЕ ИЗМЕРЕНО — в артефакте нет поля `counts`")
        return 2
    return 1 if any(counts.get(v) for v in FINDING_VERDICTS) \
        or counts.get(VERDICT_UNMEASURED) else 0


if __name__ == "__main__":
    raise SystemExit(main())
