"""Батарея ВВЕЗЁННОГО прибора мутационного замера по дельте (ADR-726, цикл #870).

Предмет — `scripts/delta_mutation_run.py`. Он мерит ЧУЖИЕ батареи, поэтому у него самого
батарея обязана быть строже обычной: прибор, который врёт о мутациях, делает ложным
главное доказательство приёмки КАЖДОГО цикла, и ошибётся он в сторону самоуспокоения
(«все убиты»), а не тревоги.

Устройство батареи — по звеньям, у каждого обратная сторона с НАЗВАННЫМ звеном:

* спецификация: отказ громкий, а пустое население НИКОГДА не читается как «чисто»;
* адрес мутации: выход за дерево, ссылка, `data/` — три отказа, каждый по измеренной
  аварии, а не из осторожности;
* вердикт: по РАЗНОСТИ НАБОРОВ ИМЁН, а не по коду возврата pytest (урок цикла #810);
* третий исход: «не применена» и «сломал сборку» доезжают до КОДА ВОЗВРАТА (инв. #17) —
  это и есть дефект, которого не было ни у одного из 25 одноразовых приборов;
* инертность: дерево после прогона побайтово то же, и это ПРОВЕРЯЕТСЯ, а не обещается;
  обратная сторона — прогон, испортивший дерево, обязан падать ГРОМКО.

Время и прогон — ВХОДЫ (`runner=`), литеральных дат и литеральных pid в файле нет
(`.claude/rules/deployment.md` §§ «ВРЕМЯ В ТЕСТАХ», «ЛИЧНОСТЬ ПРОЦЕССА»). Две сцены
намеренно поднимают НАСТОЯЩИЙ pytest — иначе разбор его вывода и закрепление окружения
остались бы непроверенными утверждениями о подпрограмме, которую никто не звал.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOL = os.path.join(_REPO_ROOT, "scripts", "delta_mutation_run.py")


def _load_tool():
    """Ввезти прибор из его файла.

    Регистрация в `sys.modules` ДО исполнения — не украшение: `dataclasses` разрешает
    строковые аннотации через `sys.modules[cls.__module__]`, и у незарегистрированного
    модуля это `None` ⇒ `AttributeError` на сборке. Прибор объявляет это требование у
    себя в шапке, чтобы следующий читатель не искал причину заново.
    """
    name = "_delta_mutation_run_under_test"
    spec = importlib.util.spec_from_file_location(name, _TOOL)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


dmr = _load_tool()


# ───────────────────────── подмостки ─────────────────────────


def _tree(tmp_path, *, body: str = "VALUE = 1\n", rel: str = "pkg/mod.py") -> str:
    """Одноразовое дерево с одним файлом. Возврат — корень."""
    root = tmp_path / "tree"
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return str(root)


def _spec(mutations, *, tests=("t/test_x.py",), title="сцена"):
    return dmr.Spec(title, tuple(tests),
                    tuple(dmr.Mutation(*m) if isinstance(m, tuple) else m
                          for m in mutations))


def _runner(script):
    """Прогон как ВХОД: `script` — список (код, вывод) по вызовам, либо callable."""
    if callable(script):
        return script
    calls = list(script)

    def _run(_tests):
        return calls.pop(0) if calls else (0, "")

    return _run


def _write_spec(tmp_path, doc) -> str:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return str(path)


# ───────────────────────── спецификация: отказ громкий ─────────────────────────


def test_a_missing_spec_refuses_loudly(tmp_path):
    with pytest.raises(dmr.SpecError) as exc:
        dmr.load_spec(str(tmp_path / "нет.json"))
    assert "спецификации нет" in str(exc.value)


def test_a_spec_that_is_not_json_refuses_loudly(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text("{не json", encoding="utf-8")
    with pytest.raises(dmr.SpecError) as exc:
        dmr.load_spec(str(path))
    assert "не читается" in str(exc.value)


def test_a_spec_that_is_not_an_object_refuses(tmp_path):
    with pytest.raises(dmr.SpecError) as exc:
        dmr.load_spec(_write_spec(tmp_path, ["список"]))
    assert "не объект" in str(exc.value)


def test_an_empty_population_is_refused_and_never_reads_as_clean(tmp_path):
    """ЗВЕНО: пустое население. Без отказа прибор напечатал бы «выживших нет»,
    ничего не измерив, — та самая подделка доказательства (ADR-468)."""
    with pytest.raises(dmr.SpecError) as exc:
        dmr.load_spec(_write_spec(tmp_path, {"tests": ["t"], "mutations": []}))
    assert "mutations" in str(exc.value) and "ничего не измерив" in str(exc.value)


def test_a_spec_without_a_battery_is_refused(tmp_path):
    """ЗВЕНО: `tests`. Батареи нет ⇒ мутанта судить нечем, и это не «ноль выживших»."""
    with pytest.raises(dmr.SpecError) as exc:
        dmr.load_spec(_write_spec(tmp_path, {
            "tests": [], "mutations": [{"name": "n", "file": "f", "old": "a", "new": "b"}]}))
    assert "tests" in str(exc.value)


def test_a_mutation_without_required_fields_is_refused(tmp_path):
    with pytest.raises(dmr.SpecError) as exc:
        dmr.load_spec(_write_spec(tmp_path, {
            "tests": ["t"], "mutations": [{"name": "n", "file": "f"}]}))
    assert "old" in str(exc.value) and "new" in str(exc.value)


def test_a_mutation_whose_anchor_equals_the_replacement_is_refused(tmp_path):
    """ЗВЕНО: `old == new`. Такая «мутация» не рвёт ничего и выжила бы по построению —
    то есть напечатала бы ДЫРУ ПОКРЫТИЯ, которой нет."""
    with pytest.raises(dmr.SpecError) as exc:
        dmr.load_spec(_write_spec(tmp_path, {
            "tests": ["t"],
            "mutations": [{"name": "n", "file": "f", "old": "a", "new": "a"}]}))
    assert "якорь равен подмене" in str(exc.value)


def test_a_valid_spec_parses_with_its_whole_population(tmp_path):
    """Обратная сторона всех отказов выше: исправная спецификация читается целиком."""
    spec = dmr.load_spec(_write_spec(tmp_path, {
        "title": "дельта", "tests": ["a.py", "b.py"],
        "mutations": [{"name": "первая", "file": "pkg/mod.py", "old": "x", "new": "y"},
                      {"name": "вторая", "file": "pkg/mod.py", "old": "p", "new": "q"}]}))
    assert spec.title == "дельта"
    assert spec.tests == ("a.py", "b.py")
    assert [m.name for m in spec.mutations] == ["первая", "вторая"]


# ───────────────────────── адрес мутации: три запрета ─────────────────────────


def test_an_absolute_path_is_refused(tmp_path):
    root = _tree(tmp_path)
    with pytest.raises(dmr.SpecError) as exc:
        dmr.resolve_target(os.path.join(root, "pkg/mod.py"), root)
    assert "ОТНОСИТЕЛЬНЫМ" in str(exc.value)


def test_a_path_escaping_the_tree_is_refused(tmp_path):
    """ЗВЕНО: выход за дерево. Мутировать чужое дерево прибор не вправе."""
    root = _tree(tmp_path)
    (tmp_path / "чужой.py").write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(dmr.SpecError) as exc:
        dmr.resolve_target(os.path.join("..", "чужой.py"), root)
    assert "наружу дерева" in str(exc.value)


def test_a_symlink_out_of_the_tree_is_refused(tmp_path):
    """ЗВЕНО: символическая ссылка НАРУЖУ. Механизм ИЗМЕРЕН карточкой
    `inbox-ubityi-progon-perepisi-ostavlyaet-mutant`: запись сквозь ссылку уходит в
    настоящий файл за пределами копии, и возврат убитого прогона его не вернёт.

    Проверяется ПРИЧИНА отказа, а не только его факт: эта сцена ловится И запретом
    выхода за дерево, поэтому утверждать «отказал» было бы утверждением о соседе."""
    root = _tree(tmp_path)
    outside = tmp_path / "настоящий.py"
    outside.write_text("VALUE = 1\n", encoding="utf-8")
    os.symlink(str(outside), os.path.join(root, "pkg", "цель.py"))
    with pytest.raises(dmr.SpecError) as exc:
        dmr.resolve_target("pkg/цель.py", root)
    assert "символическая ссылка" in str(exc.value)


def test_a_symlink_inside_the_tree_is_refused_too(tmp_path):
    """ОБРАТНАЯ СТОРОНА и НАСТОЯЩИЙ положительный контроль этого звена.

    Ссылка, разрешающаяся ВНУТРЬ дерева, запретом выхода не ловится вовсе — её ловит
    только запрет ссылки. Снятие запрета у прежней сцены переживало мутацию, потому что
    сообщение соседнего отказа содержало те же слова: тест проверял, что отказ ЕСТЬ, а
    не что отказал ТОТ ЖЕ сторож (мутация «запрет символической ссылки снят», замер
    ВВЕЗЁННЫМ прибором, цикл #870).

    Вред у такой ссылки свой: `os.replace` ПОДМЕНЯЕТ саму ссылку обычным файлом, то есть
    возврат вернул бы не ссылку, а копию, и дерево разошлось бы необратимо."""
    root = _tree(tmp_path, body="VALUE = 1\n")
    os.symlink(os.path.join(root, "pkg", "mod.py"), os.path.join(root, "pkg", "внутрь.py"))
    with pytest.raises(dmr.SpecError) as exc:
        dmr.resolve_target("pkg/внутрь.py", root)
    assert "символическая ссылка" in str(exc.value)
    # Различать отказы приходится по формуле, уникальной для СОСЕДА: слова «наружу
    # дерева» есть и в прозе запрета ссылки (он объясняет ими ВРЕД), поэтому «их нет»
    # было бы утверждением о словах, а не о том, кто отказал.
    assert "разрешается наружу дерева" not in str(exc.value), (
        "сцену обязан закрыть запрет ССЫЛКИ, а не запрет выхода за дерево")


def test_a_path_under_data_is_refused_because_the_track_lives_there(tmp_path):
    """ЗВЕНО: `data/`. Правило доставки запрещает трогать его вовсе (п. 4)."""
    root = _tree(tmp_path, rel="data/equity_curve_daily.json", body="{}\n")
    with pytest.raises(dmr.SpecError) as exc:
        dmr.resolve_target("data/equity_curve_daily.json", root)
    assert "data/" in str(exc.value)


def test_a_missing_file_is_refused_not_counted_as_not_applied(tmp_path):
    root = _tree(tmp_path)
    with pytest.raises(dmr.SpecError) as exc:
        dmr.resolve_target("pkg/нет.py", root)
    assert "файла мутации нет" in str(exc.value)


def test_an_ordinary_file_inside_the_tree_resolves(tmp_path):
    """Обратная сторона трёх запретов: обычный файл дерева разрешается."""
    root = _tree(tmp_path)
    assert dmr.resolve_target("pkg/mod.py", root) == os.path.realpath(
        os.path.join(root, "pkg/mod.py"))


# ───────────────────────── вердикт: по РАЗНОСТИ ИМЁН ─────────────────────────


def test_the_summary_parser_reads_both_failures_and_errors():
    """ЗВЕНО: разбор короткой сводки (`-rfE`). Строка `ERROR` — это упавший СБОР файла,
    и потерять её значило бы объявить мутанта выжившим там, где он снёс чужой модуль
    (мутация «разбор сводки теряет строки ERROR» переживала батарею — замер #870)."""
    out = ("FAILED t/test_a.py::test_one - assert 1 == 2\n"
           "ERROR t/test_b.py - ImportError: нет модуля\n"
           "1 failed, 1 error")
    assert dmr.parse_failures(out) == ("t/test_a.py::test_one", "t/test_b.py")
    assert dmr.parse_failures("") == ()
    assert dmr.parse_failures("2 passed") == ()


@pytest.mark.timeout(300)
def test_the_summary_parser_sees_a_failure_under_subtest(tmp_path):
    """ЗВЕНО: третья строка сводки. Падение под `self.subTest` приходит НЕ как `FAILED`.

    Сцена поднимает НАСТОЯЩИЙ pytest намеренно: предметом здесь является ФОРМА его
    вывода, и выдуманная строка проверяла бы мою память о pytest, а не pytest. Четыре
    формы суффикса закреплены ровно потому, что в них БЫВАЮТ ПРОБЕЛЫ — имя теста нельзя
    брать «вторым словом строки», и смена формы в будущей версии pytest обязана
    КРАСНИТЬ этот тест, а не молча вернуть прибору слепоту.

    Положительный контроль класса, съевшего ДЕВЯТЬ мутационных находок за четыре цикла
    (#876 ADR-761, #947 ADR-823, #950 ADR-825): до цикла #951 `parse_failures` на этом
    самом выводе возвращала ПУСТО для всех четырёх носителей, и прибор звал их дырой
    покрытия."""
    root = str(tmp_path)
    with open(os.path.join(root, "test_forms.py"), "w", encoding="utf-8") as fh:
        fh.write(
            "import unittest\n\n\n"
            "class V(unittest.TestCase):\n"
            "    def test_no_params(self):\n"
            "        with self.subTest():\n"
            "            self.assertEqual(1, 2)\n\n"
            "    def test_msg_with_a_space(self):\n"
            "        with self.subTest('метка с пробелом'):\n"
            "            self.assertEqual(1, 2)\n\n"
            "    def test_kwargs_with_a_space(self):\n"
            "        with self.subTest(n=1, k='a b'):\n"
            "            self.assertEqual(1, 2)\n\n"
            "    def test_both_inside_and_outside(self):\n"
            "        with self.subTest(n=1):\n"
            "            self.assertEqual(1, 2)\n"
            "        self.assertEqual(3, 4)\n\n"
            "    def test_plain(self):\n"
            "        self.assertEqual(1, 2)\n\n"
            "    def test_passes(self):\n"
            "        self.assertEqual(1, 1)\n")
    rc, out = dmr.pytest_runner(["test_forms.py"], repo_root=root)
    assert rc == 1, out

    # Формы, на которые опирается регекс, названы ЗАМЕРОМ — если pytest перестанет их
    # печатать, красным станет ЭТО утверждение, с названной формой в тексте.
    for form in ("SUBFAILED(<subtest>) ", "SUBFAILED[метка с пробелом] ",
                 "SUBFAILED(n=1, k='a b') ", "FAILED "):
        assert form in out, (f"pytest больше не печатает форму {form!r} — регекс "
                             f"`_FAILED_LINE` опирается на неё:\n{out}")

    assert dmr.parse_failures(out) == (
        "test_forms.py::V::test_both_inside_and_outside",
        "test_forms.py::V::test_kwargs_with_a_space",
        "test_forms.py::V::test_msg_with_a_space",
        "test_forms.py::V::test_no_params",
        "test_forms.py::V::test_plain",
    ), out
    assert "test_passes" not in " ".join(dmr.parse_failures(out)), (
        "обратная сторона: прошедший тест с `subTest` в набор упавших попасть не может")


@pytest.mark.timeout(300)
def test_a_mutant_killed_only_under_subtest_is_not_called_a_coverage_hole(tmp_path):
    """ТО ЖЕ ЗВЕНО у ПРОВОДКИ, а не у разбора: имя из `SUBFAILED` обязано доехать до
    вердикта «убит». Разбор, проверенный в отрыве от решения, — «половина инъекции»
    (урок #453): прибор мог бы читать строку и всё равно печатать дыру покрытия.

    Сцена — настоящий pytest, носитель утверждения ОДИН и живёт ТОЛЬКО под `subTest`.
    Замер ДО правки #951: `выжил · набор упавших имён не изменился — дыра покрытия`,
    при этом pytest выходил кодом 1 и печатал «2 failed, 1 passed»."""
    root = _real_tree(tmp_path, test_body=(
        "import os, sys, unittest\n"
        "sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
        "from pkg.mod import value\n\n\n"
        "class OnlyUnderSubTest(unittest.TestCase):\n"
        "    def test_value(self):\n"
        "        for n in (1, 2):\n"
        "            with self.subTest(n=n):\n"
        "                self.assertEqual(value(), 1)\n"))
    report = dmr.run(_spec([("носитель только под subTest", "pkg/mod.py",
                             "return 1", "return 2")], tests=("t/test_x.py",)),
                     repo_root=root)
    assert report.unmeasured_reason is None, report.unmeasured_reason
    assert report.baseline_failures == (), (
        "сцена обязана быть ЗЕЛЁНОЙ до мутации, иначе она сломана, а не носитель")
    assert report.results[0].outcome == dmr.KILLED, report.results[0].detail
    assert report.results[0].new_failures == (
        "t/test_x.py::OnlyUnderSubTest::test_value",), (
        "имя обязано быть РАЗОБРАНО из строки SUBFAILED и доехать до вердикта")


def test_a_new_error_line_kills_the_mutant_too(tmp_path):
    """Обратная сторона того же звена у ПРОВОДКИ, а не у разбора: имя из строки `ERROR`
    обязано доходить до вердикта «убит», иначе звено проверено в отрыве от решения."""
    root = _tree(tmp_path)
    report = dmr.run(_spec([("флип", "pkg/mod.py", "1", "2")]), repo_root=root,
                     runner=_runner([(0, "1 passed"),
                                     (1, "ERROR t/test_x.py - ImportError\n1 error")]))
    assert report.results[0].outcome == dmr.KILLED
    assert report.results[0].new_failures == ("t/test_x.py",)


def test_a_new_failing_name_kills_the_mutant(tmp_path):
    root = _tree(tmp_path)
    report = dmr.run(_spec([("флип", "pkg/mod.py", "1", "2")]), repo_root=root,
                     runner=_runner([(0, "1 passed"),
                                     (1, "FAILED t/test_x.py::test_value\n1 failed")]))
    assert [r.outcome for r in report.results] == [dmr.KILLED]
    assert report.results[0].new_failures == ("t/test_x.py::test_value",)
    assert report.exit_code() == dmr.RC_MEASURED_CLEAN


def test_an_unchanged_set_of_names_means_the_mutant_survived(tmp_path):
    root = _tree(tmp_path)
    report = dmr.run(_spec([("флип", "pkg/mod.py", "1", "2")]), repo_root=root,
                     runner=_runner([(0, "1 passed"), (0, "1 passed")]))
    assert [r.outcome for r in report.results] == [dmr.SURVIVED]
    assert "дыра покрытия" in report.results[0].detail
    assert report.exit_code() == dmr.RC_MEASURED_SURVIVORS


def test_a_foreign_red_does_not_make_every_mutant_killed(tmp_path):
    """ЗВЕНО: вердикт по РАЗНОСТИ наборов, а не по коду возврата pytest (урок #810).

    Батарея уже красна чужим падением. Прогон мутанта возвращает ненулевой код и ТО ЖЕ
    имя. Вердикт по коду объявил бы мутанта убитым; правда — он выжил."""
    root = _tree(tmp_path)
    foreign = "FAILED t/test_x.py::test_foreign\n1 failed"
    report = dmr.run(_spec([("флип", "pkg/mod.py", "1", "2")]), repo_root=root,
                     runner=_runner([(1, foreign), (1, foreign)]))
    assert [r.outcome for r in report.results] == [dmr.SURVIVED]
    assert report.baseline_failures == ("t/test_x.py::test_foreign",)


def test_a_fresh_name_next_to_a_foreign_red_kills_and_lists_only_the_fresh_one(tmp_path):
    """Обратная сторона: при чужом красном убийство ВИДНО, и в вердикт попадает
    ровно новое имя, а не оба."""
    root = _tree(tmp_path)
    report = dmr.run(_spec([("флип", "pkg/mod.py", "1", "2")]), repo_root=root,
                     runner=_runner([
                         (1, "FAILED t/test_x.py::test_foreign\n1 failed"),
                         (1, "FAILED t/test_x.py::test_foreign\n"
                             "FAILED t/test_x.py::test_mine\n2 failed")]))
    assert report.results[0].outcome == dmr.KILLED
    assert report.results[0].new_failures == ("t/test_x.py::test_mine",)


def test_a_mutant_that_extinguishes_a_foreign_red_is_named_not_called_killed(tmp_path):
    """Третья сторона того же звена: новых имён нет, но прежние ИСЧЕЗЛИ. Это не
    убийство и не тихая дыра — это отдельное обстоятельство, и оно НАЗВАНО."""
    root = _tree(tmp_path)
    report = dmr.run(_spec([("флип", "pkg/mod.py", "1", "2")]), repo_root=root,
                     runner=_runner([(1, "FAILED t/test_x.py::test_foreign\n1 failed"),
                                     (0, "1 passed")]))
    assert report.results[0].outcome == dmr.SURVIVED
    assert "ИСЧЕЗЛИ прежние" in report.results[0].detail
    assert "test_foreign" in report.results[0].detail


# ───────────────── третий исход доезжает до КОДА ВОЗВРАТА ─────────────────


def test_an_anchor_that_is_absent_is_not_applied_and_the_run_exits_nonzero(tmp_path):
    """ГЛАВНОЕ ЗВЕНО (инв. #17). У всех 25 одноразовых приборов «не применена»
    печаталась, но код возврата от неё не зависел: прогон, где мутация ничего не
    порвала, выходил НУЛЁМ рядом с убитыми и читался как «все убиты»."""
    root = _tree(tmp_path)
    report = dmr.run(_spec([("якоря нет", "pkg/mod.py", "ТАКОГО-НЕТ", "x"),
                            ("исправная", "pkg/mod.py", "1", "2")]), repo_root=root,
                     runner=_runner([(0, "1 passed"),
                                     (1, "FAILED t/test_x.py::test_value\n1 failed")]))
    assert [r.outcome for r in report.results] == [dmr.NOT_APPLIED, dmr.KILLED]
    assert report.exit_code() == dmr.RC_PARTIALLY_UNMEASURED, (
        "не применённая мутация обязана давать НЕНУЛЕВОЙ код даже рядом с убитыми")
    assert "НЕ ПРИМЕНЕНА" in report.results[0].detail


def test_an_anchor_found_twice_is_not_applied_either(tmp_path):
    """Обратная сторона того же звена: якорь, найденный ДВАЖДЫ, тоже не измеряет
    ничего — подмена ушла бы в два места, и порванным оказалось бы не названное."""
    root = _tree(tmp_path, body="VALUE = 1\nOTHER = 1\n")
    report = dmr.run(_spec([("двойной якорь", "pkg/mod.py", "1", "2")]), repo_root=root,
                     runner=_runner([(0, "1 passed")]))
    assert report.results[0].outcome == dmr.NOT_APPLIED
    assert "2 раз" in report.results[0].detail
    assert report.exit_code() == dmr.RC_PARTIALLY_UNMEASURED


def test_a_mutant_that_breaks_collection_is_not_counted_as_killed(tmp_path):
    """ЗВЕНО: «сломал сборку» ≠ «убит». Ненулевой код без единого провалившегося
    утверждения население считало убийством — вердикт выходил СТРОЖЕ правды."""
    root = _tree(tmp_path)
    report = dmr.run(_spec([("синтаксис", "pkg/mod.py", "1", "(((")]), repo_root=root,
                     runner=_runner([(0, "1 passed"),
                                     (2, "ERROR t/test_x.py\n!!! Interrupted !!!")]))
    assert report.results[0].outcome == dmr.BROKE_COLLECTION
    assert report.by_outcome(dmr.KILLED) == []
    assert report.exit_code() == dmr.RC_PARTIALLY_UNMEASURED


def test_a_baseline_that_judged_nothing_measures_no_mutant_at_all(tmp_path):
    """ЗВЕНО: контроль шума. Не собралось ни одного теста ⇒ «выживших нет» было бы
    подделкой, поэтому ни один мутант не судится вовсе."""
    root = _tree(tmp_path)
    report = dmr.run(_spec([("флип", "pkg/mod.py", "1", "2")]), repo_root=root,
                     runner=_runner([(5, "no tests ran")]))
    assert report.results == []
    assert report.unmeasured_reason and "КОНТРОЛЬ ШУМА" in report.unmeasured_reason
    assert report.exit_code() == dmr.RC_UNMEASURED


def test_a_usage_error_at_the_baseline_is_its_own_unmeasured_reason(tmp_path):
    """Обратная сторона: код 4 — дефект СПЕЦИФИКАЦИИ, а не свойство мутанта, и причина
    названа отдельно от «не собралось»."""
    root = _tree(tmp_path)
    report = dmr.run(_spec([("флип", "pkg/mod.py", "1", "2")]), repo_root=root,
                     runner=_runner([(4, "ERROR: usage")]))
    assert report.exit_code() == dmr.RC_UNMEASURED
    assert "по употреблению" in (report.unmeasured_reason or "")


def test_unmeasured_outranks_survivors_in_the_exit_code(tmp_path):
    """ЗВЕНО: старшинство кодов. «Не измерено» обязано быть видно и тогда, когда
    рядом есть измеренная находка."""
    root = _tree(tmp_path, body="VALUE = 1\nOTHER = 3\n")
    report = dmr.run(_spec([("выживет", "pkg/mod.py", "3", "4"),
                            ("якоря нет", "pkg/mod.py", "НЕТУ", "x")]), repo_root=root,
                     runner=_runner([(0, "1 passed"), (0, "1 passed")]))
    assert {r.outcome for r in report.results} == {dmr.SURVIVED, dmr.NOT_APPLIED}
    assert report.exit_code() == dmr.RC_PARTIALLY_UNMEASURED


def test_the_denominator_excludes_mutations_that_measured_nothing(tmp_path):
    """ЗВЕНО: честный знаменатель. «Применено» = убито + выжило; включить туда не
    применённые значило бы напечатать «убито 1 из 2» там, где измерена ОДНА."""
    root = _tree(tmp_path)
    report = dmr.run(_spec([("якоря нет", "pkg/mod.py", "НЕТУ", "x"),
                            ("исправная", "pkg/mod.py", "1", "2")]), repo_root=root,
                     runner=_runner([(0, "1 passed"),
                                     (1, "FAILED t/test_x.py::test_value\n1 failed")]))
    assert report.applied == 1
    assert len(report.spec.mutations) == 2


def test_the_list_of_outcomes_is_closed(tmp_path):
    """ЗВЕНО: перечень исходов ЗАКРЫТ (инв. #17) — сумма равна населению, иначе
    исчезнувшая мутация читалась бы как «ничего не нашли»."""
    root = _tree(tmp_path, body="A = 1\nB = 2\nC = 3\n")
    report = dmr.run(_spec([("убьётся", "pkg/mod.py", "A = 1", "A = 9"),
                            ("выживет", "pkg/mod.py", "B = 2", "B = 9"),
                            ("не применится", "pkg/mod.py", "НЕТУ", "x")]),
                     repo_root=root,
                     runner=_runner([(0, "1 passed"),
                                     (1, "FAILED t/test_x.py::test_a\n1 failed"),
                                     (0, "1 passed")]))
    counts = {o: len(report.by_outcome(o)) for o in dmr.OUTCOMES}
    assert sum(counts.values()) == len(report.spec.mutations) == 3
    assert counts == {dmr.KILLED: 1, dmr.SURVIVED: 1, dmr.NOT_APPLIED: 1,
                      dmr.BROKE_COLLECTION: 0}


# ───────────────────────── инертность ─────────────────────────


def test_the_mutation_actually_lands_in_the_file_during_the_run(tmp_path):
    """ЗВЕНО-ПРЕДПОСЫЛКА. Без него проверка «дерево не тронуто» ниже была бы пустой:
    прибор, который не мутирует ВООБЩЕ, прошёл бы её блестяще."""
    root = _tree(tmp_path)
    seen = []

    def _run(_tests):
        seen.append(open(os.path.join(root, "pkg/mod.py"), encoding="utf-8").read())
        return (0, "1 passed")

    dmr.run(_spec([("флип", "pkg/mod.py", "VALUE = 1", "VALUE = 2")]),
            repo_root=root, runner=_run)
    assert seen[0] == "VALUE = 1\n", "контроль шума обязан идти по НЕтронутому файлу"
    assert seen[1] == "VALUE = 2\n", "мутация обязана лежать в файле во время прогона"


def test_the_tree_is_byte_identical_after_the_run(tmp_path):
    root = _tree(tmp_path)
    path = os.path.join(root, "pkg/mod.py")
    before = open(path, "rb").read()
    dmr.run(_spec([("флип", "pkg/mod.py", "VALUE = 1", "VALUE = 2")]), repo_root=root,
            runner=_runner([(0, "1 passed"), (1, "FAILED t/test_x.py::test_a")]))
    assert open(path, "rb").read() == before


def test_a_crashing_run_still_restores_the_file(tmp_path):
    """ЗВЕНО: возврат в `finally`. У 13 одноразовых приборов из 25 его не было вовсе,
    и убитый прогон оставлял мутант чужого модуля в дереве."""
    root = _tree(tmp_path)
    path = os.path.join(root, "pkg/mod.py")
    before = open(path, "rb").read()
    calls = {"n": 0}

    def _run(_tests):
        calls["n"] += 1
        if calls["n"] == 1:
            return (0, "1 passed")
        raise KeyboardInterrupt("прогон убит руками")

    with pytest.raises(KeyboardInterrupt):
        dmr.run(_spec([("флип", "pkg/mod.py", "VALUE = 1", "VALUE = 2")]),
                repo_root=root, runner=_run)
    assert open(path, "rb").read() == before, "мутант остался лежать в дереве"


def test_a_run_that_leaves_the_tree_changed_fails_loudly(tmp_path):
    """Обратная сторона: если дерево ВСЁ РАВНО разошлось — прибор обязан падать ГРОМКО.

    Сцена не выдумана: файл ПЕРВОЙ мутации уже возвращён, и пока идёт прогон ВТОРОЙ,
    его правит кто-то ещё (параллельный цикл, агент флота, недоубитый прогон соседа).
    Свой `finally` этого не поймает — он возвращает только тот файл, который сам
    подменял, — поэтому слепок сверяется по ВСЕМ тронутым файлам в конце.

    Тихий успех здесь хуже красного: чужая правка остаётся в дереве, уезжает в пуш и
    становится «доставленной», хотя её никто не писал."""
    root = _tree(tmp_path, body="A = 1\n")
    second = os.path.join(root, "pkg", "вторая.py")
    with open(second, "w", encoding="utf-8") as fh:
        fh.write("B = 1\n")
    first = os.path.join(root, "pkg/mod.py")
    calls = {"n": 0}

    def _run(_tests):
        calls["n"] += 1
        if calls["n"] == 3:          # идёт прогон ВТОРОЙ мутации
            with open(first, "w", encoding="utf-8") as fh:
                fh.write("ЧУЖАЯ ПРАВКА\n")
        return (0, "1 passed")

    with pytest.raises(dmr.TreeNotRestored) as exc:
        dmr.run(_spec([("первая", "pkg/mod.py", "A = 1", "A = 2"),
                       ("вторая", "pkg/вторая.py", "B = 1", "B = 2")]),
                repo_root=root, runner=_run)
    assert "НЕ восстановлено" in str(exc.value) and "pkg/mod.py" in str(exc.value)
    assert "вторая.py" not in str(exc.value), (
        "назван обязан быть РАЗОШЕДШИЙСЯ файл, а не все тронутые")


def test_a_refused_address_is_refused_before_anything_is_touched(tmp_path):
    """ЗВЕНО: порядок. Отказ по адресу обязан случиться ДО первого прогона и ДО первой
    записи — иначе часть файлов осталась бы тронутой при отказе на второй мутации."""
    root = _tree(tmp_path)
    path = os.path.join(root, "pkg/mod.py")
    before = open(path, "rb").read()
    ran = []

    def _run(_tests):
        ran.append(1)
        return (0, "1 passed")

    with pytest.raises(dmr.SpecError):
        dmr.run(_spec([("исправная", "pkg/mod.py", "VALUE = 1", "VALUE = 2"),
                       ("под data", "data/equity_curve_daily.json", "a", "b")]),
                repo_root=root, runner=_run)
    assert ran == [], "батарея не должна была прогоняться ни разу"
    assert open(path, "rb").read() == before


# ───────────────────── печать и машинный вердикт ─────────────────────


def test_the_scorecard_names_every_outcome_and_the_population(tmp_path):
    root = _tree(tmp_path, body="A = 1\nB = 2\n")
    report = dmr.run(_spec([("убьётся", "pkg/mod.py", "A = 1", "A = 9"),
                            ("не применится", "pkg/mod.py", "НЕТУ", "x")]),
                     repo_root=root,
                     runner=_runner([(0, "1 passed"),
                                     (1, "FAILED t/test_x.py::test_a\n1 failed")]))
    text = dmr.render(report)
    assert "применено 1" in text and "убито 1" in text
    assert "НЕ ПРИМЕНЕНО 1" in text and "население 2" in text


def test_the_scorecard_says_not_measured_instead_of_a_clean_verdict(tmp_path):
    root = _tree(tmp_path)
    report = dmr.run(_spec([("флип", "pkg/mod.py", "1", "2")]), repo_root=root,
                     runner=_runner([(5, "no tests ran")]))
    text = dmr.render(report)
    assert "НЕ ИЗМЕРЕНО" in text
    assert "убито" not in text, "сводка «убито 0» читалась бы как измеренный ноль"


def test_the_machine_verdict_carries_the_return_code_and_the_counts(tmp_path):
    root = _tree(tmp_path)
    report = dmr.run(_spec([("флип", "pkg/mod.py", "VALUE = 1", "VALUE = 2")]),
                     repo_root=root, runner=_runner([(0, "1 passed"), (0, "1 passed")]))
    doc = report.to_dict()
    assert doc["rc"] == dmr.RC_MEASURED_SURVIVORS == report.exit_code()
    assert doc["counts"]["survived"] == 1
    assert doc["population"] == 1 and doc["applied"] == 1
    assert sorted(doc["counts"]) == sorted(dmr.OUTCOMES)


def test_the_cli_refuses_a_bad_spec_with_the_unmeasured_code(tmp_path, capsys):
    rc = dmr.main(["--spec", str(tmp_path / "нет.json")])
    assert rc == dmr.RC_UNMEASURED
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err


# ───────── две сцены на НАСТОЯЩЕМ pytest: разбор вывода и окружение ─────────


def _real_tree(tmp_path, *, test_body: str) -> str:
    root = tmp_path / "real"
    (root / "t").mkdir(parents=True)
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "mod.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (root / "t" / "test_x.py").write_text(test_body, encoding="utf-8")
    return str(root)


@pytest.mark.timeout(300)
def test_the_default_runner_really_kills_and_really_survives(tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ самого прибора на НАСТОЯЩЕМ pytest.

    Инъекция прогона выше закрывает все вердикты, но не отвечает на вопрос, разбирает
    ли прибор вывод НАСТОЯЩЕГО pytest: `parse_failures` и `pytest_runner` остались бы
    утверждениями о подпрограмме, которую никто не звал (урок #453 — «половина
    инъекции» есть та же бомба). Сцена одна, мутаций две: одну батарея видит, другую —
    нет, и прибор обязан различить их БЕЗ подсказки."""
    root = _real_tree(tmp_path, test_body=(
        "import sys, os\n"
        "sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
        "from pkg.mod import value\n\n\n"
        "def test_value():\n    assert value() == 1\n"))
    spec = _spec([("видимая батарее", "pkg/mod.py", "return 1", "return 2"),
                  ("невидимая батарее", "pkg/mod.py", "def value()", "def value(_=0)")],
                 tests=("t/test_x.py",))
    report = dmr.run(spec, repo_root=root)
    assert report.unmeasured_reason is None, report.unmeasured_reason
    outcomes = {r.mutation.name: r.outcome for r in report.results}
    assert outcomes["видимая батарее"] == dmr.KILLED, report.results
    assert outcomes["невидимая батарее"] == dmr.SURVIVED, report.results
    assert report.results[0].new_failures == ("t/test_x.py::test_value",), (
        "имя упавшего теста обязано быть РАЗОБРАНО из вывода настоящего pytest")
    assert open(os.path.join(root, "pkg/mod.py"), encoding="utf-8").read() == (
        "def value():\n    return 1\n")


@pytest.mark.timeout(300)
def test_the_pinned_environment_reaches_the_real_subprocess(tmp_path):
    """ЗВЕНО: закреплённое окружение. Объявить `PINNED_ENV` и не передать его —
    ровно тот дефект, из-за которого один и тот же мутант убивается или выживает от
    порядка обхода множеств. Сцена спрашивает у ЖИВОГО подпроцесса, что он видит."""
    root = _real_tree(tmp_path, test_body=(
        "import os\n\n\n"
        "def test_env():\n"
        "    assert os.environ.get('SPA_ENV') == 'ci', os.environ.get('SPA_ENV')\n"
        "    assert os.environ.get('PYTHONHASHSEED') == '0'\n"))
    # Родителю НАРОЧНО подставлено ЧУЖОЕ значение: прежняя редакция этой сцены мерила
    # НАСЛЕДОВАНИЕ, а не закрепление — прогон идёт с `SPA_ENV=ci` в окружении, поэтому
    # ребёнок видел `ci` и без `PINNED_ENV`, и мутация «SPA_ENV не закрепляется»
    # переживала батарею (замер ВВЕЗЁННЫМ прибором, цикл #870).
    hostile = {"SPA_ENV": "НЕ-ci", "PYTHONHASHSEED": "7"}
    saved = {k: os.environ.get(k) for k in hostile}
    os.environ.update(hostile)
    try:
        rc, out = dmr.pytest_runner(["t/test_x.py"], repo_root=root)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    assert rc == 0, out
    assert dmr.parse_failures(out) == ()


def test_the_bytecode_cache_of_the_mutated_file_is_dropped(tmp_path):
    """ЗВЕНО: снятие `__pycache__`. Вторая половина находки про кэш байткода.

    Запрет записи (`PYTHONDONTWRITEBYTECODE`) закрывает НАШУ половину — кэш, который
    создали бы мы сами. Чужой, УЖЕ ЛЕЖАЩИЙ `.pyc` он не трогает, а годность кэша
    меряется mtime исходника В СЕКУНДАХ и его РАЗМЕРОМ: мутант, РАВНЫЙ исходнику по
    длине, внутри одной секунды проходит эту мерку, импорт берёт кэш, и прибор печатает
    дыру покрытия, которой нет.

    Мерится ПРОВОДКА, а не гонка. Первая редакция этой сцены поднимала настоящий pytest
    и ждала, что мутант равной длины будет убит, — но исход там зависел от того,
    улеглись ли два записывания в ОДНУ секунду, и при снятом звене сцена ЗЕЛЕНЕЛА
    (замер ВВЕЗЁННЫМ прибором: мутант «кэш не снимается» выжил ДВА прогона подряд).
    Проверка, которая иногда ловит, не ловит ничего: теперь спрашивается ровно то, на
    что звено отвечает, — ЛЕЖИТ ЛИ кэш мутируемого файла в тот момент, когда идёт
    батарея."""
    root = _tree(tmp_path)
    cache = os.path.join(root, "pkg", "__pycache__")
    os.makedirs(cache)
    stale = os.path.join(cache, "mod.cpython-313.pyc")

    def _make_stale():
        with open(stale, "wb") as fh:
            fh.write("чужой кэш, оставшийся от прежнего прогона".encode("utf-8"))

    _make_stale()
    seen = []

    def _run(_tests):
        seen.append(os.path.exists(stale))
        return (0, "1 passed")

    dmr.run(_spec([("флип", "pkg/mod.py", "VALUE = 1", "VALUE = 2")]),
            repo_root=root, runner=_run)
    assert seen == [True, False], (
        "кэш мутируемого файла обязан быть снят ПЕРЕД подменой и не раньше: контроль "
        f"шума идёт по нетронутому файлу, и его кэш трогать не за что (измерено {seen})")
    assert not os.path.exists(stale), (
        "после возврата кэш обязан быть снят СНОВА — иначе годным остался бы `.pyc`, "
        "записанный под мутантом")


def test_dropping_the_bytecode_cache_is_safe_when_there_is_none(tmp_path):
    """Обратная сторона того же звена: кэша нет ⇒ снятие молча проходит, а не падает.

    Падение здесь стоило бы прибору всей батареи на любом чистом дереве."""
    root = _tree(tmp_path)
    target = os.path.join(root, "pkg", "mod.py")
    dmr._invalidate_bytecode(target)            # каталога `__pycache__` нет вовсе
    os.makedirs(os.path.join(root, "pkg", "__pycache__"))
    dmr._invalidate_bytecode(target)            # каталог есть, записи нет
    sibling = os.path.join(root, "pkg", "__pycache__", "сосед.cpython-313.pyc")
    with open(sibling, "wb") as fh:
        fh.write("кэш СОСЕДНЕГО модуля".encode("utf-8"))
    dmr._invalidate_bytecode(target)
    assert os.path.exists(sibling), "снят кэш ЧУЖОГО модуля — тронуто лишнее"


@pytest.mark.timeout(300)
def test_the_tool_is_runnable_as_a_command_and_its_json_is_machine_readable(tmp_path):
    """ЗВЕНО: прибор ВВЕЗЁН и зовётся КОМАНДОЙ. Это и есть предмет заказа: следующий
    цикл обязан уметь перемерить «убито N», а не читать о нём в ADR."""
    root = _real_tree(tmp_path, test_body=(
        "import sys, os\n"
        "sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
        "from pkg.mod import value\n\n\n"
        "def test_value():\n    assert value() == 1\n"))
    spec_path = _write_spec(tmp_path, {
        "title": "сцена CLI", "tests": ["t/test_x.py"],
        "mutations": [{"name": "видимая", "file": "pkg/mod.py",
                       "old": "return 1", "new": "return 2"}]})
    proc = subprocess.run(
        [sys.executable, _TOOL, "--spec", spec_path, "--repo-root", root, "--json"],
        capture_output=True, text=True)
    assert proc.returncode == dmr.RC_MEASURED_CLEAN, proc.stdout + proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["counts"]["killed"] == 1 and doc["rc"] == 0
