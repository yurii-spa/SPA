"""Контроли переписи односторонности правила принадлежности (заказ G87 п. 2).

Каждый тест ниже — положительный контроль: он воспроизводит ровно ту форму
слепоты, ради которой прибор написан, и КРАСНЕЕТ, если звено порвать
(`.claude/rules/deployment.md`, «проверка сторожа сторожей»). Проверка, никогда
не видевшая настоящей слепоты, — украшение.

Сцена — одноразовое дерево в `tmp_path`: живое дерево репозитория прибор не
трогает, часов, pid, сети и git-окружения не спрашивает вовсе (три семейства
бомб из правила доставки здесь отсутствуют по построению — единственный вход
меры есть ПУТЬ).
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from spa_core.monitoring import membership_reach_census as mrc
from spa_core.monitoring.membership_reach_census import (
    BEYOND,
    DIRECT,
    NAME_ATTR,
    NAME_IN_TREE,
    NAME_OUTCOMES,
    NAME_OUTSIDE,
    NAME_UNRESOLVED,
    NOT_REACHED,
    OUTCOMES,
    VIA_HELPER,
    build_graph,
    measure,
    verdict,
)

MODULE_PATH = pathlib.Path(mrc.__file__)


# ───────────────────────────── сцена ──────────────────────────────────────────

def _tree(tmp_path: pathlib.Path, files: dict[str, str]) -> str:
    """Одноразовое дерево. Каркас поверхности кладётся всегда — без него
    «поверхность не достигнута» было бы свойством пустой сцены, а не правила."""
    base = {
        "spa_core/__init__.py": "",
        "spa_core/risk/__init__.py": "",
        "spa_core/risk/policy.py": "APPROVED = False\n",
        "spa_core/governance/__init__.py": "",
        "spa_core/governance/kill_switch.py": "HARD = 0.10\n",
        "spa_core/tests/__init__.py": "",
        # Сосед-омоним: advisory-слой, который НЕ есть risk-политика. Сравнение
        # подстрокой поймало бы его — и население критерия наполнилось бы
        # анализаторами. Это капкан ADR-491, и он здесь воспроизведён.
        "riskwire/__init__.py": "",
        "riskwire/feed.py": "RATE = 1\n",
        # НЕ-python файл, который НЕ РАЗБИРАЕТСЯ как python (скобка не закрыта).
        # Попади он в граф — он стал бы «не разобранным», и мутация «брать из
        # дерева ВСЕ файлы» прошла бы молча. Положительный контроль на фильтр.
        "notes.json": '{"a": 1\n',
    }
    base.update(files)
    for rel, text in base.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return str(tmp_path)


# ────────────────────── находка: поверхность через помощника ──────────────────

def test_surface_reached_through_one_helper_is_the_finding(tmp_path):
    """Авария заказа дословно: тест не импортирует risk, помощник — импортирует."""
    root = _tree(tmp_path, {
        "scripts/__init__.py": "",
        "scripts/drill.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_drill.py": "import scripts.drill\n",
    })
    doc = measure(root, max_depth=3)

    assert doc["per_surface"]["risk"][VIA_HELPER] == 1
    assert doc["per_surface"]["risk"][DIRECT] == 0
    row = [f for f in doc["findings"] if f["surface"] == "risk"][0]
    assert row["file"] == "spa_core/tests/test_drill.py"
    assert row["depth"] == 1
    assert row["chain"] == ["spa_core/tests/test_drill.py", "scripts/drill.py"]
    assert verdict(doc) == "rule_is_one_sided"


def test_breaking_the_helper_link_turns_the_finding_into_not_reached(tmp_path):
    """Обратная сторона того же контроля: звено порвано ⇒ находки нет.

    Без этого теста мера могла бы объявлять находку ВСЕГДА, и первый тест был
    бы зелёным по построению (урок цикла #722)."""
    root = _tree(tmp_path, {
        "scripts/__init__.py": "",
        "scripts/drill.py": "import json\n",          # звено порвано
        "spa_core/tests/test_drill.py": "import scripts.drill\n",
    })
    doc = measure(root, max_depth=3)

    assert doc["per_surface"]["risk"][VIA_HELPER] == 0
    assert doc["per_surface"]["risk"][NOT_REACHED] == 1
    assert verdict(doc) == "no_helper_reach_found"


def test_direct_import_is_not_a_finding_the_rule_already_sees_it(tmp_path):
    """Прямой импорт — не слепота: сосед видит пару сам."""
    root = _tree(tmp_path, {
        "spa_core/tests/test_policy.py": "from spa_core.risk.policy import APPROVED\n",
    })
    doc = measure(root, max_depth=3)

    assert doc["per_surface"]["risk"][DIRECT] == 1
    assert doc["per_surface"]["risk"][VIA_HELPER] == 0
    assert doc["findings"] == []


def test_second_spelling_of_the_package_is_seen_through_a_helper(tmp_path):
    """`from risk.policy import …` — главный капкан ADR-491, теперь за помощником.

    Тесты кладут в `sys.path` то корень, то `spa_core/`; правило, знающее одно
    написание, теряет дорогу целиком."""
    root = _tree(tmp_path, {
        "scripts/__init__.py": "",
        "scripts/helper.py": "from risk.policy import APPROVED\n",
        "spa_core/tests/test_helper.py": "import scripts.helper\n",
    })
    doc = measure(root, max_depth=3)

    assert doc["per_surface"]["risk"][VIA_HELPER] == 1


# ───────────────────── граница имени, а не подстрока ──────────────────────────

def test_riskwire_helper_is_not_counted_as_risk_surface(tmp_path):
    """`riskwire` — не `risk`. Сравнение подстрокой наполнило бы население
    advisory-анализаторами: ровно та подмена именем, против которой написан
    сосед."""
    root = _tree(tmp_path, {
        "scripts/__init__.py": "",
        "scripts/wire.py": "from riskwire.feed import RATE\n",
        "spa_core/tests/test_wire.py": "import scripts.wire\n",
    })
    doc = measure(root, max_depth=3)

    assert doc["per_surface"]["risk"][VIA_HELPER] == 0
    assert doc["per_surface"]["risk"][NOT_REACHED] == 1


# ──────────────────────── предел глубины — третий исход ───────────────────────

def test_chain_longer_than_the_limit_is_a_third_outcome_not_a_clean_answer(tmp_path):
    """Дорога ЕСТЬ, но длиннее предела: это не находка и не «чисто».

    Выдать такую пару за `surface_not_reached` значило бы объявить чистым то,
    что не измерено (инв. #17)."""
    root = _tree(tmp_path, {
        "scripts/__init__.py": "",
        "scripts/a.py": "import scripts.b\n",
        "scripts/b.py": "import scripts.c\n",
        "scripts/c.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_a.py": "import scripts.a\n",
    })
    near = measure(root, max_depth=1)
    assert near["per_surface"]["risk"][BEYOND] == 1
    assert near["per_surface"]["risk"][VIA_HELPER] == 0
    assert near["per_surface"]["risk"][NOT_REACHED] == 0

    far = measure(root, max_depth=3)
    assert far["per_surface"]["risk"][VIA_HELPER] == 1
    assert far["per_surface"]["risk"][BEYOND] == 0
    assert [f["depth"] for f in far["findings"] if f["surface"] == "risk"] == [3]


def test_the_limit_is_an_input_not_a_constant(tmp_path):
    """Предел объявлен ВХОДОМ: иначе «названный предел» был бы словом."""
    root = _tree(tmp_path, {
        "scripts/__init__.py": "",
        "scripts/a.py": "import scripts.b\n",
        "scripts/b.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_a.py": "import scripts.a\n",
    })
    assert measure(root, max_depth=1)["counts"][BEYOND] == 1
    assert measure(root, max_depth=2)["counts"][VIA_HELPER] == 1


# ─────────────────────────── ось ИМЕНИ: три исхода ────────────────────────────

def test_unresolved_in_tree_name_is_its_own_third_outcome(tmp_path):
    """Имя наше, файла нет: дуга МОГЛА вести к поверхности ⇒ не ноль и не ответ."""
    root = _tree(tmp_path, {
        "scripts/__init__.py": "",
        "spa_core/tests/test_ghost.py": "import scripts.nosuchmodule\n",
    })
    graph = build_graph(root)

    assert graph["name_counts"][NAME_UNRESOLVED] >= 1
    assert "scripts.nosuchmodule" in graph["unresolved_names"]
    doc = measure(root, max_depth=3, graph=graph)
    assert doc["unresolved_examples"]


def test_outside_tree_name_is_named_not_counted_as_unresolved(tmp_path):
    """stdlib / сторонний пакет — объявленная односторонность, а не слепота."""
    root = _tree(tmp_path, {
        "spa_core/tests/test_outside.py": "import json\nimport collections.abc\n",
    })
    graph = build_graph(root)

    assert graph["name_counts"][NAME_OUTSIDE] >= 2
    assert "json" not in graph["unresolved_names"]


def test_attribute_of_a_resolved_module_is_not_unresolved(tmp_path):
    """`from a.b import C` даёт и `a.b.C`; это атрибут, и слепоты в нём нет.

    Без отдельного исхода такие имена залили бы ведро третьего исхода и
    «нижняя граница» потеряла бы смысл."""
    root = _tree(tmp_path, {
        "spa_core/tests/test_attr.py": "from spa_core.risk.policy import APPROVED\n",
    })
    graph = build_graph(root)

    assert graph["name_counts"][NAME_ATTR] >= 1
    assert graph["name_counts"][NAME_IN_TREE] >= 1
    assert "spa_core.risk.policy.APPROVED" not in graph["unresolved_names"]


# ───────────── относительный импорт: то, чего сосед не видит ПО ПОСТРОЕНИЮ ────

def test_relative_import_edge_is_resolved_by_path_not_guessed(tmp_path):
    """`from . import policy` имени не несёт — но путь несёт.

    Сосед пропускает относительный импорт намеренно и по верной причине. В
    замыкании имя выводится из МЕСТА файла, поэтому дорога находится."""
    root = _tree(tmp_path, {
        "spa_core/risk/shim.py": "from . import policy\n",
        "scripts/__init__.py": "",
        "scripts/use.py": "import spa_core.risk.shim\n",
        "spa_core/tests/test_rel.py": "import scripts.use\n",
    })
    graph = build_graph(root)
    assert graph["relative_edges_resolved"] >= 1

    doc = measure(root, max_depth=3, graph=graph)
    assert doc["per_surface"]["risk"][VIA_HELPER] == 1


def test_relative_import_invents_no_edge_for_a_missing_target(tmp_path):
    """Обратная сторона: имени, которому в дереве нет файла, дуга НЕ выдумывается.

    Дуга в сам пакет при этом законна и остаётся — `from . import x` исполняет
    `__init__`. Контроль мерит разницу между двумя сценами, а не одно число:
    отсутствующая цель не добавляет ничего, существующая добавляет ровно одну."""
    missing = build_graph(_tree(tmp_path / "missing", {
        "spa_core/risk/shim.py": "from . import nosuch\n",
    }))
    present = build_graph(_tree(tmp_path / "present", {
        "spa_core/risk/shim.py": "from . import policy\n",
    }))

    assert missing["edges"]["spa_core/risk/shim.py"] == {"spa_core/risk/__init__.py"}
    assert present["edges"]["spa_core/risk/shim.py"] == {
        "spa_core/risk/__init__.py", "spa_core/risk/policy.py"}


# ──────────────── объявление путём (self_guards) — не выпадает ────────────────

def test_declared_self_guard_counts_as_seen_by_the_rule(tmp_path):
    """Сторож, который САМ и есть проверка инварианта, объявлен ПУТЁМ.

    Импортировать ему нечего; без учёта объявления он стал бы ложной находкой
    («поверхность не достигнута») у меры, которая знает только импорты."""
    root = _tree(tmp_path, {
        "tests/__init__.py": "",
        "tests/test_security_audit.py": "import os\n",
    })
    doc = measure(root, max_depth=3)

    assert doc["per_surface"]["security"][DIRECT] >= 1
    assert not [f for f in doc["findings"]
                if f["file"] == "tests/test_security_audit.py"]


# ─────────────────── перечень ЗАКРЫТ: сумма равна населению ───────────────────

def test_outcome_list_is_closed_and_sums_to_population(tmp_path):
    """Инв. #17: сумма исходов обязана равняться населению.

    Сверка идёт с населением, посчитанным ДРУГИМ способом (тесты × поверхности),
    а не с суммой самих счётчиков: сверка суммы с собой зелена по построению."""
    root = _tree(tmp_path, {
        "scripts/__init__.py": "",
        "scripts/drill.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_drill.py": "import scripts.drill\n",
        "spa_core/tests/test_plain.py": "import json\n",
        "tests/__init__.py": "",
        "tests/test_gov.py": "from spa_core.governance.kill_switch import HARD\n",
    })
    doc = measure(root, max_depth=3)

    assert sum(doc["counts"][name] for name in OUTCOMES) == doc["population"]
    assert doc["population"] == doc["tests_scanned"] * 3
    for name in OUTCOMES:
        assert name in doc["counts"], name


def test_per_surface_counts_sum_to_the_tests_scanned(tmp_path):
    root = _tree(tmp_path, {
        "spa_core/tests/test_a.py": "import json\n",
        "spa_core/tests/test_b.py": "from spa_core.risk.policy import APPROVED\n",
    })
    doc = measure(root, max_depth=3)

    for surface, local in doc["per_surface"].items():
        assert sum(local.values()) == doc["tests_scanned"], surface


# ───────────────── пустое население — НЕ ИЗМЕРЕНО, а не «чисто» ───────────────

def test_empty_population_refuses_loudly_instead_of_printing_all_zeros(tmp_path):
    """Ноль исходов на пустом населении есть fail-OPEN, тише красного теста
    (урок `pyflakes`, цикл #465)."""
    root = _tree(tmp_path, {})           # ни одного test_*.py
    doc = measure(root, max_depth=3)

    assert doc["population"] == 0
    assert verdict(doc) == "unmeasured"
    assert "НЕ ИЗМЕРЕНО" in mrc.format_report(doc)


def test_absent_tree_is_unmeasured_with_a_named_reason(tmp_path):
    doc = measure(str(tmp_path / "nosuchtree"), max_depth=3)

    assert doc["unmeasured_reason"]
    assert verdict(doc) == "unmeasured"
    assert "НЕ ИЗМЕРЕНО" in mrc.format_report(doc)


def test_unparsed_test_file_is_named_not_silently_dropped(tmp_path):
    """Файл, который не разобрался, не объявляется ни входящим, ни не входящим."""
    root = _tree(tmp_path, {
        "spa_core/tests/test_broken.py": "def (:\n",
        "spa_core/tests/test_ok.py": "import json\n",
    })
    doc = measure(root, max_depth=3)

    assert doc["unparsed_tests"] == ["spa_core/tests/test_broken.py"]
    assert doc["tests_scanned"] == 1
    assert "НЕ ИЗМЕРЕНО" in mrc.format_report(doc)


# ───────────── паритет с соседом: контроль «К правилу, а не вместо» ───────────

def test_parity_with_the_neighbour_population_is_measured_both_ways(tmp_path):
    """Множество «видно соседу» сверяется со счётом САМОГО соседа."""
    root = _tree(tmp_path, {
        "spa_core/tests/test_policy.py": "from spa_core.risk.policy import APPROVED\n",
        "scripts/__init__.py": "",
        "scripts/drill.py": "from spa_core.governance.kill_switch import HARD\n",
        "spa_core/tests/test_drill.py": "import scripts.drill\n",
    })
    doc = measure(root, max_depth=3)
    parity = doc["parity_with_census"]

    assert parity["state"] == "equal", parity
    assert parity["census_pairs"] == parity["direct_pairs"] == 1
    assert "РАВНО" in mrc.format_report(doc)


def test_parity_reports_a_divergence_rather_than_hiding_it(monkeypatch, tmp_path):
    """Контроль самого контроля: разойдись два счёта — отчёт обязан сказать это.

    Паритет, который не умеет краснеть, был бы украшением (правило доставки,
    «проверка сторожа сторожей»)."""
    root = _tree(tmp_path, {
        "spa_core/tests/test_policy.py": "from spa_core.risk.policy import APPROVED\n",
    })
    monkeypatch.setattr(mrc, "census_population",
                        lambda _root: {"surfaces": {"risk": {"files": []},
                                                    "security": {"files": []},
                                                    "architecture": {"files": []}}})
    doc = measure(root, max_depth=3)

    assert doc["parity_with_census"]["state"] == "differs"
    assert doc["parity_with_census"]["n_only_here"] == 1
    assert "ПАРИТЕТ РАСХОДИТСЯ" in mrc.format_report(doc)


def test_parity_failure_is_unmeasured_not_silent(monkeypatch, tmp_path):
    def _boom(_root):
        raise RuntimeError("сосед не сосчитал")
    root = _tree(tmp_path, {"spa_core/tests/test_a.py": "import json\n"})
    monkeypatch.setattr(mrc, "census_population", _boom)
    doc = measure(root, max_depth=3)

    assert doc["parity_with_census"]["state"] == "unmeasured"
    assert "НЕ ИЗМЕРЕНО" in mrc.format_report(doc)


# ──────────── правило принадлежности НЕ переписано второй копией ──────────────

def test_the_membership_rule_is_imported_not_copied():
    """ADR-522 дословно: вторая копия правила и ЕСТЬ дефект.

    Разойдясь, две копии молча дали бы два разных населения у одного критерия —
    именно так три месяца врал `house_view_gap` на трёх омонимах реестра."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    defined: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and \
                node.module.endswith("no_regression_census"):
            imported |= {a.asname or a.name for a in node.names}
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined.add(target.id)

    for borrowed in ("_imported_modules", "_matches", "DECLARED_SURFACES",
                     "TEST_ROOTS"):
        assert borrowed in imported, f"{borrowed} обязан браться у соседа"
        assert borrowed not in defined, f"{borrowed} переопределён — вторая копия"


def test_the_instrument_writes_nothing(tmp_path):
    """ADR-524: артефакт этой переписи стал бы собственным операндом
    «предыдущего прогона», то есть новым членом измеряемого класса.

    Читателем служит шаг 0-офис, зовущий `measure()` напрямую."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else "")
            assert name not in {"atomic_save", "write_text", "write_bytes",
                                "mkdir", "makedirs"}, f"запись: {name}"
            if name == "open":
                mode = [a for a in node.args[1:2]]
                assert not mode or getattr(mode[0], "value", "r") == "r"
    assert "atomic_save" not in source


# ───────────────────────── отчёт как интерфейс ───────────────────────────────

def test_report_names_the_lower_bound_and_all_three_prices(tmp_path):
    """Односторонний ответ обязан называться нижней границей (урок ADR-528)."""
    root = _tree(tmp_path, {
        "scripts/__init__.py": "",
        "scripts/drill.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_drill.py": "import scripts.drill\n",
    })
    text = mrc.format_report(measure(root, max_depth=3))

    assert "НИЖНЯЯ ГРАНИЦА" in text
    assert "имя вне дерева" in text
    assert "имя не разрешено" in text
    assert "дорога длиннее предела" in text
    assert "ADVISORY" in text
    assert "НЕ ДОКЛАДЫВАЕТ" in text


def test_report_prints_every_outcome_including_the_zeros(tmp_path):
    """Инв. #17: ноль обязан быть объявлен, а не отсутствовать."""
    root = _tree(tmp_path, {"spa_core/tests/test_a.py": "import json\n"})
    text = mrc.format_report(measure(root, max_depth=3))

    for name in OUTCOMES:
        assert name in text, name


def test_cli_exit_code_separates_the_three_outcomes(tmp_path, capsys):
    """Три исхода обязаны быть различимы у ЛЮБОГО производителя числа."""
    clean = _tree(tmp_path / "clean", {"spa_core/tests/test_a.py": "import json\n"})
    assert mrc.main(["--root", clean]) == 0

    dirty = _tree(tmp_path / "dirty", {
        "scripts/__init__.py": "",
        "scripts/drill.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_drill.py": "import scripts.drill\n",
    })
    assert mrc.main(["--root", dirty]) == 1

    assert mrc.main(["--root", str(tmp_path / "nosuchtree")]) == 2
    capsys.readouterr()


def test_json_output_carries_the_full_finding_list(tmp_path, capsys):
    """Отчёт режет перечень до двенадцати; `--json` обязан нести все."""
    import json as _json
    files = {"scripts/__init__.py": ""}
    for i in range(15):
        files[f"scripts/h{i}.py"] = "from spa_core.risk.policy import APPROVED\n"
        files[f"spa_core/tests/test_h{i}.py"] = f"import scripts.h{i}\n"
    root = _tree(tmp_path, files)

    assert mrc.main(["--root", root, "--json"]) == 1
    doc = _json.loads(capsys.readouterr().out)
    assert len([f for f in doc["findings"] if f["surface"] == "risk"]) == 15


# ─────────── проводка: у находки есть ЧИТАТЕЛЬ внутри цикла (ADR-526) ────────

def _office_aliases(module_suffix: str) -> tuple[set[str], list[ast.Call]]:
    """Имена, под которыми шаг 0-офис ввёз модуль, и все его вызовы.

    Ищется ФОРМА вызова, а не имя в тексте: имя поймало бы собственный
    комментарий этой же секции, форма ловит зов (урок ADR-414)."""
    office = MODULE_PATH.parents[2] / "scripts" / "consume_office_reports.py"
    tree = ast.parse(office.read_text(encoding="utf-8"))
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module \
                and node.module.endswith(module_suffix):
            aliases |= {a.asname or a.name for a in node.names}
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    return aliases, calls


def test_the_office_step_calls_the_census_and_prints_it():
    """Прибор без артефакта имеет РОВНО одного читателя — шаг 0-офис.

    Порви зов, и находка не дойдёт ни до кого молча: ровно тот вред, который
    мерит ADR-526 (`no_reader_found`). Поэтому звено закреплено тестом, а не
    записью в реестре (запись исполнением не является, ADR-427)."""
    aliases, calls = _office_aliases("membership_reach_census")
    assert aliases, "шаг 0-офис не ввозит перепись вовсе"

    called = {c.func.id for c in calls
              if isinstance(c.func, ast.Name) and c.func.id in aliases}
    assert len(called) == 2, (
        f"офис зовёт {sorted(called)}: нужны и замер, и отрисовка — "
        "открыть артефакт и ничего не напечатать значит прочитать его вхолостую")


def test_the_census_is_not_declared_as_an_artifact_producer():
    """ADR-524 дословно: артефакт этой переписи стал бы собственным операндом.

    Контроль с другой стороны к `test_the_instrument_writes_nothing`: тот
    смотрит в модуль, этот — в манифест. Объявленный продукт без писателя дал
    бы вечный красный у сторожа SLO, чинимый только деплоем (инв. #12)."""
    import json as _json
    manifest = MODULE_PATH.parents[2] / "architecture" / "manifest.json"
    text = manifest.read_text(encoding="utf-8") if manifest.is_file() else "{}"
    assert "membership_reach_census" not in _json.dumps(_json.loads(text))


# ══════════════════════════════════════════════════════════════════════════════
# Контроли, добавленные ПО ИСХОДУ мутационного замера (цикл #743)
#
# Первый замер: 137 применено · 72 убито · **65 выжило** при ЗЕЛЁНОМ контроле на
# шум пересборки — то есть замер честный, и он говорит, что батарея выше дырява.
# Каждый тест ниже убивает названный выживший мутант, а не «добавляет покрытие».
# ══════════════════════════════════════════════════════════════════════════════

def test_the_declared_default_depth_has_the_declared_effect(tmp_path):
    """Предел по умолчанию НАГРУЖЕН: он решает, находка это или третий исход.

    Убивает `MAX_DEPTH = 3 → 4`. Утверждение не тавтологично: оно не повторяет
    константу, а требует, чтобы объявленное число имело объявленное действие —
    дорога длиной 4 обязана быть ЗА пределом, пока предел равен трём."""
    root = _tree(tmp_path, {
        "scripts/__init__.py": "",
        "scripts/a.py": "import scripts.b\n",
        "scripts/b.py": "import scripts.c\n",
        "scripts/c.py": "import scripts.d\n",
        "scripts/d.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_a.py": "import scripts.a\n",
    })
    assert measure(root)["per_surface"]["risk"][BEYOND] == 1
    assert measure(root)["per_surface"]["risk"][VIA_HELPER] == 0
    assert measure(root, max_depth=4)["per_surface"]["risk"][VIA_HELPER] == 1
    assert measure(root)["max_depth"] == mrc.MAX_DEPTH


def test_a_skipped_top_level_directory_is_outside_the_tree(tmp_path):
    """Каталог из объявленного перечня пропуска не есть НАШЕ имя верхнего уровня.

    Убивает `or → and` в фильтре `_top_level_names`: с мутацией `node_modules`
    попал бы в наши имена, и имя оттуда стало бы третьим исходом вместо
    объявленной односторонности «дуга наружу не пройдена»."""
    root = _tree(tmp_path, {
        "node_modules/placeholder.py": "X = 1\n",
        "spa_core/tests/test_vendor.py": "import node_modules.nothing\n",
    })
    graph = build_graph(root)

    assert graph["name_counts"][NAME_OUTSIDE] >= 1
    assert "node_modules.nothing" not in graph["unresolved_names"]
    assert "node_modules" not in graph["top_levels"]


def test_a_top_level_module_file_counts_as_our_name(tmp_path):
    """Имя верхнего уровня бывает ФАЙЛОМ, а не каталогом.

    Убивает `suffix == ".py" → !=`: с мутацией `conftest` перестал бы быть нашим
    именем, и неразрешённое `conftest.nosuch` ушло бы в «вне дерева», то есть
    настоящий третий исход подменился бы объявленной односторонностью."""
    root = _tree(tmp_path, {
        "conftest.py": "X = 1\n",
        "spa_core/tests/test_conf.py": "import conftest.nosuch\n",
    })
    graph = build_graph(root)

    assert "conftest" in graph["top_levels"]
    assert "conftest.nosuch" in graph["unresolved_names"]


def test_attribute_search_reaches_a_single_part_prefix(tmp_path):
    """`from scripts import nosuch` — атрибут пакета, а не слепота.

    Убивает сдвиг нижней границы перебора префиксов (`range(…, 0, -1)` → `1`):
    с мутацией однокоренной префикс не проверялся бы вовсе, и ведро третьего
    исхода залилось бы атрибутами — ровно то, от чего заказ его защищает."""
    root = _tree(tmp_path, {
        "scripts/__init__.py": "",
        "spa_core/tests/test_attr2.py": "from scripts import nosuch\n",
    })
    graph = build_graph(root)

    assert graph["name_counts"][NAME_ATTR] >= 1
    assert "scripts.nosuch" not in graph["unresolved_names"]


def test_a_two_level_relative_import_is_resolved(tmp_path):
    """`from .. import policy` — два уровня вверх, и арифметика обязана быть верной.

    Убивает `range(node.level - 1)` → `- 2`: с мутацией подъём не выполнялся бы,
    цель искалась бы в своём каталоге и дуги не нашлось бы вовсе."""
    root = _tree(tmp_path, {
        "spa_core/risk/sub/shim.py": "from .. import policy\n",
    })
    graph = build_graph(root)

    assert graph["edges"]["spa_core/risk/sub/shim.py"] == {
        "spa_core/risk/__init__.py", "spa_core/risk/policy.py"}


def test_non_python_files_never_enter_the_graph(tmp_path):
    """Фильтр `.py` — не украшение: сцена несёт файл, который как python не
    разбирается ВОВСЕ.

    Убивает «брать из дерева все файлы»: с мутацией `notes.json` стал бы
    «не разобранным», то есть мера доложила бы НЕ ИЗМЕРЕНО о файле, который к
    графу импортов не относится."""
    graph = build_graph(_tree(tmp_path, {}))

    assert graph["unparsed"] == {}
    assert all(f.endswith(".py") for f in graph["files"]), [
        f for f in graph["files"] if not f.endswith(".py")]


def test_name_counts_are_exact_on_a_controlled_scene(tmp_path):
    """Счётчики оси ИМЕНИ сверяются РАВЕНСТВОМ, а не «не меньше».

    Убивает и сдвиг начального значения, и шаг приращения: на сцене из одного
    импорта ответ известен поимённо, и «не меньше» пропустило бы оба."""
    root = _tree(tmp_path, {"spa_core/tests/test_one.py": "import json\n"})
    graph = build_graph(root)

    assert graph["name_counts"] == {NAME_IN_TREE: 0, NAME_ATTR: 0,
                                   NAME_OUTSIDE: 1, NAME_UNRESOLVED: 0}
    # Перечень третьего исхода обязан быть ПУСТ, а не «тоже посчитан»: без этой
    # строки мутация «записывать в него ЛЮБОЕ имя» жила молча, и примеры
    # неразрешённых имён заполнялись бы стандартной библиотекой.
    assert graph["unresolved_names"] == {}


def test_relative_edge_count_is_exact(tmp_path):
    """Счётчик относительных дуг сверяется РАВЕНСТВОМ.

    Это число — объявленная прибавка к зрению соседа, и оно печатается
    читателю; «не меньше нуля» не утверждает о нём ничего."""
    root = _tree(tmp_path, {
        "spa_core/risk/shim.py": "from . import policy\n",
        "spa_core/governance/shim.py": "from . import kill_switch\n",
    })
    # по две дуги на файл: сам пакет (`__init__` исполняется) и названная цель
    assert build_graph(root)["relative_edges_resolved"] == 4


def test_depth_histogram_is_exact(tmp_path):
    """Гистограмма глубин — замер, который печатается как обоснование предела."""
    root = _tree(tmp_path, {
        "scripts/__init__.py": "",
        "scripts/near.py": "from spa_core.risk.policy import APPROVED\n",
        "scripts/far.py": "import scripts.near\n",
        "spa_core/tests/test_near.py": "import scripts.near\n",
        "spa_core/tests/test_far.py": "import scripts.far\n",
    })
    assert measure(root, max_depth=3)["depth_histogram"] == {"1": 1, "2": 1}


def test_the_printed_chain_is_capped_and_the_cap_is_a_parameter(tmp_path):
    """Дорога печатается читателю, и у печати есть объявленный предел.

    Убивает и сдвиг предела, и `<= → <`: без контроля длина печатаемой дороги
    не утверждалась ни одним тестом, то есть находку можно было бы напечатать
    обрезанной молча."""
    files = {"scripts/__init__.py": ""}
    for i in range(11):
        files[f"scripts/h{i}.py"] = f"import scripts.h{i + 1}\n"
    files["scripts/h11.py"] = "from spa_core.risk.policy import APPROVED\n"
    files["spa_core/tests/test_long.py"] = "import scripts.h0\n"
    root = _tree(tmp_path, files)

    row = [f for f in measure(root, max_depth=12)["findings"]
           if f["surface"] == "risk"][0]
    assert row["depth"] == 12
    assert len(row["chain"]) == 9, row["chain"]


def test_the_unmeasured_document_carries_every_key_zeroed(tmp_path):
    """НЕ ИЗМЕРЕНО обязано быть ПОЛНЫМ документом, а не обрубком.

    Читатель отчёта обходит те же ключи; пропади один — отрисовка упала бы, то
    есть третий исход стал бы ошибкой вместо ответа."""
    doc = measure(str(tmp_path / "nosuchtree"))

    assert doc["population"] == 0
    assert doc["relative_edges_resolved"] == 0
    assert doc["files_in_graph"] == 0
    assert doc["counts"] == {name: 0 for name in OUTCOMES}
    assert doc["name_counts"] == {name: 0 for name in NAME_OUTCOMES}
    assert doc["findings"] == [] and doc["depth_histogram"] == {}
    assert doc["parity_with_census"] is None


def _many_findings(tmp_path: pathlib.Path, n: int) -> str:
    files = {"scripts/__init__.py": ""}
    for i in range(n):
        files[f"scripts/m{i}.py"] = "from spa_core.risk.policy import APPROVED\n"
        files[f"spa_core/tests/test_m{i}.py"] = f"import scripts.m{i}\n"
    return _tree(tmp_path, files)


def test_report_truncates_findings_at_twelve_and_says_how_many_remain(tmp_path):
    """Отчёт режет перечень — и ОБЯЗАН сказать, сколько скрыл.

    Убивает сдвиг обоих пределов печати: молча обрезанный перечень есть
    «не измерено», выданное за ответ."""
    text = mrc.format_report(measure(_many_findings(tmp_path, 15), max_depth=3))
    shown = [ln for ln in text.split("\n") if f"[{VIA_HELPER}]" in ln]

    assert len(shown) == 12
    assert "ещё 3 находок(и)" in text


def test_report_does_not_claim_a_remainder_when_there_is_none(tmp_path):
    """Обратная сторона: ровно двенадцать находок ⇒ клаузы об остатке нет."""
    text = mrc.format_report(measure(_many_findings(tmp_path, 12), max_depth=3))

    assert len([ln for ln in text.split("\n") if f"[{VIA_HELPER}]" in ln]) == 12
    assert "ещё" not in text.split("НИЖНЯЯ ГРАНИЦА")[0]


def test_report_truncates_the_unparsed_list_at_five(tmp_path):
    """Не разобранные тесты называются ПОИМЁННО, и у перечня объявленный предел."""
    files = {f"spa_core/tests/test_bad{i}.py": "def (:\n" for i in range(6)}
    files["spa_core/tests/test_good.py"] = "import json\n"
    text = mrc.format_report(measure(_tree(tmp_path, files), max_depth=3))
    line = [ln for ln in text.split("\n") if "тест-файлов не разобрано" in ln][0]

    assert "не разобрано 6" in line
    assert line.count("spa_core/tests/test_bad") == 5


def test_unresolved_examples_are_capped_at_eight_and_three_are_printed(tmp_path):
    """Третий исход печатается примерами, и у обоих пределов есть контроль."""
    files = {"scripts/__init__.py": ""}
    for i in range(10):
        files[f"spa_core/tests/test_g{i}.py"] = f"import scripts.ghost{i}\n"
    doc = measure(_tree(tmp_path, files), max_depth=3)

    assert len(doc["unresolved_examples"]) == 8
    clause = mrc.format_report(doc).split("например: ")[1]
    assert clause.split(")")[0].count(",") == 2      # ровно три имени


def test_parity_divergence_is_capped_but_the_full_count_is_carried(tmp_path):
    """Перечень расхождений режется, а ЧИСЛО расхождений — нет.

    Урезанный перечень без числа и есть «не измерено», выданное за находку."""
    files = {}
    for i in range(10):
        files[f"spa_core/tests/test_p{i}.py"] = (
            "from spa_core.risk.policy import APPROVED\n")
    root = _tree(tmp_path, files)
    doc = measure(root, max_depth=3, graph=None)
    # сосед считает тот же набор; подменяем ЕГО счёт пустым, чтобы разошлось
    import unittest.mock as _mock
    with _mock.patch.object(mrc, "census_population",
                            lambda _r: {"surfaces": {s: {"files": []}
                                                     for s in doc["surfaces"]}}):
        diverged = measure(root, max_depth=3)
    parity = diverged["parity_with_census"]

    assert parity["n_only_here"] == 10
    assert len(parity["only_here"]) == 8


def test_report_prints_the_share_of_roads_the_rule_sees(tmp_path):
    """Доля — головное число ответа заказа, и она обязана быть посчитана."""
    root = _tree(tmp_path, {
        "spa_core/tests/test_direct.py": "from spa_core.risk.policy import APPROVED\n",
        "scripts/__init__.py": "",
        "scripts/h.py": "from spa_core.governance.kill_switch import HARD\n",
        "spa_core/tests/test_helper2.py": "import scripts.h\n",
    })
    text = mrc.format_report(measure(root, max_depth=3))

    assert "дорог до поверхности найдено 2, правило соседа видит 1 из них (50.0 %)" in text


def test_the_share_is_unmeasured_rather_than_a_division_by_zero(tmp_path):
    """Ноль достижимых пар ⇒ доли НЕТ. Напечатать «0 %» значило бы ответить."""
    root = _tree(tmp_path, {"spa_core/tests/test_plain2.py": "import json\n"})
    text = mrc.format_report(measure(root, max_depth=3))

    assert "правило соседа видит 0 из них (НЕ ИЗМЕРЕНО)" in text


def test_cli_prints_the_report_as_text_and_json_only_when_asked(tmp_path, capsys):
    """Две формы вывода — два разных читателя; подмена одной другой молчит."""
    import json as _json
    root = _many_findings(tmp_path, 2)

    assert mrc.main(["--root", root]) == 1
    plain = capsys.readouterr().out
    assert "односторонность правила принадлежности" in plain
    with pytest.raises(_json.JSONDecodeError):
        _json.loads(plain)

    assert mrc.main(["--root", root, "--json"]) == 1
    assert _json.loads(capsys.readouterr().out)["counts"][VIA_HELPER] == 2


# ══════════════════════════════════════════════════════════════════════════════
# Второй проход мутаций: 65 → 34 выживших. Ниже — контроли на выведенное имя
# файла (`_dotted_spellings`), на котором держится ВЕСЬ относительный импорт, и
# на пределы отрисовки. Без них 14 мутантов одного этого места жили молча.
# ══════════════════════════════════════════════════════════════════════════════

def test_a_derived_spelling_never_matches_a_namesake_outside_our_package(tmp_path):
    """`scripts/risk/` — чужой пакет-омоним, и выведенное имя не вправе его
    выдать за нашу risk-поверхность.

    Тот же капкан, что `riskwire`, но на ДРУГОМ конце: там подстрока в
    объявленном префиксе, здесь — ВЫВЕДЕННОЕ из пути имя. Убивает
    `parts[0] == "spa_core" → !=`: с мутацией `scripts/risk/__init__.py` получил
    бы второе написание `risk`, и чужой каталог стал бы нашей поверхностью."""
    root = _tree(tmp_path, {
        "scripts/__init__.py": "",
        "scripts/risk/__init__.py": "",
        "scripts/risk/feed.py": "RATE = 1\n",
        "scripts/risk/user.py": "from . import feed\n",
        "spa_core/tests/test_namesake.py": "import scripts.risk.user\n",
    })
    doc = measure(root, max_depth=3)

    assert doc["per_surface"]["risk"][VIA_HELPER] == 0
    assert doc["per_surface"]["risk"][NOT_REACHED] == 1


def test_the_bare_spelling_is_load_bearing_for_a_surface_declared_without_the_package(tmp_path):
    """Три объявленных префикса соседа не несут `spa_core.` вовсе
    (`lint_llm_forbidden`, `lint_forbidden_imports`, `build_architecture_manifest`).

    Для них ВТОРОЕ написание — единственная дорога, и убить его значит потерять
    поверхность целиком. Убивает `len(parts) > 1 → > 2` и `parts[1:] → parts[2:]`."""
    root = _tree(tmp_path, {
        "spa_core/lint_llm_forbidden.py": "FORBIDDEN = True\n",
        "spa_core/mid/__init__.py": "",
        "spa_core/mid/h.py": "from .. import lint_llm_forbidden\n",
        "spa_core/tests/test_bare.py": "import spa_core.mid.h\n",
    })
    doc = measure(root, max_depth=3)

    assert doc["per_surface"]["security"][VIA_HELPER] == 1


def test_a_package_init_target_keeps_the_package_name(tmp_path):
    """`from .. import risk` ведёт в `__init__` пакета, и выведенное имя обязано
    быть ИМЕНЕМ ПАКЕТА.

    Убивает и обрезку на два элемента вместо одного, и «не выводить имя вовсе»:
    в обоих случаях дорога до поверхности исчезает молча, а исчезнувшая дорога
    читается как «чисто»."""
    root = _tree(tmp_path, {
        "spa_core/mid2/__init__.py": "",
        "spa_core/mid2/h.py": "from .. import risk\n",
        "spa_core/tests/test_pkg.py": "import spa_core.mid2.h\n",
    })
    doc = measure(root, max_depth=3)

    assert doc["per_surface"]["risk"][VIA_HELPER] == 1
    assert doc["findings"][0]["chain"][:2] == [
        "spa_core/tests/test_pkg.py", "spa_core/mid2/h.py"]


def test_a_non_python_top_level_file_is_not_our_name(tmp_path):
    """Сцена несёт `notes.json`; его основа НЕ есть наше имя верхнего уровня.

    Убивает «считать своим именем основу ЛЮБОГО файла»: с мутацией имя из
    `notes.*` ушло бы в третий исход, то есть мера доложила бы о слепоте там,
    где её нет."""
    root = _tree(tmp_path, {
        "spa_core/tests/test_notes.py": "import notes.anything\n",
    })
    graph = build_graph(root)

    assert "notes" not in graph["top_levels"]
    assert graph["name_counts"][NAME_OUTSIDE] == 1
    assert graph["unresolved_names"] == {}


def test_a_directory_without_an_init_resolves_to_nothing(tmp_path):
    """Каталог без `__init__.py` — наше имя верхнего уровня, но НЕ модуль.

    Убивает «первый же префикс считать разрешённым»: с мутацией неразрешимое
    `data.foo.x` объявлялось бы атрибутом, то есть третий исход гасился бы
    молча — ровно то, ради чего заказ его требует."""
    root = _tree(tmp_path, {
        "data/snapshot.json": "{}\n",
        "spa_core/tests/test_data.py": "from data.foo import x\n",
    })
    graph = build_graph(root)

    assert "data" in graph["top_levels"]
    assert graph["name_counts"][NAME_UNRESOLVED] == 2
    assert graph["name_counts"][NAME_ATTR] == 0
    assert sorted(graph["unresolved_names"]) == ["data.foo", "data.foo.x"]


def test_unresolved_names_carry_how_often_each_was_seen(tmp_path):
    """Частота нужна порядку примеров: он сортирует по ней.

    Убивает и сдвиг начального значения счётчика, и шаг приращения."""
    root = _tree(tmp_path, {
        "scripts/__init__.py": "",
        "spa_core/tests/test_g1.py": "import scripts.ghost\n",
        "spa_core/tests/test_g2.py": "import scripts.ghost\n",
    })
    assert build_graph(root)["unresolved_names"] == {"scripts.ghost": 2}


def test_parity_caps_the_census_only_side_too_and_carries_its_count(tmp_path):
    """Расхождение двустороннее, и у ВТОРОЙ стороны тот же предел и то же число.

    Убивает предел, оставленный без контроля: урезанная половина перечня без
    числа есть «не измерено», выданное за находку."""
    import unittest.mock as _mock
    root = _tree(tmp_path, {"spa_core/tests/test_a.py": "import json\n"})
    fake = {"surfaces": {"risk": {"files": [f"tests/test_x{i}.py" for i in range(10)]},
                         "security": {"files": []},
                         "architecture": {"files": []}}}
    with _mock.patch.object(mrc, "census_population", lambda _r: fake):
        parity = measure(root, max_depth=3)["parity_with_census"]

    assert parity["n_only_in_census"] == 10
    assert len(parity["only_in_census"]) == 8


def test_report_omits_the_histogram_line_when_there_are_no_findings(tmp_path):
    """Пустая гистограмма, напечатанная как строка, читается как замер."""
    root = _tree(tmp_path, {"spa_core/tests/test_a.py": "import json\n"})
    assert "глубина находок" not in mrc.format_report(measure(root, max_depth=3))


def test_report_omits_the_unparsed_line_when_everything_parsed(tmp_path):
    """Та же осторожность: «не разобрано» без имён есть ложная тревога."""
    root = _tree(tmp_path, {"spa_core/tests/test_a.py": "import json\n"})
    assert "не разобрано" not in mrc.format_report(measure(root, max_depth=3))


def test_report_counts_the_remainder_exactly_at_the_boundary(tmp_path):
    """Тринадцать находок: предел печати двенадцать ⇒ остаток РОВНО один.

    Замер на 15 и на 12 оба проходят и при сдвинутом пределе — граница
    различает их, и только она."""
    text = mrc.format_report(measure(_many_findings(tmp_path, 13), max_depth=3))

    assert len([ln for ln in text.split("\n") if f"[{VIA_HELPER}]" in ln]) == 12
    assert "ещё 1 находок(и)" in text


# ══════════════════════════════════════════════════════════════════════════════
# Третий проход мутаций: 34 → 14. Ниже — последние убиваемые, и один из них
# ВСКРЫЛ НАСТОЯЩУЮ ОДНОСТОРОННОСТЬ: обход теста (`rglob`) и обход графа
# (`os.walk` + перечень пропуска) видят разные множества, и файл, попавший в
# первое и не попавший во второе, РОНЯЛСЯ МОЛЧА. Теперь он третий исход.
# ══════════════════════════════════════════════════════════════════════════════

def test_a_test_file_outside_the_graph_is_named_not_dropped(tmp_path):
    """Найден мутационным замером, а не рассуждением.

    `spa_core/tests/__pycache__/test_x.py` находится обходом теста и отсутствует
    в графе (каталог в перечне пропуска). Прежняя редакция роняла его молча — то
    есть «не измерено» становилось неотличимо от «поверхность не достигнута»."""
    root = _tree(tmp_path, {
        "spa_core/tests/__pycache__/test_stale.py": "import json\n",
        "spa_core/tests/test_real.py": "import json\n",
    })
    doc = measure(root, max_depth=3)

    assert doc["tests_outside_the_graph"] == [
        "spa_core/tests/__pycache__/test_stale.py"]
    assert doc["tests_scanned"] == 1
    assert "тест-файлов вне графа 1" in mrc.format_report(doc)


def test_an_empty_dotted_name_resolves_to_nothing(tmp_path):
    """Непрозрачный импорт с пустым литералом не вправе разрешиться в корень.

    Сцена несёт `__init__.py` в корне — он есть и на `origin/main`, поэтому
    защита нагружена: без неё имя `""` разрешилось бы в этот файл, и дуга
    пошла бы из ниоткуда в корень дерева."""
    root = _tree(tmp_path, {
        "__init__.py": "",
        "spa_core/tests/test_empty.py":
            "import importlib\nimportlib.import_module('')\n",
    })
    graph = build_graph(root)

    assert graph["name_counts"][NAME_OUTSIDE] >= 1
    assert graph["edges"]["spa_core/tests/test_empty.py"] == set()


def test_the_second_search_root_is_actually_tried(tmp_path):
    """Имя `utils.helper` разрешается ТОЛЬКО относительно `spa_core/`.

    Убивает «прекратить перебор после первого корня»: с мутацией дуга через
    второе написание пакета исчезала бы, и дорога до поверхности терялась
    целиком — тот же вред, который ADR-491 ловил у себя дважды."""
    root = _tree(tmp_path, {
        "spa_core/utils/__init__.py": "",
        "spa_core/utils/helper.py": "from spa_core.risk.policy import APPROVED\n",
        "scripts/__init__.py": "",
        "scripts/mid.py": "import utils.helper\n",
        "spa_core/tests/test_second_root.py": "import scripts.mid\n",
    })
    doc = measure(root, max_depth=3)

    assert doc["per_surface"]["risk"][VIA_HELPER] == 1
    assert doc["findings"][0]["depth"] == 2


def test_attribute_search_starts_at_the_longest_prefix(tmp_path):
    """Пакет без `__init__.py`: разрешается ТОЛЬКО полное имя модуля.

    Убивает сдвиг верхней границы перебора префиксов: с мутацией самый длинный
    префикс не проверялся бы, и атрибут существующего модуля объявлялся бы
    третьим исходом — то есть слепота докладывалась бы там, где её нет."""
    root = _tree(tmp_path, {
        "pkgx/sub/mod.py": "D = 1\n",
        "spa_core/tests/test_longest.py": "from pkgx.sub.mod import D\n",
    })
    graph = build_graph(root)

    assert graph["name_counts"][NAME_ATTR] == 1
    assert graph["name_counts"][NAME_UNRESOLVED] == 0


def test_a_root_level_relative_target_has_a_single_part_name(tmp_path):
    """`from ... import conftest` выводит имя из ОДНОГО элемента пути.

    Убивает сдвиг индекса в проверке на `__init__`: при имени из одного
    элемента сдвинутый индекс выходит за границу, и перепись падает вместо
    ответа. Форма не выдумана — на `origin/main` в корне лежит `__init__.py`."""
    root = _tree(tmp_path, {
        "__init__.py": "",
        "conftest.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/mid3/__init__.py": "",
        "spa_core/mid3/h.py": "from ... import conftest\n",
        "spa_core/tests/test_rootlevel.py": "import spa_core.mid3.h\n",
    })
    doc = measure(root, max_depth=3)

    assert doc["per_surface"]["risk"][VIA_HELPER] == 1
    assert doc["unmeasured_reason"] == ""


def test_a_name_without_a_file_adds_no_edge(tmp_path):
    """Дуга рождается ТОЛЬКО из разрешённого имени.

    Убивает «добавлять в дуги и неразрешённое»: `json` — вне дерева, и дуги из
    него нет; с мутацией в множестве дуг оказался бы `None`, то есть граф начал
    бы нести узел, которого в дереве не существует."""
    root = _tree(tmp_path, {"spa_core/tests/test_one.py": "import json\n"})
    graph = build_graph(root)

    assert graph["edges"]["spa_core/tests/test_one.py"] == set()


def test_the_prefix_search_examines_every_prefix_not_every_other(tmp_path):
    """`aa/bb/__init__.py` есть, `aa/__init__.py` нет: разрешается ТОЛЬКО `aa.bb`.

    Убивает сдвиг ШАГА перебора префиксов (`-1 → -2`): с мутацией средний
    префикс пропускался бы, и атрибут существующего пакета объявлялся бы третьим
    исходом. Контроль на то, что перебор идёт по ВСЕМ префиксам, а не по
    каждому второму."""
    root = _tree(tmp_path, {
        "aa/bb/__init__.py": "",
        "spa_core/tests/test_everyprefix.py": "from aa.bb.cc import D\n",
    })
    graph = build_graph(root)

    assert graph["name_counts"][NAME_ATTR] == 1
    assert sorted(graph["unresolved_names"]) == ["aa.bb.cc"]


def test_report_omits_the_outside_graph_line_when_nothing_is_outside(tmp_path):
    """Пустое «вне графа», напечатанное строкой, читается как находка."""
    root = _tree(tmp_path, {"spa_core/tests/test_a.py": "import json\n"})
    assert "вне графа" not in mrc.format_report(measure(root, max_depth=3))


def test_report_truncates_the_outside_graph_list_at_five(tmp_path):
    """У третьего исхода тот же порядок, что у остальных: имена поимённо,
    предел объявлен, а ЧИСЛО не урезано."""
    files = {f"spa_core/tests/__pycache__/test_s{i}.py": "import json\n"
             for i in range(6)}
    files["spa_core/tests/test_real.py"] = "import json\n"
    text = mrc.format_report(measure(_tree(tmp_path, files), max_depth=3))
    line = [ln for ln in text.split("\n") if "вне графа" in ln][0]

    assert "вне графа 6" in line
    assert line.count("test_s") == 5


# ════════════════════ ОСТАТОК МУТАЦИЙ: равносильные, с доказательством ═══════
#
# Семь мутантов из 137 переживают батарею, и каждый РАЗОБРАН, а не зачтён.
# Равносильность доказывается не словом: предпосылка каждой равносильности сама
# проверяется тестом, и пропади она — тест покраснеет, а претензия будет снята.

def test_premise_every_name_outcome_key_is_always_present(tmp_path):
    """Предпосылка равносильности трёх мутантов `names.get(<ключ>, 0)` → `1`.

    Значение по умолчанию НЕДОСТИЖИМО, потому что счётчик заводится сразу по
    всем четырём исходам. Пропади это свойство — ветка умолчания станет
    достижимой, и равносильность надо будет снимать."""
    graph = build_graph(_tree(tmp_path, {}))
    assert set(graph["name_counts"]) == set(NAME_OUTCOMES)
    assert set(measure(str(tmp_path / "nosuch"))["name_counts"]) == set(NAME_OUTCOMES)


def test_premise_an_empty_bare_spelling_matches_no_surface(tmp_path):
    """Предпосылка равносильности мутанта `len(parts) > 1` → `>= 1`.

    При имени из одного элемента сдвинутое сравнение добавило бы ПУСТОЕ второе
    написание. Пустое имя не равно ни одному объявленному префиксу и не
    начинается ни с одного из них — сравнение идёт по ГРАНИЦЕ имени."""
    from spa_core.monitoring.no_regression_census import DECLARED_SURFACES, _matches
    for surface, spec in DECLARED_SURFACES.items():
        assert _matches({""}, spec["modules"]) == [], surface


def test_premise_json_output_is_parsed_not_compared_as_text(tmp_path, capsys):
    """Предпосылка равносильности трёх мутантов оформления `json.dumps`.

    `ensure_ascii` / `indent` / `sort_keys` меняют НАПИСАНИЕ, а не документ.
    Читатель у `--json` один — разборщик JSON, и он безразличен к оформлению;
    появись читатель, сверяющий ТЕКСТ, равносильность надо будет снять."""
    import json as _json
    root = _tree(tmp_path, {"spa_core/tests/test_a.py": "import json\n"})
    assert mrc.main(["--root", root, "--json"]) == 0
    doc = _json.loads(capsys.readouterr().out)
    assert doc["counts"] == {name: 0 for name in OUTCOMES} | {
        "surface_not_reached": 3}


# ────────────────────── скип вместо замера не выход ───────────────────────────

def test_the_battery_never_skips_instead_of_measuring():
    """`pytest.skip` поднимает потомка `BaseException`: «не измерено» стало бы
    неотличимо от «прошло» (урок цикла #465). В этом файле скипа быть не должно."""
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {"skip", "xfail"}:
                raise AssertionError("скип снимает проверку молча")
    assert pytest is not None  # ввоз нужен фикстурам monkeypatch/capsys
