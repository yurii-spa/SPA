"""Проба `card_claim_absent_worker_reaches_the_verdict` — контроль в ОБЕ стороны (ADR-724).

Правило `.claude/rules/acceptance.md` п. 3: новая проба регистрируется только с тестом,
где она ЗЕЛЁНАЯ на целом контуре и КРАСНАЯ на каждом порванном звене — с НАЗВАННЫМ
звеном, — и где она НЕ проходит подстрокой (ADR-333). Проба, никогда не видевшая
настоящей поломки, — украшение (`.claude/rules/deployment.md` § «проверка сторожа
сторожей»).

Каждое звено рвётся на ОДНОРАЗОВОЙ КОПИИ дерева (`scripts/`), живой репозиторий не
трогается ни на байт. Копия нужна именно потому, что проба меряет ИСХОД у читателя:
подменить функцию в памяти значило бы проверить подмену, а не читателя.

Восемь порванных звеньев, и каждое — отдельное утверждение о защите:

 1. читателя нет вовсе                         ⇒ `unmeasured` (а не `not_satisfied`);
 2. прибора бюджета нет                        ⇒ `unmeasured`;
 3. измеренное отсутствие не доезжает до вердикта ⇒ `not_satisfied`: состояние ДО правки
    (дословно авария 14.10 19:45Z на приказе владельца);
 4. находка не попадает в `claims`              ⇒ `not_satisfied`: это «свободна», то есть
    АВТО-захват, а не кандидат на ручной подъём;
 5. ЖИВОЙ носитель метки перестал держать карточку ⇒ `not_satisfied`: возврат аварии #864;
 6. неизмеримость оси выдана за ответ           ⇒ `not_satisfied`: инв. #17;
 7. измеренная ЖИЗНЬ оси запускателя перебита   ⇒ `not_satisfied`: карточку отдали бы
    из-под живого якоря;
 8. ось доезжает только ПРОЗОЙ (поля нет / слово оси в прозе) ⇒ `not_satisfied`: ADR-333.

Звено 4 — главное наравне с 3-м: правка обязана давать НАХОДКУ, а не свободу. `stale`
по-прежнему требует `claim --takeover` с письменной причиной, и проба это утверждает.
"""
import shutil
from pathlib import Path

import pytest

from spa_core.monitoring import card_acceptance as ca

ROOT = Path(__file__).resolve().parents[2]
PROBE = "card_claim_absent_worker_reaches_the_verdict"
GUARD_REL = "scripts/check_card_claim.py"
CARD_REL = "nimbalyst-local/tracker/inbox-izmerennoe-otsutstvie-rabotnika-ne-doezz.md"


def _run(root=None):
    return ca.PROBES[PROBE](None, repo_root=str(root) if root else None)


@pytest.fixture()
def tree(tmp_path):
    """Одноразовая копия дерева: только то, что проба читает."""
    dst = tmp_path / "repo"
    dst.mkdir()
    shutil.copytree(ROOT / "scripts", dst / "scripts")
    return dst


def _patch(tree, old, new, *, rel=GUARD_REL, count=1):
    """Порвать звено заменой в КОПИИ. Не нашли подстроку — падать ГРОМКО.

    Молчаливый no-op здесь был бы худшим исходом: тест «порвал звено» и получил зелёную
    пробу, то есть доложил бы о дыре, которой нет, или скрыл настоящую."""
    p = tree / rel
    text = p.read_text(encoding="utf-8")
    assert text.count(old) == count, (
        f"якорь правки не найден ровно {count} раз(а) в {rel}: {old[:80]!r} "
        f"(найдено {text.count(old)}) — звено не порвано, тест отвечал бы не на свой "
        f"вопрос")
    p.write_text(text.replace(old, new, count), encoding="utf-8")


# ── ЦЕЛЫЙ КОНТУР ────────────────────────────────────────────────────────────────

def test_the_probe_is_green_on_the_whole_contour():
    """На живом дереве критерий ВЫПОЛНЕН, и ответ называет все стороны замера."""
    verdict, why = _run()
    assert verdict == ca.SATISFIED, (verdict, why)
    for word in ("claimed", "stale", "unchecked", "not_declared"):
        assert word in why, (word, why)


def test_the_probe_is_green_on_an_untouched_copy(tree):
    """Копия без правок зелена — значит краснота ниже от ПРАВКИ, а не от копирования."""
    verdict, why = _run(tree)
    assert verdict == ca.SATISFIED, (verdict, why)


def test_the_probe_is_the_declared_criterion_of_its_card():
    """Критерий объявлен НА КАРТОЧКЕ, а не только в реестре (`acceptance.md` п. 1)."""
    card = ROOT / CARD_REL
    assert card.exists(), f"{CARD_REL} — предмета пробы нет в дереве"
    assert f"acceptance_probe: {PROBE}" in card.read_text(encoding="utf-8")


# ── ПОРВАННЫЕ ЗВЕНЬЯ ────────────────────────────────────────────────────────────

def test_a_missing_reader_is_unmeasured_not_unsatisfied(tree):
    """Звено 1: читателя нет ⇒ третий исход. «Нечем измерить» ≠ «критерий не выполнен»."""
    (tree / GUARD_REL).unlink()
    verdict, why = _run(tree)
    assert verdict == ca.UNMEASURED, (verdict, why)
    assert "check_card_claim.py" in why and "НЕ ИЗМЕРИТЬ" in why, why


def test_a_missing_budget_instrument_is_unmeasured(tree):
    """Звено 2: прибора бюджета нет ⇒ третий исход, названный поимённо."""
    (tree / "scripts/orchestrator_cycle_lock.py").unlink()
    verdict, why = _run(tree)
    assert verdict == ca.UNMEASURED, (verdict, why)
    assert "orchestrator_cycle_lock.py" in why, why


def test_an_absence_that_never_reaches_the_verdict_is_the_incident(tree):
    """Звено 3 — ГЛАВНОЕ: ветка снята ⇒ дословно состояние ДО правки.

    Это и есть авария 14.10 19:45Z: держатель приказа владельца мёртв по обеим
    измеримым осям, а шаг 0b отвечает «ЗАНЯТА, не бери эту карточку»."""
    _patch(tree,
           '            if w_axis == W_GONE and strength == STRONG '
           'and state != sibling.ACTIVE \\\n'
           '                    and not orphaned and rec["age_hours"] is not None:',
           '            if False:')
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "работника ИЗМЕРЕННО НЕТ" in why, why
    assert "claimed" in why and "stale" in why, why


def test_an_absence_without_a_finding_is_an_auto_claim(tree):
    """Звено 4: находка не попадает в `claims` ⇒ вердикт «свободна».

    Это не смягчение, а СМЕНА РОДА: `stale` требует письменной причины подъёма, `free`
    отдаёт карточку молча. Проба обязана краснеть именно здесь."""
    _patch(tree, '                report["claims"].append(rec)   # НАХОДКА, а не «свободна»',
           '                pass')
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "предмет пробы не найден" in why, why


def test_a_live_worker_that_stops_holding_is_the_other_incident(tree):
    """Звено 5: живой носитель метки отдал карточку ⇒ возврат аварии #864 (ADR-721)."""
    _patch(tree,
           '                rec["state"] = "fresh"\n'
           '                rec["session_state"] = (\n'
           '                    f"ось ЗАПУСКАТЕЛЯ: {why}; НО ось РАБОТНИКА: {w_why} — '
           'работу делает "',
           '                rec["state"] = "stale"\n'
           '                rec["session_state"] = (\n'
           '                    f"ось ЗАПУСКАТЕЛЯ: {why}; НО ось РАБОТНИКА: {w_why} — '
           'работу делает "')
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "ЖИВОЙ работник не держит карточку" in why, why


def test_an_unmeasured_axis_passed_off_as_an_answer_reddens(tree):
    """Звено 6: третий исход снят ⇒ неизмеримость выдана за ответ (инв. #17)."""
    _patch(tree,
           '            if w_axis == W_UNMEASURED:\n'
           '                _unmeasured(source,',
           '            if False:\n'
           '                _unmeasured(source,')
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "ось НЕ ИЗМЕРЕНА" in why, why


def test_overruling_a_measured_living_launcher_reddens(tree):
    """Звено 7: операнд `state != ACTIVE` снят ⇒ карточка отдана из-под ЖИВОГО якоря.

    Измеренная ЖИЗНЬ обязана быть сильнее измеренного отсутствия соседней оси: иначе
    правка не защита, а второй способ отобрать идущую работу."""
    _patch(tree,
           'if w_axis == W_GONE and strength == STRONG and state != sibling.ACTIVE \\',
           'if w_axis == W_GONE and strength == STRONG \\')
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "ось ЗАПУСКАТЕЛЯ измерила ЖИЗНЬ" in why, why


def test_an_axis_outside_the_readers_vocabulary_reddens(tree):
    """Звено 8а: поле несёт слово вне вокабуляра ⇒ ответ есть только в прозе."""
    _patch(tree, '        rec["worker_axis"] = w_axis',
           '        rec["worker_axis"] = "жив-или-нет"')
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "вне вокабуляра читателя" in why, why


def test_the_axis_word_inside_the_prose_reddens(tree):
    """Звено 8б: слово оси попало в прозу ⇒ проба прошла бы ПОДСТРОКОЙ (ADR-333)."""
    _patch(tree, '        rec["worker_detail"] = w_why',
           '        rec["worker_detail"] = f"{w_axis}: {w_why}"')
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "подстрокой" in why, why
