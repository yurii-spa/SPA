"""Проба `file_overlap_claim_measures_the_worker` — контроль в ОБЕ стороны (ADR-723).

Правило `.claude/rules/acceptance.md` п. 3: новая проба регистрируется только с тестом,
где она ЗЕЛЁНАЯ на целом контуре и КРАСНАЯ на каждом порванном звене — с НАЗВАННЫМ
звеном, — и где она НЕ проходит подстрокой (ADR-333). Проба, никогда не видевшая
настоящей поломки, — украшение (`.claude/rules/deployment.md`, § «проверка сторожа
сторожей»).

Каждое звено рвётся на ОДНОРАЗОВОЙ КОПИИ дерева (`scripts/`), живой репозиторий не
трогается ни на байт. Копия нужна именно потому, что проба меряет ИСХОД у читателя:
подменить функцию в памяти значило бы проверить подмену, а не читателя.

Девять порванных звеньев, и каждое — отдельное утверждение о защите:

 1. читателя нет вовсе                      ⇒ `unmeasured` (а не `not_satisfied`);
 2. прибора бюджета нет                     ⇒ `unmeasured`;
 3. писателя журнала нет                    ⇒ `unmeasured`: имя поля спрашивать не у кого;
 4. ось РАБОТНИКА у пересечения не спрашивается ⇒ `not_satisfied`: состояние ДО правки;
 5. вывод оси не доезжает до `orphaned`     ⇒ `not_satisfied`: вердикт читает это поле;
 6. ось оживляет пересечение на ЛЮБОМ исходе ⇒ `not_satisfied`: вечный замок на файлах;
 7. неизмеримость выдана за ответ           ⇒ `not_satisfied`: инв. #17;
 8. бюджет работника не ограничивает        ⇒ `not_satisfied`: очередь заморожена;
 9. метка ЗАИМСТВУЕТСЯ у соседней записи    ⇒ `not_satisfied`: fail-OPEN, решение нарушено.

Звено 9 — про НАЗВАННОЕ РЕШЕНИЕ, а не про проводку, и потому оно здесь главное наравне
с 4-м: метка относится к ТОЙ ЖЕ записи, где объявлены файлы. Заимствуй её у родственной —
и переиспользованный ярлык отдаст ЖИВУЮ метку мёртвой сессии, а сужения `borrow_durable`
«процесс стартовал не позже записи» у метки нет: времени старта у неё не существует.
"""
import re
import shutil
from pathlib import Path

import pytest

from spa_core.monitoring import card_acceptance as ca

ROOT = Path(__file__).resolve().parents[2]
PROBE = "file_overlap_claim_measures_the_worker"
GUARD_REL = "scripts/check_card_claim.py"


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
    """На живом дереве критерий ВЫПОЛНЕН, и ответ называет все стороны замера."""
    verdict, why = _run()
    assert verdict == ca.SATISFIED, (verdict, why)
    for word in ("claimed", "stale", "unchecked", "not_declared"):
        assert word in why, (word, why)


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


def test_a_missing_writer_is_unmeasured(tree):
    """Звено 3: писателя журнала нет ⇒ имя поля метки спрашивать НЕ У КОГО.

    Своей копии строки у пробы нет намеренно (та же причина, что у читателя), поэтому
    отсутствие писателя обязано быть третьим исходом, а не угаданным именем поля."""
    (tree / "scripts/log_session_change.py").unlink()
    verdict, why = _run(tree)
    assert verdict == ca.UNMEASURED, (verdict, why)
    assert "log_session_change.py" in why, why


def test_not_asking_the_worker_axis_at_all_leaves_files_unprotected(tree):
    """Звено 4 — ГЛАВНОЕ: ось у пересечения не спрашивается ⇒ состояние ДО правки.

    Дословно то, что нашёл цикл #866: ярлык мёртв по оси запускателя, работник жив и
    правит те же файлы, а шаг 0b говорит «ждать некого» — две сессии правят одно."""
    _patch(tree, "                            _overlap_worker(row, entry, session, ts)\n",
           "")
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "ЖИВОЙ работник не держит ОБЪЯВЛЕННЫЕ ИМ ФАЙЛЫ" in why, why
    assert "stale" in why, why


def test_a_verdict_that_never_reaches_orphaned_is_not_protection(tree):
    """Звено 5: ось посчитана, но до `orphaned` не доехала ⇒ вердикт её не увидит.

    Поле `orphaned` — единственная дорога к «ЗАНЯТА» (`live_overlaps`). Проба обязана
    мерить ИСХОД, а не наличие вычисления: «посчитали и не применили» выглядит в коде
    как работающая защита."""
    _patch(tree, '            row["orphaned"] = False\n', "")
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "ЖИВОЙ работник не держит ОБЪЯВЛЕННЫЕ ИМ ФАЙЛЫ" in why, why


def test_losing_the_launcher_measurement_reddens(tree):
    """Звено 5-bis: замер оси ЗАПУСКАТЕЛЯ не сохранён ⇒ вывод оси выдан за замер pid.

    Звено добавлено ПО НАХОДКЕ МУТАЦИЙ, а не по аналогии: мутант «проба не проверяет
    `launcher_orphaned`» ВЫЖИЛ — свойство дискриминировала только батарея поведения, а
    сама проба была к нему слепа. Для критерия приёмки это дыра, а не равносильность:
    пробу читает шаг 0-офис каждый цикл, и слепая проба подтвердила бы читателя, который
    печатает «долгоживущий процесс не опровергнут» там, где `ps` его измеренно не нашёл.

    Звено рвётся ПОДМЕНОЙ значения, а не удалением строки, и это не стилистика: удаление
    ломает САМ читатель (`worker_detail` читает поле тем же выражением ⇒ `KeyError` ⇒
    проба честно отвечает `unmeasured`), и такой разрыв проверяет ввоз модуля, а не
    слепоту пробы — то есть не изолирует предмет. Подмена оставляет читатель рабочим и
    отличает ровно одно: доехал ли ЗАМЕР оси запускателя до поля."""
    _patch(tree, '            row["launcher_orphaned"] = row["orphaned"]',
           '            row["launcher_orphaned"] = False')
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "ИЗМЕРЕНИЕ оси запускателя" in why, why


def test_never_releasing_the_files_is_an_eternal_lock_not_a_guard(tree):
    """Звено 6: пересечение оживает на ЛЮБОМ исходе оси ⇒ вечный замок на чужих файлах."""
    _patch(tree, "        if w_axis == W_ALIVE:\n            # Файлы держит ЖИВАЯ работа.",
           "        if w_axis:\n            # Файлы держит ЖИВАЯ работа.")
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "вечный замок на чужих файлах" in why, why


def test_passing_unmeasured_off_as_an_answer_reddens(tree):
    """Звено 7: неизмеримость не даёт третьего исхода ⇒ `not_satisfied`, инв. #17."""
    _patch(tree, "        if w_axis == W_UNMEASURED:\n"
                 '            _unmeasured("announce-log-files",',
           "        if False:\n"
           '            _unmeasured("announce-log-files",')
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "инв. #17" in why, why


def test_ignoring_the_worker_budget_freezes_the_queue(tree):
    """Звено 8: бюджет не ограничивает ⇒ повисший работник держит чужие файлы вечно.

    Звено ОБЩЕЕ с пробой захвата (`over_worker_budget` — одна копия на обе двери), и это
    свойство, а не совпадение: расхождение двух копий границы было бы молчаливым."""
    _patch(tree, "    return age_sec > ttl", "    return False")
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "очередь заморожена" in why, why


def test_borrowing_the_mark_from_a_kin_record_breaks_the_named_decision(tree):
    """Звено 9: метка заимствуется у соседней записи ⇒ fail-OPEN, и проба это видит.

    Рвётся ровно названное решение: метка берётся не из записи с файлами, а у первой
    записи того же ярлыка, несущей её хоть где. Так переиспользованный ярлык отдал бы
    живую метку мёртвой сессии — направление ошибки обратное нужному."""
    _patch(tree,
           '        mark = str(entry.get(field_name) or "").strip() if field_name else ""',
           '        mark = str(entry.get(field_name) or "").strip() if field_name else ""\n'
           "        if not mark and field_name:\n"
           "            for _kin in (entries or ()):\n"
           '                if (str((_kin or {}).get("session") or "").strip() == session\n'
           '                        and str((_kin or {}).get(field_name) or "").strip()):\n'
           '                    mark = str(_kin.get(field_name)).strip()\n'
           "                    break")
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "РОДСТВЕННОЙ записи" in why, why
    assert "fail-OPEN" in why, why


# ── ПРОБА НЕ ПРОХОДИТ ПОДСТРОКОЙ (ADR-333) ──────────────────────────────────────


def test_prose_alone_does_not_satisfy_the_probe(tree):
    """Читатель, пересказывающий ось ПРОЗОЙ без машинного поля, пробу НЕ проходит."""
    _patch(tree, '        row["worker_axis"] = w_axis',
           '        row["worker_axis"] = "ось: " + str(w_axis)')
    verdict, why = _run(tree)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "вне вокабуляра читателя" in why, why


def test_the_probe_reads_the_tree_it_was_given_not_the_one_it_runs_in(tree):
    """Проба грузит читателя ПО ПУТИ из `repo_root`, а не копию из `sys.modules`.

    Класс G718 п. 2 (находка #863): звено, зелёное при полностью ослеплённом приборе,
    потому что в целевую дверь ведёт тот же зов. Проверяется наблюдаемо: правка в КОПИИ
    меняет вердикт, значит мерилась копия — и живое дерево при этом не пострадало."""
    before, _ = _run(tree)
    _patch(tree, "                            _overlap_worker(row, entry, session, ts)\n",
           "")
    after, _why = _run(tree)
    assert (before, after) == (ca.SATISFIED, ca.NOT_SATISFIED), (before, after)
    assert _run()[0] == ca.SATISFIED


def test_the_probe_is_registered_under_exactly_one_name():
    """Имя в реестре одно: два имени одной пробы — две мерки одного критерия."""
    names = [n for n, fn in ca.PROBES.items() if fn is ca.PROBES[PROBE]]
    assert names == [PROBE], names


def test_the_probe_docstring_names_the_measurement_not_just_the_intent():
    """Проба обязана назвать ЗАМЕР и ДАТУ, иначе критерий нечем перепроверить."""
    doc = ca.PROBES[PROBE].__doc__ or ""
    assert "durable_process_gone" in doc, doc[:300]
    assert "ADR-720" in doc and "ADR-721" in doc and "ADR-722" in doc, doc[:400]
    assert re.search(r"#866", doc), doc[:400]


def test_the_scene_carries_no_claim_so_the_verdict_cannot_come_from_a_neighbour():
    """Сцена пробы НЕ содержит захвата — иначе она мерила бы ADR-721/722, а не себя.

    Это предпосылка ОСМЫСЛЕННОСТИ всей пробы, и рвётся она НАОБОРОТ: записи сцены
    добавляется поле `card:`, то есть объявление файлов становится ещё и захватом. Тогда
    `claimed` приходил бы от записи захвата, и порванное пересечение выглядело бы целым —
    ровно та односторонность, которой проба и не должна страдать.

    Правка живёт в САМОЙ пробе, а не в читателе, поэтому и рвётся копия пробы: собирается
    отдельный модуль из подменённого текста `card_acceptance`, живой не трогается."""
    import types

    src_path = ROOT / "spa_core/monitoring/card_acceptance.py"
    src = src_path.read_text(encoding="utf-8")
    old = ('                entry = {"ts": at, "session": label, '
           '"summary": "сцена приёмки: файлы",')
    assert src.count(old) == 1, (
        "якорь сцены пробы не единственный — звено не порвано, тест отвечал бы не на "
        "свой вопрос")
    patched = src.replace(
        old,
        '                entry = {"card": "inbox-scene", "card_state": "claim",\n'
        '                         "ts": at, "session": label, '
        '"summary": "сцена приёмки: файлы",', 1)
    mod = types.ModuleType("_c867_card_acceptance_patched")
    mod.__file__ = str(src_path)
    try:
        exec(compile(patched, str(src_path), "exec"), mod.__dict__)   # noqa: S102
    except Exception as exc:                         # pragma: no cover — предпосылка
        pytest.fail(f"копия пробы не собралась ({type(exc).__name__}: {exc}) — "
                    f"звено не порвано")
    verdict, why = mod.PROBES[PROBE](None)
    assert verdict == ca.NOT_SATISFIED, (verdict, why)
    assert "появилась находка-ЗАХВАТ" in why, why
