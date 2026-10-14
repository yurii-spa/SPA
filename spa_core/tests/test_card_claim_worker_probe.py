"""Проба приёмки `card_claim_measures_the_worker` — контроль в ОБЕ стороны (ADR-721).

Правило `.claude/rules/acceptance.md` п. 3: новая проба регистрируется только с тестом,
где она ЗЕЛЁНАЯ на целом контуре и КРАСНАЯ на каждом порванном звене — с НАЗВАННЫМ
звеном, — и где она НЕ проходит подстрокой (ADR-333). Проба, никогда не видевшая
настоящей поломки, — украшение (`.claude/rules/deployment.md`, § «проверка сторожа
сторожей»).

Каждое звено рвётся на ОДНОРАЗОВОЙ КОПИИ дерева (`scripts/` + `architecture/`), живой
репозиторий не трогается ни на байт. Копия нужна именно потому, что проба меряет ИСХОД у
читателя: подменить функцию в памяти значило бы проверить подмену, а не читателя.

Семь порванных звеньев, и каждое — отдельное утверждение о защите:

1. читателя нет вовсе                      ⇒ `unmeasured` (а не `not_satisfied`);
2. прибора бюджета нет                     ⇒ `unmeasured`;
3. у читателя нет вокабуляра оси           ⇒ `not_satisfied` (замер ДО ADR-721);
4. ось РАБОТНИКА не спрашивается           ⇒ `not_satisfied`: живая работа отдаётся;
5. ось не отдаёт карточку мёртвого         ⇒ `not_satisfied`: вечный замок;
6. неизмеримость выдана за ответ           ⇒ `not_satisfied`: инв. #17;
7. бюджет работника не ограничивает        ⇒ `not_satisfied`: очередь заморожена;
8. метка не объявлена строкой захвата      ⇒ `not_satisfied`: переживёт подъём.
"""
import re
import shutil
from pathlib import Path

import pytest

from spa_core.monitoring import card_acceptance as ca

ROOT = Path(__file__).resolve().parents[2]
PROBE = "card_claim_measures_the_worker"
GUARD_REL = "scripts/check_card_claim.py"


def _run(root=None):
    return ca.PROBES[PROBE](None, repo_root=str(root) if root else None)


@pytest.fixture()
def tree(tmp_path):
    """Одноразовая копия дерева: только то, что проба читает."""
    dst = tmp_path / "repo"
    (dst).mkdir()
    shutil.copytree(ROOT / "scripts", dst / "scripts")
    return dst


def _patch(tree, old, new, *, rel=GUARD_REL, count=1):
    """Порвать звено заменой в КОПИИ. Не нашли подстроку — падать ГРОМКО.

    Молчаливый no-op здесь был бы худшим исходом: тест «порвал звено» и получил зелёную
    пробу, то есть доложил бы о дыре, которой нет, или скрыл настоящую.
    """
    p = tree / rel
    text = p.read_text(encoding="utf-8")
    assert text.count(old) == count, (
        f"якорь правки не найден ровно {count} раз(а) в {rel}: {old[:80]!r} "
        f"(найдено {text.count(old)}) — звено не порвано, тест отвечал бы не на свой вопрос")
    p.write_text(text.replace(old, new, count), encoding="utf-8")


# ── ЦЕЛЫЙ КОНТУР ────────────────────────────────────────────────────────────────


def test_the_probe_is_green_on_the_whole_contour():
    """На живом дереве критерий ВЫПОЛНЕН, и ответ называет обе стороны замера."""
    verdict, why = _run()
    assert verdict == ca.SATISFIED, (verdict, why)
    assert "claimed" in why and "stale" in why and "unchecked" in why, why


def test_the_probe_is_green_on_an_untouched_copy(tree):
    """Копия без правок зелена — значит краснота ниже от ПРАВКИ, а не от копирования."""
    verdict, why = _run(tree)
    assert verdict == ca.SATISFIED, (verdict, why)


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


def test_a_reader_without_the_axis_vocabulary_is_the_state_before_the_fix(tree):
    """Звено 3: вокабуляра оси у читателя НЕТ ⇒ `not_satisfied` — замер до ADR-721.

    Состояние воспроизводится ЦЕЛИКОМ, а не переименованием одной строки: имена `W_*`
    читает и сам модуль, поэтому «убрать только объявление» дало бы `NameError`, то есть
    ответ на вопрос «ввозится ли читатель», а не на нужный. Переименованы ОБЕ стороны —
    объявление и все чтения, — и модуль остаётся рабочим читателем без вокабуляра оси:
    ровно та форма, в которую вернулся бы откат правки.
    """
    guard = tree / GUARD_REL
    text = guard.read_text(encoding="utf-8")
    names = ("W_NOT_DECLARED", "W_ALIVE", "W_GONE", "W_UNMEASURED")
    before = sum(text.count(n) for n in names)
    # Нижняя граница, а не точное число: ПРЕДПОСЫЛКА тут — «имена есть и их читают»,
    # и она обязана падать громко, если вокабуляр исчез, но не краснеть от каждого
    # нового чтения (замер на день правки: 16 вхождений в 10 строках).
    assert before >= 10, f"имён оси в читателе всего {before} — звено рвать нечем"
    for name in names:
        text = text.replace(name, "_" + name[2:] + "_X")
    assert not any(n in text for n in names), "переименование неполное"
    guard.write_text(text, encoding="utf-8")
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "вокабуляра оси" in why, why
    assert "до ADR-721" in why, why


def test_not_asking_the_worker_axis_at_all_hands_live_work_away(tree):
    """Звено 4 — ГЛАВНОЕ: ось не спрашивается ⇒ живая работа снова отдаётся.

    Это дословный замер 14.10: тот же вход, тот же вердикт `stale`, та же цена —
    голодающий приказ владельца выдан второй сессии.
    """
    _patch(tree,
           "        if w_axis != W_NOT_DECLARED and w_ttl is not None and over is False:",
           "        if False:")
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "ЖИВОЙ работник не держит карточку" in why, why
    assert "stale" in why, why


def test_never_releasing_the_card_is_an_eternal_lock_not_a_guard(tree):
    """Звено 5: ось держит карточку и при измеренном отсутствии работника ⇒ вечный замок."""
    _patch(tree, "            if w_axis == W_ALIVE:\n", "            if w_axis:\n")
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "вечный замок" in why, why


def test_passing_unmeasured_off_as_an_answer_reddens(tree):
    """Звено 6: неизмеримость не даёт третьего исхода ⇒ `not_satisfied`, инв. #17."""
    _patch(tree, "            if w_axis == W_UNMEASURED:\n", "            if False:\n")
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "инв. #17" in why, why


def test_ignoring_the_worker_budget_freezes_the_queue(tree):
    """Звено 7: бюджет не ограничивает ⇒ повисший работник держит приказ навсегда.

    ЯКОРЬ ПРАВКИ ПЕРЕНЕСЁН НАМЕРЕННО (цикл #867, ADR-723), инв. #16: границу бюджета
    меряют теперь ДВЕ двери — захват и пересечение по объявленным файлам, — и выражение
    вынесено в единственную `over_worker_budget`. Прежний якорь
    (`over = (None if (w_ttl is None …) else age_sec > w_ttl)`) перестал быть
    единственным в файле, и `_patch` ЧЕСТНО отказал «найдено 2» вместо того чтобы
    порвать половину звена. Ни один ассерт не ослаблен: тот же разрыв теперь краснит
    ОБЕ пробы вместо одной, то есть проверка УСИЛЕНА."""
    _patch(tree, "    return age_sec > ttl", "    return False")
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "очередь заморожена" in why, why


def test_a_mark_outside_the_claim_keys_outlives_the_claim(tree):
    """Звено 8: метка не в строках захвата ⇒ уцелеет после подъёма, и проба это видит.

    Литерал кортежа обновлён циклом #869 (ADR-725 добавил в него якорь запускателя):
    утверждение и разрыв те же — из строк захвата убирается РОВНО `claimed_run_id`.
    Якорь мутация не трогает намеренно: его уцелевание — предмет соседней батареи.
    Контроль `_patch` отказал громко, а не позеленел молча, и это он и должен делать.
    """
    _patch(tree,
           '_CLAIM_KEYS = ("claimed_by", "claimed_at", "claimed_run_id", '
           '"claim_takeover_reason",\n               "claimed_pid", "claimed_pid_start")',
           '_CLAIM_KEYS = ("claimed_by", "claimed_at", "claim_takeover_reason",\n'
           '               "claimed_pid", "claimed_pid_start")')
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "_CLAIM_KEYS" in why, why


def test_dropping_the_mark_from_the_finding_reddens(tree):
    """Звено 9: метка не доезжает до находки ⇒ читателю нечем проверить вывод."""
    _patch(tree,
           '        rec["worker_run_id"] = str(run_id or "").strip() or None',
           '        rec["worker_run_id"] = None')
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "не доехала до находки" in why, why


# ── ПРОБА НЕ ПРОХОДИТ ПОДСТРОКОЙ (ADR-333) ──────────────────────────────────────


def test_prose_alone_does_not_satisfy_the_probe(tree):
    """Читатель, пересказывающий ось ПРОЗОЙ без машинного поля, пробу НЕ проходит."""
    _patch(tree, '        rec["worker_axis"] = w_axis',
           '        rec["worker_axis"] = "ось: " + str(w_axis)')
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "вне вокабуляра читателя" in why, why


def test_the_probe_reads_the_tree_it_was_given_not_the_one_it_runs_in(tree):
    """Проба грузит читателя ПО ПУТИ из `repo_root`, а не копию из `sys.modules`.

    Это класс G718 п. 2 (находка #863): звено, зелёное при полностью ослеплённом
    приборе, потому что в целевую дверь ведёт тот же зов. Проверяется наблюдаемо:
    правка в КОПИИ меняет вердикт, значит мерилась копия.
    """
    before, _ = _run(tree)
    _patch(tree,
           "        if w_axis != W_NOT_DECLARED and w_ttl is not None and over is False:",
           "        if False:")
    after, _why = _run(tree)
    assert (before, after) == (ca.SATISFIED, ca.NOT_SATISFIED), (before, after)
    # И живое дерево от этого НЕ пострадало — иначе проба правила бы то, что мерит.
    assert _run()[0] == ca.SATISFIED


def test_the_probe_is_registered_under_exactly_one_name():
    """Имя в реестре одно: два имени одной пробы — две мерки одного критерия."""
    names = [n for n, fn in ca.PROBES.items()
             if fn is ca.PROBES[PROBE]]
    assert names == [PROBE], names


def test_the_probe_docstring_names_the_measurement_not_just_the_intent():
    """Проба обязана назвать ЗАМЕР, которым обоснована, — иначе это намерение."""
    doc = ca.PROBES[PROBE].__doc__ or ""
    assert "ЗАМЕР ДО ПРАВКИ" in doc, doc[:200]
    assert "69661" in doc and "69075" in doc, doc[:400]
    # Дата замера названа явно: критерий без даты нечем перепроверить.
    assert re.search(r"14\.10", doc), doc[:400]
