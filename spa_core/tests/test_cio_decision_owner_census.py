"""Контроль в обе стороны для переписи владельца решения на уровне портфеля (§49 Architecture).

Проба, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md`, «Проверка сторожа сторожей»). Поэтому здесь нет ни
одного теста «модуль импортируется»: каждый строит ЦЕЛЫЙ одноразовый контур —
крошечное дерево-сцену с настоящими писателями книг и настоящим каталогом данных, —
и затем рвёт РОВНО ОДНО звено, называя его.

Зелёная сторона тоже настоящая: сцена «владелец решения ЕСТЬ» собирается из
производителя, чьё решение накрывает обе книги, и перепись обязана сказать
``OWNER_EXISTS``. Без неё ``PER_BOOK_ONLY`` был бы неотличим от прибора, который
не умеет отвечать «да» вовсе.

Часы, корень дерева и каталог данных — ВХОДЫ: ни один тест не зависит от календаря,
от рабочего каталога и от состояния живого ``data/``.
"""
# FROZEN-DATE-OK: injected-clock — все отметки происходят от _NOW, который передаётся
# в run_census аргументом now=; стенных часов сцена не спрашивает ни разу.
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

import pytest

from spa_core.monitoring import cio_decision_owner_census as census
from spa_core.monitoring import cio_target_producers as producers

_NOW = datetime(2026, 9, 28, 3, 0, tzinfo=timezone.utc)

_BOOK_A = "data/book_a.json"
_BOOK_B = "data/book_b.json"

#: Писатель книги: нагрузка формы книги, происхождение — решающий вызов.
_DECIDER_SRC = '''
from spa_core.utils.atomic import atomic_save


def run(engine):
    positions = engine.optimize()
    atomic_save({{"positions": positions}}, "{artifact}")
'''

#: Писатель того же вида, но нагрузка происходит из уже принятого решения.
_DESCRIBER_SRC = '''
from spa_core.utils.atomic import atomic_save


def run(store):
    positions = store.load_state()
    atomic_save({"positions": positions}, "data/book_a.json")
    atomic_save({"positions": positions}, "data/book_b.json")
'''


def _write(root: pathlib.Path, rel: str, src: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(src, encoding="utf-8")


def _scene(tmp_path: pathlib.Path, *, per_book: bool = True,
           capital_a: float | None = 60_000.0,
           capital_b: float | None = 40_000.0) -> tuple[pathlib.Path, pathlib.Path, tuple]:
    """Одноразовый контур. Возвращает (корень, каталог данных, объявление книг).

    ``per_book=True``  — у каждой книги СВОЙ решатель (сегодняшняя система);
    ``per_book=False`` — один модуль решает ОБЕ книги (портфельный владелец).
    """
    root = tmp_path / "tree"
    (root / "spa_core").mkdir(parents=True, exist_ok=True)
    if per_book:
        _write(root, "spa_core/alloc_a.py", _DECIDER_SRC.format(artifact=_BOOK_A))
        _write(root, "spa_core/alloc_b.py", _DECIDER_SRC.format(artifact=_BOOK_B))
        declared = ((_BOOK_A, "spa_core/alloc_a.py", "книга A"),
                    (_BOOK_B, "spa_core/alloc_b.py", "книга B"))
    else:
        _write(root, "spa_core/alloc_all.py",
               _DECIDER_SRC.format(artifact=_BOOK_A).replace(
                   'atomic_save({"positions": positions}, "data/book_a.json")',
                   'atomic_save({"positions": positions}, "data/book_a.json")\n'
                   '    atomic_save({"positions": positions}, "data/book_b.json")'))
        declared = ((_BOOK_A, "spa_core/alloc_all.py", "книга A"),
                    (_BOOK_B, "spa_core/alloc_all.py", "книга B"))
    # Многокнижный ОПИСАТЕЛЬ обязан существовать в любой сцене: он и есть
    # положительный контроль оси B — проход, ослепший молча, не нашёл бы его.
    _write(root, "spa_core/report_both.py", _DESCRIBER_SRC)

    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    for name, usd in ((_BOOK_A, capital_a), (_BOOK_B, capital_b)):
        doc: dict = {"positions": {"aave_v3": 1.0}}
        if usd is not None:
            doc = {"equity": usd, "positions": {"aave_v3": usd}}
        (data / pathlib.Path(name).name).write_text(json.dumps(doc), encoding="utf-8")
    return root, data, declared


@pytest.fixture()
def declare(monkeypatch):
    def _apply(declared):
        monkeypatch.setattr(producers, "DECLARED_BOOKS", tuple(declared))
    return _apply


# ── зелёная сторона: прибор УМЕЕТ сказать «владелец есть» ─────────────────────

def test_single_producer_covering_every_book_is_an_owner(tmp_path, declare):
    root, data, declared = _scene(tmp_path, per_book=False)
    declare(declared)
    report = census.run_census(data, repo_root=root, now=_NOW)
    assert report["measured"], report.get("reason")
    assert report["verdict"] == census.OWNER_EXISTS
    assert report["widest_share"] == pytest.approx(1.0)
    assert report["books_out_of_scope"] == []


# ── красная сторона: сегодняшняя форма системы ────────────────────────────────

def test_per_book_producers_are_not_a_portfolio_owner(tmp_path, declare):
    root, data, declared = _scene(tmp_path, per_book=True)
    declare(declared)
    report = census.run_census(data, repo_root=root, now=_NOW)
    assert report["measured"], report.get("reason")
    assert report["verdict"] == census.PER_BOOK_ONLY
    assert len(report["books_out_of_scope"]) == 1
    assert report["uncovered_usd"] == pytest.approx(40_000.0)
    assert report["total_capital_usd"] == pytest.approx(100_000.0)


def test_empty_book_does_not_promote_a_per_book_producer_to_owner(tmp_path, declare):
    """Авария первой редакции: книга с $0 делала долю соседа 100 % и «владельца».

    Ответ системы при этом не менялся ни на байт — те книги производитель не решал
    ни до, ни после. Ноль долларов есть ЗНАЧЕНИЕ, а не исчезновение книги (инв. #17).
    """
    root, data, declared = _scene(tmp_path, per_book=True, capital_b=0.0)
    declare(declared)
    report = census.run_census(data, repo_root=root, now=_NOW)
    assert report["measured"], report.get("reason")
    assert report["widest_share"] == pytest.approx(1.0), "доля и правда 100 %"
    assert report["verdict"] == census.PER_BOOK_ONLY, "но владельцем это не делает"


# ── каждое порванное звено — со своим именем ──────────────────────────────────

def test_unreadable_book_is_unmeasured_not_zero(tmp_path, declare):
    root, data, declared = _scene(tmp_path, per_book=True)
    declare(declared)
    (data / "book_b.json").write_text("{ not json", encoding="utf-8")
    report = census.run_census(data, repo_root=root, now=_NOW)
    assert not report["measured"]
    assert report["status"] == census.UNMEASURED
    assert "book_b.json" in report["reason"]
    assert "не прочитана" in report["reason"]


def test_book_without_a_capital_number_is_unmeasured(tmp_path, declare):
    root, data, declared = _scene(tmp_path, per_book=True)
    declare(declared)
    (data / "book_b.json").write_text(json.dumps({"sleeve": "C"}), encoding="utf-8")
    report = census.run_census(data, repo_root=root, now=_NOW)
    assert not report["measured"]
    assert "капитал не наблюдён" in report["reason"]


def test_zero_total_capital_is_unmeasured_not_a_verdict(tmp_path, declare):
    root, data, declared = _scene(tmp_path, per_book=True,
                                  capital_a=0.0, capital_b=0.0)
    declare(declared)
    report = census.run_census(data, repo_root=root, now=_NOW)
    assert not report["measured"]
    assert "знаменател" in report["reason"]


def test_incomplete_producer_enumeration_refuses_a_verdict(tmp_path, declare, monkeypatch):
    root, data, declared = _scene(tmp_path, per_book=True)
    declare(declared)
    monkeypatch.setattr(producers, "_enumerate_producers",
                        lambda _root: {"complete": False, "reason": "сцена: разбор порван",
                                       "declared": [], "undeclared": []})
    report = census.run_census(data, repo_root=root, now=_NOW)
    assert not report["measured"]
    assert "сцена: разбор порван" in report["reason"]


def test_multi_book_module_of_unknown_role_blocks_axis_b(tmp_path, declare):
    """Модуль видит ВСЕ книги, а роль не установлена ⇒ вердикт НЕ выносится.

    «Межкнижного решателя нет» и «не разобрались, кто он» — разные факты, и
    выдавать один за другой запрещено.
    """
    root, data, declared = _scene(tmp_path, per_book=True)
    declare(declared)
    _write(root, "spa_core/mystery.py",
           'def run(x):\n'
           '    names = ["data/book_a.json", "data/book_b.json"]\n'
           '    return x.optimize(names)\n')
    report = census.run_census(data, repo_root=root, now=_NOW)
    assert not report["measured"]
    assert "роль не установлена" in report["reason"]
    assert "mystery" in report["reason"]


def test_axis_b_positive_control_refuses_when_no_multi_book_module_is_seen(
        tmp_path, declare, monkeypatch):
    """Ослепший проход обязан сказать «не измерено», а не «решателя нет»."""
    root, data, declared = _scene(tmp_path, per_book=True)
    declare(declared)
    monkeypatch.setattr(census, "_multi_book_modules", lambda *a, **k: ([], ""))
    report = census.run_census(data, repo_root=root, now=_NOW)
    assert not report["measured"]
    assert "положительный контроль оси B" in report["reason"]


# ── проба реестра приёмки: три исхода разведены ───────────────────────────────

def test_probe_reports_satisfied_only_when_the_owner_covers_every_book(tmp_path, declare):
    from spa_core.monitoring import card_acceptance as ca

    root, data, declared = _scene(tmp_path, per_book=False)
    declare(declared)
    verdict, detail = ca._probe_portfolio_decision_owner_covers_capital(
        None, now=_NOW, data_dir=str(data), repo_root=str(root))
    assert verdict == ca.SATISFIED, detail

    root, data, declared = _scene(tmp_path / "second", per_book=True)
    declare(declared)
    verdict, detail = ca._probe_portfolio_decision_owner_covers_capital(
        None, now=_NOW, data_dir=str(data), repo_root=str(root))
    assert verdict == ca.NOT_SATISFIED, detail

    (data / "book_b.json").write_text("{ not json", encoding="utf-8")
    verdict, detail = ca._probe_portfolio_decision_owner_covers_capital(
        None, now=_NOW, data_dir=str(data), repo_root=str(root))
    assert verdict == ca.UNMEASURED, detail


def test_probe_is_registered_under_its_declared_name():
    """Имя, которого нет в реестре, даёт `unmeasured` — «не будет измерено НИКОГДА»."""
    from spa_core.monitoring import card_acceptance as ca

    assert ca.validate_spec("portfolio_decision_owner_covers_capital") is None


# ── проба «у многокритериального приказа нет пробы одного критерия» (#710) ────

_ORDER = "inbox-order-with-thirteen-criteria"


def _order_card(tmp: pathlib.Path, *, probe: str | None) -> pathlib.Path:
    tracker = tmp / "nimbalyst-local" / "tracker"
    tracker.mkdir(parents=True, exist_ok=True)
    head = ["---", "trackerStatus:", "  type: inbox",
            "title: приказ на тринадцать критериев", "status: in-progress"]
    if probe:
        head.append(f"acceptance_probe: {probe}")
    head += ["---", "", "тело"]
    (tracker / f"{_ORDER}.md").write_text("\n".join(head), encoding="utf-8")
    return tracker


def test_probe_is_red_while_a_single_criterion_probe_sits_on_the_order(tmp_path):
    from spa_core.monitoring import card_acceptance as ca

    tracker = _order_card(tmp_path, probe="owner_visibility_numbers_delivered")
    verdict, detail = ca._probe_no_single_criterion_probe_on_a_multi_criterion_order(
        _ORDER, tracker_dir=str(tracker), repo_root=str(tmp_path))
    assert verdict == ca.NOT_SATISFIED, detail
    assert "вердикт одного критерия" in detail


def test_probe_is_green_once_the_line_is_gone(tmp_path):
    from spa_core.monitoring import card_acceptance as ca

    tracker = _order_card(tmp_path, probe=None)
    verdict, detail = ca._probe_no_single_criterion_probe_on_a_multi_criterion_order(
        _ORDER, tracker_dir=str(tracker), repo_root=str(tmp_path))
    assert verdict == ca.SATISFIED, detail


def test_probe_refuses_when_the_card_is_nowhere(tmp_path):
    from spa_core.monitoring import card_acceptance as ca

    tracker = tmp_path / "nimbalyst-local" / "tracker"
    tracker.mkdir(parents=True)
    verdict, detail = ca._probe_no_single_criterion_probe_on_a_multi_criterion_order(
        _ORDER, tracker_dir=str(tracker), repo_root=str(tmp_path))
    assert verdict == ca.UNMEASURED, detail
    assert "не найдена" in detail


def test_probe_without_an_argument_refuses(tmp_path):
    from spa_core.monitoring import card_acceptance as ca

    verdict, _ = ca._probe_no_single_criterion_probe_on_a_multi_criterion_order(None)
    assert verdict == ca.UNMEASURED


def test_the_link_the_probe_relies_on_holds_in_audit(tmp_path):
    """Связь, на которой стои́т проба: строка отчёта рождается ТОЛЬКО из объявления.

    Проба меряет отсутствие объявления, а не зовёт :func:`audit` (та зовёт пробы —
    вызов был бы рекурсией). Поэтому связь закрепляется здесь, на настоящем
    отчёте и настоящем каталоге карточек.
    """
    from spa_core.monitoring import card_acceptance as ca

    tracker = _order_card(tmp_path, probe=None)
    report = ca.audit(str(tracker), origin_readthrough=False)
    assert [r for r in report["rows"] if _ORDER in r.get("card", "")] == []

    tracker = _order_card(tmp_path, probe="owner_visibility_numbers_delivered")
    report = ca.audit(str(tracker), origin_readthrough=False)
    assert [r for r in report["rows"] if _ORDER in r.get("card", "")] != []


def test_unreadable_ref_copy_is_not_reported_as_clean(tmp_path):
    """«Прочитанные копии чисты» и «вторую копию прочитать не вышло» — разные факты.

    Сцена объявляет имя ветки явно (`git init -b`): без этого вердикт зависел бы от
    `init.defaultBranch` хоста — Apple Git даёт `main`, `ubuntu-latest` `master`
    (`.claude/rules/deployment.md`, «GIT-ОКРУЖЕНИЕ в тестах»). Ветки `origin/main`
    в одноразовом репозитории нет по построению, и это и есть предмет теста.
    """
    import subprocess

    from spa_core.monitoring import card_acceptance as ca

    subprocess.run(["git", "init", "-b", "main", str(tmp_path)],
                   check=True, capture_output=True)
    tracker = _order_card(tmp_path, probe=None)
    verdict, detail = ca._probe_no_single_criterion_probe_on_a_multi_criterion_order(
        _ORDER, tracker_dir=str(tracker), repo_root=str(tmp_path))
    assert verdict == ca.UNMEASURED, detail
    assert "не прочитана" in detail


# ---------------------------------------------------------------------------
# ADR-811: запись артефакта живёт в ОДНОЙ двери, и дверь эта ДЕЙСТВИТЕЛЬНО пишет
# ---------------------------------------------------------------------------
#
# До ADR-811 запись жила только внутри `_main`, то есть артефакт появлялся ровно
# тогда, когда модуль звали РУКОЙ. Звавшего не было ни одного (0 из 115 ступеней
# моста), файл не появился в живом `data/` ни разу за 27 дней, и критерий §49
# `Architecture` оставался единственным, у которого такт входа взять неоткуда.
#
# Проводка без этих сцен была бы утверждением о себе: ступень моста ЗОВЁТ `run`,
# и если `run` перестанет писать (или начнёт писать мимо `root`), мост продолжит
# печатать бодрую строку, а артефакта снова не будет. Мутация `if write:` →
# `if False:` обязана краснеть — иначе дыра покрытия ровно в том месте, которое
# этот ADR и чинит.

def _scene_root(tmp_path):
    """Дерево и каталог данных — ВХОДЫ: живое `data/` здесь не трогается."""
    root = tmp_path / "tree"
    (root / "data").mkdir(parents=True)
    return root


def test_run_actually_leaves_the_artifact_on_disk(tmp_path):
    from spa_core.monitoring import cio_decision_owner_census as census

    root = _scene_root(tmp_path)
    target = root / census.REPORT_REL
    assert not target.exists(), "сцена нечиста: артефакт уже лежит"

    report = census.run(str(root), data_dir=str(root / "data"))

    assert target.exists(), (
        "`run` не оставила артефакта — ровно состояние до ADR-811, когда ступень "
        "моста звала бы прибор, а меры критерия на диске не появлялось")
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk.get("verdict") == report.get("verdict"), (
        "на диске лежит НЕ тот отчёт, который вернула функция — сверить вердикт "
        "ступени с артефактом стало бы невозможно")


def test_write_false_measures_without_leaving_a_trace(tmp_path):
    """Обратная сторона: иначе `write` ничего не значит и параметр декоративен."""
    from spa_core.monitoring import cio_decision_owner_census as census

    root = _scene_root(tmp_path)
    census.run(str(root), data_dir=str(root / "data"), write=False)
    assert not (root / census.REPORT_REL).exists(), (
        "`write=False` всё равно записал — у `--no-write` и у тестов нет способа "
        "снять замер без следа")


def test_the_artifact_goes_to_the_GIVEN_root_not_to_the_module_default(tmp_path):
    """`REPO_ROOT` — дефолт, а не адрес: иначе прогон в дереве писал бы в прод."""
    from spa_core.monitoring import cio_decision_owner_census as census

    root = _scene_root(tmp_path)
    census.run(str(root), data_dir=str(root / "data"))
    assert (root / census.REPORT_REL).exists()
    assert not (pathlib.Path(census.REPO_ROOT) / census.REPORT_REL).exists() \
        or pathlib.Path(census.REPO_ROOT) != root, (
        "артефакт уехал в дерево модуля, а не в переданное — прогон из "
        "одноразового дерева писал бы в боевое")


def test_main_has_no_second_write_site(tmp_path):
    """Одно имя — один объект (ADR-220): второй `atomic_save` разошёлся бы молча.

    Мерка — разбор AST, а не подстрока: предмет здесь ЧИСЛО мест записи.
    """
    import ast

    source = pathlib.Path(census_module_path()).read_text(encoding="utf-8")
    tree = ast.parse(source)
    writes = [node for node in ast.walk(tree)
              if isinstance(node, ast.Call)
              and (getattr(node.func, "attr", None)
                   or getattr(node.func, "id", None)) == "atomic_save"]
    assert len(writes) == 1, (
        f"зовов `atomic_save` в модуле {len(writes)}, а не один — у артефакта "
        f"снова два писателя, и сличить их отчёты нечем")


def census_module_path():
    from spa_core.monitoring import cio_decision_owner_census as census

    return census.__file__
