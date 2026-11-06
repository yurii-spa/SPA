"""Помощник записи: помечается ПУТЬ, а не ПЭЙЛОАД (цикл #1053).

Авария, восстановленная здесь в её НАСТОЯЩЕМ месте: `_WRITE_ANY_ARG` просматривал
ВСЕ аргументы вызова помощника, поэтому значение, СОБРАННОЕ ИЗ ЧТЕНИЙ, объявлялось
записанным. Замер репозитория: 22 ложных атрибуции записи в 10 файлах, и одна
доезжала до вердикта флота — `B7:contradiction:com.spa.site_freshness`, находка
WARN, которой НЕТ в мире, и она ПРЯТАЛА истинный вердикт агента (`contradiction`
возвращается ДО расчёта покрытия).

Контроль двусторонний НАМЕРЕННО: ошибка этой правки идёт в сторону ТИШИНЫ (не
заметить настоящую запись), а тишина дороже шума — поэтому ниже проверяется не
только исчезновение ложной записи, но и сохранность настоящих, включая помощника,
у которого путь стоит ВТОРЫМ, помощника с путём по КЛЮЧУ и помощника, чьё тело
разобрать не удалось (он обязан остаться ГРОМКИМ, каким и был).

Только stdlib. Файл не зависит ни от календаря, ни от номера процесса, ни от
git-окружения: все сцены — текст исходника, разбираемый `ast`.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
from pathlib import Path

from spa_core.monitoring import artifact_contract, artifact_io_scan

REPO = Path(__file__).resolve().parents[2]


# ── 1. АВАРИЯ В ЕЁ НАСТОЯЩЕМ МЕСТЕ ──────────────────────────────────────────────

def test_site_freshness_monitor_does_not_write_the_shelf():
    """Сторож сайта витрину только ЧИТАЕТ — и так обязан выглядеть в сканере.

    `scripts/site_freshness_monitor.py` трогает `landing/src/data/site_numbers.json`
    ровно двумя способами: `.exists()` и `.read_text()`. Запись ему приписывал
    вызов `_atomic_write(_REPORT, report)`, где `report` происходит от
    `evaluate(..., site_numbers=site_numbers, ...)`, то есть от ПРОЧИТАННОЙ
    витрины. Витрина — предмет №2 границы владельца (числа сайта), и ложный
    писатель у неё дороже, чем у любого другого файла дерева.
    """
    got = artifact_io_scan.scan_file(REPO / "scripts" / "site_freshness_monitor.py")
    kinds = got.get("site_numbers.json", set())
    assert artifact_io_scan.WRITE not in kinds, (
        "витрина сайта снова числится ЗАПИСАННОЙ сторожем свежести; "
        f"получено {sorted(kinds)}")
    assert artifact_io_scan.READ in kinds, (
        "чтение витрины пропало — это уже ошибка в сторону ТИШИНЫ, "
        "а она дороже шума")


def test_site_freshness_verdict_is_no_longer_a_false_contradiction():
    """Вердикт флота об этом агенте — не ложное ПРОТИВОРЕЧИЕ, а его покрытие.

    Положительный контроль именно на ВЕРДИКТЕ, а не только на сканере: между ними
    лежит `check_agent`, который на `contradiction` выходит ДО расчёта покрытия, —
    то есть ложная находка не просто добавляла строку, а СКРЫВАЛА ответ.
    """
    rows = {r["label"]: r for r in artifact_contract.audit_fleet(REPO)["rows"]}
    row = rows.get("com.spa.site_freshness")
    assert row is not None, "агент выбыл из переписи контрактов — это другой вопрос (B7:left_census)"
    assert row["verdict"] != artifact_contract.CONTRADICTION, (
        "вернулось ложное противоречие: "
        f"{row.get('undeclared_writes')}")
    coverage = row.get("coverage") or {}
    assert coverage.get("declared") == len(coverage.get("confirmed") or []), (
        "покрытие агента перестало быть полным — вердикт обязан это НАЗЫВАТЬ, "
        f"а не молчать: {coverage}")


def test_the_whole_fleet_has_no_contradiction_from_a_payload_argument():
    """Ни одно ПРОТИВОРЕЧИЕ флота не стои́т на аргументе с данными.

    Проверяется не «противоречий ноль» (это свойство дня, а не кода), а то, что
    у каждого оставшегося противоречия названный артефакт действительно виден
    записанным в позиции ПУТИ собственного модуля агента.
    """
    for row in artifact_contract.audit_fleet(REPO)["rows"]:
        if row.get("verdict") != artifact_contract.CONTRADICTION:
            continue
        module_file = REPO / (row["module"].replace(".", "/") + ".py")
        if not module_file.is_file():
            continue
        written = {a.split("/")[-1]
                   for a, kinds in artifact_io_scan.scan_file(module_file).items()
                   if artifact_io_scan.WRITE in kinds}
        for name in row.get("undeclared_writes") or ():
            assert name.split("/")[-1] in written, (
                f"{row['label']}: противоречие названо по артефакту {name}, "
                f"которого модуль не пишет — это ложная находка")


# ── 2. ПОЗИЦИЯ ПУТИ, ИЗМЕРЕННАЯ ПО ТЕЛУ ПОМОЩНИКА ──────────────────────────────

def _scan(src: str) -> dict:
    return artifact_io_scan.scan_source(src)


_PAYLOAD_SCENE = '''
import json, os
REPORT = "own_report.json"
SOURCE = "foreign_source.json"

def _atomic_write(path, data):
    tmp = str(path) + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(json.dumps(data))
    os.replace(tmp, path)

def run():
    source = json.loads(open(SOURCE).read())
    report = build(source=source)
    _atomic_write(REPORT, report)
'''


def test_payload_argument_is_not_a_writer():
    """Сцена аварии в миниатюре: путь arg0, данные arg1, имя источника в данных."""
    got = _scan(_PAYLOAD_SCENE)
    assert artifact_io_scan.WRITE in got.get("own_report.json", set()), \
        "настоящая запись отчёта потеряна"
    assert artifact_io_scan.WRITE not in got.get("foreign_source.json", set()), \
        "прочитанный источник снова объявлен записанным"
    assert artifact_io_scan.READ in got.get("foreign_source.json", set())


_PATH_SECOND_SCENE = '''
import json, os
OUT = "second_position.json"
SOURCE = "read_only.json"

def _atomic_write_rows(rows, out):
    with open(out, "w") as fh:
        fh.write(json.dumps(rows))

def run():
    rows = json.loads(open(SOURCE).read())
    _atomic_write_rows(rows, OUT)
'''


def test_path_may_stand_second_and_is_still_found():
    """Обратный контроль: у помощника путь ВТОРЫМ — и он обязан находиться.

    Это та самая причина, по которой `_WRITE_ANY_ARG` вообще появился, и
    починка, потерявшая такой путь, была бы ошибкой в сторону тишины.
    """
    got = _scan(_PATH_SECOND_SCENE)
    assert artifact_io_scan.WRITE in got.get("second_position.json", set()), \
        "путь во ВТОРОЙ позиции потерян — починка ушла в сторону тишины"
    assert artifact_io_scan.WRITE not in got.get("read_only.json", set())


_KEYWORD_SCENE = '''
import json, os
DEST = "by_keyword.json"
SOURCE = "read_only.json"

def _atomic_write(path, data):
    with open(path, "w") as fh:
        fh.write(json.dumps(data))

def run():
    data = json.loads(open(SOURCE).read())
    _atomic_write(data=data, path=DEST)
'''


def test_path_passed_by_keyword_is_found():
    """Путь переданный КЛЮЧОМ — позиции нет, и ответ даёт имя параметра."""
    got = _scan(_KEYWORD_SCENE)
    assert artifact_io_scan.WRITE in got.get("by_keyword.json", set()), \
        "путь по ключу потерян"
    assert artifact_io_scan.WRITE not in got.get("read_only.json", set())


_UNRESOLVED_SCENE = '''
import json
DEST = "unresolved_dest.json"
SOURCE = "unresolved_source.json"

def run():
    data = json.loads(open(SOURCE).read())
    # Определения `_write_json` в этом модуле НЕТ — позиция пути не разобрана.
    _write_json(DEST, data)
'''


def test_unresolved_helper_stays_loud():
    """Помощника здесь не определяли ⇒ прежнее ГРОМКОЕ поведение, а не тишина.

    Третий исход (инв. #17) обязан быть отличим от «позиция названа»: не
    разобрали — говорим обо всех аргументах, как и до правки. Тишина на этом
    месте была бы потерей настоящих писателей в каждом модуле, который зовёт
    чужого помощника.
    """
    got = _scan(_UNRESOLVED_SCENE)
    assert artifact_io_scan.WRITE in got.get("unresolved_dest.json", set()), \
        "неразобранный помощник перестал называть путь"


_DISAGREEING_SCENE = '''
import json, os

def _atomic_write(path, data):
    with open(path, "w") as fh:
        fh.write(json.dumps(data))

class Other:
    pass

def _atomic_write(data, path):          # noqa: F811 — два определения СПОРЯТ
    with open(path, "w") as fh:
        fh.write(json.dumps(data))

def run():
    _atomic_write("ambiguous.json", {})
'''


def test_disagreeing_definitions_are_named_not_guessed():
    """Два определения спорят о позиции ⇒ `None`, то есть прежнее поведение.

    Выбрать одно из двух значило бы вывести ответ из догадки — а догадка здесь
    и есть предмет правки.
    """
    tree = ast.parse(_DISAGREEING_SCENE)
    spots = artifact_io_scan.write_helper_paths(tree)
    assert "_atomic_write" in spots, "спор определений вообще не замечен"
    assert spots["_atomic_write"] is None, (
        "позиция выбрана при споре определений — это догадка, "
        f"получено {spots['_atomic_write']}")
    assert artifact_io_scan.WRITE in _scan(_DISAGREEING_SCENE).get("ambiguous.json", set()), \
        "при споре определений путь обязан остаться названным"


def test_resolver_reads_the_real_helper_of_the_real_accident():
    """Позиция пути у настоящего помощника настоящего файла — ноль, и это ЗАМЕР."""
    tree = ast.parse((REPO / "scripts" / "site_freshness_monitor.py").read_text(encoding="utf-8"))
    spots = artifact_io_scan.write_helper_paths(tree)
    assert spots.get("_atomic_write") == (0, "path"), (
        "позиция пути у `_atomic_write` сторожа сайта больше не разбирается; "
        f"получено {spots.get('_atomic_write')}")


# ── 3. ОБЪЯВЛЕНИЕ МОСТА ↔ ЕГО СОБСТВЕННЫЕ ЗАПИСИ ───────────────────────────────

def test_bridge_declares_every_artifact_its_own_module_writes():
    """Что мост ПИШЕТ сам — то и объявлено в `PRODUCES` (кроме внутренней памяти).

    Положительный контроль правки этого же цикла: до неё `PRODUCES` не называл
    `data/ci_control_verdict.json` и `data/worker_axis_census.json`, хотя
    `architecture/manifest.json` числил их продуктами того же агента — два
    объявления ОДНОГО контракта расходились, и сверка кода с объявлением
    отвечала ПРОТИВОРЕЧИЕ.

    Списка-исключений у проверки нет намеренно: вопрос задаётся ровно о
    СОБСТВЕННЫХ записях модуля, поэтому артефакт, который пишет подпроцесс
    (`data/no_regression_census.json`), сюда не попадает по построению — и
    дописывать для него имя в базу не приходится.
    """
    from spa_core.monitoring import findings_bridge

    module_file = REPO / "spa_core" / "monitoring" / "findings_bridge.py"
    written = {a.split("/")[-1]
               for a, kinds in artifact_io_scan.scan_file(module_file).items()
               if artifact_io_scan.WRITE in kinds}
    declared = {p.split("/")[-1] for p in findings_bridge.PRODUCES}
    internal = {p.split("/")[-1] for p in findings_bridge.INTERNAL_WRITES}
    undeclared = sorted(written - declared - internal)
    assert not undeclared, (
        "собственный модуль моста пишет артефакт, которого нет ни в `PRODUCES`, "
        f"ни в `INTERNAL_WRITES`: {undeclared} — объявить его тем или другим "
        "(это ровно та находка B7, которую закрыл цикл #1053)")

# ── 4. ОБЪЯВЛЕНИЕ КАНОНИЧЕСКИХ ДВЕРЕЙ ↔ ИХ НАСТОЯЩИЕ ПОДПИСИ ────────────────────

def test_canonical_door_path_positions_match_the_real_module():
    """`CANONICAL_PATH_ARG` сверяется с подписями `spa_core/utils/atomic.py`.

    Таблица объявлена руками по одной причине: `write_doors` принимает ТЕКСТ одного
    исходника и файловой двери не имеет по контракту, а определения этих шести живут в
    другом модуле. Объявление, которое само себе мерка, и есть тот дефект, против
    которого написан весь файл, — поэтому истину здесь добывает ТОТ ЖЕ резолвер
    (`_path_param_index`), которым разбираются локальные помощники, а не второй список.

    Разойдись объявление с кодом (переименовали параметр, поменяли порядок) — краснеет
    этот тест, а не молчит таблица.
    """
    atomic = REPO / "spa_core" / "utils" / "atomic.py"
    assert atomic.is_file(), f"нет модуля канонических дверей: {atomic}"
    tree = ast.parse(atomic.read_text(encoding="utf-8"))

    measured: dict[str, int | None] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name in artifact_io_scan.CANONICAL_DOORS:
            measured[node.name] = artifact_io_scan._path_param_index(node)

    unmeasured = sorted(n for n, idx in measured.items() if idx is None)
    assert not unmeasured, (
        "позицию пути у канонических дверей больше не удаётся разобрать по их телу: "
        f"{unmeasured} — это НЕ ИЗМЕРЕНО, и объявление в таблице перестало быть "
        "проверяемым; сверять его стало нечем")

    declared = dict(artifact_io_scan.CANONICAL_PATH_ARG)
    assert declared == measured, (
        "объявление `CANONICAL_PATH_ARG` разошлось с настоящими подписями "
        f"`spa_core/utils/atomic.py`:\n  объявлено: {declared}\n  измерено:  {measured}")

    missing = sorted(artifact_io_scan.CANONICAL_DOORS - set(measured))
    assert not missing, (
        f"канонические двери {missing} не определены в `spa_core/utils/atomic.py` — "
        "объявление о них нечем проверить, и молчать об этом нельзя")


def test_intraday_equity_does_not_write_the_live_track():
    """Авария ВТОРОГО читателя в её настоящем месте: живой трек — не продукт этого модуля.

    `spa_core/monitoring/intraday_equity.py` читает `data/equity_curve_daily.json` и
    пишет свой `intraday_equity.json`. До цикла #1053 ветка канонических дверей
    помечала ВСЕ аргументы, и живой трек числился записанным — через `write_doors` это
    уходило в `slo_keepability`, то есть в НАЗНАЧЕНИЕ СРОКОВ ГОДНОСТИ.
    """
    src = (REPO / "spa_core" / "monitoring" / "intraday_equity.py").read_text(encoding="utf-8")
    doors = artifact_io_scan.write_doors(src)
    for name in ("equity_curve_daily.json", "data/equity_curve_daily.json"):
        assert name not in doors, (
            f"живой трек снова числится записанным этим модулем: {name} -> {doors.get(name)}")
    assert any("intraday_equity.json" in k for k in doors), (
        "собственный продукт модуля пропал из ответа — ошибка в сторону ТИШИНЫ")


# ── 5. ПОРЯДОК АРГУМЕНТОВ У КАНОНИЧЕСКОЙ ДВЕРИ ─────────────────────────────────

def test_no_call_site_inverts_a_canonical_door():
    """Ни один вызов канонической двери не ставит путь мимо объявленной позиции.

    Первая НАСТОЯЩАЯ находка исправленного сканера (цикл #1053), и она не про
    сканер: `scripts/book_second_record.py` и `scripts/build_knowledge_graph.py`
    зовут `atomic_save(ПУТЬ, данные)`, тогда как подпись — `atomic_save(data, path)`.
    Каноническая дверь на это ОТКАЗЫВАЕТ fail-CLOSED
    (`ValueError: path must be a str/PathLike, got dict`) — и правильно, — но у обоих
    вызовов рядом стои́т широкий `except Exception`, который отказ ГЛОТАЕТ, после чего
    запись уходит в рукописный неатомарный запас (`write_text` / `open(..., "w")`).

    То есть инвариант #5 (атомарная запись через `atomic_save`) не исполнялся в этих
    двух местах НИКОГДА, и сказать об этом было нечему: сторож двери числил их за
    ОБЩЕЙ дверью, потому что помечал все аргументы вызова без разбора.

    Население класса на день правки ИЗМЕРЕНО и равно **2** — обе починены. Проверка
    держит ноль; найдётся третий — краснеет сразу, а не через два месяца.
    """
    hits = []
    for path in sorted(REPO.rglob("*.py")):
        if any(part in {".git", ".claude", "node_modules", "__pycache__"}
               for part in path.parts) or "worktrees" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        module_table = artifact_io_scan._name_table(tree.body)
        for body, is_module in artifact_io_scan._scopes(tree):
            table = (module_table if is_module
                     else artifact_io_scan._name_table(body, seed=module_table))
            for node in artifact_io_scan._own_nodes(body):
                if not isinstance(node, ast.Call):
                    continue
                name = artifact_io_scan._call_name(node)
                idx = artifact_io_scan.CANONICAL_PATH_ARG.get(name)
                if idx is None or len(node.args) <= idx:
                    continue
                on_path = artifact_io_scan._names_in(node.args[idx], table)
                elsewhere = set()
                for i, arg in enumerate(node.args):
                    if i != idx:
                        elsewhere |= artifact_io_scan._names_in(arg, table)
                # Имя артефакта найдено, но НЕ на позиции пути ⇒ аргументы перевёрнуты.
                if not on_path and elsewhere:
                    hits.append(f"{path.relative_to(REPO)}:{node.lineno} "
                                f"{name}(...) — имя артефакта на ДРУГОЙ позиции: "
                                f"{sorted(elsewhere)}")
    assert not hits, (
        "вызов канонической двери записи ставит путь мимо объявленной позиции — дверь "
        "ОТКАЖЕТ, а соседний `except` отказ проглотит, и запись уйдёт в неатомарный "
        "запас МОЛЧА (инв. #5):\n  " + "\n  ".join(hits))
