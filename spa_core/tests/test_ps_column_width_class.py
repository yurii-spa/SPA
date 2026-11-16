"""Сторож класса «вердикт есть свойство того, как `ps` сегодня рисует вывод» (ADR-1032).

# LLM_FORBIDDEN

Каждая проверка здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ настоящей аварии, а не украшение
(`.claude/rules/deployment.md`, § «Проверка сторожа сторожей»):

* авария ADR-1031 — GNU-`ps` обрезал строку, прибор не узнал своего же дочернего
  процесса, и семь тестов были красны в CI и зелены на Маке;
* авария самого прибора ADR-1032 — `.strip()` съел подбитую пробелами колонку `ppid`,
  и дверь `call_provenance` вышла «устойчивой» там, где она переворачивается;
* авария объявления — `asks_ww`, прочитанный у СВОЕГО объявления вместо исходника,
  напечатал «`-ww` НЕТ» про уже починенные двери.

Предмет сторожа — не «красно ли сегодня», а два утверждения:
**(1)** поверхность объявлена целиком — новый зов `ps` с колонкой `command` краснит
сразу; **(2)** ни одна дверь не является членом класса. `FROZEN-DATE-OK` здесь не
нужен: литеральных дат в сценах нет, а субъекты — строки процессов, не календарь.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from spa_core.tests import _ps_column_width as pscw

_ROOT = Path(__file__).resolve().parents[2]


# ── 1. Поверхность объявлена целиком ─────────────────────────────────────────

def test_every_ps_door_carrying_the_command_column_is_declared():
    """Новый зов `ps` с колонкой `command` обязан получить объявленную дверь.

    Иначе класс закрывается молча: следующая дверь родится необмеренной, а счётчик
    «членов 0» будет верен ПО СВОЕЙ мерке и ничего не скажет о новой.
    """
    rep = pscw.build_report()
    assert rep["surface_not_declared"] == [], (
        "зов `ps` с колонкой `command` не объявлен дверью — объявить в "
        "`_ps_column_width.DOORS` и ИЗМЕРИТЬ, переворачивается ли его вердикт: "
        f"{rep['surface_not_declared']}")
    assert rep["declared_not_in_surface"] == [], (
        "объявленная дверь в исходниках не найдена — формат зова изменился, объявление "
        f"устарело: {rep['declared_not_in_surface']}")
    assert rep["unreadable"] == [], f"файл не разобран — НЕ ИЗМЕРЕНО: {rep['unreadable']}"


def test_the_surface_is_measured_and_not_assumed():
    """Поверхность — ЗАМЕР, и её размер назван числом, а не словом «все»."""
    surf = pscw.surface()
    assert len(surf["sites"]) >= len(surf["with_command"]) > 0
    # зов без колонки `command` членом класса не является по построению: сравнивать нечего
    for site in surf["without_command"]:
        assert not site.carries_command


# ── 2. Главное утверждение ───────────────────────────────────────────────────

def test_no_door_is_a_member_of_the_class():
    """Переворачивается ⇒ обязана просить `-ww`. Это и есть закрытие класса."""
    rep = pscw.build_report()
    members = [r for r in rep["rows"] if pscw.is_member(r)]
    assert members == [], "\n".join(
        f"{r['path']}:{r.get('line')} — {r.get('why')}" for r in members)


def test_every_door_outcome_is_one_of_the_declared_three():
    """Четвёртого ярлыка нет, и пустого вердикта нет (инв. #17)."""
    rep = pscw.build_report()
    assert len(rep["rows"]) == len(pscw.DOORS)
    for r in rep["rows"]:
        assert r.get("outcome") in pscw.OUTCOMES, r
        assert str(r.get("why") or "").strip(), f"исход без названной причины: {r}"


def test_a_stable_door_carries_a_measured_slack_not_only_prose():
    """«Не переворачивается» без ЧИСЛА — не ответ: запас в одну колонку и в сорок разные.

    Замер ADR-1032: `check_undelivered_work` 76 колонок · `director_report` 39 ·
    `telegram_health` ШЕСТЬ — и последнее названо вслух, потому что запас есть длина
    пути к интерпретатору, а не свойство предиката.
    """
    rep = pscw.build_report()
    stable = [r for r in rep["rows"] if r.get("outcome") == pscw.STABLE]
    assert stable, "устойчивых дверей не осталось — сцена потеряла предмет"
    for r in stable:
        assert "slack_columns" in r, r
        assert r["slack_columns"] is None or isinstance(r["slack_columns"], int)
        assert "ЗАПАС" in r["why"] or "НЕ ИЗМЕРЕН" in r["why"], r["why"]
    # «запас НЕ ИЗМЕРЕН» у ВСЕХ трёх было бы честной формой пустого прибора: ярлык стоит,
    # числа нет. Замер ADR-1032 дал число у каждой — требуем его, иначе сломанный
    # `flip_width` прошёл бы сцену молча.
    measured = [r for r in stable if isinstance(r.get("slack_columns"), int)]
    assert len(measured) == len(stable), (
        "запас обязан быть ИЗМЕРЕН у каждой устойчивой двери: "
        f"{[(r['path'], r.get('slack_columns')) for r in stable]}")
    assert min(r["slack_columns"] for r in measured) <= 6, (
        "самый узкий измеренный запас — шесть колонок у `telegram_health`; если он вырос, "
        "предмет сцены изменился и это надо ПЕРЕМЕРИТЬ, а не подогнать")


# ── 3. Контроль: прибор УМЕЕТ увидеть аварию ─────────────────────────────────

def _door(**kw) -> pscw.Door:
    base = dict(path="x.py", name="сцена", fmt="command=", decides="нечто",
                verdict=lambda t: t.strip(), frozen=("x" * 100,), frozen_from="сцена")
    base.update(kw)
    return pscw.Door(**base)


def test_the_instrument_calls_a_flipping_door_a_flip():
    """Вердикт, зависящий от хвоста длинной строки, обязан быть назван `flips`."""
    door = _door(verdict=lambda t: "МАРКЕР" in t,
                 frozen=("a" * 90 + "МАРКЕР",))
    row = pscw.measure(door)
    assert row["outcome"] == pscw.FLIPS, row
    assert row["asks_ww"] is None, "у объявления флага нет — его меряет исходник"


def test_the_instrument_replays_the_real_adr_1031_failure():
    """Настоящая строка раннера: прибор мутаций не узнаёт СЕБЯ на обрезанной строке."""
    door = pscw.DOORS_BY_KEY["scripts/delta_mutation_run.py::lstart=,command="]
    subject = door.frozen[0]
    assert len(subject) > pscw.GNU_DEFAULT_COLUMNS
    assert door.verdict(subject) == "alive"
    assert door.verdict(pscw.truncate(subject)) == "unmeasured", (
        "обрезанная строка раннера обязана давать `unmeasured` — это и была авария")


def test_the_instrument_replays_the_concurrent_pytest_blindness():
    """Сторож параллельных прогонов на обрезанной строке не видит НИ ОДНОГО прогона."""
    door = pscw.DOORS_BY_KEY["scripts/check_concurrent_pytest.py::pid=,ppid=,lstart=,command="]
    subject = door.frozen[0]
    assert door.verdict(subject), "на полной строке прогон обязан быть виден"
    assert door.verdict(pscw.truncate(subject)) == (), (
        "на обрезанной строке сторож слепнет — это fail-OPEN, ради которого правка")


def test_the_padded_column_is_not_stripped_away():
    """Контроль аварии САМОГО прибора: `.strip()` подделывал устойчивость двери.

    Строка ребёнка launchd несёт колонку `ppid`, подбитую пробелами слева. С ними
    маркер `scripts/agent_template.sh` кончается на колонке 84 и обрезанием теряется;
    без них — ровно на 80, и дверь выглядит устойчивой. Разница в четырёх пробелах
    переворачивает ВЫВОД О КЛАССЕ, поэтому проверка стои́т здесь, а не в прозе.
    """
    door = pscw.DOORS_BY_KEY["spa_core/monitoring/call_provenance.py::ppid=,command="]
    padded = door.frozen[0]
    stripped = "\n".join(l.strip() for l in padded.splitlines())
    assert door.verdict(padded) != door.verdict(pscw.truncate(padded)), (
        "на НАСТОЯЩЕЙ (подбитой) строке дверь обязана переворачиваться")
    assert door.verdict(stripped) == door.verdict(pscw.truncate(stripped)), (
        "срезав паддинг, прибор перестаёт видеть переворот — ровно его собственный дефект")


def test_truncation_cuts_every_line_and_not_the_text():
    """GNU-`ps` режет КАЖДУЮ строку. Резать текст целиком — другая мера и неверная."""
    text = "a" * 100 + "\n" + "b" * 100
    cut = pscw.truncate(text, 10)
    assert cut == "a" * 10 + "\n" + "b" * 10
    assert len(cut.splitlines()) == 2, "строки не теряются — теряются их хвосты"


# ── 4. Контроль третьего исхода ──────────────────────────────────────────────

def test_an_absent_subject_is_unmeasured_and_never_clean():
    """Субъекта нет ⇒ `unmeasured` с причиной, а не «не переворачивается»."""
    row = pscw.measure(_door(frozen=("",)))
    assert row["outcome"] == pscw.UNMEASURED
    assert "субъекта нет" in row["why"]


def test_a_door_that_refuses_to_answer_is_unmeasured():
    """Дверь бросила исключение ⇒ НЕ ИЗМЕРЕНО, а не «чисто»."""
    def boom(_t):
        raise RuntimeError("дверь молчит")
    row = pscw.measure(_door(verdict=boom))
    assert row["outcome"] == pscw.UNMEASURED
    assert "НЕ ИЗМЕРЕН" in row["why"]


def test_a_subject_shorter_than_the_limit_is_unreachable_not_stable():
    """Предел не достигается — ОТДЕЛЬНОЕ наблюдение, а не устойчивость."""
    row = pscw.measure(_door(frozen=("короткая строка",)))
    assert row["outcome"] == pscw.UNREACHABLE
    assert "НЕ ДОХОДИТ" in row["why"]


def test_unmeasured_ww_never_counts_as_a_member():
    """`asks_ww is None` — это «не измерено», и членом класса не делает (инв. #17)."""
    assert pscw.is_member({"outcome": pscw.FLIPS, "asks_ww": None}) is False
    assert pscw.is_member({"outcome": pscw.FLIPS, "asks_ww": False}) is True
    assert pscw.is_member({"outcome": pscw.FLIPS, "asks_ww": True}) is False


# ── 5. Контроль: флаг меряется в ИСХОДНИКЕ, а не в объявлении ────────────────

def test_asks_ww_is_read_from_the_source_and_not_from_the_declaration(tmp_path):
    """Объявление о флаге ответом не является — это измеренная авария ADR-1032."""
    pkg = tmp_path / "spa_core"
    pkg.mkdir()
    (pkg / "fake_door.py").write_text(textwrap.dedent('''
        import subprocess
        def read():
            # в прозе написано `-ww`, а в вызове его нет
            return subprocess.run(["ps", "-eo", "pid=,command="])
    '''), encoding="utf-8")
    surf = pscw.surface(tmp_path)
    found = [s for s in surf["with_command"] if s.path.endswith("fake_door.py")]
    assert len(found) == 1, surf["with_command"]
    assert found[0].asks_ww is False, "флаг обязан читаться у ВЫЗОВА, а не у комментария"

    (pkg / "fixed_door.py").write_text(
        'import subprocess\n'
        'def read():\n'
        '    return subprocess.run(["ps", "-ww", "-eo", "pid=,command="])\n',
        encoding="utf-8")
    surf2 = pscw.surface(tmp_path)
    fixed = [s for s in surf2["with_command"] if s.path.endswith("fixed_door.py")]
    assert fixed and fixed[0].asks_ww is True


def test_build_report_takes_ww_from_the_surface_for_every_door():
    """Отчёт обязан нести ИЗМЕРЕННЫЙ флаг у КАЖДОЙ двери, а не подставленный.

    Мутант «asks_ww = True всегда» выжил на первой редакции сцены: у всех шести
    переворачивающихся дверей флаг и правда стои́т, и подстановка давала тот же ответ.
    Различают её три УСТОЙЧИВЫЕ двери, у которых флага нет: отчёт обязан сказать про
    них `False`, иначе он читает не исходник.
    """
    rep = pscw.build_report()
    in_source = {s.key: s.asks_ww for s in pscw.surface()["with_command"]}
    for r in rep["rows"]:
        assert r["asks_ww"] == in_source[r["key"]], (
            f"{r['path']}: отчёт говорит {r['asks_ww']}, исходник — {in_source[r['key']]}")
    assert sorted(set(in_source.values())) == [False, True], (
        "сцена различает отчёт и подстановку только пока в дереве есть двери БЕЗ флага "
        "и С флагом; остался один род — проверка выродилась и это надо ПЕРЕМЕРИТЬ")


def test_the_ps_line_door_keeps_the_leading_padding(monkeypatch):
    """Единственная дверь к строке `ps` не срезает ведущие пробелы колонок.

    Положительный контроль дефекта САМОГО прибора (ADR-1032): `.strip()` сдвинул все
    колонки на ширину паддинга, и переворот двери `call_provenance` стал невидим.
    """
    monkeypatch.setattr(pscw, "_ps", lambda argv: "    1 /bin/bash /x/y\n")
    assert pscw._ps_line(["ps"]) == "    1 /bin/bash /x/y"


def test_the_door_key_survives_an_edit_above_it(tmp_path):
    """Ключ двери — файл и ФОРМАТ: номер строки съезжает и ключом быть не может."""
    pkg = tmp_path / "spa_core"
    pkg.mkdir()
    body = 'import subprocess\nf = lambda: subprocess.run(["ps", "-eo", "pid=,command="])\n'
    (pkg / "d.py").write_text(body, encoding="utf-8")
    before = pscw.surface(tmp_path)["with_command"][0]
    (pkg / "d.py").write_text("# добавленная строка\n" * 7 + body, encoding="utf-8")
    after = pscw.surface(tmp_path)["with_command"][0]
    assert after.line != before.line, "сцена обязана СДВИНУТЬ номер строки"
    assert after.key == before.key, "ключ от сдвига меняться не имеет права"


# ── 6. Коды возврата прибора различимы ───────────────────────────────────────

def test_the_instrument_exit_code_separates_finding_from_unmeasured():
    """0 — чисто · 1 — находка · 2 — НЕ ИЗМЕРЕНО. Три исхода у кода возврата тоже."""
    out = subprocess.run([sys.executable, "-m", "spa_core.tests._ps_column_width"],
                         cwd=_ROOT, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, (
        f"прибор на чистом дереве обязан выходить 0; вышел {out.returncode}\n{out.stdout}\n{out.stderr}")
    assert "ЧЛЕНОВ КЛАССА: 0" in out.stdout, out.stdout


@pytest.mark.parametrize("counters,unreadable,expected", [
    ({"НЕ ИЗМЕРЕНО": 0, "ЧЛЕНОВ КЛАССА": 0}, [], 0),
    ({"НЕ ИЗМЕРЕНО": 0, "ЧЛЕНОВ КЛАССА": 1}, [], 1),
    ({"НЕ ИЗМЕРЕНО": 1, "ЧЛЕНОВ КЛАССА": 0}, [], 2),
    ({"НЕ ИЗМЕРЕНО": 0, "ЧЛЕНОВ КЛАССА": 0}, [{"path": "p", "why": "w"}], 2),
    # РАЗЛИЧАЮЩАЯ сцена: обе причины сразу. Без неё мутант «находка важнее НЕ ИЗМЕРЕНО»
    # выживал — каждая строка выше включает ровно одно условие, и порядок не наблюдался.
    # «Не измерено» обязано ПОБЕЖДАТЬ находку: вердикт о классе при неполном замере не
    # выносится вовсе (fail-CLOSED, инв. #17), а код 1 читался бы как полный ответ.
    ({"НЕ ИЗМЕРЕНО": 1, "ЧЛЕНОВ КЛАССА": 1}, [], 2),
    ({"НЕ ИЗМЕРЕНО": 0, "ЧЛЕНОВ КЛАССА": 2}, [{"path": "p", "why": "w"}], 2),
])
def test_exit_code_prefers_unmeasured_over_clean(monkeypatch, counters, unreadable, expected):
    """«Не измерено» НИКОГДА не выдаётся за «чисто» — даже когда находок нет."""
    fake = {"source": "сцена", "rows": [], "counters": counters, "unreadable": unreadable,
            "surface_not_declared": [], "declared_not_in_surface": [], "without_command": []}
    monkeypatch.setattr(pscw, "build_report", lambda **kw: fake)
    assert pscw.main([]) == expected
