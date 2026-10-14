"""Проба приёмки `journal_claim_measures_the_worker` — контроль в ОБЕ стороны (ADR-722).

Правило `.claude/rules/acceptance.md` п. 3: новая проба регистрируется только с тестом,
где она ЗЕЛЁНАЯ на целом контуре и КРАСНАЯ на КАЖДОМ порванном звене — с НАЗВАННЫМ
звеном, — и где она НЕ проходит подстрокой (ADR-333). Проба, никогда не видевшая
настоящей поломки, — украшение (`.claude/rules/deployment.md` § «проверка сторожа сторожей»).

Каждое звено рвётся на ОДНОРАЗОВОЙ КОПИИ дерева (`scripts/`), живой репозиторий не
трогается ни на байт. Копия нужна именно потому, что проба меряет ИСХОД У ЧИТАТЕЛЯ:
подменить функцию в памяти значило бы проверить подмену, а не читателя.

Девять порванных звеньев, и каждое — отдельное утверждение о защите:

1. читателя нет вовсе                         ⇒ `unmeasured` (а не `not_satisfied`);
2. прибора бюджета нет                        ⇒ `unmeasured`;
3. ПИСАТЕЛЯ нет                               ⇒ `unmeasured`;
4. писатель не объявил имя поля               ⇒ `not_satisfied`: мерить нечем;
5. читатель называет поле ИНАЧЕ               ⇒ `not_satisfied`: две копии строки;
6. журнальный захват оси не спрашивает        ⇒ `not_satisfied`: замер ДО ADR-722;
7. живой работник не держит карточку          ⇒ `not_satisfied`: кража работы;
8. писатель метит ЧУЖУЮ запись                ⇒ `not_satisfied`: защита выключится;
9. у читателя нет вокабуляра оси              ⇒ `not_satisfied`.
"""
import shutil
from pathlib import Path

import pytest

from spa_core.monitoring import card_acceptance as ca

ROOT = Path(__file__).resolve().parents[2]
PROBE = "journal_claim_measures_the_worker"
GUARD = "scripts/check_card_claim.py"
WRITER = "scripts/log_session_change.py"
LOCK = "scripts/orchestrator_cycle_lock.py"


def _run(root=None):
    return ca.PROBES[PROBE](None, repo_root=str(root) if root else None)


@pytest.fixture()
def tree(tmp_path):
    dst = tmp_path / "repo"
    dst.mkdir()
    shutil.copytree(ROOT / "scripts", dst / "scripts")
    return dst


def _patch(tree, old, new, *, rel=GUARD, count=1):
    """Порвать звено заменой в КОПИИ. Якорь не найден ровно `count` раз — падать ГРОМКО.

    Молчаливый no-op здесь худший исход: тест «порвал звено», получил зелёную пробу и
    доложил бы о дыре, которой нет, либо скрыл настоящую. (Эта самая ошибка случилась в
    первой редакции батареи этого же цикла — `str.replace` без проверки числа вхождений
    тихо не сделал ничего, и три теста покраснели по причине, к предмету не относящейся.)
    """
    p = tree / rel
    text = p.read_text(encoding="utf-8")
    assert text.count(old) == count, (
        f"якорь правки не найден ровно {count} раз(а) в {rel}: {old[:70]!r} "
        f"(найдено {text.count(old)}) — звено не порвано, тест отвечал бы не на свой вопрос")
    p.write_text(text.replace(old, new, count), encoding="utf-8")


# ── ЦЕЛЫЙ КОНТУР ────────────────────────────────────────────────────────────────


def test_the_probe_is_green_on_the_whole_contour():
    verdict, why = _run()
    assert verdict == ca.SATISFIED, (verdict, why)
    for word in ("claimed", "stale", "unchecked", "not_declared"):
        assert word in why, (word, why)


def test_the_probe_is_green_on_an_untouched_copy(tree):
    """Копия без правок зелена ⇒ краснота ниже от ПРАВКИ, а не от копирования."""
    verdict, why = _run(tree)
    assert verdict == ca.SATISFIED, (verdict, why)


# ── ПОРВАННЫЕ ЗВЕНЬЯ ────────────────────────────────────────────────────────────


def test_a_missing_reader_is_unmeasured(tree):
    """Звено 1. «Нечем измерить» ≠ «критерий не выполнен»."""
    (tree / GUARD).unlink()
    verdict, why = _run(tree)
    assert verdict == ca.UNMEASURED, (verdict, why)
    assert "check_card_claim.py" in why and "НЕ ИЗМЕРИТЬ" in why


def test_a_missing_budget_instrument_is_unmeasured(tree):
    """Звено 2: без бюджета работника ось была бы вечным замком, и это не «не выполнено»."""
    (tree / LOCK).unlink()
    verdict, why = _run(tree)
    assert verdict == ca.UNMEASURED, (verdict, why)
    assert "orchestrator_cycle_lock.py" in why


def test_a_missing_writer_is_unmeasured(tree):
    """Звено 3: писателя нет ⇒ поле никто не поставит, но это третий исход."""
    (tree / WRITER).unlink()
    verdict, why = _run(tree)
    assert verdict == ca.UNMEASURED, (verdict, why)
    assert "log_session_change.py" in why


def test_a_writer_that_declares_no_field_name_fails(tree):
    """Звено 4: имя поля — ОДНО, и объявляет его писатель. Нет имени — мерить нечем."""
    _patch(tree, 'RUN_ID_FIELD = "session_run_id"', 'RUN_ID_FIELD = ""', rel=WRITER)
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "RUN_ID_FIELD" in why


def test_a_reader_with_its_own_copy_of_the_name_fails(tree):
    """Звено 5: вторая копия строки переживает переименование МОЛЧА и тихо возвращает
    прежнее поведение — а оно выглядит как «так и было задумано»."""
    _patch(tree,
           '    name = str(getattr(mod, "RUN_ID_FIELD", "") or "").strip()',
           '    name = "session_pid"  # сцена: своя копия имени')
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "по-разному" in why, why


def test_a_reader_that_never_asks_the_axis_for_journal_claims_fails(tree):
    """Звено 6 — ЗАМЕР ДО ПРАВКИ: ровно то состояние, в котором ось была до ADR-722."""
    _patch(tree,
           '''            _classify(session, ts, "announce-log", strength, detail, process,
                      run_id=run_id)''',
           '''            _classify(session, ts, "announce-log", strength, detail, process)''')
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "ЖИВОЙ работник не держит карточку" in why, why


def test_an_axis_that_does_not_hold_the_card_fails(tree):
    """Звено 7: живая работа отдаётся второй сессии — та самая кража, от которой 0b."""
    _patch(tree, '            if w_axis == W_ALIVE:',
           '            if w_axis == "никогда-такого-слова-нет":')
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "ЖИВОЙ работник не держит карточку" in why, why


def test_a_writer_that_stamps_a_foreign_entry_fails(tree):
    """Звено 8: штамп своей личности поверх чужого ярлыка уже стоил выключенной защиты
    от коллизий (`agent-claim-guard-blind-when-session-pid-is-set`)."""
    _patch(tree,
           '''    if worker is not None:
        wlabel, _wwhy = worker
    elif label == own_id:''',
           '''    if worker is not None:
        wlabel, _wwhy = worker
    elif True:''', rel=WRITER)
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "ЧУЖОЙ сессии" in why, why


def test_a_reader_without_the_axis_vocabulary_fails(tree):
    """Звено 9: вокабуляр собирается ОБХОДОМ (`W_*`), а не парой слов из головы."""
    text = (tree / GUARD).read_text(encoding="utf-8")
    renamed = text.replace("W_ALIVE", "AXIS_ALIVE").replace("W_GONE", "AXIS_GONE") \
                  .replace("W_UNMEASURED", "AXIS_UNMEASURED") \
                  .replace("W_NOT_DECLARED", "AXIS_NOT_DECLARED")
    assert renamed != text
    (tree / GUARD).write_text(renamed, encoding="utf-8")
    verdict, why = _run(tree)
    assert verdict in (ca.NOT_SATISFIED, ca.UNMEASURED), (verdict, why)
    assert "вокабуляр" in why or "W_*" in why or "НЕ ИЗМЕРЕНО" in why, why


# ── ПОДСТРОКОЙ НЕ ПРОХОДИТ ──────────────────────────────────────────────────────


def test_the_probe_does_not_pass_by_prose(tree):
    """ADR-333: ответ обязан лежать в ПОЛЕ, а не в прозе. Читатель, который слово оси
    лишь пересказывает, пробу не проходит."""
    _patch(tree, '        rec["worker_axis"] = w_axis',
           '        rec["worker_axis"] = "пересказ прозой"')
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "вне вокабуляра" in why or "ЖИВОЙ работник" in why, why
