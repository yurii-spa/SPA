"""Lint guard (Task 9, Block D hygiene): no bare ``datetime.utcnow()`` in runtime.

``datetime.datetime.utcnow`` is deprecated (Python 3.12) and — critically —
returns a NAIVE datetime whose ``.isoformat()`` differs from the AWARE
``datetime.now(timezone.utc)`` (no ``+00:00`` offset). The codebase persists
those strings to ``data/*.json`` state files, so a careless swap would change
output. All runtime call-sites must go through :func:`spa_core.utils.clock.utcnow`
(a naive-preserving, deprecation-free drop-in).

Сторож спрашивает у AST, а не у подстроки (инв. #16 — замер цикла #1183)
---------------------------------------------------------------------------
Прежняя редакция грепала ``\\bdatetime\\.utcnow\\(`` по СТРОКАМ файла и поэтому
не могла отличить КОД от ПРОЗЫ. На контрольном прогоне CI 44136743562 она была
КРАСНОЙ с единственной находкой — ``spa_core/monitoring/identity_field_kind.py:75``,
— и находка лежала внутри МОДУЛЬНОЙ ДОКСТРОКИ, перечисляющей двери стенных
часов, которые тот модуль УМЕЕТ НАХОДИТЬ: «``datetime.now()``,
``datetime.utcnow()``, ``date.today()``, ``time.time()`` — напрямую, через
привязку или через обёртку». Требовать от этой строки «мигрируй на
``clock.utcnow``» значило бы требовать подделать описание прибора. Это тот же
класс, что уже закрыт у двух соседей — ``tests/test_spaerror_complete.py``
(grep → AST, 10.09) и ``scripts/dead_code_scanner.py`` (слово «hack» прозы,
#1183): **упоминание становилось доказательством факта.**

Проверка от этого не ослабла, а расширилась, и разность ИЗМЕРЕНА на `a19e8ea96`:

======================================  ======  ======
множество                               старая  новая
======================================  ======  ======
находок в ``spa_core/`` + ``scripts/``       1       0
из них внутри докстроки/комментария          1       0
``clock.utcnow()`` (санкционированных)       —     110
«есть у НОВОЙ, нет у СТАРОЙ»                 —       0
======================================  ======  ======

Новая редакция ловит СТРОГО БОЛЬШЕ форм: кроме ``datetime.utcnow()`` и
``datetime.datetime.utcnow()`` — ещё и переименованные
(``import datetime as dt`` ⇒ ``dt.datetime.utcnow()``;
``from datetime import datetime as DT`` ⇒ ``DT.utcnow()``), которых регулярка
не видела вовсе.

Три исхода различимы (инв. #17)
-------------------------------
* **ЧИСТО** — зов ``.utcnow()`` опознан как часы SPA (``clock``);
* **НАХОДКА** — получатель привязан к ``datetime`` стандартной библиотеки;
* **НЕ ОПОЗНАНО** — получателя в импортах модуля нет вовсе (параметр, атрибут
  объекта, динамический импорт). Такой зов НЕ выдаётся за чистый: он
  называется поимённо и краснит сторожа, потому что про него неизвестно
  главное — чьи это часы. Файл, который не разобрался, — тоже третий исход, а
  не «чисто».
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("spa_core", "scripts")

#: Единственная санкционированная дверь (ADR-«наивные часы»): модуль часов SPA.
_CLOCK_MODULE = "spa_core.utils.clock"

#: Files/dirs that are allowed to mention utcnow (helper + the test tree itself).
_ALLOWLIST = {"clock.py"}


def _is_excluded(path: Path) -> bool:
    parts = set(path.parts)
    if "tests" in parts:
        return True
    if path.name in _ALLOWLIST:
        return True
    return False


def _bindings(tree: ast.AST) -> tuple[set, set, set]:
    """Имена модуля, привязанные к ``datetime`` stdlib и к часам SPA.

    Возврат: (имена МОДУЛЯ ``datetime``, имена КЛАССА ``datetime.datetime``,
    имена часов SPA — модуля ``clock`` либо самой функции ``utcnow``).
    """
    dt_module: set = set()
    dt_class: set = set()
    spa_clock: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "datetime":
                    dt_module.add(alias.asname or "datetime")
                elif alias.name == _CLOCK_MODULE:
                    # `import spa_core.utils.clock as c` — иначе имя составное
                    if alias.asname:
                        spa_clock.add(alias.asname)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                bound = alias.asname or alias.name
                if module == "datetime" and alias.name == "datetime":
                    dt_class.add(bound)
                elif module == _CLOCK_MODULE:
                    spa_clock.add(bound)
                elif alias.name == "clock" and module.endswith(".utils"):
                    spa_clock.add(bound)
    return dt_module, dt_class, spa_clock


def _receiver(node: ast.AST) -> tuple:
    """Корневое ИМЯ точечной цепочки и её хвост: ``a.b.utcnow`` → ("a", ["b"])."""
    attrs: list = []
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return node.id, list(reversed(attrs))[:-1]
    return None, None


def audit_tree(root: Path) -> dict:
    """Три исхода по всему дереву: находки · санкционированные · НЕ ОПОЗНАНО."""
    offenders: list = []
    unresolved: list = []
    sanctioned = 0
    for d in SCAN_DIRS:
        base = root / d
        if not base.exists():
            continue
        for py in sorted(base.rglob("*.py")):
            if _is_excluded(py):
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError) as exc:  # третий исход
                unresolved.append(
                    f"{py.relative_to(root)}:0: НЕ РАЗОБРАН "
                    f"({type(exc).__name__}: {exc})")
                continue
            dt_module, dt_class, spa_clock = _bindings(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if isinstance(func, ast.Name):
                    if func.id != "utcnow":
                        continue
                    if func.id in spa_clock:
                        sanctioned += 1
                    else:
                        unresolved.append(
                            f"{py.relative_to(root)}:{node.lineno}: голый "
                            f"utcnow() — имя не привязано ни к одной известной двери")
                    continue
                if not (isinstance(func, ast.Attribute) and func.attr == "utcnow"):
                    continue
                name, middle = _receiver(func)
                where = f"{py.relative_to(root)}:{node.lineno}"
                if name is None:
                    unresolved.append(
                        f"{where}: получатель .utcnow() — не имя, чьи это часы НЕ ОПОЗНАНО")
                elif name in dt_class and not middle:
                    offenders.append(f"{where}: {name}.utcnow()")
                elif name in dt_module and middle == ["datetime"]:
                    offenders.append(f"{where}: {name}.datetime.utcnow()")
                elif name in spa_clock and not middle:
                    sanctioned += 1
                else:
                    unresolved.append(
                        f"{where}: {name}{''.join('.' + m for m in middle)}.utcnow() "
                        f"— имя не привязано ни к одной известной двери")
    return {"offenders": offenders, "unresolved": unresolved,
            "sanctioned": sanctioned}


def test_no_bare_utcnow_in_runtime() -> None:
    report = audit_tree(ROOT)
    assert not report["offenders"], (
        "Bare datetime.utcnow() found — use spa_core.utils.clock.utcnow() "
        "(naive-preserving, deprecation-free):\n"
        + "\n".join(report["offenders"])
    )


def test_unrecognised_utcnow_doors_are_named_not_passed_as_clean() -> None:
    """Инв. #17: «чьи это часы неизвестно» — отдельный исход, а не чистота."""
    report = audit_tree(ROOT)
    assert not report["unresolved"], (
        "зов .utcnow() через имя, которого нет в импортах модуля — НЕ ИЗМЕРЕНО, "
        "а не «чисто»: проверить вручную, чьи это часы:\n"
        + "\n".join(report["unresolved"][:20])
    )


def test_the_measurement_actually_reaches_the_live_tree() -> None:
    """Контроль предпосылки: зелень выше не от того, что ничего не прочитано.

    Без этой проверки обе проверки выше были бы зелены на ПУСТОМ ответе —
    дословно класс «не измерено, выданное за ответ» (`.claude/rules/deployment.md`).
    """
    report = audit_tree(ROOT)
    assert report["sanctioned"] > 0, (
        "в дереве не найдено НИ ОДНОГО зова clock.utcnow() — такого состояния "
        "у этого репозитория не было ни разу; значит прочитано не дерево")


def test_a_real_offender_is_still_caught_in_every_alias_form() -> None:
    """Положительный контроль: четыре формы настоящего нарушения — находки."""
    import tempfile

    forms = {
        "direct.py": "from datetime import datetime\nx = datetime.utcnow()\n",
        "module.py": "import datetime\nx = datetime.datetime.utcnow()\n",
        "aliased_module.py": "import datetime as dt\nx = dt.datetime.utcnow()\n",
        "aliased_class.py": "from datetime import datetime as DT\nx = DT.utcnow()\n",
    }
    with tempfile.TemporaryDirectory() as tmp:
        scene = Path(tmp)
        (scene / "spa_core").mkdir()
        for name, body in forms.items():
            (scene / "spa_core" / name).write_text(body, encoding="utf-8")
        report = audit_tree(scene)
    assert len(report["offenders"]) == len(forms), report
    assert report["unresolved"] == [], report


def test_a_docstring_mention_is_NOT_an_offender() -> None:
    """Обратная сторона той же пары: авария #1183 дословно."""
    import tempfile

    body = (
        '"""Двери стенных часов, которые этот модуль УМЕЕТ находить:\n'
        "``datetime.now()``, ``datetime.utcnow()``, ``date.today()``.\n"
        '"""\n'
        "from spa_core.utils import clock\n"
        "x = clock.utcnow()\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        scene = Path(tmp)
        (scene / "spa_core").mkdir()
        (scene / "spa_core" / "prose.py").write_text(body, encoding="utf-8")
        report = audit_tree(scene)
    assert report["offenders"] == [], report
    assert report["unresolved"] == [], report
    assert report["sanctioned"] == 1, report


def test_an_unknown_door_is_unresolved_and_not_silently_clean() -> None:
    """Третий исход предъявлен, а не рассказан."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        scene = Path(tmp)
        (scene / "spa_core").mkdir()
        (scene / "spa_core" / "mystery.py").write_text(
            "def f(src):\n    return src.utcnow()\n", encoding="utf-8")
        report = audit_tree(scene)
    assert report["offenders"] == [], report
    assert len(report["unresolved"]) == 1, report
    assert "НЕ ОПОЗНАНО" in report["unresolved"][0] or "не привязано" in report["unresolved"][0]
